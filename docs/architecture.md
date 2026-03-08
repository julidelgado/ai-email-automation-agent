# Architecture (MVP)

## Core components

- **API layer (FastAPI):** Admin/API endpoints and health monitoring.
- **Ingestion layer:** Pulls incoming emails and normalizes content.
- **AI pipeline:** Intent classification + entity extraction.
- **Routing layer:** Maps intent and confidence to actions using configurable rules.
- **Action executors:** Performs downstream actions (forward invoice, create calendar event, create task).
- **Audit layer:** Stores model decisions and action outcomes (`action_events`) for traceability.
- **Scheduler:** Runs IMAP pull and classification jobs on configurable intervals.
- **Dashboard:** Provides manual action review and inline rule threshold/approval tuning.

## Runtime mode

- **Local-first** for a free MVP.
- SQLite for local persistence.
- Ollama as local LLM runtime.
- Optional external connectors are kept pluggable and disabled by default.

## Data flow

1. Email ingested and saved to `emails`.
2. AI classifies intent and stores output in `classifications`.
3. Extracted entities are persisted in `entities`.
4. Rules engine resolves action in `rules`.
5. Planned actions are persisted in `actions` (`pending_approval` by default).
6. Reviewer approves/rejects actions; approved actions execute and store outcomes.
7. Failed actions move to `retry_pending` with exponential backoff until max attempts.
8. Action lifecycle events are written to `action_events`.
9. Request actions create local records in `tasks`.

## Scheduled jobs

- `imap_pull_job`: pulls emails from IMAP on `APP_IMAP_PULL_INTERVAL_MINUTES`.
- `classification_job`: classifies pending emails on `APP_CLASSIFY_INTERVAL_MINUTES`.
- `action_planning_job`: plans actions for classified emails on `APP_ACTION_PLAN_INTERVAL_MINUTES`.
- `action_execution_job`: executes approved pending actions on `APP_ACTION_EXECUTION_INTERVAL_MINUTES`.
