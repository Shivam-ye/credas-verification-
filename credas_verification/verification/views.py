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
    InitiateVerificationSerializer,
    VerificationResultSerializer,
)
from .services.credas_service import CredasAPIException, CredasService
from .utils import error_response, generate_reference, success_response

logger = logging.getLogger("verification")


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
                "verificationLink": verification_link,
                "emailSent": True,
                "message": (
                    f"Verification email sent to {data['email']}. "
                    "Magic link also provided as backup."
                ),
            },
            http_status=status.HTTP_201_CREATED,
        )


class CredasWebhookView(APIView):
    """POST /api/webhook/credas/ — receive completion callbacks from Credas.

    This endpoint must always return 200, even on internal errors, so Credas
    does not retry and create duplicate processing.
    """

    # No authentication and CSRF-exempt: this is an external machine callback.
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        """Process the webhook payload and update the matching record."""
        payload = request.data
        # 1. Log the full incoming payload for traceability.
        logger.info("Webhook received from Credas: %s", payload)

        try:
            # 2. Extract the processId from the body.
            process_id = payload.get("processId") if isinstance(payload, dict) else None
            if not process_id:
                logger.warning("Webhook missing processId; ignoring. Payload=%s", payload)
                return success_response(
                    data={"received": True}, http_status=status.HTTP_200_OK
                )

            # 3. Find the matching local record.
            try:
                record = VerificationRecord.objects.get(process_id=process_id)
            except VerificationRecord.DoesNotExist:
                logger.warning("No record for processId=%s; ignoring webhook", process_id)
                return success_response(
                    data={"received": True}, http_status=status.HTTP_200_OK
                )

            # 4. Pull the authoritative result from Credas (don't trust the
            #    webhook body alone for the verdict).
            service = CredasService()
            summary = service.get_entity_summary(record.entity_id)

            # 5/6. Extract and map the overall result.
            verifications = summary.get("identityVerifications") or []
            if not verifications:
                logger.warning(
                    "Summary for entity %s has no identityVerifications",
                    record.entity_id,
                )
                return success_response(
                    data={"received": True}, http_status=status.HTTP_200_OK
                )

            iv = verifications[0]
            overall_result = iv.get("overallResult", 0)
            mapped_status = service.map_result(overall_result)

            # 7. Update the record.
            record.status = mapped_status
            record.verified = mapped_status == "VERIFIED"
            record.completed_at = timezone.now()
            record.raw_result = summary
            record.document_result = iv.get("documentResult")
            record.liveness_result = iv.get("livenessResult")
            record.name_match_result = iv.get("nameMatchResult")
            record.document_number = iv.get("documentNumber")
            record.save()
            logger.info(
                "Updated record %s from webhook: status=%s verified=%s",
                record.entity_id,
                mapped_status,
                record.verified,
            )
        except Exception as exc:  # noqa: BLE001 — webhook must never 500.
            # 8. Log but always return 200 so Credas does not retry.
            logger.exception("Error processing Credas webhook: %s", exc)

        return success_response(
            data={"received": True}, http_status=status.HTTP_200_OK
        )


@api_view(["GET"])
def verification_result(request, entity_id):
    """GET /api/verify/result/{entityId}/ — return the stored result.

    Reads straight from the DB; the webhook keeps it up to date.
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

    base = VerificationResultSerializer(record).data

    # 3. If still pending, return the minimal pending shape.
    if record.status == "PENDING":
        return success_response(
            data={
                "entityId": record.entity_id,
                "verified": False,
                "status": "PENDING",
                "details": None,
                "message": "User has not completed verification yet",
            },
            http_status=status.HTTP_200_OK,
        )

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
