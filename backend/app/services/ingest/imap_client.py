from __future__ import annotations

import imaplib

from app.config import Settings, get_settings
from app.services.ingest.types import FetchedMessage


class ImapClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def validate_configuration(self) -> None:
        missing = []
        if not self.settings.imap_host:
            missing.append("APP_IMAP_HOST")
        if not self.settings.imap_username:
            missing.append("APP_IMAP_USERNAME")
        if not self.settings.imap_password:
            missing.append("APP_IMAP_PASSWORD")

        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(f"IMAP is not configured. Missing: {missing_str}")

    def fetch_messages(self, mailbox: str, unseen_only: bool, limit: int) -> list[FetchedMessage]:
        self.validate_configuration()

        connection = self._connect()
        try:
            status, _ = connection.login(self.settings.imap_username or "", self.settings.imap_password or "")
            if status != "OK":
                raise RuntimeError("IMAP login failed.")

            status, _ = connection.select(mailbox, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Cannot select mailbox '{mailbox}'.")

            criteria = "UNSEEN" if unseen_only else "ALL"
            status, search_data = connection.uid("search", None, criteria)
            if status != "OK":
                raise RuntimeError("IMAP search failed.")

            uid_values = self._extract_uid_values(search_data)
            if limit > 0 and len(uid_values) > limit:
                uid_values = uid_values[-limit:]

            messages: list[FetchedMessage] = []
            for uid in uid_values:
                status, fetch_data = connection.uid("fetch", uid, "(RFC822)")
                if status != "OK":
                    continue
                raw_message = self._extract_raw_message(fetch_data)
                if not raw_message:
                    continue
                messages.append(FetchedMessage(uid=uid.decode("utf-8", errors="ignore"), raw_message=raw_message))

            return messages
        finally:
            try:
                connection.logout()
            except imaplib.IMAP4.error:
                pass

    def _connect(self):
        if self.settings.imap_use_ssl:
            return imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port)
        return imaplib.IMAP4(self.settings.imap_host, self.settings.imap_port)

    @staticmethod
    def _extract_uid_values(search_data) -> list[bytes]:
        if not search_data:
            return []
        raw_uids = search_data[0]
        if not raw_uids:
            return []
        return raw_uids.split()

    @staticmethod
    def _extract_raw_message(fetch_data) -> bytes | None:
        for item in fetch_data:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        return None

