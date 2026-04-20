# AI Decision Layer and Feedback Layer Workflow

This diagram shows how AI recommendation, deterministic safety gates, trigger activation, and feedback persistence work together during the popups stage.

```mermaid
flowchart TD
    %% =========================
    %% NODES
    %% =========================
    A[User Interaction Event\nquestion_loaded, answer_changed, wrong_answer, etc.] --> B[Frontend Event Collector\nrequestTriggerFromAI]

    B --> C[Build Decision Payload\ncontext + telemetry + user_state + preferences]
    C --> D[POST /api/triggers/recommend]

    D --> E[Backend Recommendation Pipeline]

    subgraph PIPE[Backend AI Decision Layer]
        E1[Normalize Event and Context]
        E2[Phase Gating\nbaseline/escalation/crucible/final_sprint]
        E3[Allowlist Filter\nphase-allowed triggers only]
        E4[Emotion Target + Priority Build]
        E5[Interest Bias\nprefer bollywoodReelTrap when topic preference exists]
        E6[LLM Recommendation\ntrigger_name, intensity, timeout, reason]
        E7[Budget Gate\nvalidate cost <= current budget]
        E8[Fallback Policy\nif AI fails or invalid]

        E1 --> E2 --> E3 --> E4 --> E5 --> E6 --> E7
        E7 -->|passes| E9[Return Decision]
        E7 -->|fails| E8 --> E9
    end

    E --> E1
    E9 --> F[Frontend Deterministic Gate Check\ncanActivateTrigger]

    subgraph GATES[Frontend Deterministic Safety Gates]
        G1[Stage must be popups\nunless force=true]
        G2[No interruption lock]
        G3[Not in quiet-break window]
        G4[Not active already + cooldown elapsed]
        G5[No trigger conflict]
        G6[Reduced-motion restrictions]
        G7[Budget Deduction + Cooldown Set]

        G1 --> G2 --> G3 --> G4 --> G5 --> G6 --> G7
    end

    F --> G1
    G7 --> H[Activate Trigger Handler\noptionShuffle, stressTimer, bollywoodReelTrap, ...]

    H --> I[Popup/Effect Rendered]
    I --> J[Capture Outcome Metrics\npre/post/recovery snapshots]
    J --> K[POST /session/{session_id}/trigger-feedback]

    subgraph FEEDBACK[Feedback Layer]
        L1[Feedback Pulse Cadence\nmin interval + auto-close + lock-aware]
        L2[Single Question Survey\nmood or difficulty or topic]
        L3[Preference Update\nintensity bias + topic preference]
        L4[Optional Immediate Reel Decision\nfeedback_topic_selected]
        L5[Persist Rolling Effectiveness\nrecent_triggers + per-trigger scoring]

        L1 --> L2 --> L3 --> L4 --> L5
    end

    I --> L1
    K --> L5
    L3 --> C
    L5 --> C

    %% =========================
    %% STYLING
    %% =========================
    classDef user fill:#f8fafc,stroke:#334155,stroke-width:1.4px,color:#0f172a;
    classDef frontend fill:#ecfeff,stroke:#0e7490,stroke-width:1.4px,color:#0f172a;
    classDef backend fill:#eff6ff,stroke:#1d4ed8,stroke-width:1.4px,color:#0f172a;
    classDef guard fill:#fff7ed,stroke:#c2410c,stroke-width:1.4px,color:#0f172a;
    classDef feedback fill:#f5f3ff,stroke:#6d28d9,stroke-width:1.4px,color:#0f172a;
    classDef outcome fill:#f0fdf4,stroke:#15803d,stroke-width:1.4px,color:#0f172a;

    class A user;
    class B,C,D,F,H,I,J,K frontend;
    class E,E1,E2,E3,E4,E5,E6,E7,E8,E9 backend;
    class G1,G2,G3,G4,G5,G6,G7 guard;
    class L1,L2,L3,L4,L5 feedback;
```

## Reading Guide

1. The AI decision layer proposes a trigger.
2. Deterministic frontend gates decide if activation is actually allowed.
3. Activated triggers produce measurable outcomes.
4. The feedback layer updates user preferences and rolling effectiveness.
5. Updated preferences and effectiveness feed into subsequent AI decisions.
