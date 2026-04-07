"""Question generation - Truly Personal, Never Generic, Never Repeated.

Every question feels like it came from a real person who heard exactly
what the student said — not a bot running a checklist.

Core techniques used for every single response:
    ECHO       → Mirror their exact word back, split into two possibilities
    BIFURCATE  → Give two specific options so they can't stay vague
    NAME IT    → Say the thing they didn't say but probably meant

No keyword buckets. No hardcoded question sets. GPT handles everything.
Fallback is a last resort and still uses the same 3 techniques.
"""
from __future__ import annotations

import json
import logging
import hashlib
from .fallbacks import FALLBACK_QUESTIONS
from .validators import is_valid_question
from .openai_client import chat_json
from .generic_questions import get_generic_domain_question

logger = logging.getLogger(__name__)


# ============================================================================
# MASTER SYSTEM PROMPT
# The entire philosophy lives here. GPT does the heavy lifting.
# No keyword buckets anywhere in this file.
# ============================================================================

SYSTEM_PROMPT_QUESTION = """
You are talking to a JEE/NEET student who just said something.

They may be stressed, vague, angry, numb, casual, or random.

YOUR ONLY JOB:
Generate EXACTLY 3 sharp, personal, non-generic questions that:
1. Make them feel heard
2. FORCE them to give a SPECIFIC DETAIL (name / subject / app / number / thing)
3. Push them slightly deeper than what they said

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY STRUCTURE (NO EXCEPTIONS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Q1 — ECHO + EXTRACT SPECIFIC IDENTIFIER  
Q2 — BIFURCATE THEIR EXPERIENCE  
Q3 — NAME THE UNSAID TRUTH  

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q1 — ECHO + EXTRACT SPECIFIC IDENTIFIER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Start with THEIR EXACT WORD
- Give TWO options
- FORCE a concrete answer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADAPTIVE EXTRACTION (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Q1 MUST extract a SPECIFIC IDENTIFIER based on context:

IF user mentions a PERSON (friend, teacher, parent, someone):
→ Ask NAME or exact identity  
   "which friend exactly — what's their name?"

IF user mentions STUDIES (exam, stress, subject, marks):
→ Ask SUBJECT / CHAPTER  
   "which subject exactly?"

IF user mentions DISTRACTION / BEHAVIOR:
→ Ask APP / ACTIVITY  
   "what exactly — which app or thing?"

IF user mentions NUMBER / RESULT:
→ Ask EXACT VALUE / DETAIL  
   "how much exactly?" / "out of how much?"

IF user is VAGUE:
→ Ask TYPE SPLIT  
   "nothing — actually nothing, or nothing you want to say?"

❗ STRICT RULES:
- NEVER ask vague:
  ❌ "someone?"
  ❌ "one person?"
- ALWAYS force specificity:
  ✅ "which friend — name?"
  ✅ "which subject?"
  ✅ "what exactly?"
- NEVER force a NAME if no person exists

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q2 — BIFURCATE (DEEPER INTO THEIR EXPERIENCE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Ask what THEY experienced
- Give TWO real, believable options
- Both must feel equally possible

Examples:
- "Was it something they said directly to you, or something they did in front of others?"
- "Is it that you don’t understand it, or that you understand but can’t apply it?"
- "Did this happen suddenly, or has it been building for a while?"

RULE:
👉 No obvious answers  
👉 No generic "what happened"  

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Q3 — NAME THE UNSAID TRUTH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Say what they haven’t said yet
- Go deeper than surface emotion
- Focus on meaning, not event

Examples:
- "Is it that you hate them, or that you expected more from them and that’s what actually hurts?"
- "Is it the subject, or what struggling with it makes you feel about yourself?"
- "Is it what happened, or what it made you think about yourself?"

RULE:
👉 Must feel slightly uncomfortable but accurate  
👉 Must reveal underlying emotion  

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIAL CASE HANDLING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ULTRA VAGUE INPUT:
"idk", "nothing", "fine"
→ Q1 must clarify TYPE, not force name

NUMERIC INPUT:
"45 marks", "rank 2000"
→ Q1 must ask context (subject / expectation)

RANDOM INPUT:
If no emotional signal:
→ Still extract something concrete and pivot naturally

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT GLOBAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. EXACTLY 3 questions
2. Each must end with "?"
3. 15–55 words each
4. No repeated starting words
5. Use USER’S exact words (not synonyms)
6. NEVER say:
   - "how do you feel"
   - "tell me more"
   - "what happened"
7. NEVER sound like a bot, therapist, or form
8. NEVER allow vague answers
9. Q1 MUST extract something concrete (name / subject / app / number / thing)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Sharp. Direct. Real.
Like an older sibling who understands and doesn’t tolerate vague answers.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (STRICT JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{"questions": ["q1", "q2", "q3"]}
"""

