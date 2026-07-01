"""
Serializers for the verification app.

These handle all input validation (so views stay thin) and shape the output
for verification records into the public JSON contract.
"""
from rest_framework import serializers

from .models import VerificationRecord


class _PassthroughField(serializers.Field):
    """A field that accepts any value (file or string) and returns it as-is.

    Used for ``documentImage`` so a single serializer handles both JSON base64
    strings and multipart file uploads; the view does the real normalisation
    and format validation.
    """

    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value


class InitiateVerificationSerializer(serializers.Serializer):
    """Validates the input body for POST /api/verify/initiate/."""

    # Allowed document types for the journey.
    DOCUMENT_TYPE_CHOICES = ["passport", "driving_licence", "national_id"]

    firstName = serializers.CharField(max_length=100)
    surname = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    documentType = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)


class DocumentOnlyVerificationSerializer(serializers.Serializer):
    """Validates the input body for POST /api/verify/document-only/.

    Accepts both ``application/json`` (with a base64 ``documentImage`` string)
    and ``multipart/form-data`` (with an uploaded ``documentImage`` file). The
    text fields validate identically for both; ``documentImage`` is passed
    through untouched here and normalised/format-checked in the view, so that
    invalid image formats can return the dedicated ``INVALID_FORMAT`` error.
    """

    # Maps the public documentType strings to Credas' numeric document types.
    DOCUMENT_TYPE_MAP = {
        "passport": 10,
        "driving_licence": 2,
        "national_id": 9,
        "visa": 13,
        "travel_permit": 12,
    }

    # Only documentType + documentImage are required. Personal details are
    # optional: Credas needs a name to create the entity, so a placeholder is
    # used in the view when firstName/surname are omitted. Document-only never
    # does name-matching, so the name is just a label; email/phone are dropped
    # from the Credas call when not supplied.
    firstName = serializers.CharField(max_length=100, required=False, allow_blank=True)
    surname = serializers.CharField(max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    documentType = serializers.ChoiceField(choices=list(DOCUMENT_TYPE_MAP.keys()))
    # Accept either a base64 string (JSON) or an uploaded file (multipart).
    # Required, but not otherwise coerced — the view normalises and validates
    # the actual image bytes.
    documentImage = _PassthroughField()

    def validate_documentImage(self, value):
        """Ensure an image payload was actually provided (file or base64)."""
        if value is None or (isinstance(value, str) and not value.strip()):
            raise serializers.ValidationError("This field is required.")
        return value


class VerificationResultSerializer(serializers.ModelSerializer):
    """Shapes a VerificationRecord into the result response payload.

    The view decides whether to include the ``details`` block (only when the
    journey is no longer PENDING), so this serializer focuses on the stable,
    always-present fields.
    """

    entityId = serializers.CharField(source="entity_id")
    name = serializers.SerializerMethodField()
    verificationType = serializers.CharField(source="verification_type")
    documentType = serializers.CharField(source="document_type")
    createdAt = serializers.DateTimeField(source="created_at")
    completedAt = serializers.DateTimeField(source="completed_at")

    class Meta:
        model = VerificationRecord
        fields = [
            "entityId",
            "name",
            "email",
            "verificationType",
            "verified",
            "status",
            "documentType",
            "createdAt",
            "completedAt",
        ]

    def get_name(self, obj):
        """Return the user's full name."""
        return f"{obj.first_name} {obj.surname}".strip()
