from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from functools import lru_cache
import json
import logging
import smtplib
import threading
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from app.config import Settings, get_settings
from app.observability.metrics import get_metrics_registry

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._last_sent_by_key: dict[str, float] = {}

    def send_error_alert(
        self,
        *,
        title: str,
        message: str,
        source: str,
        dedupe_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if not self.settings.alerts_enabled:
            return False

        key = (dedupe_key or f"{source}:{title}").strip().lower()
        if not key:
            key = "default"

        now_ts = datetime.now(timezone.utc).timestamp()
        if self._is_rate_limited(key=key, now_ts=now_ts):
            logger.info(
                "Alert suppressed by cooldown.",
                extra={"event": "alert_suppressed", "source": source, "dedupe_key": key},
            )
            return False

        payload = {
            "title": title,
            "message": message,
            "source": source,
            "service": self.settings.name,
            "environment": self.settings.environment,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": details or {},
        }

        delivered = False
        attempted_channel = False
        if self.settings.alerts_webhook_url:
            attempted_channel = True
            delivered = self._send_webhook(payload=payload) or delivered
        if self.settings.alerts_email_to:
            attempted_channel = True
            delivered = self._send_email(payload=payload) or delivered

        if delivered:
            with self._lock:
                self._last_sent_by_key[key] = now_ts
        elif not attempted_channel:
            logger.warning(
                "Alerting is enabled but no delivery channel is configured.",
                extra={"event": "alert_config_missing", "source": source},
            )
            get_metrics_registry().record_alert(
                delivered=False,
                channel="config",
                error_message="No alert delivery channel configured.",
            )

        return delivered

    def _is_rate_limited(self, *, key: str, now_ts: float) -> bool:
        cooldown = max(0, int(self.settings.alerts_min_interval_seconds))
        if cooldown <= 0:
            return False
        with self._lock:
            previous = self._last_sent_by_key.get(key)
        if previous is None:
            return False
        return now_ts - previous < float(cooldown)

    def _send_webhook(self, *, payload: dict[str, Any]) -> bool:
        if not self.settings.alerts_webhook_url:
            return False
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        request = urllib_request.Request(
            self.settings.alerts_webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=max(1, self.settings.alerts_webhook_timeout_seconds)) as response:
                status_code = getattr(response, "status", 200)
                if 200 <= int(status_code) < 300:
                    logger.info("Alert delivered to webhook.", extra={"event": "alert_sent", "channel": "webhook"})
                    get_metrics_registry().record_alert(delivered=True, channel="webhook")
                    return True
                error_text = f"Webhook returned status {status_code}."
                logger.warning(
                    "Alert webhook delivery failed.",
                    extra={"event": "alert_failed", "channel": "webhook", "error": error_text},
                )
                get_metrics_registry().record_alert(delivered=False, channel="webhook", error_message=error_text)
                return False
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError) as exc:
            logger.warning(
                "Alert webhook delivery failed.",
                extra={"event": "alert_failed", "channel": "webhook", "error": str(exc)},
            )
            get_metrics_registry().record_alert(delivered=False, channel="webhook", error_message=str(exc))
            return False

    def _send_email(self, *, payload: dict[str, Any]) -> bool:
        recipient = self.settings.alerts_email_to
        if not recipient:
            return False

        sender = self.settings.smtp_from_email or self.settings.smtp_username
        if not sender:
            error_text = "SMTP sender is not configured for alert email."
            logger.warning("Alert email delivery failed.", extra={"event": "alert_failed", "channel": "email", "error": error_text})
            get_metrics_registry().record_alert(delivered=False, channel="email", error_message=error_text)
            return False
        if not self.settings.smtp_host:
            error_text = "SMTP host is not configured for alert email."
            logger.warning("Alert email delivery failed.", extra={"event": "alert_failed", "channel": "email", "error": error_text})
            get_metrics_registry().record_alert(delivered=False, channel="email", error_message=error_text)
            return False

        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = f"[{self.settings.name}] {payload.get('title', 'Error Alert')}"
        message.set_content(
            "\n".join(
                [
                    f"Service: {payload.get('service')}",
                    f"Environment: {payload.get('environment')}",
                    f"Source: {payload.get('source')}",
                    f"Timestamp: {payload.get('timestamp')}",
                    "",
                    f"Message: {payload.get('message')}",
                    "",
                    f"Details: {json.dumps(payload.get('details', {}), ensure_ascii=True)}",
                ]
            )
        )

        smtp = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20)
        try:
            if self.settings.smtp_use_tls:
                smtp.starttls()
            if self.settings.smtp_username and self.settings.smtp_password:
                smtp.login(self.settings.smtp_username, self.settings.smtp_password)
            smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning(
                "Alert email delivery failed.",
                extra={"event": "alert_failed", "channel": "email", "error": str(exc)},
            )
            get_metrics_registry().record_alert(delivered=False, channel="email", error_message=str(exc))
            return False
        finally:
            try:
                smtp.quit()
            except OSError:
                pass

        logger.info("Alert delivered by email.", extra={"event": "alert_sent", "channel": "email"})
        get_metrics_registry().record_alert(delivered=True, channel="email")
        return True


@lru_cache
def get_alert_service() -> AlertService:
    return AlertService(get_settings())
