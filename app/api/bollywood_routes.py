"""AI-backed Bollywood fact routes."""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from flask import Blueprint, jsonify, request

from ..services.openai_client import chat_json, chat_text

logger = logging.getLogger(__name__)

bp = Blueprint("bollywood", __name__, url_prefix="/api/bollywood")


SYSTEM_PROMPT = """
You generate ONE concise factual Bollywood-oriented update for a distraction popup.

Output STRICT JSON only:
{
  "title": "...",
  "summary": "...",
    "detail": "...",
    "joke": "...",
  "source": "...",
    "topic": "movies|music|sports|games|technology|health|science|world"
}

Rules:
- If force_topic=true in input, you MUST keep content on topic_hint and must not drift to movies unless topic_hint is movies.
- If force_topic is false and no specific preference is present, Bollywood/movie relevance is allowed.
- Use the provided student_profile and recent_context to personalize the angle.
- Prefer a topic that matches student interests when possible.
- Avoid repeating any title listed in avoid_titles.
- Keep title under 110 chars.
- Keep summary under 260 chars.
- Keep detail under 260 chars.
- Keep joke under 140 chars.
- Must sound factual and neutral, not motivational.
- Joke should be light and harmless, related to the same update context.
- No markdown. No extra keys.
- If specific real-time claims are uncertain, generate an evergreen factual-style update.
"""


def _extract_first_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def _normalize_ai_payload(data: dict[str, Any], topic_hint: str, force_topic: bool = False) -> dict[str, Any] | None:
    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    detail = str(data.get("detail") or "").strip()
    joke = str(data.get("joke") or "").strip()
    source = str(data.get("source") or "AI Fact Wire").strip() or "AI Fact Wire"
    topic = _normalize_topic(str(topic_hint if force_topic else (data.get("topic") or topic_hint)))

    if not title:
        return None
    if not summary:
        summary = "Quick factual update generated from your recent response pattern."
    if not detail:
        detail = "Audience engagement data indicates this trend continues to hold attention among student age groups."
    if not joke:
        joke = "Director said one more take; students said one more attempt."

    if force_topic and topic_hint != "movies":
        drift_text = f"{title} {summary}".lower()
        if re.search(r"\b(movie|movies|film|cinema|actor|actress|bollywood|box office)\b", drift_text):
            return None

    return {
        "title": title[:110],
        "summary": summary[:260],
        "detail": detail[:260],
        "joke": joke[:140],
        "source": source[:60],
        "topic": topic,
        "fallback": False,
    }


