from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import Settings, get_settings
from app.models.email import Email
from app.services.ai.types import ClassificationOutput, ExtractedEntity

ALLOWED_INTENTS = {"invoice", "meeting", "request", "other"}


class OllamaAIProvider:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def analyze_email(self, email: Email) -> ClassificationOutput:
        prompt = self._build_prompt(email)
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        response_body = self._request_generate(payload)
        response_json = json.loads(response_body)

        raw_output = response_json.get("response")
        if not isinstance(raw_output, str):
            raise ValueError("Ollama response does not include a valid JSON payload in 'response'.")

        model_output = json.loads(raw_output)
        return self._parse_output(model_output)

    def _request_generate(self, payload: dict) -> str:
        base_url = self.settings.ollama_base_url.rstrip("/")
        request = urllib.request.Request(
            url=f"{base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.ollama_timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama connection error: {exc.reason}") from exc

    def _parse_output(self, payload: dict) -> ClassificationOutput:
        intent_value = str(payload.get("intent", "other")).strip().lower()
        intent = intent_value if intent_value in ALLOWED_INTENTS else "other"

        confidence_raw = payload.get("confidence", 0.5)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(confidence, 1.0))

        rationale_raw = payload.get("rationale")
        rationale = str(rationale_raw).strip() if isinstance(rationale_raw, str) and rationale_raw.strip() else None

        entities = self._parse_entities(payload.get("entities"), default_type=intent)

        return ClassificationOutput(
            intent=intent,
            confidence=confidence,
            rationale=rationale,
            entities=entities,
            model_name=f"ollama:{self.settings.ollama_model}",
            model_version=None,
        )

    def _parse_entities(self, raw_entities, default_type: str) -> list[ExtractedEntity]:
        if not isinstance(raw_entities, list):
            return []

        parsed_entities: list[ExtractedEntity] = []
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                continue

            key = raw_entity.get("entity_key")
            if not isinstance(key, str) or not key.strip():
                continue

            entity_type_raw = raw_entity.get("entity_type")
            entity_type = (
                entity_type_raw.strip().lower()
                if isinstance(entity_type_raw, str) and entity_type_raw.strip()
                else default_type
            )

            value_text_raw = raw_entity.get("value_text")
            value_text = value_text_raw.strip() if isinstance(value_text_raw, str) and value_text_raw.strip() else None

            value_json = raw_entity.get("value_json")
            if not isinstance(value_json, (dict, list)):
                value_json = None

            confidence = None
            raw_confidence = raw_entity.get("confidence")
            if raw_confidence is not None:
                try:
                    confidence = float(raw_confidence)
                    confidence = max(0.0, min(confidence, 1.0))
                except (TypeError, ValueError):
                    confidence = None

            parsed_entities.append(
                ExtractedEntity(
                    entity_type=entity_type,
                    entity_key=key.strip().lower(),
                    value_text=value_text,
                    value_json=value_json,
                    confidence=confidence,
                )
            )

        return parsed_entities

    def _build_prompt(self, email: Email) -> str:
        subject = email.subject or ""
        body_text = email.body_text or email.body_html or ""
        body_excerpt = body_text.strip()[:4000]

        return f"""
You are an email automation classifier.
Classify the email intent into exactly one of: invoice, meeting, request, other.
Extract key entities from the email.

Return only strict JSON with this schema:
{{
  "intent": "invoice|meeting|request|other",
  "confidence": 0.0,
  "rationale": "short reason",
  "entities": [
    {{
      "entity_type": "invoice|meeting|request|other",
      "entity_key": "string_key",
      "value_text": "string or null",
      "value_json": {{}} or [] or null,
      "confidence": 0.0
    }}
  ]
}}

Email metadata:
- sender: {email.sender}
- subject: {subject}
- body:
{body_excerpt}
""".strip()

