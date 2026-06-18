"""
Helper utilities shared across the verification app.

Keeping response-shaping and small helpers here ensures every endpoint emits
a consistent JSON envelope and avoids duplicated formatting logic in views.
"""
import uuid

from rest_framework.response import Response


def generate_reference():
    """Generate a unique reference string for a verification journey.

    Returns:
        str: A UUID4 hex string used as the Credas ``reference``.
    """
    return str(uuid.uuid4())


def success_response(data, http_status):
    """Build a standardised success JSON response.

    Args:
        data (dict): Payload to return under the ``data`` key.
        http_status (int): HTTP status code for the response.

    Returns:
        rest_framework.response.Response: ``{"success": true, "data": {...}}``.
    """
    return Response({"success": True, "data": data}, status=http_status)


def error_response(code, message, http_status, details=None):
    """Build a standardised error JSON response.

    Args:
        code (str): Machine-readable error code, e.g. "CREDAS_API_ERROR".
        message (str): Human-readable error message (safe for clients).
        http_status (int): HTTP status code for the response.
        details (str, optional): Extra context; omitted when None.

    Returns:
        rest_framework.response.Response: ``{"success": false, "error": {...}}``.
    """
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return Response({"success": False, "error": error}, status=http_status)
