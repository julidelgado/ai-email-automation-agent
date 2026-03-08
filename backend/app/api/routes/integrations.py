from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.integrations import (
    GoogleIntegrationConnectResponse,
    GoogleIntegrationDisconnectResponse,
    GoogleIntegrationStatusResponse,
)
from app.services.integrations.credential_store import GOOGLE_CALENDAR_PROVIDER
from app.services.integrations.google_oauth_service import GoogleOAuthIntegrationService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/google/status", response_model=GoogleIntegrationStatusResponse, status_code=status.HTTP_200_OK)
def google_status(db: Session = Depends(get_db)) -> GoogleIntegrationStatusResponse:
    service = GoogleOAuthIntegrationService(db)
    integration_status = service.get_status()
    return GoogleIntegrationStatusResponse(
        provider=GOOGLE_CALENDAR_PROVIDER,
        connected=integration_status.connected,
        oauth_ready=integration_status.oauth_ready,
        encryption_ready=integration_status.encryption_ready,
        calendar_enabled=integration_status.calendar_enabled,
        account_id=integration_status.account_id,
        expires_at=integration_status.expires_at,
        scopes=integration_status.scopes,
        has_refresh_token=integration_status.has_refresh_token,
    )


@router.get("/google/connect", response_model=GoogleIntegrationConnectResponse, status_code=status.HTTP_200_OK)
def google_connect(
    redirect: bool = Query(default=False, description="When true, return a browser redirect to Google auth."),
    db: Session = Depends(get_db),
) -> GoogleIntegrationConnectResponse | RedirectResponse:
    service = GoogleOAuthIntegrationService(db)
    try:
        auth_url = service.build_connect_url()
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if redirect:
        return RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    return GoogleIntegrationConnectResponse(provider=GOOGLE_CALENDAR_PROVIDER, auth_url=auth_url)


@router.get("/google/callback", status_code=status.HTTP_303_SEE_OTHER)
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error:
        return _dashboard_redirect(status_text="error", message=f"Google OAuth error: {error}")
    if not code:
        return _dashboard_redirect(status_text="error", message="Google OAuth callback missing authorization code.")
    if not state:
        return _dashboard_redirect(status_text="error", message="Google OAuth callback missing state parameter.")

    service = GoogleOAuthIntegrationService(db)
    try:
        service.handle_callback(code=code, state=state)
    except RuntimeError as exc:
        return _dashboard_redirect(status_text="error", message=str(exc))

    return _dashboard_redirect(status_text="connected", message="Google Calendar connected successfully.")


@router.post("/google/disconnect", response_model=GoogleIntegrationDisconnectResponse, status_code=status.HTTP_200_OK)
def google_disconnect(db: Session = Depends(get_db)) -> GoogleIntegrationDisconnectResponse:
    service = GoogleOAuthIntegrationService(db)
    disconnected_count = service.disconnect()
    return GoogleIntegrationDisconnectResponse(
        status="ok",
        provider=GOOGLE_CALENDAR_PROVIDER,
        disconnected_count=disconnected_count,
    )


def _dashboard_redirect(*, status_text: str, message: str) -> RedirectResponse:
    location = f"/dashboard?google_oauth={quote_plus(status_text)}&message={quote_plus(message)}"
    return RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)

