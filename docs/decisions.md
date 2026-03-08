# Technical Decisions

## D-001: Python + FastAPI backend

- **Status:** Accepted
- **Reason:** Fast delivery, clean async support, strong ecosystem for APIs and integrations.

## D-002: SQLite first, Postgres-ready schema

- **Status:** Accepted
- **Reason:** Zero-cost local development while retaining straightforward migration path to Postgres.

## D-003: Local AI via Ollama for MVP

- **Status:** Accepted
- **Reason:** Free runtime, local privacy, and no dependency on paid API keys in early phases.

## D-004: Rule-driven routing with confidence thresholds

- **Status:** Accepted
- **Reason:** Safer automation and explicit control over when to auto-run vs require approval.

## D-005: Scheduled background orchestration with APScheduler

- **Status:** Accepted
- **Reason:** Simple, lightweight interval-based execution for local-first automation workloads.

## D-006: Ollama-first with rule-based fallback

- **Status:** Accepted
- **Reason:** Keeps local AI capability while preserving deterministic classification if Ollama is unavailable.

## D-007: Manual approval as default for action execution

- **Status:** Accepted
- **Reason:** Prevents high-impact automatic actions until confidence/rules are validated in real usage.

## D-008: Local task persistence for request actions

- **Status:** Accepted
- **Reason:** Keeps request handling fully local and testable before integrating external task systems.

## D-009: Exponential backoff retries for failed actions

- **Status:** Accepted
- **Reason:** Improves robustness against transient connector and network failures while bounding retry cost.

## D-010: Action audit timeline persistence

- **Status:** Accepted
- **Reason:** Provides traceability for planning, approvals, retries, execution, and failures.

## D-011: Google Calendar REST integration for meetings

- **Status:** Accepted
- **Reason:** Enables real downstream scheduling actions while preserving a safe draft fallback when disabled.

## D-012: OAuth refresh-token flow for Google Calendar access tokens

- **Status:** Accepted
- **Reason:** Prevents manual access-token rotation and keeps scheduled execution resilient over long runtimes.
