"""
API views for the verification app.

Views are intentionally thin: they validate input via serializers, delegate
all Credas networking to :class:`CredasService`, persist via the ORM, and
return responses through the shared ``success_response`` / ``error_response``
helpers so every endpoint emits the same JSON envelope.
"""
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.views import APIView

from .models import VerificationRecord
from .serializers import (
    DocumentOnlyVerificationSerializer,
    InitiateVerificationSerializer,
    VerificationResultSerializer,
)
from .services.credas_service import CredasAPIException, CredasService
from .utils import (
    InvalidImageError,
    error_response,
    generate_reference,
    normalize_document_image,
    success_response,
)

logger = logging.getLogger("verification")


def sync_record_from_credas(record, service=None):
    """Fetch the latest summary from Credas and persist it onto ``record``.

    Shared by the webhook (push path) and the result endpoint (self-heal poll
    path): both need the authoritative verdict from Credas, mapped and stored.
    DOCUMENT_ONLY journeys keep liveness / name-match null; FULL journeys
    record them.

    Args:
        record (VerificationRecord): The record to refresh (updated in place).
        service (CredasService, optional): Reuse an existing client if given.

    Returns:
        VerificationRecord: The record. If Credas has no result yet, it is
        returned unchanged (still PENDING).

    Raises:
        CredasAPIException: If the Credas call fails. Callers decide how to
            handle it (the webhook swallows it; the result view degrades to
            returning the stale PENDING state).
    """
    service = service or CredasService()
    summary = service.get_entity_summary(record.entity_id)

    # No verification block yet means Credas is still analysing — leave PENDING.
    verifications = summary.get("identityVerifications") or []
    if not verifications:
        logger.info(
            "No identityVerifications yet for entity %s; leaving PENDING",
            record.entity_id,
        )
        return record

    iv = verifications[0]
    mapped_status = service.map_result(iv.get("overallResult", 0))

    # Shared fields for both flows.
    record.status = mapped_status
    record.verified = mapped_status == "VERIFIED"
    record.completed_at = timezone.now()
    record.raw_result = summary
    record.document_result = iv.get("documentResult")
    record.document_number = iv.get("documentNumber")

    # DOCUMENT_ONLY journeys have no liveness / selfie / name-match stage, so
    # those fields stay null; FULL journeys record them.
    if record.verification_type == "DOCUMENT_ONLY":
        logger.info(
            "Sync branch=DOCUMENT_ONLY for entity %s: document only",
            record.entity_id,
        )
    else:
        logger.info(
            "Sync branch=FULL for entity %s: document + liveness",
            record.entity_id,
        )
        record.liveness_result = iv.get("livenessResult")
        record.name_match_result = iv.get("nameMatchResult")

    record.save()
    logger.info(
        "Synced record %s: type=%s status=%s verified=%s",
        record.entity_id,
        record.verification_type,
        mapped_status,
        record.verified,
    )
    return record


class InitiateVerificationView(APIView):
    """POST /api/verify/initiate/ — start a Credas verification journey."""

    def post(self, request):
        """Validate input, create the Credas entity + process, fetch the magic
        link, persist a PENDING record and return the identifiers.

        Per the spec, if the entity is created but a later step fails we still
        save a partial record so the journey is not lost.
        """
        # 1. Validate input.
        serializer = InitiateVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Initiate validation failed: %s", serializer.errors)
            return error_response(
                code="VALIDATION_ERROR",
                message="Invalid input data",
                http_status=status.HTTP_400_BAD_REQUEST,
                details=serializer.errors,
            )

        data = serializer.validated_data
        # 2. Generate a unique reference for this journey.
        reference = generate_reference()

        service = CredasService()

        # 3. Create the entity on Credas.
        try:
            entity = service.create_entity(
                first_name=data["firstName"],
                surname=data["surname"],
                email=data["email"],
                phone=data["phone"],
                reference=reference,
            )
        except CredasAPIException as exc:
            logger.error("Entity creation failed: %s | %s", exc.message, exc.details)
            return error_response(
                code="CREDAS_API_ERROR",
                message="Failed to create entity on Credas",
                http_status=status.HTTP_502_BAD_GATEWAY,
                details=exc.details,
            )

        entity_id = entity["entityId"]
        registration_code = entity["registrationCode"]

        # Persist a partial PENDING record immediately so we never lose the
        # entity even if process creation fails below.
        record = VerificationRecord.objects.create(
            entity_id=entity_id,
            process_id=None,
            registration_code=registration_code,
            first_name=data["firstName"],
            surname=data["surname"],
            email=data["email"],
            phone=data["phone"],
            document_type=data["documentType"],
            reference=reference,
            status="PENDING",
        )
        logger.info("Saved partial VerificationRecord for entity %s", entity_id)

        # 4. Create the verification process (triggers the email to the user).
        try:
            process_id = service.create_process(entity_id, reference)
        except CredasAPIException as exc:
            logger.error("Process creation failed: %s | %s", exc.message, exc.details)
            # Partial record already saved; report the failure to the caller.
            return error_response(
                code="CREDAS_API_ERROR",
                message="Failed to create verification process on Credas",
                http_status=status.HTTP_502_BAD_GATEWAY,
                details=exc.details,
            )

        record.process_id = process_id
        record.save(update_fields=["process_id"])
        logger.info("Updated record %s with process %s", entity_id, process_id)

        # 5. Fetch the magic link (backup for iFrame embedding).
        try:
            verification_link = service.get_magic_link(process_id, entity_id)
        except CredasAPIException as exc:
            logger.error("Magic link fetch failed: %s | %s", exc.message, exc.details)
            return error_response(
                code="CREDAS_API_ERROR",
                message="Failed to fetch verification link from Credas",
                http_status=status.HTTP_502_BAD_GATEWAY,
                details=exc.details,
            )

        # 6/7. Return the success response.
        return success_response(
            data={
                "entityId": entity_id,
                "processId": process_id,
                "verificationType": "FULL",
                "verificationLink": verification_link,
                "emailSent": True,
                "message": (
                    f"Verification email sent to {data['email']}. "
                    "Magic link also provided as backup."
                ),
            },
            http_status=status.HTTP_201_CREATED,
        )


