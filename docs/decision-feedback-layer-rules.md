# Decision Layer and Feedback Layer Rules (Source of Truth)

Last updated: 2026-04-20

This document explains how the stress trigger decision system works end-to-end, with only the code references needed to verify behavior quickly.

---

## 1) System Overview

The runtime has three cooperating layers:
- Trigger decision layer: frontend runtime + AI recommender API
- Feedback layer: student check-in popup + preference capture
- Content layer: Bollywood reel trap with topic lock behavior

Core principle:
- Only one stress trigger can be active at a time.
- Activation is event-driven and state-gated.
- AI recommends, deterministic guards enforce safety.

Code refs:
- frontend runtime core: [static/app.js](../static/app.js#L771)
- recommender endpoint: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L662)
- feedback persistence endpoint: [app/api/session_routes.py](../app/api/session_routes.py#L899)
- reel content endpoint: [app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L159)

---

## 2) Trigger Inventory

Current trigger set:
- optionShuffle, phantomCompetitor, stressTimer, confidenceBreaker, mirageHighlight
- blurAttack, screenFlip, colorInversion, heartbeatVibration, waveDistortion
- fakeMentorCount, chaosBackground, shepardTone, spatialTicking
- fakeLowBattery, fakeCrashScreen, blackout, hesitationHeatmap, bollywoodReelTrap

Code refs:
- canonical trigger config: [static/app.js](../static/app.js#L1068)
- trigger handler registry: [static/app.js](../static/app.js#L3024)

---

## 3) Global Activation Gates (Deterministic)

A trigger is blocked unless required checks pass.

Mandatory gates:
- stage is popups (unless force=true)
- no interruption lock
- no quiet-break lock
- trigger not active already
- cooldown elapsed
- no conflict with active trigger(s)
- reduced-motion guard for heavy visual effects

Additional controls:
- queued follow-up requests
- AI decision timeout/backoff behavior
- popup rendering suppressed while screen is busy

Budget controls:
- stress budget range: 0..100
- trigger cost by intensity: low=8, medium=15, high=25
- frontend deducts budget on activation
- backend also budget-gates recommendations

Code refs:
- gate checks: [static/app.js](../static/app.js#L1372)
- interruption and busy-screen checks: [static/app.js](../static/app.js#L1215), [static/app.js](../static/app.js#L1254)
- cooldown/conflict config: [static/app.js](../static/app.js#L1068), [static/app.js](../static/app.js#L1403)
- frontend budget state and update: [static/app.js](../static/app.js#L825), [static/app.js](../static/app.js#L1480)
- backend budget cost and gating: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L134), [app/api/trigger_routes.py](../app/api/trigger_routes.py#L782)

---

## 4) How Trigger Decisions Are Made

### 4.1 Event sources

Decision requests are initiated on events such as:
- enter_popups, question_loaded, answer_changed, interaction_hesitation
- submit_attempt, wrong_answer, time_pressure
- idle_resumed, context_switched, device_agitation
- high_tap_intensity, queued_followup, feedback_topic_selected

Code refs:
- event dispatch points: [static/app.js](../static/app.js#L3359), [static/app.js](../static/app.js#L3428), [static/app.js](../static/app.js#L3598)

### 4.2 AI recommendation call

Frontend sends structured payload to:
- POST /api/triggers/recommend

Payload includes:
- event_name/event_type
- context (platform, elapsed time, phase, budget)
- telemetry and user_state
- performance metrics, recent triggers, followup answers
- student preferences and session metadata

Code refs:
- payload build and call: [static/app.js](../static/app.js#L3153), [static/app.js](../static/app.js#L3224)
- endpoint handler: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L662)

### 4.3 Backend recommendation logic

Pipeline:
1. normalize event + context
2. phase gating from elapsed/progress
3. allowlist filtering by phase
4. emotion target classification
5. event/emotion priority build
6. interest bias for bollywoodReelTrap when preferred topic exists
7. LLM call with schema contract
8. output normalization/validation
9. budget gate
10. deterministic fallback when AI fails

Code refs:
- normalization and phase: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L315), [app/api/trigger_routes.py](../app/api/trigger_routes.py#L346)
- phase allowlist: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L65), [app/api/trigger_routes.py](../app/api/trigger_routes.py#L695)
- emotion and interest bias: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L381), [app/api/trigger_routes.py](../app/api/trigger_routes.py#L726)
- LLM + fallback path: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L769), [app/api/trigger_routes.py](../app/api/trigger_routes.py#L536)

---

## 5) Feedback Layer Rules

Feedback popup influences future trigger decisions.

Cadence and visibility:
- minimum interval between feedback popups: 60s
- auto-close without response: 18s
- blocked while interruption lock is active
- intentionally larger popup for visibility

Single-question survey mode:
- one question type per popup: mood, difficulty, or topic
- avoids immediate repetition
- tends to prioritize topic/difficulty early in popups stage

What feedback changes:
- difficulty preference adjusts trigger intensity bias
- topic preference updates content preference and can trigger reel decision flow
- persistence writes metrics and rolling effectiveness

Code refs:
- cadence and popup gating: [static/app.js](../static/app.js#L780), [static/app.js](../static/app.js#L2917)
- survey generation and anti-repeat: [static/app.js](../static/app.js#L1030), [static/app.js](../static/app.js#L1053)
- difficulty/topic preference updates: [static/app.js](../static/app.js#L906), [static/app.js](../static/app.js#L900), [static/app.js](../static/app.js#L2989)
- persistence endpoint + scoring: [static/app.js](../static/app.js#L3008), [app/api/session_routes.py](../app/api/session_routes.py#L899), [app/api/session_routes.py](../app/api/session_routes.py#L920)

---

## 6) BollywoodReelTrap Topic-Control Rules

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

Code ref:
- mapping function: [static/app.js](../static/app.js#L900)

### 6.2 Preference lock precedence

When topic preference exists, reel topic selection is locked.

Frontend behavior:
- preferred topic is used before inferred topic
- request includes force_topic=true to reel API
- rendered chosenTopic uses locked topic first

Backend behavior:
- reel API accepts force_topic
- force_topic=true pins topic to topic_hint
- non-movie forced topics reject movie drift
- fallback content remains topic-specific

Code refs:
- frontend lock + request: [static/app.js](../static/app.js#L2777), [static/app.js](../static/app.js#L2818)
- backend enforcement: [app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L72), [app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L89), [app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L163)
- topic fallback content: [app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L240)

### 6.3 Mandatory reel within 15 seconds after interest selection

After topic choice:
- reel scheduled at random time within first 15s
- retries if temporarily blocked
- hard deadline force-activates bollywoodReelTrap
- deadline path may preempt active triggers (within popups stage)

Code refs:
- scheduling and retries: [static/app.js](../static/app.js#L940), [static/app.js](../static/app.js#L967), [static/app.js](../static/app.js#L987)
- hard-deadline force path: [static/app.js](../static/app.js#L942), [static/app.js](../static/app.js#L953)

---

## 7) AI Control vs Deterministic Control

AI controls:
- recommended trigger_name, timeout_ms, intensity
- reason/reason_code and learning fields
- devil brief text
- reel fact text generation

Deterministic controls:
- all activation gates and safety checks
- stress budget enforcement
- phase allowlists and fallback policy
- feedback cadence policy
- topic mapping/lock behavior
- mandatory 15-second reel guarantee
- force_topic drift rejection

Code refs:
- AI response consumption: [static/app.js](../static/app.js#L3230)
- deterministic gate entry: [static/app.js](../static/app.js#L3046)
- devil brief API: [app/api/trigger_routes.py](../app/api/trigger_routes.py#L821)

---

## 8) APIs Used by Frontend (Runtime)

Session and flow:
- POST /session/start ([app/api/session_routes.py](../app/api/session_routes.py#L266))
- POST /session/{session_id}/next-question ([app/api/session_routes.py](../app/api/session_routes.py#L446))
- POST /session/{session_id}/answer ([app/api/session_routes.py](../app/api/session_routes.py#L331))
- POST /session/{session_id}/complete ([app/api/session_routes.py](../app/api/session_routes.py#L802))
- POST /session/{session_id}/start-simulation ([app/api/session_routes.py](../app/api/session_routes.py#L846))
- POST /session/transcribe ([app/api/session_routes.py](../app/api/session_routes.py#L248))

Trigger and feedback:
- POST /api/triggers/recommend ([app/api/trigger_routes.py](../app/api/trigger_routes.py#L662))
- POST /api/triggers/devil-brief ([app/api/trigger_routes.py](../app/api/trigger_routes.py#L821))
- POST /session/{session_id}/trigger-feedback ([app/api/session_routes.py](../app/api/session_routes.py#L899))

Reel content:
- POST /api/bollywood/reel-fact ([app/api/bollywood_routes.py](../app/api/bollywood_routes.py#L159))

Test questions:
- GET /api/questions/load-test-questions ([app/api/question_routes.py](../app/api/question_routes.py#L415))
- POST /api/questions/mutate/{question_id} ([app/api/question_routes.py](../app/api/question_routes.py#L498))

---

## 9) WebSocket Events and Session Detail Fetching

Client -> Server:
- join_session (payload: session_id)
- suggest_request (payload: partial text)

Server -> Client:
- server_hello
- joined
- popup
- suggestions

Important clarification:
- REST is the source of full session details.
- WebSocket is used mainly for popup stream, suggestions, and connection lifecycle notifications.

Code refs:
- client emits/listeners: [static/app.js](../static/app.js#L3679), [static/app.js](../static/app.js#L3696), [static/app.js](../static/app.js#L3710), [static/app.js](../static/app.js#L4401)
- server handlers/emits: [app/realtime/socket_events.py](../app/realtime/socket_events.py#L16), [app/realtime/socket_events.py](../app/realtime/socket_events.py#L22), [app/realtime/socket_events.py](../app/realtime/socket_events.py#L31), [app/realtime/socket_events.py](../app/realtime/socket_events.py#L54)
- REST detail endpoints: [app/api/session_routes.py](../app/api/session_routes.py#L756), [app/api/session_routes.py](../app/api/session_routes.py#L772), [app/api/session_routes.py](../app/api/session_routes.py#L846)

---

## 10) Server-Side Popup Simulation Rules

- simulation starts from /session/{id}/start-simulation
- popups are emitted sequentially into session room
- max popups capped by env/config
- random interval used between emissions
- mutation route can check simulation active flag

Code refs:
- session kickoff and scheduling: [app/api/session_routes.py](../app/api/session_routes.py#L846), [app/realtime/scheduler.py](../app/realtime/scheduler.py#L24)
- active-state and limits: [app/realtime/scheduler.py](../app/realtime/scheduler.py#L16), [app/realtime/scheduler.py](../app/realtime/scheduler.py#L27)
- emit path: [app/realtime/scheduler.py](../app/realtime/scheduler.py#L37)
- mutation guard: [app/api/question_routes.py](../app/api/question_routes.py#L503)

---

## 11) Decision and Feedback Data Stored Per Session

Session meta stores rolling trigger feedback:
- recent_triggers (bounded)
- effectiveness per trigger (count, score, level)
- baseline stats/metrics for recovery scoring
- impact labels and effectiveness levels

Client runtime state stores:
- feedback difficulty preference
- feedback topic preference
- feedback response history
- reel history and mandatory timer/deadline state

Code refs:
- session meta persistence/retrieval: [app/api/session_routes.py](../app/api/session_routes.py#L926), [app/api/session_routes.py](../app/api/session_routes.py#L963), [app/api/session_routes.py](../app/api/session_routes.py#L1001)
- client runtime feedback state: [static/app.js](../static/app.js#L834), [static/app.js](../static/app.js#L842)

---

## 12) Practical Rule Summary

1. AI suggests; deterministic gates decide whether activation is allowed.
2. Only one trigger can be active at a time.
3. Feedback changes future trigger intensity and topic behavior.
4. Topic choice is locked through decision + reel generation path.
5. bollywoodReelTrap is guaranteed within 15s after interest selection.
6. Full session details are REST-driven; WebSocket is stream-driven.
