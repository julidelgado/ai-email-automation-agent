from __future__ import annotations

import json
from urllib.parse import quote
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.services.actions.google_oauth_token_service import GoogleOAuthTokenService


class GoogleCalendarClient:
    def __init__(
        self,
        settings: Settings | None = None,
        token_service: GoogleOAuthTokenService | None = None,
        db: Session | None = None,
    ):
        self.settings = settings or get_settings()
        self.token_service = token_service or GoogleOAuthTokenService(self.settings, db=db)

    def create_event(
        self,
        *,
        summary: str,
        description: str,
        start_iso: str,
        end_iso: str,
        timezone_name: str,
    ) -> dict:
        if not self.settings.google_calendar_enabled:
            raise RuntimeError("Google Calendar integration is disabled. Set APP_GOOGLE_CALENDAR_ENABLED=true.")

        calendar_id = quote(self.settings.google_calendar_calendar_id, safe="")
        base_url = self.settings.google_calendar_base_url.rstrip("/")
        url = f"{base_url}/calendars/{calendar_id}/events"

        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso, "timeZone": timezone_name},
            "end": {"dateTime": end_iso, "timeZone": timezone_name},
        }

        token = self.token_service.get_access_token()
        try:
            return self._post_event(url=url, payload=payload, token=token)
        except PermissionError:
            if not self.token_service.can_refresh():
                raise RuntimeError("Google Calendar unauthorized and refresh token flow is not configured.")
            refreshed_token = self.token_service.get_access_token(force_refresh=True)
            return self._post_event(url=url, payload=payload, token=refreshed_token)

    def _post_event(self, *, url: str, payload: dict, token: str) -> dict:
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 401:
                raise PermissionError(f"Unauthorized: {detail}") from exc
            raise RuntimeError(f"Google Calendar HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Google Calendar connection error: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Google Calendar returned non-JSON response.") from exc