def _generate_with_ai(payload: dict[str, Any], topic_hint: str, force_topic: bool = False) -> dict[str, Any] | None:
    preferred_model = os.getenv("BOLLYWOOD_AI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    model_candidates = [preferred_model]
    for extra in ("gpt-4o-mini", "gpt-5-mini"):
        if extra not in model_candidates:
            model_candidates.append(extra)

    for model in model_candidates:
        # Attempt 1: strict JSON response format.
        try:
            response = chat_json(
                model=model,
                system=SYSTEM_PROMPT,
                user=json.dumps(payload, ensure_ascii=False),
                temperature=0.65,
            )
            data = _extract_first_json_object(response.choices[0].message.content or "")
            if isinstance(data, dict):
                normalized = _normalize_ai_payload(data, topic_hint, force_topic=force_topic)
                if normalized:
                    return normalized
        except Exception as exc:
            logger.info("reel_fact chat_json failed model=%s reason=%s", model, exc)

        # Attempt 2: free text with explicit JSON instruction.
        try:
            response = chat_text(
                model=model,
                system=SYSTEM_PROMPT,
                user=(
                    f"{json.dumps(payload, ensure_ascii=False)}\n"
                    "Return valid JSON only. No markdown, no extra text."
                ),
                temperature=0.65,
            )
            data = _extract_first_json_object(response.choices[0].message.content or "")
            if isinstance(data, dict):
                normalized = _normalize_ai_payload(data, topic_hint, force_topic=force_topic)
                if normalized:
                    return normalized
        except Exception as exc:
            logger.info("reel_fact chat_text failed model=%s reason=%s", model, exc)

    return None


def _normalize_topic(value: str) -> str:
    topic = " ".join((value or "").strip().lower().split())
    allowed = {"movies", "music", "sports", "games", "technology", "health", "science", "world"}
    if topic in allowed:
        return topic
    return "movies"


@bp.post("/reel-fact")
def reel_fact():
    body = request.get_json(force=True, silent=True) or {}
    topic_hint = _normalize_topic(str(body.get("topic_hint") or "movies"))
    force_topic = bool(body.get("force_topic"))
    followup_answers = body.get("followup_answers")
    student_profile_raw = body.get("student_profile")
    avoid_titles_raw = body.get("avoid_titles")
    variation_seed = body.get("variation_seed")

    student_profile = student_profile_raw if isinstance(student_profile_raw, dict) else {}
    student_name = str(student_profile.get("name") or "").strip()[:60]
    student_emotion = str(student_profile.get("emotion") or "").strip()[:30]

    interests_raw = student_profile.get("interests")
    interests: list[str] = []
    if isinstance(interests_raw, list):
        for item in interests_raw[:6]:
            value = str(item or "").strip().lower()
            if value:
                interests.append(value[:40])

    recent_context_raw = student_profile.get("recent_context")
    recent_context: list[str] = []
    if isinstance(recent_context_raw, list):
        for item in recent_context_raw[:4]:
            value = str(item or "").strip()
            if value:
                recent_context.append(value[:180])

    avoid_titles: list[str] = []
    if isinstance(avoid_titles_raw, list):
        for item in avoid_titles_raw[:8]:
            value = str(item or "").strip()
            if value:
                avoid_titles.append(value[:110])

    if not isinstance(followup_answers, list):
        followup_answers = []

    compact_answers = []
    for item in followup_answers[-12:]:
        if not isinstance(item, dict):
            continue
        compact_answers.append(
            {
                "answer": str(item.get("answer") or "")[:240],
                "domain": str(item.get("domain") or "")[:80],
                "slot": str(item.get("slot") or "")[:80],
            }
        )

    payload: dict[str, Any] = {
        "topic_hint": topic_hint,
        "force_topic": force_topic,
        "followup_answers": compact_answers,
        "student_profile": {
            "name": student_name,
            "emotion": student_emotion,
            "interests": interests,
            "recent_context": recent_context,
        },
        "avoid_titles": avoid_titles,
        "variation_seed": variation_seed,
        "priority": "Respect explicit interest topic when provided.",
        "randomize_if_missing_context": True,
        "instruction": (
            "If follow-up context is empty, generate a random factual update aligned with topic_hint. "
            "If student_profile has interests, tailor the update angle to those interests. "
            "If force_topic=true, keep title and summary on topic_hint and avoid movie/bollywood drift unless topic_hint is movies. "
            "Avoid repeating titles from avoid_titles."
        ),
    }

    try:
        generated = _generate_with_ai(payload, topic_hint, force_topic=force_topic)
        if generated:
            return jsonify(generated)
        raise ValueError("no valid AI payload from model candidates")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("reel_fact fallback topic=%s reason=%s", topic_hint, exc)
        fallback_by_topic = {
            "games": {
                "title": "Game-style sprint planning is helping students handle timed tests",
                "summary": "Students using quick strategy loops from competitive gaming report better pacing under exam pressure.",
                "detail": "Early coaching reports suggest checkpoint thinking from gaming improves decision speed in timed sections.",
                "joke": "Final boss today is the timer, not the game lobby.",
                "source": "Game Insight Desk",
                "topic": "games",
            },
            "technology": {
                "title": "AI study tools are changing revision speed for students",
                "summary": "Students are combining short AI summaries with self-notes to revise larger portions faster.",
                "detail": "Educators report improved topic coverage when students use concise AI outlines before deep study rounds.",
                "joke": "AI can summarize chapters, but not your excuses.",
                "source": "Tech Brief",
                "topic": "technology",
            },
            "sports": {
                "title": "Micro-break drills from sports are being used for exam stamina",
                "summary": "Short reset routines from athletic training are now common in long test practice sessions.",
                "detail": "Mentors note better late-section performance when students follow structured reset intervals.",
                "joke": "Coach said hydrate, student heard celebrate.",
                "source": "Sports Analytics Desk",
                "topic": "sports",
            },
            "music": {
                "title": "Low-distraction playlists remain top pick during revision blocks",
                "summary": "Students report calmer focus when using predictable instrumental tracks during timed practice.",
                "detail": "Playback behavior shows lower skip rates with ambient loops compared to lyric-heavy tracks.",
                "joke": "Playlist ended; panic playlist started.",
                "source": "Audio Trends",
                "topic": "music",
            },
            "health": {
                "title": "Hydration and sleep timing remain key for stable exam focus",
                "summary": "Campus wellness checks keep linking basic routines to better concentration under pressure.",
                "detail": "Students with regular sleep windows show steadier timing and fewer decision dips in mock tests.",
                "joke": "Water bottle is now class topper.",
                "source": "Health Notes",
                "topic": "health",
            },
            "science": {
                "title": "Sleep consistency still correlates with better next-day recall",
                "summary": "Learning science findings continue to show improved recall with stable sleep habits.",
                "detail": "Irregular sleep patterns are repeatedly linked to slower retrieval during timed assessments.",
                "joke": "Night owl met morning exam and forgot the script.",
                "source": "Science Digest",
                "topic": "science",
            },
            "world": {
                "title": "Student mobility trends continue across major education hubs",
                "summary": "Cross-city movement for specialized programs remains high among senior students.",
                "detail": "Policy and placement patterns indicate flexibility-first decisions are increasing each term.",
                "joke": "Suitcase is ready before the admission letter.",
                "source": "Global Education Watch",
                "topic": "world",
            },
            "movies": {
                "title": "Bollywood box office trends continue to favor youth-focused stories",
                "summary": "Recent Indian film audience patterns show stronger traction for fast-paced, emotionally relatable cinema among students.",
                "detail": "Streaming and campus viewing behavior both indicate higher repeat watchability for emotionally direct story arcs.",
                "joke": "Exam hall has one hero too: the one who remembers formulas after interval.",
                "source": "Fallback Fact Desk",
                "topic": "movies",
            },
        }
        chosen_fallback = fallback_by_topic.get(topic_hint) or fallback_by_topic["movies"]
        return jsonify(
            {
                **chosen_fallback,
                "fallback": True,
            }
        )
