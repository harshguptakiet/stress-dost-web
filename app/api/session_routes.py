
"""Session routes."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..db.repo import create_session, get_session, save_session
from ..extensions import socketio
from ..realtime.scheduler import start_popup_simulation
from ..services.combo_answer_parser import PARSERS as COMBO_PARSERS
from ..services.combo_question_generator import generate_combo_question
from ..services.combo_specs import COMBO_SPECS
from ..services.fallbacks import CLARIFIER_QUESTION
from ..services.gpt_client import detect_causes, extract_components
from ..services.openai_client import transcribe_audio
from ..services.planner import (
    activate_domains_from_causes,
    pick_next_slot,
)
from ..services.popup_generator import generate_popups
from ..services.question_generator import (
    ai_ready_to_complete,
    generate_initial_clarifiers,
    generate_next_followup,
    generate_question,
    get_generic_domain_question,
)
from ..services.slot_manager import (
    add_negated_slots,
    get_missing_slots,
    infer_emotion_signals,
    is_slot_allowed,
    set_slot_value,
)
from ..services.slot_prefill_llm import prefill_slots_with_llm, update_state_with_user_reply
from ..services.slot_prefill_schema import SessionState
from ..services.relevance import combo_relevant, domain_relevant
from ..services.stop_engine import should_stop

bp = Blueprint("session", __name__, url_prefix="/session")


@bp.post("/transcribe")
def transcribe_session_audio():
    try:
        audio = request.files.get("audio")
        if not audio:
            return jsonify({"error": "audio file is required"}), 400

        transcript = transcribe_audio(audio)
        current_app.logger.info("transcribe_session_audio: transcript len=%s", len(transcript))
        if not transcript:
            return jsonify({"error": "could not transcribe audio"}), 400

        return jsonify({"text": transcript})
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("transcribe_session_audio failed: %s", exc)
        return jsonify({"error": "transcription failed", "detail": str(exc)}), 500


@bp.post("/start")
def start_session():
    try:
        body = request.get_json(force=True, silent=True) or {}
        text = (body.get("text") or "").strip()
        current_app.logger.info("start_session: incoming text len=%s", len(text))
        if not text:
            return jsonify({"error": "text is required"}), 400

        session = create_session(text)
        current_app.logger.info("start_session: created session_id=%s", session.id)

        prefill = prefill_slots_with_llm(text)
        current_app.logger.debug("start_session: prefill=%s", prefill)

        causes = detect_causes(text)
        current_app.logger.debug("start_session: causes=%s", causes)
        meta = dict(session.meta or {})
        meta["causes"] = causes
        meta["clarifier_queue"] = []
        if getattr(prefill, "extracted_state", None):
            meta["extracted_state"] = prefill.extracted_state.model_dump()
        raw_client = body.get("client_user")
        if isinstance(raw_client, dict):
            safe_user = {}
            for key in ("user_id", "display_name", "email", "mood"):
                val = raw_client.get(key)
                if isinstance(val, str):
                    val = val.strip()[:240]
                    if val:
                        safe_user[key] = val
            if safe_user:
                meta["client_user"] = safe_user
        session.meta = meta

        session.active_domains = prefill.active_domains or activate_domains_from_causes(causes)
        current_app.logger.debug("start_session: active_domains=%s", session.active_domains)

        for domain, slots in (prefill.prefill or {}).items():
            for slot, value in slots.items():
                set_slot_value(session.filled_slots, domain, slot, value)
        add_negated_slots(session.filled_slots, prefill.negated_slots or [])

        if not session.active_domains:
            session.active_domains = ["time_pressure", "distractions", "academic_confidence"]

        save_session(session)
        current_app.logger.info("start_session: saved session_id=%s", session.id)

        return jsonify(
            {
                "session_id": str(session.id),
                "status": session.status,
                "active_domains": session.active_domains,
                "prefilled": session.filled_slots,
            }
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("start_session failed: %s", exc)
        return jsonify({"error": "internal error", "detail": str(exc)}), 500


@bp.post("/<session_id>/answer")
def answer(session_id: str):
    session = get_session(session_id)
    current_app.logger.info("answer: session_id=%s", session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404
    if session.status != "active":
        return jsonify({"error": "session is not active"}), 400

    body = request.get_json(force=True, silent=True) or {}
    answer_text = (body.get("answer") or "").strip()

    meta = dict(session.meta or {})

    def _update_extracted_state(new_text: str) -> None:
        raw = meta.get("extracted_state") or {}
        try:
            current_state = SessionState(**raw)
        except Exception:
            current_state = SessionState()
        updated = update_state_with_user_reply(current_state, new_text)
        meta["extracted_state"] = updated.model_dump()

    current_question = meta.get("current_question") or {}
    if current_question.get("type") == "clarifier":
        clarifier_answers = list(meta.get("clarifier_answers") or [])
        clarifier_answers.append({"question": current_question.get("question"), "answer": answer_text})
        meta["clarifier_answers"] = clarifier_answers
        meta["current_question"] = None
        _update_extracted_state(answer_text)
        session.meta = meta
        session.history.append({"role": "user", "text": answer_text})
        save_session(session)
        return jsonify({"ok": True, "clarifier": True, "meta": session.meta})

    if current_question.get("type") == "combo":
        combo_id = current_question.get("combo_id")
        parser = COMBO_PARSERS.get(combo_id)
        if parser:
            parsed = parser(answer_text)
            if not parsed:
                hint = COMBO_SPECS.get(combo_id, {}).get("hint", "")
                return jsonify(
                    {
                        "need_clarification": True,
                        "question": f"Please follow the format:\n{hint}",
                    }
                )

            for key, value in parsed["slots"].items():
                domain_key, slot_key = key.split(".", 1)
                set_slot_value(session.filled_slots, domain_key, slot_key, value)

            emotion = parsed.get("emotion")
            if emotion:
                signals = list(meta.get("emotion_signals") or [])
                signals.append(emotion)
                meta["emotion_signals"] = signals

            meta["current_question"] = None
            _update_extracted_state(answer_text)
            session.meta = meta
            session.history.append({"role": "user", "text": answer_text})
            save_session(session)
            return jsonify({"ok": True, "filled_slots": session.filled_slots, "meta": session.meta})

    domain = body.get("domain")
    slot = body.get("slot")
    domain = domain or current_question.get("domain")
    slot = slot or current_question.get("slot")
    current_app.logger.debug("answer: domain=%s slot=%s", domain, slot)

    if not (domain and slot):
        return jsonify({"error": "domain/slot missing (no current_question found)"}), 400

    if not is_slot_allowed(domain, slot):
        return jsonify({"error": "invalid domain/slot"}), 400

    if not answer_text:
        return jsonify({"error": "answer is required"}), 400

    clarifier_used = list(meta.get("clarifier_used") or [])
    key = f"{domain}.{slot}"
    if len(answer_text.split()) < 2 and key not in clarifier_used:
        clarifier_used.append(key)
        meta["clarifier_used"] = clarifier_used
        meta["current_question"] = {
            "domain": domain,
            "slot": slot,
            "question": CLARIFIER_QUESTION,
        }
        session.meta = meta

        session.history.append({"role": "user", "text": answer_text})
        session.history.append({"role": "assistant", "text": CLARIFIER_QUESTION})
        save_session(session)
        return jsonify(
            {
                "need_clarification": True,
                "domain": domain,
                "slot": slot,
                "question": CLARIFIER_QUESTION,
            }
        )

    session.history.append({"role": "user", "text": answer_text})
    set_slot_value(session.filled_slots, domain, slot, answer_text)
    meta["current_question"] = None
    _update_extracted_state(answer_text)
    session.meta = meta

    save_session(session)
    return jsonify({"ok": True, "filled_slots": session.filled_slots, "meta": session.meta})


@bp.post("/<session_id>/next-question")
def next_question(session_id: str):
    session = get_session(session_id)
    current_app.logger.info("next_question: session_id=%s", session_id)
    if not session or session.status != "active":
        return jsonify({"error": "invalid session"}), 400

    meta = dict(session.meta or {})
    current_q = meta.get("current_question")
    if current_q:
        return jsonify(
            {
                "done": False,
                "domain": current_q.get("domain"),
                "slot": current_q.get("slot"),
                "question": current_q.get("question"),
                "meta": session.meta,
                "pending": True,
                "message": "Answer the current question first",
            }
        )

    asked_questions = [
        item.get("text", "")
        for item in (session.history or [])
        if isinstance(item, dict) and item.get("role") == "assistant"
    ]
    total_questions = int(meta.get("total_questions_asked", 0))
    min_required_questions = max(3, int(current_app.config.get("MIN_QUESTIONS", 3)))

    if total_questions >= min_required_questions:
        ready, reason = ai_ready_to_complete(
            session.raw_initial_text or "",
            conversation_history=session.history or [],
            asked_questions=asked_questions,
        )
        if ready:
            current_app.logger.info("next_question: ai completed session reason=%s", reason)
            return _complete_session(session)

    asked_hashes = {" ".join((q or "").strip().lower().split()) for q in asked_questions if q}

    followup = generate_next_followup(
        user_text=session.raw_initial_text or "",
        asked_questions=asked_questions,
        conversation_history=session.history or [],
    )
    followup_norm = " ".join((followup or "").strip().lower().split())
    if followup and followup_norm not in asked_hashes:
        meta["current_question"] = {"type": "clarifier", "question": followup}
        meta["total_questions_asked"] = total_questions + 1
        session.meta = meta
        session.history.append({"role": "assistant", "text": followup})
        save_session(session)
        return jsonify(
            {
                "done": False,
                "clarifier": True,
                "question": followup,
                "meta": session.meta,
            }
        )

    if not session.active_domains:
        session.active_domains = extract_components(session.raw_initial_text or "")

    if not session.active_domains:
        causes = meta.get("causes")
        if not causes:
            causes = detect_causes(session.raw_initial_text or "")
            meta["causes"] = causes
            session.meta = meta
        session.active_domains = activate_domains_from_causes(causes)

    if not session.active_domains:
        session.active_domains = ["time_pressure", "distractions", "academic_confidence"]

    missing = get_missing_slots(session.active_domains, session.filled_slots)

    def _is_missing(domain: str, slot: str) -> bool:
        return not session.filled_slots.get(domain, {}).get(slot)

    domain_counts = dict(meta.get("domain_question_count") or {})
    combo_history = set(meta.get("combo_history") or [])
    raw_text = session.raw_initial_text or ""

    combo_spec_id = None
    combo_spec = None

    if total_questions <= 2:
        if (
            "friend_compare_emotion" not in combo_history
            and combo_relevant("friend_compare_emotion", raw_text)
            and domain_relevant("social_comparison", raw_text)
            and (
                _is_missing("distractions", "friend_name")
                or _is_missing("social_comparison", "comparison_person")
                or _is_missing("social_comparison", "comparison_gap")
            )
        ):
            combo_spec_id = "friend_compare_emotion"
        elif (
            "distraction_time_combo" not in combo_history
            and combo_relevant("distraction_time_combo", raw_text)
            and domain_relevant("distractions", raw_text)
            and domain_relevant("time_pressure", raw_text)
            and (
                _is_missing("distractions", "gaming_app")
                or _is_missing("distractions", "gaming_time")
                or _is_missing("time_pressure", "timetable_breaker")
            )
        ):
            combo_spec_id = "distraction_time_combo"

    if combo_spec_id:
        combo_spec = COMBO_SPECS[combo_spec_id]
        question = generate_combo_question(combo_spec_id, session, session.raw_initial_text or "")
    if combo_spec_id and combo_spec and question:
        current_app.logger.info("next_question: serving combo %s", combo_spec_id)
        meta["total_questions_asked"] = total_questions + 1
        meta["current_question"] = {
            "type": "combo",
            "combo_id": combo_spec_id,
            "question": question,
        }
        history = list(combo_history)
        history.append(combo_spec_id)
        meta["combo_history"] = history
        session.meta = meta
        session.history.append({"role": "assistant", "text": question})
        save_session(session)
        return jsonify(
            {
                "done": False,
                "combo": True,
                "question": question,
                "hint": combo_spec["hint"],
                "meta": session.meta,
            }
        )
    elif combo_spec_id and not question:
        combo_spec_id = None

    if should_stop(
        total_questions_asked=total_questions,
        missing_slots_count=len(missing),
        min_questions=min_required_questions,
        max_questions=current_app.config["MAX_QUESTIONS"],
    ):
        return _complete_session(session)

    question = None
    domain = slot = None
    attempts = 0
    max_attempts = len(missing) + 3

    while attempts < max_attempts:
        missing = get_missing_slots(session.active_domains, session.filled_slots)
        next_slot = pick_next_slot(
            session.active_domains,
            missing,
            domain_counts,
            current_app.config["MAX_DOMAIN_QUESTIONS"],
            session.raw_initial_text or "",
            session.filled_slots,
            meta.get("causes") or {},
        )
        if not next_slot:
            return _complete_session(session)

        domain, slot = next_slot
        current_app.logger.debug("next_question: picked domain=%s slot=%s", domain, slot)
        profile = session.filled_slots or {}
        domain_profile = profile.get(domain) or {}

        excerpt = None
        if domain == "academic_confidence":
            weak = domain_profile.get("weak_subject") or ""
            last = domain_profile.get("last_test_experience") or ""
            if weak or last:
                excerpt = f"Weak in {weak}. Last test felt {last}."
        elif domain == "family_pressure":
            expect = domain_profile.get("expectation_type") or ""
            member = domain_profile.get("family_member") or ""
            if expect or member:
                excerpt = f"Family member {member} expects {expect}."
        elif domain == "distractions":
            friend = domain_profile.get("friend_name") or ""
            app = domain_profile.get("phone_app") or ""
            if friend or app:
                excerpt = f"Distractions include {friend} and app {app}."

        last_question = (meta.get("last_question") or "").strip()
        context = {
            "user_text": session.raw_initial_text or "",
            "filled_slots": session.filled_slots,
            "domain": domain,
            "slot": slot,
            "causes": meta.get("causes") or {},
        }
        context["meta"] = {
            "last_question": last_question,
            "clarifier_answers": meta.get("clarifier_answers") or [],
        }

        if slot == "__generic__":
            generic = get_generic_domain_question(domain)
            if generic:
                next_slot, generic_question = generic
                if generic_question == last_question:
                    add_negated_slots(session.filled_slots, [next_slot])
                    attempts += 1
                    continue
                slot, question = next_slot, generic_question
                break
            attempts += 1
            continue

        question = generate_question(domain, slot, excerpt=excerpt, context=context)
        if question:
            break

        generic = get_generic_domain_question(domain)
        if generic:
            next_slot, generic_question = generic
            if generic_question == last_question:
                add_negated_slots(session.filled_slots, [next_slot])
                attempts += 1
                continue
            slot, question = next_slot, generic_question
            break

        add_negated_slots(session.filled_slots, [slot])
        attempts += 1

    if not question:
        return _complete_session(session)

    session.history.append({"role": "assistant", "text": question})
    meta["total_questions_asked"] = total_questions + 1
    domain_counts[domain] = int(domain_counts.get(domain, 0)) + 1
    meta["domain_question_count"] = domain_counts
    meta["current_question"] = {"domain": domain, "slot": slot, "question": question}
    meta["last_question"] = question
    session.meta = meta

    save_session(session)

    return jsonify(
        {
            "done": False,
            "domain": domain,
            "slot": slot,
            "question": question,
            "meta": session.meta,
        }
    )


@bp.get("/<session_id>/status")
def status(session_id: str):
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404
    return jsonify(
        {
            "session_id": str(session.id),
            "status": session.status,
            "active_domains": session.active_domains,
            "filled_slots": session.filled_slots,
            "meta": session.meta,
        }
    )


@bp.get("/<session_id>/debug")
def debug_session(session_id: str):
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404
    return jsonify(
        {
            "id": str(session.id),
            "status": session.status,
            "popups_count": len(session.popups or []),
            "popups": session.popups or [],
            "filled_slots": session.filled_slots,
            "meta": session.meta,
        }
    )


@bp.post("/<session_id>/complete")
def complete_session_early(session_id: str):
    """Mark session as completed early when user skips remaining questions."""
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404

    if session.status == "completed":
        return jsonify(
            {
                "ok": True,
                "already_completed": True,
                "popups_count": len(session.popups or []),
            }
        )

    return _complete_session(session)


@bp.post("/<session_id>/start-simulation")
def start_simulation(session_id: str):
    session = get_session(session_id)
    if not session or session.status != "completed":
        return jsonify({"error": "session not completed"}), 400

    start_popup_simulation(session_id, session.popups or [])
    return jsonify({"ok": True, "popups_scheduled": len(session.popups or [])})


@bp.post("/<session_id>/test-popup")
def test_popup(session_id: str):
    session = get_session(session_id)
    if not session:
        return jsonify({"error": "session not found"}), 404

    payload = {
        "type": "distraction",
        "message": "Test popup ✅\nIf you see this, WS works.",
        "ttl": 8000,
    }
    socketio.emit("popup", payload, room=str(session_id))
    return jsonify({"ok": True, "sent": True, "payload": payload})




def _complete_session(session):
    session.status = "completed"
    stress_profile = session.filled_slots or {}
    stress_profile["__raw_text__"] = session.raw_initial_text or ""
    # pass clarifier answers to popup generator for personalization
    meta = dict(session.meta or {})
    clarifier_answers = meta.get("clarifier_answers")
    if clarifier_answers:
        stress_profile["__clarifiers__"] = clarifier_answers
    inferred_signals = infer_emotion_signals(stress_profile)
    stored_signals = (session.meta or {}).get("emotion_signals") or []
    emotion_signals = list(dict.fromkeys(stored_signals + inferred_signals))
    popups = generate_popups(stress_profile, emotion_signals)
    session.popups = popups
    save_session(session)
    return jsonify(
        {
            "done": True,
            "status": session.status,
            "popups_ready": True,
            "popups_count": len(session.popups or []),
            "filled_slots": session.filled_slots,
        }
    )
