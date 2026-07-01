"""
URL routing for the verification app.

All paths are mounted under ``/api/`` by the project urls.py.
"""
from django.urls import path

from . import views

urlpatterns = [
    # Start a new verification journey.
    path(
        "verify/initiate/",
        views.InitiateVerificationView.as_view(),
        name="verify-initiate",
    ),
    # Start a document-only verification (direct image upload, no magic link).
    path(
        "verify/document-only/",
        views.DocumentOnlyVerificationView.as_view(),
        name="verify-document-only",
    ),
    # Credas completion webhook (CSRF-exempt, always 200).
    path(
        "webhook/credas/",
        views.CredasWebhookView.as_view(),
        name="credas-webhook",
    ),
    # Fetch the stored result for an entity.
    path(
        "verify/result/<str:entity_id>/",
        views.verification_result,
        name="verify-result",
    ),
]
