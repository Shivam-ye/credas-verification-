"""
Database models for the verification app.

A single VerificationRecord row represents one identity-verification journey
for one user on Credas, tracked from initiation through to the final result.
"""
from django.db import models


class VerificationRecord(models.Model):
    """Persisted state of a Credas identity-verification journey."""

    # Allowed values for the local status field.
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("VERIFIED", "Verified"),
        ("NOT_VERIFIED", "Not Verified"),
        ("FAILED", "Failed"),
    ]

    # Which flavour of verification this record represents.
    #   FULL          — magic-link journey (document + liveness + name match)
    #   DOCUMENT_ONLY — direct document image upload, no liveness / selfie
    VERIFICATION_TYPE_CHOICES = [
        ("FULL", "Full - Document + Liveness"),
        ("DOCUMENT_ONLY", "Document Only"),
    ]

    # ─── Credas IDs ────────────────────────────────────────────────────────
    # entity_id is the Credas entity UUID and our primary key.
    entity_id = models.CharField(max_length=100, primary_key=True)
    # process_id may be blank if process creation failed after the entity was
    # created (partial record). unique only enforced for non-null values.
    process_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    registration_code = models.CharField(max_length=50, blank=True)

    # ─── User info ─────────────────────────────────────────────────────────
    first_name = models.CharField(max_length=100)
    surname = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    document_type = models.CharField(max_length=50)
    reference = models.CharField(max_length=100, unique=True)

    # ─── Verification flavour ─────────────────────────────────────────────
    verification_type = models.CharField(
        max_length=20,
        choices=VERIFICATION_TYPE_CHOICES,
        default="FULL",
    )

    # ─── Status ────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="PENDING"
    )
    verified = models.BooleanField(default=False)

    # ─── Timestamps ────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # ─── Raw results from Credas ──────────────────────────────────────────
    raw_result = models.JSONField(null=True, blank=True)

    # ─── Verification detail fields ───────────────────────────────────────
    document_result = models.IntegerField(null=True, blank=True)
    liveness_result = models.IntegerField(null=True, blank=True)
    name_match_result = models.IntegerField(null=True, blank=True)
    document_number = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Verification Record"
        verbose_name_plural = "Verification Records"

    def __str__(self):
        """Human-readable representation used in admin / logs."""
        return f"{self.first_name} {self.surname} <{self.email}> [{self.status}]"
