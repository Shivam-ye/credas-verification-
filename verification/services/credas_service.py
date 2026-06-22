"""
Credas API service layer.

ALL outbound calls to the Credas REST API live in this module. Views never
talk to ``requests`` directly — they go through :class:`CredasService`. This
keeps networking, retries, error translation and logging in one place.

Configuration (base URL, API key, journey/actor IDs, webhook URL) is read
from Django settings, which in turn loads it from the .env file. Nothing is
hardcoded here.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger("verification")

# Sensible network timeout (connect, read) so a slow Credas never hangs a
# request worker indefinitely.
DEFAULT_TIMEOUT = (10, 30)


class CredasAPIException(Exception):
    """Raised when a Credas API call fails or returns an unexpected response.

    Attributes:
        message (str): Safe, human-readable summary of what went wrong.
        details (str): Extra technical context for logging / debugging.
    """

    def __init__(self, message, details=None):
        self.message = message
        self.details = details or ""
        super().__init__(self.message)


class CredasService:
    """Thin client around the Credas Connect (CI) v2 API."""

    def __init__(self):
        """Initialise the service from Django settings (.env backed)."""
        self.base_url = settings.CREDAS_BASE_URL
        self.api_key = settings.CREDAS_API_KEY
        self.journey_id = settings.CREDAS_JOURNEY_ID
        self.actor_id = settings.CREDAS_ACTOR_ID
        self.webhook_url = settings.CREDAS_WEBHOOK_URL

        # Fail fast and loudly if configuration is missing — this is a
        # deployment error, not a per-request error.
        missing = [
            name
            for name, value in {
                "CREDAS_BASE_URL": self.base_url,
                "CREDAS_API_KEY": self.api_key,
                "CREDAS_JOURNEY_ID": self.journey_id,
                "CREDAS_ACTOR_ID": self.actor_id,
                "CREDAS_WEBHOOK_URL": self.webhook_url,
            }.items()
            if not value
        ]
        if missing:
            raise CredasAPIException(
                "Credas integration is not configured",
                details=f"Missing environment variables: {', '.join(missing)}",
            )

    # ─── Internal helpers ──────────────────────────────────────────────────
    def _headers(self):
        """Return the standard headers for every Credas request."""
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _request(self, method, path, *, json_body=None):
        """Perform an HTTP request to Credas and return the parsed JSON.

        Centralises logging, timeout handling and error translation so each
        public method stays small.

        Args:
            method (str): HTTP verb, e.g. "GET" / "POST".
            path (str): API path beginning with "/", appended to base URL.
            json_body (dict, optional): JSON request payload for writes.

        Returns:
            The parsed JSON response (dict, list or str).

        Raises:
            CredasAPIException: On network errors, non-2xx responses or
                responses that cannot be parsed as JSON.
        """
        url = f"{self.base_url}{path}"
        logger.info("Credas request: %s %s payload=%s", method, url, json_body)

        try:
            response = requests.request(
                method,
                url,
                headers=self._headers(),
                json=json_body,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as exc:
            # DNS failure, connection refused, timeout, etc.
            logger.error("Credas network error on %s %s: %s", method, url, exc)
            raise CredasAPIException(
                "Could not reach the Credas service", details=str(exc)
            ) from exc

        # Log the raw response for traceability (status + body).
        logger.info(
            "Credas response: %s %s -> %s %s",
            method,
            url,
            response.status_code,
            response.text,
        )

        # Credas returns 200 for successful creates (not 201); accept any 2xx.
        if not 200 <= response.status_code < 300:
            raise CredasAPIException(
                "Credas returned an error response",
                details=f"HTTP {response.status_code}: {response.text}",
            )

        try:
            return response.json()
        except ValueError as exc:
            logger.error("Credas returned non-JSON body on %s %s", method, url)
            raise CredasAPIException(
                "Credas returned an unreadable response", details=str(exc)
            ) from exc

    # ─── Public API methods ────────────────────────────────────────────────
    def create_entity(self, first_name, surname, email, phone, reference):
        """Create a Credas entity (the person being verified).

        Calls ``POST /api/v2/ci/entities``.

        Args:
            first_name (str): Entity first name.
            surname (str): Entity surname.
            email (str): Entity email address.
            phone (str): Entity phone number.
            reference (str): Our unique reference for this journey.

        Returns:
            dict: ``{"entityId": str, "registrationCode": str}``.

        Raises:
            CredasAPIException: If the call fails or no id is returned.
        """
        payload = {
            "firstName": first_name,
            "surname": surname,
            "emailAddress": email,
            "phoneNumber": phone,
            "reference": reference,
            "userGroupId": "",
        }
        data = self._request("POST", "/api/v2/ci/entities", json_body=payload)

        entity_id = data.get("id")
        if not entity_id:
            raise CredasAPIException(
                "Credas did not return an entity id",
                details=f"Response: {data}",
            )

        logger.info("Created Credas entity %s (reference=%s)", entity_id, reference)
        return {
            "entityId": entity_id,
            "registrationCode": data.get("registrationCode", ""),
        }

    def create_process(self, entity_id, reference):
        """Create a verification process for an entity.

        Calls ``POST /api/v2/ci/processes`` with ``contactViaEmail: true`` so
        Credas emails the user automatically. The webhook URL comes from .env.

        Args:
            entity_id (str): The Credas entity id from :meth:`create_entity`.
            reference (str): The same reference used for the entity.

        Returns:
            str: The created process id.

        Raises:
            CredasAPIException: If the call fails or no id is returned.
        """
        payload = {
            "title": "Identity Verification",
            "journeyId": self.journey_id,
            "webhookUrl": self.webhook_url,
            "userGroupId": "",
            "processEntities": [
                {
                    "id": entity_id,
                    "reference": reference,
                    # actorId must be an int for the Credas API.
                    "actorId": int(self.actor_id),
                    "contactViaEmail": True,
                    "contactViaSms": True,
                    "inPerson": False,
                }
            ],
        }
        data = self._request("POST", "/api/v2/ci/processes", json_body=payload)

        process_id = data.get("id")
        if not process_id:
            raise CredasAPIException(
                "Credas did not return a process id",
                details=f"Response: {data}",
            )

        logger.info(
            "Created Credas process %s for entity %s", process_id, entity_id
        )
        return process_id

    def get_magic_link(self, process_id, entity_id):
        """Fetch the magic (deep) link for the user to start verification.

        Calls ``GET /api/v2/ci/processes/{processId}/entities/{entityId}/magic-link``.
        Credas returns the URL as a bare JSON string.

        Args:
            process_id (str): The Credas process id.
            entity_id (str): The Credas entity id.

        Returns:
            str: The verification URL.

        Raises:
            CredasAPIException: If the call fails or the link is empty.
        """
        path = (
            f"/api/v2/ci/processes/{process_id}"
            f"/entities/{entity_id}/magic-link"
        )
        data = self._request("GET", path)

        # The endpoint returns a plain JSON string (e.g. "https://...").
        link = data if isinstance(data, str) else data.get("magicLink")
        if not link:
            raise CredasAPIException(
                "Credas did not return a magic link",
                details=f"Response: {data}",
            )

        logger.info("Fetched magic link for process %s", process_id)
        return link

    def get_entity_summary(self, entity_id):
        """Fetch the full verification summary for an entity.

        Calls ``GET /api/v2/ci/entities/{entityId}/summary``.

        Args:
            entity_id (str): The Credas entity id.

        Returns:
            dict: The full summary, including ``identityVerifications``.

        Raises:
            CredasAPIException: If the call fails.
        """
        path = f"/api/v2/ci/entities/{entity_id}/summary"
        data = self._request("GET", path)
        logger.info("Fetched summary for entity %s", entity_id)
        return data

    @staticmethod
    def map_result(overall_result):
        """Map a Credas numeric ``overallResult`` to our status string.

        Args:
            overall_result (int): 0, 1 or 2 from Credas.

        Returns:
            str: "PENDING", "VERIFIED", "NOT_VERIFIED", or "FAILED" for any
                unexpected value.
        """
        mapping = {
            0: "PENDING",
            1: "VERIFIED",
            2: "NOT_VERIFIED",
        }
        return mapping.get(overall_result, "FAILED")
