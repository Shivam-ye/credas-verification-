"""
Serializers for the verification app.

These handle all input validation (so views stay thin) and shape the output
for verification records into the public JSON contract.
"""
from rest_framework import serializers

from .models import VerificationRecord


class InitiateVerificationSerializer(serializers.Serializer):
    """Validates the input body for POST /api/verify/initiate/."""

    # Allowed document types for the journey.
    DOCUMENT_TYPE_CHOICES = ["passport", "driving_licence", "national_id"]

    firstName = serializers.CharField(max_length=100)
    surname = serializers.CharField(max_length=100)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20)
    documentType = serializers.ChoiceField(choices=DOCUMENT_TYPE_CHOICES)


class VerificationResultSerializer(serializers.ModelSerializer):
    """Shapes a VerificationRecord into the result response payload.

    The view decides whether to include the ``details`` block (only when the
    journey is no longer PENDING), so this serializer focuses on the stable,
    always-present fields.
    """

    entityId = serializers.CharField(source="entity_id")
    name = serializers.SerializerMethodField()
    documentType = serializers.CharField(source="document_type")
    createdAt = serializers.DateTimeField(source="created_at")
    completedAt = serializers.DateTimeField(source="completed_at")

    class Meta:
        model = VerificationRecord
        fields = [
            "entityId",
            "name",
            "email",
            "verified",
            "status",
            "documentType",
            "createdAt",
            "completedAt",
        ]

    def get_name(self, obj):
        """Return the user's full name."""
        return f"{obj.first_name} {obj.surname}".strip()
