"""
Helper utilities shared across the verification app.

Keeping response-shaping and small helpers here ensures every endpoint emits
a consistent JSON envelope and avoids duplicated formatting logic in views.
"""
import base64
import binascii
import uuid

from rest_framework.response import Response

# Magic-byte signatures used to confirm an uploaded/base64 payload really is a
# JPG or PNG image. Anything else (PDF, GIF, etc.) is rejected.
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class InvalidImageError(Exception):
    """Raised when a document image is not a decodable JPG or PNG."""


def _is_supported_image(content):
    """Return True if raw bytes start with a JPG or PNG signature."""
    return content.startswith(_JPEG_MAGIC) or content.startswith(_PNG_MAGIC)


def normalize_document_image(raw):
    """Normalise a document image payload into a canonical base64 string.

    Accepts either an uploaded file object (multipart) or a base64-encoded
    string (JSON, optionally a ``data:`` URI). The decoded bytes are checked
    against JPG/PNG magic bytes so non-image formats (e.g. PDF) are rejected.

    Args:
        raw: An uploaded file (with ``.read()``) or a base64 string.

    Returns:
        str: Canonical base64 (no whitespace) of the validated image bytes.

    Raises:
        InvalidImageError: If the payload is not a decodable JPG or PNG.
    """
    # Multipart: an uploaded file exposes .read().
    if hasattr(raw, "read"):
        content = raw.read()
        if not _is_supported_image(content):
            raise InvalidImageError("Uploaded file is not a JPG or PNG image")
        return base64.b64encode(content).decode("ascii")

    # JSON: a base64 string, possibly a data URI with whitespace/newlines.
    if isinstance(raw, str):
        b64 = raw.strip()
        if "base64," in b64:
            b64 = b64.split("base64,", 1)[1]
        # Drop any embedded whitespace/newlines before strict decoding.
        b64 = "".join(b64.split())
        try:
            content = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InvalidImageError("documentImage is not valid base64") from exc
        if not _is_supported_image(content):
            raise InvalidImageError("Decoded image is not a JPG or PNG")
        # Re-encode canonically so what we send Credas is clean.
        return base64.b64encode(content).decode("ascii")

    raise InvalidImageError("Unsupported documentImage payload")


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
