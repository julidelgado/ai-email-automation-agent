from __future__ import annotations

import base64
import binascii
import hmac
from typing import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from app.config import Settings

_HEALTH_SUFFIXES = {"/health", "/ready"}


def validate_security_configuration(settings: Settings) -> None:
    if not settings.security_basic_auth_enabled:
        return

    missing = []
    if not (settings.security_basic_auth_username or "").strip():
        missing.append("APP_SECURITY_BASIC_AUTH_USERNAME")
    if not (settings.security_basic_auth_password or "").strip():
        missing.append("APP_SECURITY_BASIC_AUTH_PASSWORD or APP_SECURITY_BASIC_AUTH_PASSWORD_FILE")
    if missing:
        missing_csv = ", ".join(missing)
        raise RuntimeError(f"Basic auth is enabled but required settings are missing: {missing_csv}")


def build_basic_auth_middleware(
    settings: Settings,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def basic_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not settings.security_basic_auth_enabled:
            return await call_next(request)

        path = request.url.path
        if not _requires_auth(path=path, api_prefix=settings.api_v1_prefix):
            return await call_next(request)

        if _has_valid_credentials(request=request, settings=settings):
            return await call_next(request)

        return _unauthorized_response(path=path, api_prefix=settings.api_v1_prefix)

    return basic_auth_middleware


def _requires_auth(*, path: str, api_prefix: str) -> bool:
    if path == "/dashboard" or path.startswith("/dashboard/"):
        return True
    if path == "/metrics" or path.startswith("/metrics/"):
        return True
    if path.startswith(api_prefix):
        for suffix in _HEALTH_SUFFIXES:
            if path == f"{api_prefix}{suffix}":
                return False
        return True
    return False


def _has_valid_credentials(*, request: Request, settings: Settings) -> bool:
    authorization = request.headers.get("Authorization") or request.headers.get("authorization")
    if not authorization:
        return False

    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        return False

    scheme, encoded = parts
    if scheme.lower() != "basic":
        return False

    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
    except (UnicodeDecodeError, binascii.Error):
        return False

    if ":" not in decoded:
        return False

    username, password = decoded.split(":", 1)
    expected_username = (settings.security_basic_auth_username or "").strip()
    expected_password = (settings.security_basic_auth_password or "").strip()
    return hmac.compare_digest(username, expected_username) and hmac.compare_digest(password, expected_password)


def _unauthorized_response(*, path: str, api_prefix: str) -> Response:
    headers = {"WWW-Authenticate": 'Basic realm="AI Email Automation Agent", charset="UTF-8"'}
    if path.startswith(api_prefix):
        return JSONResponse(status_code=401, content={"detail": "Authentication required."}, headers=headers)
    return PlainTextResponse("Authentication required.", status_code=401, headers=headers)
