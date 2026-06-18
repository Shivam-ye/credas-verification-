# Credas Identity Verification API

A production-grade Django REST API that integrates with [Credas](https://portal.credasdemo.com)
for identity verification. It creates a verification journey for a user, triggers
the Credas verification email, returns a magic link for iFrame embedding, receives
the Credas completion webhook, and exposes the final verified / not-verified result.

---

## Features

- **Clean architecture** — views, serializers, services, and models are fully separated.
- **All config from `.env`** — no API keys, IDs, or URLs hardcoded anywhere.
- **Consistent JSON envelope** — every response is `{"success": ..., "data"|"error": ...}`.
- **Robust error handling** — custom `CredasAPIException`, every external call wrapped.
- **Webhook-safe** — the webhook endpoint is CSRF-exempt and always returns `200` so
  Credas never retries and creates duplicates.
- **Full logging** — every Credas call, DB save, webhook, and error is logged to the
  console and `credas_verification.log`.

---

## Project structure

```
credas_verification/
├── manage.py
├── .env                          # all secrets/config (gitignored)
├── .env.example                  # template without values
├── requirements.txt
├── credas_verification/          # project package
│   ├── settings.py               # loads .env via python-dotenv
│   ├── urls.py
│   └── wsgi.py
└── verification/                 # app
    ├── models.py                 # VerificationRecord
    ├── serializers.py            # input/output validation
    ├── services/
    │   └── credas_service.py     # ALL Credas API calls + CredasAPIException
    ├── views.py                  # endpoint logic
    ├── urls.py                   # routing
    ├── utils.py                  # response helpers + reference generator
    └── admin.py
```

---

## Setup

This project uses a Conda environment named `credasv2` (Python 3.11).

```bash
# 1. Create & activate the environment
conda create -y -n credasv2 python=3.11
conda activate credasv2

# 2. Install dependencies
cd credas_verification
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env          # then fill in real values

# 4. Run migrations
python manage.py migrate

# 5. Start the server
python manage.py runserver
```

The API is then available at `http://localhost:8000/api/`.

---

## Configuration (`.env`)

| Variable             | Description                                      |
|----------------------|--------------------------------------------------|
| `CREDAS_BASE_URL`    | Credas API base URL                              |
| `CREDAS_API_KEY`     | Credas API key (sent as the `x-api-key` header)  |
| `CREDAS_JOURNEY_ID`  | Identity journey ID                              |
| `CREDAS_ACTOR_ID`    | Actor ID for the process entity                  |
| `CREDAS_WEBHOOK_URL` | URL Credas POSTs to on completion                |
| `DJANGO_SECRET_KEY`  | Django secret key                                |
| `DEBUG`              | `True` / `False`                                 |
| `ALLOWED_HOSTS`      | Comma-separated allowed hosts (e.g. `*`)         |

> `.env` is gitignored. Never commit real credentials — only `.env.example`.

---

## API endpoints

### 1. Initiate verification

`POST /api/verify/initiate/`

Creates the Credas entity + process, triggers the verification email, and returns
a backup magic link.

**Request**
```json
{
  "firstName": "Shivam",
  "surname": "Test",
  "email": "shivam.yehsu@yopmail.com",
  "phone": "9876543221",
  "documentType": "passport"
}
```
`documentType` must be one of: `passport`, `driving_licence`, `national_id`.

**Response — `201`**
```json
{
  "success": true,
  "data": {
    "entityId": "uuid",
    "processId": "uuid",
    "verificationLink": "https://myconnect.credasdemo.com/landing?...",
    "emailSent": true,
    "message": "Verification email sent to shivam.yehsu@yopmail.com. Magic link also provided as backup."
  }
}
```

### 2. Credas webhook

`POST /api/webhook/credas/`

Called by Credas when the user completes verification. CSRF-exempt; **always returns
`200`**. It re-fetches the authoritative entity summary from Credas and updates the
local record (status, verified flag, completion time, raw result, and detail fields).

**Request (from Credas)**
```json
{ "processId": "uuid", "clientId": "uuid", "status": 2 }
```

**Response — `200`**
```json
{ "success": true, "data": { "received": true } }
```

### 3. Get result

`GET /api/verify/result/{entityId}/`

Returns the stored result from the database.

**Response — `200` (completed)**
```json
{
  "success": true,
  "data": {
    "entityId": "uuid",
    "name": "Shivam Test",
    "email": "shivam@example.com",
    "verified": true,
    "status": "VERIFIED",
    "documentType": "passport",
    "createdAt": "2026-06-18T10:00:00Z",
    "completedAt": "2026-06-18T10:05:00Z",
    "details": {
      "documentResult": 1,
      "livenessResult": 1,
      "nameMatchResult": 1,
      "documentNumber": "P1234567",
      "overallResult": 1
    }
  }
}
```

**Response — `200` (pending)**
```json
{
  "success": true,
  "data": {
    "entityId": "uuid",
    "verified": false,
    "status": "PENDING",
    "details": null,
    "message": "User has not completed verification yet"
  }
}
```

**Response — `404` (not found)**
```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "No verification record found for this entityId"
  }
}
```

---

## Result mapping

Credas `overallResult` values map to local status as follows:

| Credas value | Status         | `verified` |
|--------------|----------------|------------|
| `0`          | `PENDING`      | `false`    |
| `1`          | `VERIFIED`     | `true`     |
| `2`          | `NOT_VERIFIED` | `false`    |

---

## End-to-end flow

1. `POST /api/verify/initiate/` → user receives the Credas email; a `PENDING` record is saved.
2. User opens the email (or the returned `verificationLink`) and completes the flow.
3. Credas POSTs to `/api/webhook/credas/` → the record is updated with the final result.
4. `GET /api/verify/result/{entityId}/` → returns `VERIFIED` / `NOT_VERIFIED`.

---

## Manual test commands

```bash
# Initiate
curl -X POST http://localhost:8000/api/verify/initiate/ \
  -H "Content-Type: application/json" \
  -d '{"firstName":"Shivam","surname":"Test","email":"shivam.yehsu@yopmail.com","phone":"9876543221","documentType":"passport"}'

# Result
curl http://localhost:8000/api/verify/result/{entityId}/

# Webhook (simulate Credas)
curl -X POST http://localhost:8000/api/webhook/credas/ \
  -H "Content-Type: application/json" \
  -d '{"processId":"{processId}","status":2}'
```

---

## Logging

Logs are written to both the console and `credas_verification.log` (project root),
covering every Credas request/response, DB save, webhook payload, and error.

---

## Tech stack

- Django 4.2
- Django REST Framework 3.14
- python-dotenv 1.0
- requests 2.31
- SQLite (swap the `DATABASES` setting for Postgres/MySQL in production)
