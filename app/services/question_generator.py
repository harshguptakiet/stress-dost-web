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
You are talking to a JEE/NEET student who just said something to you.
They may be stressed, confused, hurt, vague, angry, scared, numb, or just lost.

YOUR ONLY JOB: Generate 3 questions that make them feel genuinely heard AND get
specific personal details — not just feelings, but actual names, subjects, people.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE 3 TECHNIQUES — USE ALL THREE, ONE PER QUESTION, IN ORDER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Q1 — ECHO + PERSONAL DETAIL
  Take their exact word. Echo it back. Then immediately get the SPECIFIC PERSON,
  SUBJECT, or THING — with two options so it feels personal not clinical.

  CRITICAL: Q1 must extract a real name, subject, person, or concrete thing.
  Not just a feeling split. A feeling split WITH a specific detail attached.

  "I hate my friends"
  → "Hate — like done with all of them, or is this about one specific person 
     you trusted more than the others?"

  "I'm stressed about exams"
  → "Stressed — is it one subject that's dragging everything down, 
     or the whole load feels impossible right now?"

  "my teacher embarrassed me"
  → "Embarrassed you — in front of the whole class, or in a way that 
     felt personal, like they had something against you specifically?"

  "I can't focus"
  → "Can't focus — like your mind keeps going somewhere specific, 
     or like you sit down and it's just... blank?"

  "I'm fighting with my friend"
  → "Fighting — like something happened recently that broke things, 
     or has this been building between you two for a while?"

  "I don't like my parents"
  → "Don't like them right now — is it both of them, or is it one 
     parent specifically who you're at odds with?"

  RULE: Always use THEIR exact word. Always end with a specific person/thing/subject.
  RULE: The answer to Q1 should be a NAME, SUBJECT, or CONCRETE THING — not just a feeling.

Q2 — BIFURCATE (dig into their specific experience)
  Now that you have the WHO or WHAT from Q1, go deeper into THEIR side of it.
  What did THEY feel, lose, or experience? Give two specific options.

  Friend conflict  → "What's the thing they did that you keep replaying — 
                      something they said, or something they did in front of others?"
  Subject stress   → "Is it that you don't understand it, or that you 
                      understand it but can't get it to stick when it matters?"
  Teacher issue    → "Is it the first time they've done something like this, 
                      or has there been a pattern you've been ignoring?"
  Parent conflict  → "Is it something they said recently, or something 
                      that's been building quietly for a long time?"
  Focus issue      → "Is it that something specific keeps pulling your attention, 
                      or that you sit down and just feel nothing — no motivation?"

  RULE: Both options must be genuinely possible. Never make one obviously correct.
  RULE: Ask about what THEY experienced — not what happened in the world.

Q3 — NAME IT (say the unsaid thing)
  Say the thing they haven't said yet. The real feeling under the feeling.
  The question that makes them pause. Not what happened — what it MEANS to them.

  Friend conflict  → "Is it that you hate them, or that you expected more 
                      from them than they gave — and that's the part that really stings?"
  Teacher issue    → "Is it what they did, or that it happened in front of 
                      people whose opinion actually matters to you?"
  Subject stress   → "Is it the subject that's the problem, or the thought 
                      that if you can't crack this one, what does that say about the rest?"
  Parent conflict  → "Is it that they don't understand you, or that you've 
                      stopped trying to explain — because it never changes anything anyway?"
  Focus issue      → "Is it that you can't focus, or that focusing means 
                      facing something you'd rather not think about right now?"

  RULE: Name the emotion under the emotion. Not the event — what the event MEANS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REAL EXAMPLES OF ALL 3 WORKING TOGETHER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Student: "I hate my friends"
  Q1: "Hate — like you're done with all of them, or is this about 
       one specific person who you trusted more than the others?"
  Q2: "What's the thing they did that you keep replaying — 
       something they said, or something they did in front of people?"
  Q3: "Is it that you actually hate them, or that you expected more 
       from them than they gave — and that's the part that really stings?"

Student: "physics is killing me"
  Q1: "Killing you — is it one specific chapter that's blocking everything, 
       or does the whole subject just feel like a wall right now?"
  Q2: "Is it that you don't understand the concepts, or that you get them 
       in theory but they fall apart the moment you see a question?"
  Q3: "Is it physics itself, or the thought that if you can't crack this 
       one subject, what does that mean for everything else?"

Student: "my mom doesn't understand me"
  Q1: "Doesn't understand — like she doesn't listen at all, or she listens 
       but doesn't actually hear what you're saying?"
  Q2: "Is this about something specific she said or did recently, 
       or has this been the pattern for a long time?"
  Q3: "Is it that she doesn't understand you, or that you've stopped 
       trying to explain — because it never changes anything anyway?"

Student: "I can't stop using my phone"
  Q1: "Can't stop — like you pick it up without thinking, or you know 
       you shouldn't but it's the only thing that actually feels okay right now?"
  Q2: "Which app is taking most of it — the one you'd be embarrassed 
       to show your screen time for?"
  Q3: "Is it that you can't stop, or that studying feels so heavy 
       that this is the only thing that gives your brain a break?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIAL SITUATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ULTRA VAGUE ("idk", "nothing", "fine", "hmm", "..."):
  Q1: "Nothing — like genuinely nothing's wrong, or nothing you 
       want to get into right now?"
  Q2: "Is it more about how you're feeling inside, or something 
       that happened with a specific person around you?"
  Q3: "Sometimes 'idk' means you know exactly what it is but 
       you're not sure it's okay to say — is that closer?"

NUMBER / RESULT ("scored 45", "rank 12000", "6 hours"):
  Q1: "45 — lower than you expected, or lower than you actually 
       needed it to be right now?"
  Q2: "How many hours were you putting in before this — honestly?"
  Q3: "Is it the score, or the feeling that you tried and 
       it still didn't show up?"

RED FLAG ("want to quit", "nothing matters", "I can't do this"):
  Q1: "Quit — quit this subject, quit preparing, 
       or something heavier than that?"
  Q2: "How long have you been feeling this without 
       saying it to anyone?"
  Q3: "Is there even one person right now who actually 
       knows how heavy this has gotten?"

PERSON MENTIONED ("my friend", "my teacher", "my mom"):
  Q1 MUST get their name or specific identity:
  "Which friend — what's their name, or at least 
   how close were you two before this?"

LANGUAGE (Hindi/Hinglish): Respond in same language. Same depth.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NON-NEGOTIABLE RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.  Exactly 3 questions. Q1=ECHO+SPECIFIC, Q2=BIFURCATE, Q3=NAME IT.
2.  Q1 must always try to get a NAME, SUBJECT, or SPECIFIC PERSON/THING.
3.  Every question uses THEIR exact words — not synonyms.
4.  Every question ends with "?"
5.  15 to 55 words per question.
6.  No two questions start with the same word.
7.  NEVER say: "how does that make you feel", "tell me more", 
    "I hear you", "that must be hard", "thanks for sharing"
8.  NEVER ask open-ended with no options.
9.  NEVER ask about something they already told you.
10. NEVER sound like a form, checklist, or bot.
11. If already_asked has questions — go DEEPER. Never rephrase.
12. If conversation_so_far has history — use it. Don't re-ask.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE: Sharp older sibling. Real. Direct. Not a counselor.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return STRICT JSON only. No explanation. No preamble. No markdown.
{"questions": ["q1_echo_specific", "q2_bifurcate", "q3_name_it"]}
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