class DocumentOnlyVerificationView(APIView):
    """POST /api/verify/document-only/ — document-image-only verification.

    Accepts either JSON (base64 ``documentImage``) or multipart/form-data (an
    uploaded ``documentImage`` file). Creates a Credas entity, uploads the ID
    document directly for analysis (no magic link, no liveness) and persists a
    PENDING DOCUMENT_ONLY record. The verdict arrives later via the webhook.
    """

    def post(self, request):
        """Validate input, normalise the image, upload to Credas, persist."""
        # 1. Validate the text fields + presence of documentImage.
        serializer = DocumentOnlyVerificationSerializer(data=request.data)
        if not serializer.is_valid():
            logger.warning("Document-only validation failed: %s", serializer.errors)
            return error_response(
                code="VALIDATION_ERROR",
                message="Invalid input data",
                http_status=status.HTTP_400_BAD_REQUEST,
                details=serializer.errors,
            )

        data = serializer.validated_data

        # 2/3/4. Normalise the image (file → base64 or base64 passthrough) and
        # enforce that only JPG/PNG are accepted.
        try:
            base64_image = normalize_document_image(data["documentImage"])
        except InvalidImageError as exc:
            logger.warning("Document-only rejected bad image: %s", exc)
            return error_response(
                code="INVALID_FORMAT",
                message="Only JPG and PNG image formats are supported.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        # 5. Map the documentType string to Credas' numeric type.
        document_type_int = (
            DocumentOnlyVerificationSerializer.DOCUMENT_TYPE_MAP[data["documentType"]]
        )

        # 6. Generate a unique reference for this journey.
        reference = generate_reference()

        service = CredasService()

        # 7. Create the entity on Credas.
        try:
            entity = service.create_entity(
                first_name=data["firstName"],
                surname=data["surname"],
                email=data["email"],
                phone=data["phone"],
                reference=reference,
            )
        except CredasAPIException as exc:
            logger.error("Entity creation failed: %s | %s", exc.message, exc.details)
            return error_response(
                code="CREDAS_API_ERROR",
                message="Failed to create entity on Credas",
                http_status=status.HTTP_502_BAD_GATEWAY,
                details=exc.details,
            )

        entity_id = entity["entityId"]
        registration_code = entity["registrationCode"]

        # 8. Upload the document image directly (async — result via webhook).
        try:
            service.upload_id_document(entity_id, document_type_int, base64_image)
        except CredasAPIException as exc:
            logger.error("Document upload failed: %s | %s", exc.message, exc.details)
            return error_response(
                code="CREDAS_API_ERROR",
                message="Failed to upload document to Credas",
                http_status=status.HTTP_502_BAD_GATEWAY,
                details=exc.details,
            )

        # 9. Persist a PENDING DOCUMENT_ONLY record (no process_id).
        VerificationRecord.objects.create(
            entity_id=entity_id,
            process_id=None,
            registration_code=registration_code,
            first_name=data["firstName"],
            surname=data["surname"],
            email=data["email"],
            phone=data["phone"],
            document_type=data["documentType"],
            reference=reference,
            verification_type="DOCUMENT_ONLY",
            status="PENDING",
        )
        logger.info(
            "Saved DOCUMENT_ONLY VerificationRecord for entity %s", entity_id
        )

        # 10. Return 202 Accepted.
        return success_response(
            data={
                "entityId": entity_id,
                "verificationType": "DOCUMENT_ONLY",
                "status": "PENDING",
                "message": (
                    "Document submitted successfully. Use "
                    f"GET /api/verify/result/{entity_id}/ to check the result."
                ),
            },
            http_status=status.HTTP_202_ACCEPTED,
        )


class CredasWebhookView(APIView):
    """POST /api/webhook/credas/ — receive completion callbacks from Credas.

    This endpoint must always return 200, even on internal errors, so Credas
    does not retry and create duplicate processing.
    """

    # No authentication and CSRF-exempt: this is an external machine callback.
    authentication_classes = []
    permission_classes = []

    # Keys Credas may use to carry the entity id in a webhook payload.
    _ENTITY_ID_KEYS = ("entityId", "entity_id", "id")

    @classmethod
    def _extract_entity_id(cls, payload):
        """Best-effort extraction of the entity id from a webhook payload."""
        if not isinstance(payload, dict):
            return None
        for key in cls._ENTITY_ID_KEYS:
            value = payload.get(key)
            if value:
                return value
        return None

    def post(self, request):
        """Process the webhook payload and update the matching record."""
        payload = request.data
        # 1. Log the full incoming payload for traceability.
        logger.info("Webhook received from Credas: %s", payload)

        try:
            # 2. Extract identifiers from the body. process_id is present for
            #    magic-link (FULL) journeys but absent for DOCUMENT_ONLY ones,
            #    which we then locate by entity id instead.
            process_id = payload.get("processId") if isinstance(payload, dict) else None
            entity_id = self._extract_entity_id(payload)

            # 3. Locate the record: by process_id first (FULL records), then
            #    fall back to entity_id (DOCUMENT_ONLY records have no
            #    process_id).
            record = None
            if process_id:
                record = VerificationRecord.objects.filter(
                    process_id=process_id
                ).first()
            if record is None and entity_id:
                record = VerificationRecord.objects.filter(
                    entity_id=entity_id
                ).first()

            if record is None:
                logger.warning(
                    "No record for processId=%s / entityId=%s; ignoring webhook",
                    process_id,
                    entity_id,
                )
                return success_response(
                    data={"received": True}, http_status=status.HTTP_200_OK
                )

            # 4-7. Pull the authoritative result from Credas (don't trust the
            #      webhook body alone for the verdict) and persist it.
            logger.info("Webhook syncing record %s from Credas", record.entity_id)
            sync_record_from_credas(record)
        except Exception as exc:  # noqa: BLE001 — webhook must never 500.
            # 8. Log but always return 200 so Credas does not retry.
            logger.exception("Error processing Credas webhook: %s", exc)

        return success_response(
            data={"received": True}, http_status=status.HTTP_200_OK
        )


@api_view(["GET"])
def verification_result(request, entity_id):
    """GET /api/verify/result/{entityId}/ — return the stored result.

    The webhook keeps the record up to date, but webhooks can be missed or
    unreachable (e.g. no public URL in local dev). So if the record is still
    PENDING we self-heal: fetch the latest summary from Credas on the spot and
    persist it, so the caller always sees the true status without depending on
    the webhook.
    """
    # 1/2. Look up the record.
    try:
        record = VerificationRecord.objects.get(entity_id=entity_id)
    except VerificationRecord.DoesNotExist:
        logger.info("Result lookup miss for entity %s", entity_id)
        return error_response(
            code="NOT_FOUND",
            message="No verification record found for this entityId",
            http_status=status.HTTP_404_NOT_FOUND,
        )

    # Self-heal: refresh a PENDING record straight from Credas so a missed or
    # unreachable webhook does not leave it stuck. Degrade gracefully (keep the
    # stale PENDING view) if Credas cannot be reached.
    if record.status == "PENDING":
        try:
            sync_record_from_credas(record)
        except CredasAPIException as exc:
            logger.warning(
                "Self-heal sync failed for entity %s: %s | %s",
                entity_id,
                exc.message,
                exc.details,
            )

    base = VerificationResultSerializer(record).data

    # 3. If still pending, return the record shape with a null details block.
    if record.status == "PENDING":
        base["details"] = None
        base["message"] = "User has not completed verification yet"
        return success_response(data=base, http_status=status.HTTP_200_OK)

    # Otherwise include the full details block.
    base["details"] = {
        "documentResult": record.document_result,
        "livenessResult": record.liveness_result,
        "nameMatchResult": record.name_match_result,
        "documentNumber": record.document_number,
        "overallResult": (
            1 if record.status == "VERIFIED"
            else 2 if record.status == "NOT_VERIFIED"
            else 0
        ),
    }
    return success_response(data=base, http_status=status.HTTP_200_OK)