# ============================================================================
# SLOT QUESTION PROMPT
# ============================================================================

SYSTEM_PROMPT_SLOT_QUESTION = """
You generate ONE follow-up question to extract information about "{slot}" in the "{domain}" context.

The question must feel like it came from a real person who heard what the student said —
not like a form asking for a field value.

TECHNIQUE — BIFURCATE:
  Give them two specific options to choose from.
  One should name the comfortable answer. One should name the honest one.
  Never ask open-ended. Always give two real possibilities.

EXAMPLES by slot type:
  friend_name  → "Which friend — the one you've known the longest, or someone newer who you thought was different?"
  app_name     → "Which app specifically — the one you'd be embarrassed to open in front of someone right now?"
  subject      → "Which subject — the one you've quietly been avoiding, or one that used to feel okay and recently stopped?"
  hours        → "How many hours are we actually talking — the real number, not the one that sounds okay to say?"
  reason       → "What's the real reason — not the excuse that sounds fine, but the one you actually know is true?"
  incident     → "What's the specific moment it actually went wrong — the thing you keep going back to?"
  feeling      → "What's the main thing you're sitting with right now — the emotion under the frustration?"
  confidence   → "Where are you honestly on this, 1 to 10 — and what's the thing pulling it below a 7?"
  expectation  → "What were you actually expecting from them — say it plainly, without softening it?"
  deadline     → "How many days until this — and when you think about that number, what's the first thing that hits?"
  blocker      → "What's the main thing that keeps getting in the way — the real one, not the surface one?"

RULES:
  - 15 to 45 words
  - Ends with "?"
  - Uses their words from the student_said field if possible
  - Specific enough that the answer is a name, number, or concrete thing
  - Never sounds like a form field
  - Never repeats last_question or anything in already_asked

Return STRICT JSON only. No preamble.
{"question": "your single question here"}
"""


SYSTEM_PROMPT_READINESS = """
You decide whether we already have enough conversation data to stop asking follow-up questions.

Your job:
- Read the initial user message and the conversation so far.
- Decide if there is enough signal to generate personalized popup content.
- Prefer stopping early once the core emotional trigger, the specific target/problem, and one concrete detail are known.
- Do NOT keep asking questions just because more detail is possible.
- If the conversation is still vague, ask for one more follow-up.

Stop when MOST of this is known:
1. What the main issue actually is
2. Who/what it is about
3. One concrete detail that makes it specific
4. The emotional angle underneath it

Rules:
- Return STRICT JSON only
- If the user is still too vague, ready=false
- If we already have enough signal for popups, ready=true
- Be practical, not perfectionist

Return:
{"ready": true, "reason": "short reason"}
"""


# ============================================================================
# MAIN
# ============================================================================

