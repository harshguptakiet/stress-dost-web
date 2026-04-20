# Decision Layer and Feedback Layer Rules (Source of Truth)

Last updated: 2026-04-18

This document explains how the stress trigger decision system works end-to-end in the current codebase, including:
- exact rule layers
- trigger activation conditions
- feedback layer behavior
- AI-controlled vs deterministic-controlled parts
- API and WebSocket contracts used by the frontend

---

## 1) System Overview

The runtime has three cooperating layers:

1. Trigger decision layer (StressTriggers in frontend + AI recommender API)
2. Feedback layer (student check-in popup + preference capture)
3. Content layer for Bollywood reel trap (topic-locked content generation)

Core principle:
- only one stress trigger can be active at a time
- activation is event-driven and state-gated, not free-running random timers
- AI recommends, but deterministic guards enforce safety and preference rules

---

## 2) Trigger Inventory

Current trigger set:
- optionShuffle
- phantomCompetitor
- stressTimer
- confidenceBreaker
- mirageHighlight
- blurAttack
- screenFlip
- colorInversion
- heartbeatVibration
- waveDistortion
- fakeMentorCount
- chaosBackground
- shepardTone
- spatialTicking
- fakeLowBattery
- fakeCrashScreen
- blackout
- hesitationHeatmap
- bollywoodReelTrap

---

## 3) Global Activation Gates (Deterministic)

A trigger is blocked unless all required conditions pass.

Mandatory checks before activation:
- stage must be popups (unless force=true)
- no interruption lock active
- not inside quiet-break window
- trigger is not already active
- max one active trigger overall
- not immediate same-trigger repeat
- trigger cooldown elapsed
- no conflict with currently active trigger(s)
- reduced-motion restrictions can block specific visual-heavy triggers

Additional scheduling controls:
- queued requests are debounced
- AI decision has minimum gap and backoff on failures
- popup rendering is suppressed while screen is busy

Budget controls:
- stress budget 0..100
- trigger cost by intensity:
  - low=8
  - medium=15
  - high=25
- frontend deducts budget on activation
- backend recommender also budget-gates recommended trigger

---

## 4) How Trigger Decisions Are Made

### 4.1 Event sources that call decision logic

Decision requests are initiated on runtime events such as:
- enter_popups
- question_loaded
- answer_changed
- interaction_hesitation
- submit_attempt
- wrong_answer
- time_pressure
- idle_resumed
- context_switched
- device_agitation
- high_tap_intensity
- queued_followup
- feedback_topic_selected

### 4.2 AI recommendation call

Frontend sends a structured payload to:
- POST /api/triggers/recommend

Payload includes:
- event_name/event_type
- context (platform, elapsed time, phase, budget)
- telemetry (latency, hesitation, accuracy, pressure/tap/device indicators)
- user_state (question timing, idle, answer changes, difficulty, submitting)
- metrics (wrong count, streak, recent accuracy)
- available_triggers
- recent_triggers
- followup_answers
- student_preferences (interest topic, preferred trigger difficulty, recent feedback)
- extra.session_id

### 4.3 Backend recommendation logic

Backend pipeline:
1. normalize event + context
2. phase gating by elapsed time and submission progress
3. filter available triggers by phase allowlist
4. classify emotion target (doubt/overload/urgency/steady)
5. build event priority + emotion priority
6. apply interest bias:
   - if preferred_interest_topic exists and bollywoodReelTrap is available, it is prioritized
7. call LLM with strict JSON schema contract
8. normalize/validate output
9. apply budget gate
10. fallback to deterministic policy if AI fails

---

## 5) Feedback Layer Rules

Feedback popup is a separate layer that influences future trigger decisions.

### 5.1 Cadence and visibility

- minimum interval: 60s between feedback popups
- auto-close if no response: 18s
- blocked while interruption lock is active
- popup is intentionally larger for visibility

### 5.2 Single-question random survey mode

Each feedback popup asks exactly one question type at a time:
- mood check
- difficulty tuning (Easy/Medium/Hard)
- topic preference (Movies/News/Games/Music/Sports/Technology/Science/Health/Other)

Selection behavior:
- avoids repeating same question type back-to-back
- tends to prioritize topic/difficulty earlier in popups stage

### 5.3 What feedback changes

Difficulty preference updates intensity bias:
- Easy shifts intensity downward
- Hard shifts intensity upward
- Medium keeps baseline

Topic preference updates content preference:
- mapped topic is stored and reused in future decisions
- can immediately request a topic-selected reel decision event

Feedback persistence:
- POST /session/{session_id}/trigger-feedback
- stores pre/post/recovery metrics and rolling effectiveness in session meta

---

## 6) BollywoodReelTrap Topic-Control Rules

