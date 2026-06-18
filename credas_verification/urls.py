"""
Root URL configuration for the credas_verification project.

The verification app owns all the API routes; they are included under the
``/api/`` prefix here.
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("verification.urls")),
]
