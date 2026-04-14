"""User summary generation for completed sessions."""
from __future__ import annotations

import json
import logging

from .openai_client import chat_json

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_USER_SUMMARY = """
You summarize a user's conversation into a compact, useful profile.

Return STRICT JSON only:
{
  "user_type": "...",
  "main_issue": "...",
  "pressure_sources": ["..."],
  "distraction_sources": ["..."],
  "negative_thought_patterns": ["..."],
  "what_bothers_them_most": "...",
  "key_objects": ["..."]
}

Rules:
- Be descriptive, not clinical.
- Base everything only on the conversation and extracted slots.
- Keep each string short and concrete.
- Use empty arrays if something is unknown.
- user_type should be a short phrase like "overloaded and avoidant under pressure".
- key_objects means the concrete people, subjects, apps, deadlines, or situations mentioned.
"""


def generate_user_summary(
    initial_text: str,
    filled_slots: dict | None = None,
    conversation_history: list[dict] | None = None,
    emotion_signals: list[str] | None = None,
) -> dict:
    payload = {
        "initial_text": (initial_text or "")[:2000],
        "filled_slots": filled_slots or {},
        "conversation_history": (conversation_history or [])[-12:],
        "emotion_signals": emotion_signals or [],
    }

    empty = {
        "user_type": "",
        "main_issue": "",
        "pressure_sources": [],
        "distraction_sources": [],
        "negative_thought_patterns": [],
        "what_bothers_them_most": "",
        "key_objects": [],
    }

    try:
        resp = chat_json(
            model="gpt-4o-mini",
            system=SYSTEM_PROMPT_USER_SUMMARY,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=300,
            temperature=0.3,
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        result = empty.copy()
        for key in result:
            value = data.get(key)
            if isinstance(result[key], list):
                if isinstance(value, list):
                    result[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                if value is not None:
                    result[key] = str(value).strip()
        return result
    except Exception as exc:
        logger.warning("generate_user_summary failed: %s", exc)
        return empty


__all__ = ["generate_user_summary"]