This area has strict preference lock behavior.

### 6.1 Interest mapping

Current deterministic mapping:
- Movies -> movies
- News -> world
- Games -> games
- Music -> music
- Sports -> sports
- Technology -> technology
- Science -> science
- Health -> health
- Other -> world

### 6.2 Preference lock precedence

When a topic preference exists, reel topic selection is locked to that topic.

Frontend behavior:
- preferred topic is used before inferred topic
- request includes force_topic=true to backend reel API
- rendered chosenTopic uses locked topic first

Backend behavior:
- reel API accepts force_topic
- if force_topic=true, topic is pinned to topic_hint
- non-movie forced topics reject AI drift containing movie-centric keywords
- fallback content is topic-specific (including games), not always movies

### 6.3 Mandatory reel within 15 seconds after interest selection

After topic choice:
- reel is scheduled at random time within first 15s
- retries if temporarily blocked
- hard deadline at 15s force-activates bollywoodReelTrap
- hard deadline path can preempt active triggers to guarantee activation (while in popups stage)

This mandatory rule is deterministic and does not depend on AI acceptance.

---

## 7) AI Control vs Deterministic Control

### 7.1 AI controls

AI controls:
- recommended trigger_name
- timeout_ms
- intensity suggestion
- reason/reason_code
- metrics and learning_update fields in recommendation response
- devil briefing text
- reel fact text generation

### 7.2 Deterministic controls (hard guards)

Code-controlled, not AI-overridable:
- activation gates (stage, interruption, quiet-break, conflicts, cooldown, max-active)
- stress budget bounds and gating
- phase allowlists
- reduced-motion restrictions
- fallback selection logic
- feedback cadence and popup policy
- preference mapping and lock behavior
- mandatory 15-second reel guarantee
- force_topic reel enforcement and drift rejection

---

## 8) APIs Used by Frontend (Runtime)

### 8.1 Session and flow

- POST /session/start
  - create active session, prefill slots/domains

- POST /session/{session_id}/next-question
  - get next follow-up/slot question

- POST /session/{session_id}/answer
  - submit answer for current question

- POST /session/{session_id}/complete
  - complete early and switch to completed state

- POST /session/{session_id}/start-simulation
  - lazily generate/schedule popups and start simulation

- POST /session/transcribe
  - voice input transcription

### 8.2 Trigger/feedback

- POST /api/triggers/recommend
  - AI trigger decision endpoint

- POST /api/triggers/devil-brief
  - devil-mode briefing generation

- POST /session/{session_id}/trigger-feedback
  - persist trigger/feedback outcome metrics

### 8.3 Reel content

- POST /api/bollywood/reel-fact
  - returns topic-specific reel content (honors force_topic)

### 8.4 Test questions

- GET /api/questions/load-test-questions
  - fetch initial test question set

- POST /api/questions/mutate/{question_id}
  - mutate question during stress stage (unless popup simulation active)

---

## 9) WebSocket Events and Session Detail Fetching

### 9.1 Client -> Server

- join_session
  - payload: session_id
  - joins room for popup stream

- suggest_request
  - payload: partial text
  - requests AI/local suggestion completions

### 9.2 Server -> Client

- server_hello
  - connection acknowledgment

- joined
  - room join acknowledgment

- popup
  - real-time popup payload for active session room

- suggestions
  - suggestion completions for intro text

### 9.3 Important clarification

WebSocket is not the primary source of full session details.

Session state/details are fetched and updated via REST APIs (session endpoints).
WebSocket is used mainly for:
- room-based popup stream
- suggestion stream
- connection lifecycle notifications

---

## 10) Server-Side Popup Simulation Rules

- popup simulation starts with /session/{id}/start-simulation
- popups are emitted sequentially into session room
- max popups capped by env/config
- random interval between emissions (configurable range)
- simulation active flag can be checked by question mutation route

---

## 11) Decision and Feedback Data Stored Per Session

Session meta stores rolling trigger feedback and effectiveness:
- recent_triggers (bounded)
- effectiveness by trigger (count, avg score, recovery stats, level)
- baseline stats/metrics used for recovery scoring
- trigger impact labels and levels (low/medium/high effectiveness)

Also stored/used in runtime state on client:
- feedback difficulty preference
- feedback topic preference
- feedback response history
- recent reel history (topic/image/title)
- mandatory reel timer/deadline state

---

## 12) Practical Rule Summary

1. AI suggests trigger; deterministic gates decide if it can run.
2. Only one trigger can run at a time.
3. Feedback layer modifies future trigger intensity and reel topic.
4. Topic choice is locked and propagated to AI + reel generator.
5. BollywoodReelTrap is mandatory within 15s after topic selection.
6. Session details are REST-driven; WebSocket is event-stream-driven.
