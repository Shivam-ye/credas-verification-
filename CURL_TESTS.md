# curl Test Cases — Verification API

Base URL assumes the dev server: `http://localhost:8000`
All routes are mounted under `/api/`.

Set a reusable base variable first:

```bash
export BASE=http://localhost:8000/api
```

Every endpoint returns the shared JSON envelope:
- Success: `{"success": true, "data": {...}}`
- Error:   `{"success": false, "error": {"code": "...", "message": "...", "details": ...}}`

---

## 1. POST /api/verify/initiate/ — start a verification journey

### 1.1 Happy path (valid input) → 201 Created
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "Jane",
    "surname": "Doe",
    "email": "jane.doe@example.com",
    "phone": "+447700900123",
    "documentType": "passport"
  }'
```
Expect `201` with `data.entityId`, `data.processId`, `data.verificationLink`,
`data.emailSent: true`.

### 1.2 Missing required field (no `email`) → 400 VALIDATION_ERROR
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "Jane",
    "surname": "Doe",
    "phone": "+447700900123",
    "documentType": "passport"
  }'
```
Expect `400`, `error.code: "VALIDATION_ERROR"`, `error.details.email` present.

### 1.3 Invalid email format → 400 VALIDATION_ERROR
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "Jane",
    "surname": "Doe",
    "email": "not-an-email",
    "phone": "+447700900123",
    "documentType": "passport"
  }'
```
Expect `400`, `error.details.email`.

### 1.4 Invalid documentType (not in choices) → 400 VALIDATION_ERROR
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "Jane",
    "surname": "Doe",
    "email": "jane.doe@example.com",
    "phone": "+447700900123",
    "documentType": "id_card"
  }'
```
Expect `400`. Valid values: `passport`, `driving_licence`, `national_id`.

### 1.5 Field over max length (firstName > 100 chars) → 400 VALIDATION_ERROR
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d "{
    \"firstName\": \"$(printf 'A%.0s' {1..101})\",
    \"surname\": \"Doe\",
    \"email\": \"jane.doe@example.com\",
    \"phone\": \"+447700900123\",
    \"documentType\": \"passport\"
  }"
```
Expect `400`, `error.details.firstName`.

### 1.6 Empty body → 400 VALIDATION_ERROR
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{}'
```
Expect `400` listing all required fields.

### 1.7 Malformed JSON → 400 (parse error)
```bash
curl -i -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{ "firstName": "Jane", '
```
Expect `400` parse error from DRF.

### 1.8 Wrong method (GET on initiate) → 405 Method Not Allowed
```bash
curl -i -X GET "$BASE/verify/initiate/"
```
Expect `405`.

> Note: cases 1.1 depends on Credas being reachable. If the upstream Credas
> call fails, expect `502` with `error.code: "CREDAS_API_ERROR"`.

---

## 2. POST /api/webhook/credas/ — Credas completion callback

This endpoint is CSRF-exempt, unauthenticated, and **always returns 200** so
Credas does not retry.

### 2.1 Valid webhook with known processId → 200
```bash
# Replace PROCESS_ID with a processId returned from an initiate call.
curl -i -X POST "$BASE/webhook/credas/" \
  -H "Content-Type: application/json" \
  -d '{
    "processId": "PROCESS_ID",
    "status": "completed"
  }'
```
Expect `200`, `data.received: true`. The matching record is updated from the
authoritative Credas entity summary.

### 2.2 Missing processId → 200 (ignored)
```bash
curl -i -X POST "$BASE/webhook/credas/" \
  -H "Content-Type: application/json" \
  -d '{ "status": "completed" }'
```
Expect `200`, `data.received: true` (payload logged and ignored).

### 2.3 Unknown processId → 200 (ignored)
```bash
curl -i -X POST "$BASE/webhook/credas/" \
  -H "Content-Type: application/json" \
  -d '{ "processId": "does-not-exist-123" }'
```
Expect `200`, `data.received: true`.

### 2.4 Empty / non-dict body → 200 (ignored)
```bash
curl -i -X POST "$BASE/webhook/credas/" \
  -H "Content-Type: application/json" \
  -d '[]'
```
Expect `200`, `data.received: true`.

### 2.5 Wrong method (GET) → 405
```bash
curl -i -X GET "$BASE/webhook/credas/"
```
Expect `405`.

---

## 3. GET /api/verify/result/{entityId}/ — fetch stored result

### 3.1 Existing record, still PENDING → 200 (minimal shape)
```bash
# Use an entityId from an initiate call before the user completes the journey.
curl -i "$BASE/verify/result/ENTITY_ID/"
```
Expect `200` with `data.status: "PENDING"`, `data.verified: false`,
`data.details: null`.

### 3.2 Existing record, completed → 200 (full details)
```bash
curl -i "$BASE/verify/result/ENTITY_ID/"
```
Expect `200` with `data.status` of `VERIFIED` / `NOT_VERIFIED` / `FAILED`,
`data.verified`, and a populated `data.details` block (`documentResult`,
`livenessResult`, `nameMatchResult`, `documentNumber`, `overallResult`).

### 3.3 Unknown entityId → 404 NOT_FOUND
```bash
curl -i "$BASE/verify/result/non-existent-entity/"
```
Expect `404`, `error.code: "NOT_FOUND"`.

### 3.4 Wrong method (POST) → 405
```bash
curl -i -X POST "$BASE/verify/result/ENTITY_ID/"
```
Expect `405`.

---

## End-to-end flow (chaining with jq)

```bash
# 1. Initiate and capture entityId + processId.
RESP=$(curl -s -X POST "$BASE/verify/initiate/" \
  -H "Content-Type: application/json" \
  -d '{
    "firstName": "Jane",
    "surname": "Doe",
    "email": "jane.doe@example.com",
    "phone": "+447700900123",
    "documentType": "passport"
  }')

ENTITY_ID=$(echo "$RESP" | jq -r '.data.entityId')
PROCESS_ID=$(echo "$RESP" | jq -r '.data.processId')
echo "entity=$ENTITY_ID process=$PROCESS_ID"

# 2. Poll the result (PENDING until the user completes).
curl -s "$BASE/verify/result/$ENTITY_ID/" | jq

# 3. Simulate the Credas completion webhook.
curl -s -X POST "$BASE/webhook/credas/" \
  -H "Content-Type: application/json" \
  -d "{\"processId\": \"$PROCESS_ID\"}" | jq

# 4. Re-fetch the now-updated result.
curl -s "$BASE/verify/result/$ENTITY_ID/" | jq
```
