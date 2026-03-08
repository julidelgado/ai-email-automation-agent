from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    name: str = "AI Email Automation Agent"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./app.db"
    log_level: str = "INFO"
    log_json: bool = True

    ai_provider: str = "ollama"
    ollama_model: str = "qwen2.5:7b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: int = 20

    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_password_file: str | None = None
    imap_default_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    scheduler_enabled: bool = True
    scheduler_timezone: str = "UTC"
    imap_pull_interval_minutes: int = 5
    imap_pull_unseen_only: bool = True
    imap_pull_limit: int = 25
    classify_interval_minutes: int = 2
    classify_batch_size: int = 25
    action_plan_interval_minutes: int = 2
    action_plan_batch_size: int = 25
    action_execution_interval_minutes: int = 1
    action_execution_batch_size: int = 25

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_password_file: str | None = None
    smtp_use_tls: bool = True
    smtp_from_email: str | None = None

    action_invoice_accounting_email: str | None = None
    action_meeting_default_duration_minutes: int = 30
    action_calendar_timezone: str = "UTC"
    action_max_attempts: int = 3
    action_retry_base_seconds: int = 60
    action_retry_max_seconds: int = 3600

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_client_secret_file: str | None = None
    google_redirect_uri: str | None = None
    credentials_encryption_key: str | None = None
    credentials_encryption_key_file: str | None = None
    google_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_oauth_state_ttl_seconds: int = 600
    google_calendar_scopes: str = "https://www.googleapis.com/auth/calendar.events"

    google_calendar_enabled: bool = False
    google_calendar_access_token: str | None = None
    google_calendar_access_token_file: str | None = None
    google_calendar_refresh_token: str | None = None
    google_calendar_refresh_token_file: str | None = None
    google_calendar_calendar_id: str = "primary"
    google_calendar_base_url: str = "https://www.googleapis.com/calendar/v3"

    alerts_enabled: bool = False
    alerts_webhook_url: str | None = None
    alerts_webhook_timeout_seconds: int = 8
    alerts_email_to: str | None = None
    alerts_min_interval_seconds: int = 300

    security_basic_auth_enabled: bool = False
    security_basic_auth_username: str | None = None
    security_basic_auth_password: str | None = None
    security_basic_auth_password_file: str | None = None

    @model_validator(mode="after")
    def resolve_file_backed_secrets(self):
        self.imap_password = _resolve_secret(self.imap_password, self.imap_password_file, "APP_IMAP_PASSWORD_FILE")
        self.smtp_password = _resolve_secret(self.smtp_password, self.smtp_password_file, "APP_SMTP_PASSWORD_FILE")
        self.google_client_secret = _resolve_secret(
            self.google_client_secret,
            self.google_client_secret_file,
            "APP_GOOGLE_CLIENT_SECRET_FILE",
        )
        self.google_calendar_access_token = _resolve_secret(
            self.google_calendar_access_token,
            self.google_calendar_access_token_file,
            "APP_GOOGLE_CALENDAR_ACCESS_TOKEN_FILE",
        )
        self.google_calendar_refresh_token = _resolve_secret(
            self.google_calendar_refresh_token,
            self.google_calendar_refresh_token_file,
            "APP_GOOGLE_CALENDAR_REFRESH_TOKEN_FILE",
        )
        self.credentials_encryption_key = _resolve_secret(
            self.credentials_encryption_key,
            self.credentials_encryption_key_file,
            "APP_CREDENTIALS_ENCRYPTION_KEY_FILE",
        )
        self.security_basic_auth_password = _resolve_secret(
            self.security_basic_auth_password,
            self.security_basic_auth_password_file,
            "APP_SECURITY_BASIC_AUTH_PASSWORD_FILE",
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _resolve_secret(value: str | None, file_path: str | None, variable_name: str) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not file_path:
        return value

    path = Path(file_path).expanduser()
    if not path.exists():
        raise ValueError(f"{variable_name} points to a missing file: {path}")

    secret_value = path.read_text(encoding="utf-8").strip()
    if not secret_value:
        raise ValueError(f"{variable_name} points to an empty file: {path}")
    return secret_value
