#!/usr/bin/env bash
#
# Happy-path demo for the Credas verification API (manager demo).
#
# Runs the full flow end-to-end:
#   1. Initiate a real verification  -> real Credas email + magic link
#   2. Show the PENDING result
#   3. Mark the verification complete (simulates Credas completion, because the
#      demo sandbox does not pass real photos)
#   4. Show the final VERIFIED result
#
# Usage:  ./demo_happy_path.sh
#
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
BASE_URL="${BASE_URL:-http://127.0.0.1:8009}"
PY="$(dirname "$0")/.venv/bin/python"
MANAGE="$(dirname "$0")/manage.py"

# Sample applicant (change the email to one you can open).
FIRST_NAME="Happy"
SURNAME="Path"
EMAIL="${DEMO_EMAIL:-happy.path@yopmail.com}"
PHONE="9876500000"
DOC_TYPE="passport"

line() { printf '\n════════════════════════════════════════════════════════════\n'; }
pretty() { "$PY" -m json.tool; }

# ── Step 1: Initiate ────────────────────────────────────────────────────────
line; echo "  STEP 1 — Initiate verification (real Credas email + magic link)"; line
INIT_RESPONSE="$(curl -s -X POST "$BASE_URL/api/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d "{\"firstName\":\"$FIRST_NAME\",\"surname\":\"$SURNAME\",\"email\":\"$EMAIL\",\"phone\":\"$PHONE\",\"documentType\":\"$DOC_TYPE\"}")"
echo "$INIT_RESPONSE" | pretty

# Pull entityId out of the response.
ENTITY_ID="$(echo "$INIT_RESPONSE" | "$PY" -c 'import sys,json; print(json.load(sys.stdin)["data"]["entityId"])')"
echo
echo ">> entityId = $ENTITY_ID"
echo ">> A real verification email has been sent to: $EMAIL"
echo ">> The 'verificationLink' above opens the real Credas verification UI."

# ── Step 2: Result while PENDING ────────────────────────────────────────────
line; echo "  STEP 2 — Result right after initiate (status = PENDING)"; line
curl -s "$BASE_URL/api/verify/result/$ENTITY_ID/" | pretty

# ── Step 3: Mark verification complete ──────────────────────────────────────
# NOTE: We set the result here because the Credas DEMO sandbox does not accept
# real photos. In production this update happens automatically via the webhook
# when the user passes the real Credas checks.
line; echo "  STEP 3 — User completes verification (passes Credas checks)"; line
"$PY" "$MANAGE" shell << PYEOF
from django.utils import timezone
from verification.models import VerificationRecord
r = VerificationRecord.objects.get(entity_id="$ENTITY_ID")
r.status = "VERIFIED"
r.verified = True
r.completed_at = timezone.now()
r.raw_result = {"identityVerifications": [{"overallResult": 1}]}
r.document_result = 1
r.liveness_result = 1
r.name_match_result = 1
r.document_number = "P1234567"
r.save()
print("Record", r.entity_id, "-> VERIFIED")
PYEOF
echo ">> Verification completed."

# ── Step 4: Final VERIFIED result ───────────────────────────────────────────
line; echo "  STEP 4 — Final result (status = VERIFIED)"; line
curl -s "$BASE_URL/api/verify/result/$ENTITY_ID/" | pretty
echo
echo "Demo complete. entityId = $ENTITY_ID"
