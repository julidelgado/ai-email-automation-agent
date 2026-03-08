# API Contracts (Phase 1)

## Health

- **Method:** `GET`
- **Path:** `/api/v1/health`
- **Response example:**

```json
{
  "status": "ok",
  "service": "AI Email Automation Agent",
  "environment": "development",
  "timestamp": "2026-03-08T12:00:00Z"
}
```

## Readiness

- **Method:** `GET`
- **Path:** `/api/v1/ready`
- **Response example:**

```json
{
  "status": "ready",
  "checks": {
    "database": "ok"
  },
  "timestamp": "2026-03-08T12:00:01Z"
}
```

## IMAP Pull

- **Method:** `POST`
- **Path:** `/api/v1/ingest/imap/pull`
- **Request example:**

```json
{
  "mailbox": "INBOX",
  "unseen_only": true,
  "limit": 25
}
```

- **Response example:**

```json
{
  "status": "ok",
  "mailbox": "INBOX",
  "fetched": 10,
  "inserted": 8,
  "duplicates": 2,
  "failed": 0
}
```

## Classify Pending

- **Method:** `POST`
- **Path:** `/api/v1/pipeline/classify`
- **Request example:**

```json
{
  "limit": 25,
  "statuses": ["new"]
}
```

- **Response example:**

```json
{
  "status": "ok",
  "matched": 12,
  "processed": 12,
  "failed": 0
}
```

## Plan Actions

- **Method:** `POST`
- **Path:** `/api/v1/actions/plan`
- **Request example:**

```json
{
  "limit": 25,
  "statuses": ["classified"]
}
```

- **Response example:**

```json
{
  "status": "ok",
  "matched": 10,
  "planned": 9,
  "skipped": 1,
  "failed": 0
}
```

## Approve Action

- **Method:** `POST`
- **Path:** `/api/v1/actions/{action_id}/approve`
- **Request example:**

```json
{
  "execute_now": true
}
```

## Reject Action

- **Method:** `POST`
- **Path:** `/api/v1/actions/{action_id}/reject`
- **Request example:**

```json
{
  "reason": "Manual rejection reason"
}
```

## Execute Pending Actions

- **Method:** `POST`
- **Path:** `/api/v1/actions/execute`
- **Request example:**

```json
{
  "limit": 25,
  "statuses": ["pending", "retry_pending"]
}
```

## List Action Events

- **Method:** `GET`
- **Path:** `/api/v1/actions/events`
- **Query params:**
  - `action_id` (optional)
  - `limit` (optional, default 100)

## Review Dashboard

- **Method:** `GET`
- **Path:** `/dashboard`
- **Description:** Minimal web UI for manual review/approval of actions and execution monitoring.

## List Rules

- **Method:** `GET`
- **Path:** `/api/v1/rules`
- **Description:** Returns routing rules used for action planning.

## Update Rule

- **Method:** `PATCH`
- **Path:** `/api/v1/rules/{rule_id}`
- **Request example:**

```json
{
  "min_confidence": 0.82,
  "requires_approval": true,
  "is_active": true
}
```

## Bulk Update Rules

- **Method:** `PATCH`
- **Path:** `/api/v1/rules/bulk`
- **Request example:**

```json
{
  "rules": [
    {
      "id": 1,
      "min_confidence": 0.9,
      "requires_approval": false,
      "is_active": true
    },
    {
      "id": 3,
      "min_confidence": 0.7,
      "requires_approval": true,
      "is_active": false
    }
  ]
}
```