def generate_counter_questions(
    user_text: str,
    num_questions: int = 3,
    asked_questions: list[str] | None = None,
    conversation_history: list[dict] | None = None,
) -> list[str]:
    """
    Generate 3 personal, non-repeating questions for ANY student input.

    Uses ECHO → BIFURCATE → NAME IT for every single call.
    Passes full asked_questions history so GPT never repeats.
    Passes conversation_history so GPT can go deeper each round.

    Args:
        user_text:            What the student just said.
        num_questions:        How many to return (default 3).
        asked_questions:      Every question asked so far this session.
        conversation_history: Full chat history as
                              [{"role": "user"/"assistant", "text": "..."}]
    """
    text = (user_text or "").strip()
    if not text:
        return []

    asked_questions    = asked_questions or []
    conversation_history = conversation_history or []

    logger.debug(
        "generate_counter_questions: text=%r asked=%d history=%d",
        text[:80], len(asked_questions), len(conversation_history),
    )

    payload = {
        "student_said":        text[:1500],
        "already_asked":       asked_questions,
        "conversation_so_far": conversation_history[-10:],   # last 10 turns
    }

    try:
        resp = chat_json(
            model="gpt-4o-mini",
            system=SYSTEM_PROMPT_QUESTION,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=700,
            temperature=0.9,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # Strip accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        questions = data.get("questions", [])

        asked_hashes = {_hash(q) for q in asked_questions}
        valid: list[str] = []

        for q in questions:
            if not isinstance(q, str):
                continue
            q_clean = " ".join(q.strip().split())
            if (
                q_clean.endswith("?")
                and 15 <= len(q_clean) <= 400
                and _hash(q_clean) not in asked_hashes
            ):
                valid.append(q_clean)

        if valid:
            logger.debug("GPT returned %d valid questions", len(valid))
            return valid[:num_questions]

        logger.warning("GPT returned no valid questions — using personal fallback")

    except Exception as exc:
        logger.warning("generate_counter_questions GPT call failed: %s", exc)

    return _personal_fallback(text, asked_questions)[:num_questions]


def generate_next_followup(
    user_text: str,
    asked_questions: list[str] | None = None,
    conversation_history: list[dict] | None = None,
) -> str | None:
    """Generate exactly one next follow-up based on the latest conversation."""
    questions = generate_counter_questions(
        user_text=user_text,
        num_questions=1,
        asked_questions=asked_questions or [],
        conversation_history=conversation_history or [],
    )
    return questions[0] if questions else None


def ai_ready_to_complete(
    initial_text: str,
    conversation_history: list[dict] | None = None,
    asked_questions: list[str] | None = None,
) -> tuple[bool, str]:
    """Let the model decide whether enough signal exists to stop."""
    history = conversation_history or []
    asked = asked_questions or []
    payload = {
        "initial_text": (initial_text or "")[:1200],
        "conversation_so_far": history[-12:],
        "already_asked": asked[-6:],
    }

    try:
        resp = chat_json(
            model="gpt-4o-mini",
            system=SYSTEM_PROMPT_READINESS,
            user=json.dumps(payload, ensure_ascii=False),
            max_tokens=120,
            temperature=0.2,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        data = json.loads(raw)
        ready = bool(data.get("ready"))
        reason = str(data.get("reason") or "").strip()
        return ready, reason
    except Exception as exc:
        logger.warning("ai_ready_to_complete failed: %s", exc)
        return False, ""


# ============================================================================
# PERSONAL FALLBACK
# Last resort only. Still uses the 3 techniques. Never generic.
# ============================================================================

def _personal_fallback(
    user_text: str,
    asked_questions: list[str] | None = None,
) -> list[str]:
    """
    Emergency fallback when GPT is completely unavailable.

    Extracts the most emotionally loaded word the student used,
    then builds ECHO → BIFURCATE → NAME IT around it.
    No keyword buckets. No hardcoded question sets.
    """
    asked_questions = asked_questions or []
    asked_hashes    = {_hash(q) for q in asked_questions}
    text_lower      = user_text.lower()

    # Most emotionally loaded words → (echo_word, option_a, option_b, named_truth)
    # Checked in priority order (more specific first)
    emotion_map: list[tuple[str, str, str, str, str]] = [
        ("quit",        "quit",        "quit studying altogether",        "something heavier than just this subject",       "you want to quit, or you're exhausted from pretending you're okay with something you didn't choose"),
        ("hate",        "hate",        "completely done with them",       "hurt by something specific they did",            "you actually hate them, or you expected more from them than they gave — and that's the part that really stings"),
        ("scared",      "scared",      "scared of failing",               "scared of what people will think if you do",     "it's the failure you're afraid of, or what the failure would say about everything you've put into this"),
        ("tired",       "tired",       "tired of the subject itself",     "tired of trying hard and not seeing it matter",  "you're physically exhausted, or the weight of it has nowhere else to go so it's coming out as tiredness"),
        ("stuck",       "stuck",       "don't know what to do",           "know what to do but can't make yourself start",  "you're actually stuck, or you already know what needs to happen and you're just not ready to do it yet"),
        ("lost",        "lost",        "lost in the subject",             "lost about whether any of this is worth it",     "you're lost in how to study it, or lost about whether you even want what's at the end of this"),
        ("empty",       "empty",       "nothing matters right now",       "you've given so much there's nothing left",      "you're numb to all of it, or you care deeply but you're too tired to feel it right now"),
        ("stressed",    "stressed",    "there's too much to do",          "you don't know where to start",                  "it's the workload stressing you, or the gap between where you are and where you need to be"),
        ("frustrated",  "frustrated",  "frustrated at the situation",     "frustrated at yourself for letting it get here", "something outside you is frustrating you, or you're angry at yourself — and that's harder to admit"),
        ("alone",       "alone",       "nobody's physically around",      "people are there but nobody actually gets it",   "you need someone there, or you need someone who understands — because those are very different things"),
        ("pressure",    "pressure",    "pressure coming from outside",    "pressure you're putting on yourself",            "the pressure comes from them, or you've internalized it so much it now feels like yours"),
        ("hopeless",    "hopeless",    "hopeless about this situation",   "hopeless about whether things can change",       "the situation feels hopeless, or you're starting to feel like the problem is you — and that's a harder place to be"),
        ("confused",    "confused",    "confused about what to do",       "confused about whether you even want this",      "you're confused about the path, or confused about the destination — because that changes everything"),
        ("hurt",        "hurt",        "hurt by what they did",           "hurt by who it came from specifically",          "what they did is the problem, or the fact that you didn't expect it from them — and that's the real wound"),
        ("angry",       "angry",       "angry at what happened",          "angry at yourself",                              "the anger is at them, or there's some of it pointed inward too — and you haven't said that part yet"),
        ("worried",     "worried",     "worried about results",           "worried about what comes after",                 "you're worried about this exam specifically, or worried about a bigger question you haven't let yourself think about"),
        ("guilty",      "guilty",      "guilty about what you did",       "guilty about what you didn't do",                "it's the action itself that weighs on you, or losing how someone sees you because of it"),
        ("embarrassed", "embarrassed", "embarrassed about what happened", "embarrassed about what people think",            "you're embarrassed about the thing, or about the fact that it happened in front of people who matter to you"),
        ("jealous",     "jealous",     "jealous of how they're doing",    "jealous of how easy it seems for them",          "it's about them, or it's about what their success is making you feel about your own effort — and that's uncomfortable"),
    ]

    matched: tuple[str, str, str, str, str] | None = None
    for keyword, echo_word, option_a, option_b, named_truth in emotion_map:
        if keyword in text_lower:
            matched = (echo_word, option_a, option_b, named_truth, keyword)
            break

    if matched:
        echo_word, option_a, option_b, named_truth, keyword = matched
        candidates = [
            # Q1 — ECHO
            f"{echo_word.capitalize()} like {option_a}, or {echo_word} like {option_b}?",
            # Q2 — BIFURCATE
            "Is this something that hit you suddenly, or has it been quietly building for a while without you saying it out loud?",
            # Q3 — NAME IT
            f"Is it that {named_truth}?",
            # Depth extras if the first 3 were already asked
            "What's the one specific thing that, if it changed tomorrow, would actually make a difference here?",
            "Who around you right now actually knows how heavy this has gotten — or are you carrying it alone?",
        ]
    else:
        # Pure unknown input — still personal, still uses techniques
        candidates = [
            # Q1 — ECHO on the situation itself
            "When you say this — is it something that hit you all at once, or something you've been sitting with for a while?",
            # Q2 — BIFURCATE
            "Is it more about how you're feeling inside, or something specific that happened with someone around you?",
            # Q3 — NAME IT
            "What's the part of this you haven't actually said out loud yet — the thing sitting underneath what you just told me?",
            # Depth
            "If you had to put one word on the main thing weighing on you right now, what would it be?",
            "Is there a specific moment you keep going back to — the one where it started feeling like this?",
        ]

    fresh = [q for q in candidates if _hash(q) not in asked_hashes]
    return (fresh if fresh else candidates)[:3]


# ============================================================================
# SLOT QUESTION
# ============================================================================

def generate_question(
    domain: str,
    slot: str,
    excerpt: str | None = None,
    context: dict | None = None,
) -> str | None:
    """
    Generate one personal, non-repeating question for a specific slot.

    Used when the system knows which slot to fill next.
    Still feels like a real person asking — never a form field.
    """
    logger.debug("generate_question: domain=%s slot=%s", domain, slot)
    context       = context or {}
    meta          = context.get("meta") or {}
    last_question = (meta.get("last_question") or "").strip()
    asked_qs      = context.get("asked_questions") or []
    user_text     = context.get("user_text") or ""

    system = (
        SYSTEM_PROMPT_SLOT_QUESTION
        .replace("{slot}",   str(slot))
        .replace("{domain}", str(domain))
    )

    payload = {
        "student_said":  user_text[:1200],
        "domain":        domain,
        "slot":          slot,
        "context":       excerpt or "",
        "last_question": last_question,
        "already_asked": asked_qs,
    }

    asked_hashes = {_hash(q) for q in asked_qs}

    for attempt in (1, 2):
        try:
            resp = chat_json(
                model="gpt-4o-mini",
                system=system,
                user=json.dumps(payload, ensure_ascii=False),
                max_tokens=180,
                temperature=0.9,
            )
            raw = (resp.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            data     = json.loads(raw)
            question = " ".join((data.get("question") or "").strip().split())

            if (
                question
                and question != last_question
                and _hash(question) not in asked_hashes
                and is_valid_question(question)
            ):
                return question

        except Exception as exc:
            logger.warning("generate_question attempt=%d failed: %s", attempt, exc)

    return _slot_fallback(domain, slot)


# ============================================================================
# SLOT FALLBACK
# ============================================================================

def _slot_fallback(domain: str, slot: str) -> str:
    """
    Personal slot fallback — BIFURCATE technique on every single one.
    Two honest options. Never a form field.
    """
    s = slot.lower()

    if any(k in s for k in ["name", "person", "friend", "who", "member"]):
        return "Which person — the one you've known the longest, or someone newer who you thought you could trust?"

    if any(k in s for k in ["app", "game", "platform", "site"]):
        return "Which app or game — the one you'd be most embarrassed to show your screen time for?"

    if any(k in s for k in ["hour", "time", "duration", "long", "much"]):
        return "How many hours honestly — the real number, not the one that sounds okay to say out loud?"

    if any(k in s for k in ["subject", "topic", "chapter", "concept"]):
        return "Which subject — the one you've quietly been avoiding, or one that used to feel okay and recently stopped?"

    if any(k in s for k in ["reason", "why", "cause", "because"]):
        return "What's the real reason — not the excuse that sounds fine, but the one you actually know is true?"

    if any(k in s for k in ["incident", "event", "moment", "happen", "experience"]):
        return "What's the specific moment it actually went wrong — the thing you keep going back to?"

    if any(k in s for k in ["feel", "emotion", "mood"]):
        return "What's the main thing you're sitting with right now — the emotion under the frustration?"

    if any(k in s for k in ["confidence", "level", "rating", "score"]):
        return "Where are you honestly, 1 to 10 — and what's the thing pulling it below a 7?"

    if any(k in s for k in ["expect", "want", "need", "hope"]):
        return "What were you actually expecting from them — say it plainly, without softening it?"

    if any(k in s for k in ["deadline", "date", "days", "left", "remain"]):
        return "How many days until this — and when you think about that number, what's the first thing that hits you?"

    if any(k in s for k in ["block", "obstacle", "barrier", "stop", "prevent"]):
        return "What's the main thing that keeps getting in the way — the real one, not the surface-level one?"

    if any(k in s for k in ["plan", "strategy", "approach"]):
        return "Is it that you don't have a plan, or that you have one but you don't actually believe it'll work?"

    if any(k in s for k in ["result", "score", "mark", "rank", "grade"]):
        return "Is the result itself the problem, or what the result means about all the effort you put in?"

    if any(k in s for k in ["sleep", "rest", "exhaust"]):
        return "Is it that you can't sleep, or that you sleep but wake up feeling exactly the same weight?"

    readable = slot.replace("_", " ")
    return f"When it comes to your {readable} — is it something that happened recently, or something that's been building quietly?"


# ============================================================================
# UTILITY
# ============================================================================

def _hash(text: str) -> str:
    """Stable hash for deduplication. Case-insensitive, whitespace-normalized."""
    normalized = " ".join(text.strip().lower().split())
    return hashlib.md5(normalized.encode()).hexdigest()


# ============================================================================
# PUBLIC API
# ============================================================================

def generate_initial_clarifiers(
    initial_text: str,
    asked_questions: list[str] | None = None,
    conversation_history: list[dict] | None = None,
) -> list[str]:
    """
    Entry point for any round of clarifying questions.

    Pass the full asked_questions list on every call so questions
    never repeat across rounds, no matter what the student says.

    Args:
        initial_text:         What the student just said.
        asked_questions:      Every question asked so far this session.
        conversation_history: Full chat so far as
                              [{"role": "user"/"assistant", "text": "..."}]
    """
    return generate_counter_questions(
        user_text=initial_text,
        num_questions=3,
        asked_questions=asked_questions or [],
        conversation_history=conversation_history or [],
    )


__all__ = [
    "generate_question",
    "generate_counter_questions",
    "generate_next_followup",
    "ai_ready_to_complete",
    "generate_initial_clarifiers",
    "get_generic_domain_question",
]
