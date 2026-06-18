"""App configuration for the verification app."""
from django.apps import AppConfig


class VerificationConfig(AppConfig):
    """Default configuration for the verification app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "verification"
