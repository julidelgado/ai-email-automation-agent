# AI Email Automation Agent

Automates email workflows end to end: ingest -> classify -> extract entities -> plan actions -> approval/retry/dead-letter execution.

## Implemented capabilities

- IMAP ingestion with dedupe by `external_id`
- AI/rule-based classification (`invoice`, `meeting`, `request`, `other`)
- Entity extraction and routing rules with editable thresholds
- Action planner and executors:
  - `forward_to_accounting` (SMTP)
  - `schedule_calendar` (Google Calendar OAuth + refresh token)
  - `create_task` (local tasks table)
- Manual review dashboard (`/dashboard`)
- Retry with exponential backoff and dead-letter queue
- Idempotency guards for dispatch side effects
- Action audit timeline
- Structured JSON logs + error alerts + runtime metrics
- Docker deployment with PostgreSQL persistent volume + process manager (`supervisord`) running:
  - API server
  - scheduler worker

## Project layout

```text
backend/
  app/
  alembic/
  deploy/
  tests/
docs/
```

## Local quick start (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Docker deployment (recommended)

1. Configure env:

```powershell
Copy-Item backend\.env.example backend\.env
```

2. Ensure `backend/.env` has required integration values (`IMAP`, `SMTP`, Google OAuth, encryption key).

3. Run:

```powershell
docker compose up --build -d
```

4. Open:

- Dashboard: `http://127.0.0.1:8000/dashboard`
- Metrics dashboard: `http://127.0.0.1:8000/metrics`

PostgreSQL data is persisted in Docker volume `postgres_data`.

## API endpoints

- `GET /api/v1/health`
- `GET /api/v1/ready`
- `POST /api/v1/ingest/imap/pull`
- `POST /api/v1/pipeline/classify`
- `POST /api/v1/actions/plan`
- `GET /api/v1/actions`
- `POST /api/v1/actions/execute`
- `GET /api/v1/actions/dead-letter`
- `POST /api/v1/actions/{action_id}/requeue`
- `POST /api/v1/actions/{action_id}/approve`
- `POST /api/v1/actions/{action_id}/reject`
- `POST /api/v1/actions/{action_id}/execute`
- `GET /api/v1/actions/events`
- `GET /api/v1/tasks`
- `GET /api/v1/rules`
- `PATCH /api/v1/rules/{rule_id}`
- `PATCH /api/v1/rules/bulk`
- `GET /api/v1/integrations/google/status`
- `GET /api/v1/metrics`
- `GET /dashboard`
- `GET /metrics`

## Security and secrets

Enable Basic Auth:

```env
APP_SECURITY_BASIC_AUTH_ENABLED=true
APP_SECURITY_BASIC_AUTH_USERNAME=admin
APP_SECURITY_BASIC_AUTH_PASSWORD=change-this-password
```

Secret file options are supported for IMAP/SMTP/Google/Auth credentials using `*_FILE` variables.

## Observability env vars

```env
APP_LOG_LEVEL=INFO
APP_LOG_JSON=true
APP_ALERTS_ENABLED=false
APP_ALERTS_WEBHOOK_URL=
APP_ALERTS_WEBHOOK_TIMEOUT_SECONDS=8
APP_ALERTS_EMAIL_TO=
APP_ALERTS_MIN_INTERVAL_SECONDS=300
```
