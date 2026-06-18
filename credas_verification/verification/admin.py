"""Django admin registration for the verification app."""
from django.contrib import admin

from .models import VerificationRecord


@admin.register(VerificationRecord)
class VerificationRecordAdmin(admin.ModelAdmin):
    """Read-friendly admin view of verification records."""

    list_display = (
        "entity_id",
        "first_name",
        "surname",
        "email",
        "status",
        "verified",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "verified", "document_type")
    search_fields = ("entity_id", "process_id", "email", "reference")
    readonly_fields = ("created_at",)
