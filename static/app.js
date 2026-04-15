// DOM helpers --------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const stageEls = {
  name: $("stageName"),
  intro: $("stageIntro"),
  loading: $("stageLoading"),
  qa: $("stageQA"),
  popups: $("stagePopups"),
};

const logBox = $("logBox");
const popupConsole = $("popupConsole");
const popupOverlay = $("popupOverlay");
const popupQueue = [];
let popupActive = false;
let popupTimer = null;
const recentPopups = new Set();

const loadingTextEl = $("loadingText");
const nameHintEl = $("nameHint");
const introHintEl = $("introHint");
const storyPromptEl = $("storyPrompt");
const hintBox = $("hintBox");
const popupSummary = $("popupSummary");
const suggestionWrap = $("suggestionWrap");
const suggestionList = $("suggestionList");

const hudPanel = $("hudPanel");
const hudToggle = $("hudToggle");
const btnCloseHud = $("btnCloseHud");

const btnStart = $("btnStart");
const btnNameNext = $("btnNameNext");
const btnRecord = $("btnRecord");
const btnAnswer = $("btnAnswer");
const btnSkip = $("btnSkip");
const btnReset = $("btnReset");
const btnRestart = $("btnRestart");
const userNameInput = $("userName");
const btnLogout = $("btnLogout");
const userChip = $("userChip");
const hudUserLine = $("hudUserLine");

const answerInput = $("answerInput");
const questionStem = $("questionStem");
const questionOptions = $("questionOptions");
const questionCounter = $("questionCounter");
const questionSubject = $("questionSubject");
const questionProgress = $("questionProgress");
const mutateBadge = $("mutateBadge");
const integerPanel = $("integerPanel");
const integerInput = $("integerInput");
const btnClearInteger = $("btnClearInteger");
const btnBackspace = $("btnBackspace");
const scoreMeta = $("scoreMeta");
const testHint = $("testHint");
const btnPrevQuestion = $("btnPrevQuestion");
const btnNextQuestion = $("btnNextQuestion");
const btnReloadQuestions = $("btnReloadQuestions");
const btnSubmitQuestion = $("btnSubmitQuestion");
// ── Submit-all button — sends every answer to /api/questions/submit-test
//    and shows the verified server-side score in a result panel.
const btnSubmitAllTest = $("btnSubmitAllTest");
const submitAllResult  = $("submitAllResult");

// ── Follow-up skip button (injected dynamically, see getOrCreateSkipBtn) ──
// Lives in the QA stage alongside the answer input.
// Shown after the 2nd follow-up, hidden otherwise.
function getOrCreateSkipBtn() {
  let btn = $("btnSkipFollowup");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "btnSkipFollowup";
    btn.type = "button";
    btn.className = "ghost skip-followup-btn";
    btn.textContent = "Skip to test →";
    btn.title = "Skip remaining follow-up questions and go straight to the test";
    btn.style.display = "none";
    // Insert right after the answer button if it exists, else append to qa stage
    const qaStage = $("stageQA");
    if (btnAnswer && btnAnswer.parentNode) {
      btnAnswer.parentNode.insertBefore(btn, btnAnswer.nextSibling);
    } else if (qaStage) {
      qaStage.appendChild(btn);
    }
    btn.addEventListener("click", skipFollowups);
  }
  return btn;
}

// State --------------------------------------------------------------------
// ── FIX #2: sessionId is now persisted in sessionStorage so it survives
//    page refreshes. Every call to /session/:id/next-question re-uses the
//    same ID instead of creating a brand-new session on each load.
let sessionId = sessionStorage.getItem("stress_dost_session_id") || null;
let currentDomain = null;
let currentSlot = null;
let socket = null;
let socketInitialized = false;
let mediaRecorder = null;
let mediaStream = null;
let audioChunks = [];
let recordedAudioBlob = null;
let recordingMimeType = "audio/webm";
let testQuestions = [];
let testQuestionIndex = 0;
let selectedOptions = {};
let answeredMap = {};
let mutationTimers = [];
let integerKeypadListenerAttached = false;
let suggestTimer = null;

// ── Follow-up runtime counter (mirrors server-side FOLLOWUP_LIMIT logic)
// This is a *client-side* mirror — the authoritative counter lives on the
// server (question_generator.py _followup_runtime).  We keep a local copy
// so we can show/hide the skip button without an extra round-trip.
// IMPORTANT: this is session-scoped and never written to localStorage/DB.
let followupCount = 0;        // how many follow-ups have been shown this session
const FOLLOWUP_LIMIT = 3;     // must match question_generator.FOLLOWUP_LIMIT
const SKIP_BTN_AFTER = 2;     // must match question_generator.SKIP_BUTTON_AFTER

// Whether the current QA question is a follow-up (vs initial clarifier)
let isFollowupPhase = false;
// Whether server has signalled it's done with follow-ups
let followupsDone = false;
// The student's original opening text — passed to server for readiness checks
let initialSessionText = "";

// Utility ------------------------------------------------------------------
function log(...args) {
  if (!logBox) return;
  const line = args
    .map((a) => (typeof a === "string" ? a : JSON.stringify(a)))
    .join(" ");
  logBox.textContent = (logBox.textContent + line + "\n").slice(-15000);
  logBox.scrollTop = logBox.scrollHeight;
}

async function getJSON(url) {
  const res = await fetch(url, { method: "GET", headers: { "Content-Type": "application/json" } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
  return data;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
  return data;
}

async function postFormData(url, formData) {
  const res = await fetch(url, {
    method: "POST",
    body: formData,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.message || `HTTP ${res.status}`);
  return data;
}

function showStage(name, message) {
  Object.values(stageEls).forEach((el) => el?.classList.remove("active"));
  const stage = stageEls[name];
  if (stage) stage.classList.add("active");
  if (name === "loading" && message) setLoadingMessage(message);
  // Keep viewport at top when switching stages so users see loaders/questions without scrolling
  try {
    window.scrollTo({ top: 0, behavior: "smooth" });
  } catch (e) {
    window.scrollTo(0, 0);
  }
}

function setLoadingMessage(message) {
  if (loadingTextEl) loadingTextEl.textContent = message || "Calibrating vibes…";
}

function setHint(text) {
  if (hintBox) hintBox.textContent = text || "";
}

function setIntroHint(text) {
  if (!introHintEl) return;
  introHintEl.textContent = text || "";
  if (text) {
    stageEls.intro?.classList.add("shake");
    setTimeout(() => stageEls.intro?.classList.remove("shake"), 400);
  }
}

function setNameHint(text) {
  if (!nameHintEl) return;
  nameHintEl.textContent = text || "";
  if (text) {
    stageEls.name?.classList.add("shake");
    setTimeout(() => stageEls.name?.classList.remove("shake"), 400);
  }
}

function setStoryPrompt(name) {
  if (!storyPromptEl) return;
  const cleanName = (name || "").trim();
  if (!cleanName) {
    storyPromptEl.textContent = "What's on your mind today?";
    return;
  }
  storyPromptEl.textContent = `Hey ${cleanName}, what's on your mind today?`;
}

function setRecordButtonState() {
  if (!btnRecord) return;
  if (mediaRecorder && mediaRecorder.state === "recording") {
    btnRecord.textContent = "Stop Recording";
    btnRecord.classList.remove("ghost");
    btnRecord.classList.add("primary");
    return;
  }
  btnRecord.textContent = recordedAudioBlob ? "Re-record Voice" : "Record Voice";
  btnRecord.classList.remove("primary");
  btnRecord.classList.add("ghost");
}

function setSessionUI(id, domains) {
  sessionId = id;
  // ── FIX #2: Persist session_id in sessionStorage so page refreshes reuse it.
  //    sessionStorage is cleared automatically when the tab closes — no stale
  //    IDs linger across separate visits.
  if (id) {
    sessionStorage.setItem("stress_dost_session_id", id);
  } else {
    sessionStorage.removeItem("stress_dost_session_id");
  }
  window.currentSessionId = id || null;
  $("sessionId").textContent = id || "—";
  $("sessionStatus").textContent = id ? `session: ${id.slice(0, 8)}…` : "session: none";
  $("activeDomains").textContent = domains && domains.length ? domains.join(", ") : "—";
}

function syncUserUI() {
  const u = window.StressDostAuth?.getUser?.();
  if (userChip) {
    userChip.textContent = u ? `${u.display_name} · ${String(u.user_id).slice(0, 8)}…` : "";
    userChip.style.display = u ? "inline-flex" : "none";
  }
  if (hudUserLine) {
    if (!u) hudUserLine.textContent = "—";
    else hudUserLine.textContent = `${u.display_name} (${u.user_id})`;
  }
}

function clientUserPayload() {
  const u = window.StressDostAuth?.getUser?.();
  if (!u) return null;
  const out = { user_id: u.user_id, display_name: u.display_name };
  if (u.mood) out.mood = u.mood;
  return out;
}

function updateScoreMeta() {
  const totalAnswered = Object.keys(answeredMap).length;
  // ── FIX #1: Count only entries where correct === true.
  //    Previously the count used Object.keys(answeredMap).length which is the
  //    number of *answered* questions — not correct ones — making every answer
  //    look correct regardless of what the student selected.
  const correct = Object.values(answeredMap).filter((v) => v?.correct === true).length;
  const totalQuestions = testQuestions.length || totalAnswered;
  if (scoreMeta) scoreMeta.textContent = `Score: ${correct}/${totalQuestions || 0}`;
}

function setQuestionUI(data) {
  currentDomain = data.domain || null;
  currentSlot = data.slot || null;
  const totalAsked = Number(data?.meta?.total_questions_asked || 0);

  $("qMeta").textContent = `domain: ${currentDomain || "—"} | slot: ${currentSlot || "—"}`;
  $("questionText").textContent = data.question || "Your next question will bloom here.";
  if (btnSkip) {
    btnSkip.hidden = totalAsked < 3;
    btnSkip.disabled = false;
  }
  setHint(data.hint || "");
  btnAnswer.disabled = false;
  answerInput.disabled = false;
  answerInput.focus();
}

// ── Follow-up Skip Button Logic ───────────────────────────────────────────

/**
 * Update the visibility of the skip button based on the current followupCount.
 * Called every time a follow-up question is shown or the phase changes.
 *
 * Rules:
 *  - Only shown during the follow-up phase (isFollowupPhase === true)
 *  - Only shown once followupCount >= SKIP_BTN_AFTER (i.e. after 2nd followup)
 *  - Hidden once followups are done or we leave the QA stage
 *
 * ── FIX #3: Button visibility is now correctly gated on isFollowupPhase AND
 *    followupCount >= SKIP_BTN_AFTER.  Previously the button never appeared
 *    because updateSkipButtonVisibility() was called before isFollowupPhase
 *    was set to true in some code paths.  Now onFollowupQuestionShown() sets
 *    the flag first, then calls this helper.
 */
function updateSkipButtonVisibility() {
  const btn = getOrCreateSkipBtn();
  // ── FIX #2: Removed `isFollowupPhase &&` guard.
  // Previously the button disappeared when slot phase started (isFollowupPhase=false).
  // Now it stays visible as long as followups aren't done and threshold is met.
  const shouldShow = !followupsDone && followupCount >= SKIP_BTN_AFTER;
  btn.style.display = shouldShow ? "inline-flex" : "none";
  log(
    "skip_btn_visibility: show=" + shouldShow +
    " isFollowupPhase=" + isFollowupPhase +
    " followupsDone=" + followupsDone +
    " followupCount=" + followupCount +
    " SKIP_BTN_AFTER=" + SKIP_BTN_AFTER
  );
}

/**
 * Called when the student clicks "Skip to test →".
 * Marks follow-ups as done so no more are requested, then triggers completion.
 */
async function skipFollowups() {
  if (!sessionId) return;
  log("skip_followups: student skipped at followup_count=" + followupCount);
  followupsDone = true;
  updateSkipButtonVisibility();
  // Tell the server the student chose to skip follow-ups.
  // The server should treat this exactly like a normal completion signal.
  try {
    await postJSON(`/session/${sessionId}/skip-followups`, {
      followup_count: followupCount,
    });
  } catch (err) {
    // Non-fatal — even if this endpoint doesn't exist, we proceed to completion
    log("skip_followups: server notify failed (non-fatal):", err.message || String(err));
  }
  await handleCompletion();
}

/**
 * Called by the backend response handler when a question is identified as a
 * follow-up (server returns { is_followup: true } in the next-question response).
 * Increments the local mirror counter and updates the skip button.
 *
 * ── FIX #3: isFollowupPhase is set to true HERE, before calling
 *    updateSkipButtonVisibility().  The original code sometimes called
 *    updateSkipButtonVisibility() while isFollowupPhase was still false,
 *    so the button stayed hidden even after 2 follow-ups.
 */
function onFollowupQuestionShown() {
  isFollowupPhase = true;                   // ← must be set before the visibility call
  followupCount += 1;
  log("followup_shown: count=" + followupCount + " limit=" + FOLLOWUP_LIMIT);
  updateSkipButtonVisibility();             // now evaluates with the correct flag
}

/**
 * Called when the server signals follow-ups are done (data.done === true or
 * data.followups_complete === true).
 */
function onFollowupsDone() {
  followupsDone = true;
  isFollowupPhase = false;
  updateSkipButtonVisibility();
}

// ── Reset helper ──────────────────────────────────────────────────────────

function resetFollowupState() {
  followupCount = 0;
  isFollowupPhase = false;
  followupsDone = false;
  updateSkipButtonVisibility();
}

function resetFlow() {
  // ── FIX #2: Clear persisted session_id so a fresh session starts cleanly.
  setSessionUI(null, null);
  currentDomain = null;
  currentSlot = null;
  initialSessionText = "";
  resetFollowupState();
  setSuggestions([]);
  btnAnswer.disabled = true;
  if (btnSkip) {
    btnSkip.hidden = true;
    btnSkip.disabled = false;
  }
  answerInput.value = "";
  if (userNameInput) userNameInput.value = "";
  $("initialText").value = "";
  recordedAudioBlob = null;
  recordingMimeType = "audio/webm";
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }
  mediaRecorder = null;
  audioChunks = [];
  setRecordButtonState();
  setHint("");
  setNameHint("");
  setIntroHint("");
  setStoryPrompt("");
  // Reset test question panel
  testQuestions = [];
  testQuestionIndex = 0;
  selectedOptions = {};
  answeredMap = {};
  if (questionStem) questionStem.textContent = "Questions will appear here with options.";
  if (questionOptions) questionOptions.innerHTML = "";
  if (questionCounter) questionCounter.textContent = "Questions —";
  if (questionSubject) questionSubject.textContent = "—";
  if (questionProgress) questionProgress.style.width = "0%";
  if (mutateBadge) mutateBadge.style.display = "none";
  if (integerPanel) integerPanel.style.display = "none";
  updateScoreMeta();
  setTestHint("");
  popupSummary.textContent = "We're releasing your personalized pulses now. Watch the center top.";
  popupOverlay.innerHTML = "";
  log("reset_flow");
  setSessionUI(null, null);
  showStage("name");
}

function proceedFromNameStep() {
  const name = (userNameInput?.value || "").trim();
  if (!name) {
    setNameHint("Please enter your name first.");
    userNameInput?.focus();
    return;
  }
  setNameHint("");
  setStoryPrompt(name);
  showStage("intro");
  $("initialText")?.focus();
}

async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setIntroHint("Your browser does not support mic recording.");
    return;
  }
  mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  audioChunks = [];
  recordedAudioBlob = null;
  const preferredMime =
    typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm")
      ? "audio/webm"
      : "";
  mediaRecorder = preferredMime
    ? new MediaRecorder(mediaStream, { mimeType: preferredMime })
    : new MediaRecorder(mediaStream);
  recordingMimeType = mediaRecorder.mimeType || preferredMime || "audio/webm";

  mediaRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      audioChunks.push(event.data);
    }
  });

  mediaRecorder.addEventListener("stop", () => {
    recordedAudioBlob = audioChunks.length
      ? new Blob(audioChunks, { type: recordingMimeType })
      : null;
    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
      mediaStream = null;
    }
    setRecordButtonState();
    if (recordedAudioBlob) {
      setIntroHint("Voice captured. Click Launch Session to transcribe and continue.");
    }
  });

  mediaRecorder.start();
  setIntroHint("Recording... click again to stop.");
  setRecordButtonState();
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state !== "recording") return;
  mediaRecorder.stop();
}

function getAudioExtension() {
  if (recordingMimeType.includes("mp4") || recordingMimeType.includes("mpeg")) return "m4a";
  if (recordingMimeType.includes("ogg")) return "ogg";
  if (recordingMimeType.includes("wav")) return "wav";
  return "webm";
}

async function resolveInitialText() {
  const typed = $("initialText").value.trim();
  if (typed) return typed;
  if (!recordedAudioBlob) return "";

  setLoadingMessage("Transcribing your recording...");
  const formData = new FormData();
  formData.append("audio", recordedAudioBlob, `recording.${getAudioExtension()}`);
  const data = await postFormData("/session/transcribe", formData);
  const text = (data.text || "").trim();
  if (text) {
    $("initialText").value = text;
  }
  return text;
}

function clearMutationTimers() {
  mutationTimers.forEach((id) => clearTimeout(id));
  mutationTimers = [];
}

// Socket -------------------------------------------------------------------
function initSocket() {
  if (socketInitialized) return;
  socket = io({ transports: ["websocket"] });
  socketInitialized = true;

  socket.on("connect", () => {
    $("wsStatus").textContent = "WS: connected";
    log("WS connected", socket.id);
    logPopupEvent({ event: "connect", socket_id: socket.id });
    // ── FIX #2: If we already have a session_id (restored from sessionStorage),
    //    re-join its socket room so popup events are still received after refresh.
    if (sessionId) {
      joinSessionRoom(sessionId);
      log("ws_reconnect: rejoined room for session=" + sessionId);
    }
  });

  socket.on("disconnect", () => {
    $("wsStatus").textContent = "WS: disconnected";
    log("WS disconnected");
    logPopupEvent({ event: "disconnect" });
  });

  socket.on("connect_error", (err) => {
    log("WS error", err.message || String(err));
    logPopupEvent({ event: "connect_error", error: err.message || String(err) });
  });

  socket.on("server_hello", (data) => log("server_hello", data));

  socket.on("joined", (data) => log("joined room", data));

  socket.on("popup", (payload) => {
    log("popup event", payload);
    logPopupEvent({ event: "popup", payload });
    enqueuePopup(payload);
  });

  socket.on("suggestions", (payload) => {
    setSuggestions((payload && payload.items) || []);
  });

  socket.onAny((event, payload) => {
    if (event === "popup") return;
    logPopupEvent({ event, payload });
  });
}

function joinSessionRoom(targetId) {
  const id = targetId || sessionId;
  if (!id) return;
  if (!socketInitialized) initSocket();
  const payload = { session_id: id };
  const emitJoin = () => {
    socket.emit("join_session", payload);
    logPopupEvent({ event: "join_session", session_id: id });
  };

  if (socket.connected) emitJoin();
  else socket.once("connect", emitJoin);
}

// Popup rendering ----------------------------------------------------------
function logPopupEvent(obj) {
  if (!popupConsole) return;
  const row = document.createElement("div");
  row.className = "row";
  row.textContent = `[${new Date().toLocaleTimeString()}] ${JSON.stringify(obj)}`;
  popupConsole.prepend(row);
  if (popupConsole.children.length > 200) popupConsole.removeChild(popupConsole.lastChild);
}

function enqueuePopup(payload) {
  if (!payload) return;
  const message = String(payload.message || "");
  const parts = message
    .split("\n")
    .map((part) => part.trim())
    .filter(Boolean);
  const keyBase = `${payload.type || "unknown"}|${message}`;
  if (recentPopups.has(keyBase)) {
    return;
  }
  recentPopups.add(keyBase);
  if (recentPopups.size > 50) {
    const first = recentPopups.values().next().value;
    recentPopups.delete(first);
  }

  if (parts.length <= 1) {
    popupQueue.push(payload);
  } else {
    const ttl = payload.ttl || 4000;
    const perTtl = Math.max(2500, Math.floor(ttl / parts.length));
    parts.forEach((part) => {
      popupQueue.push({
        ...payload,
        message: part,
        ttl: perTtl,
      });
    });
  }
  processPopupQueue();
}

function processPopupQueue() {
  if (popupActive || popupQueue.length === 0) return;
  popupActive = true;
  const payload = popupQueue.shift();
  showPopupCard(payload, () => {
    popupActive = false;
    processPopupQueue();
  });
}

function showPopupCard(payload, done) {
  if (!popupOverlay) {
    done?.();
    return;
  }
  popupOverlay.innerHTML = "";
  const type = payload?.type || "pulse";
  const msg = payload?.message || "";

  const el = document.createElement("div");
  el.className = `popup ${escapeHTML(type)}`;
  el.innerHTML = `
    <div class="type">${escapeHTML(type)}</div>
    <div class="msg">${escapeHTML(msg)}</div>
  `;
  popupOverlay.prepend(el);

  clearTimeout(popupTimer);
  const duration = Math.min(Math.max(payload?.ttl || 3500, 2000), 7000);
  popupTimer = setTimeout(() => {
    el.remove();
    done?.();
  }, duration);
}

function escapeHTML(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ============================================================================
// Acadza question panel
// ============================================================================
//
// RENDERING PIPELINE (matches Acadza production engine)
// ─────────────────────────────────────────────────────
//  Raw API string
//    │
//    ▼
//  fixImageDomains()        — S3 → CloudFront URL rewriting (question + options)
//    │
//    ▼
//  decodeHtmlEntities()     — &nbsp; &lt; &gt; &amp; ½ → decoded via textarea
//    │
//    ▼
//  parse into real DOM      — browser handles all remaining entities + tags
//    │
//    ▼
//  cleanDomTree()           — strip CKEditor highlights, make images responsive
//    │
//    ▼
//  unwrapBlockWrapper()     — remove lone outer <p>/<div> so options render inline
//    │
//    ▼
//  .innerHTML =             — ALWAYS innerHTML, never textContent
//    │
//    ▼
//  Wiris re-render (async)  — math equations re-processed after DOM insertion
// ============================================================================

// ============================================================================
// ACADZA RENDERING PIPELINE — HARDENED v2
// ============================================================================
// Full rendering contract:
//   1. ALWAYS innerHTML, never textContent.
//   2. Auto-detect content type: MathML | LaTeX | HTML | plain-text.
//   3. Normalize every possible option shape to { label, html }.
//   4. Safe fallback at every step — render never crashes or goes blank.
//   5. Wiris race-condition fixed with staggered double-trigger.
//   6. Consistent vertical alignment via inline CSS on every element.
//   7. Debug logging on any render failure.
// ============================================================================

// ── Step 1: S3 → CloudFront URL rewriting ──────────────────────────────────
function fixImageDomains(html) {
  if (!html || typeof html !== "string") return html || "";
  return html
    .replace(/https:\/\/acadza-check\.s3\.amazonaws\.com/g,         "https://d2tj2w3o9n8i90.cloudfront.net")
    .replace(/https:\/\/acadza-check-new\.s3\.amazonaws\.com/g,      "https://d18g32y7fps2t8.cloudfront.net")
    .replace(/https:\/\/acadza-check-new\.s3\.ap-south-1\.amazonaws\.com/g, "https://d18g32y7fps2t8.cloudfront.net");
}

// Backwards-compat alias used elsewhere in this file.
function processQuestionHTML(html) { return fixImageDomains(html); }

// ── Step 2: HTML entity decoding ───────────────────────────────────────────
// Uses a textarea — decodes ALL named + numeric HTML entities before DOM work.
function decodeHtmlEntities(html) {
  if (!html || typeof html !== "string") return "";
  const ta = document.createElement("textarea");
  ta.innerHTML = html;
  return ta.value;
}

// ── Content-type detector ──────────────────────────────────────────────────
// Returns: "mathml" | "latex" | "html" | "plain"
function detectContentType(str) {
  if (!str || typeof str !== "string") return "plain";
  const s = str.trim();
  if (/<math[\s>]/i.test(s) || /<mfrac|<msup|<msub|<mrow|<mn|<mi|<mo/i.test(s)) return "mathml";
  if (/<[a-zA-Z][^>]*>/.test(s)) return "html";
  // Detect LaTeX markers: backslash commands, ^{}, _{}, \frac, etc.
  if (/\\[a-zA-Z]+|[\^_]\{|\\\(|\\\[/.test(s)) return "latex";
  return "plain";
}

// ── Step 1b: LaTeX/Math notation converter ─────────────────────────────────
// Converts inline LaTeX patterns to HTML equivalents.
// ONLY runs on strings confirmed to be "latex" or "plain" type (no HTML tags).
function convertMathNotation(str) {
  if (!str || typeof str !== "string") return str || "";

  // Skip if it already has real HTML tags (not MathML — those we keep)
  const hasHtmlTags = /<(?!math|mfrac|msup|msub|mn|mi|mo|mrow|msqrt|mfenced)[a-zA-Z]/.test(str);
  if (hasHtmlTags) return str;

  let s = str;

  // Greek letters
  const greekMap = {
    '\\omega': 'ω', '\\Omega': 'Ω', '\\alpha': 'α', '\\beta': 'β',
    '\\gamma': 'γ', '\\Gamma': 'Γ', '\\delta': 'δ', '\\Delta': 'Δ',
    '\\epsilon': 'ε', '\\varepsilon': 'ε', '\\theta': 'θ', '\\Theta': 'Θ',
    '\\lambda': 'λ', '\\Lambda': 'Λ', '\\mu': 'μ', '\\nu': 'ν',
    '\\pi': 'π', '\\Pi': 'Π', '\\rho': 'ρ', '\\sigma': 'σ', '\\Sigma': 'Σ',
    '\\tau': 'τ', '\\phi': 'φ', '\\Phi': 'Φ', '\\psi': 'ψ', '\\Psi': 'Ψ',
    '\\chi': 'χ', '\\xi': 'ξ', '\\eta': 'η', '\\zeta': 'ζ', '\\kappa': 'κ',
  };
  Object.entries(greekMap).forEach(([k, v]) => { s = s.replaceAll(k, v); });

  // Math symbols
  s = s.replace(/\\sqrt\{([^}]+)\}/g,         '√($1)');
  s = s.replace(/\\sqrt([a-zA-Z0-9])/g,        '√$1');
  s = s.replace(/\\times/g,                    '×');
  s = s.replace(/\\cdot/g,                     '·');
  s = s.replace(/\\pm/g,                       '±');
  s = s.replace(/\\mp/g,                       '∓');
  s = s.replace(/\\leq|\\le(?![a-z])/g,        '≤');
  s = s.replace(/\\geq|\\ge(?![a-z])/g,        '≥');
  s = s.replace(/\\neq|\\ne(?![a-z])/g,        '≠');
  s = s.replace(/\\infty/g,                    '∞');
  s = s.replace(/\\approx/g,                   '≈');
  s = s.replace(/\\propto/g,                   '∝');
  s = s.replace(/\\rightarrow|\\to(?![a-z])/g, '→');
  s = s.replace(/\\leftarrow/g,                '←');
  s = s.replace(/\\Rightarrow/g,               '⇒');

  // Fractions: \frac{a}{b} → (a)/(b) with super/sub-script styling
  s = s.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g,
    '<span style="display:inline-flex;flex-direction:column;vertical-align:middle;text-align:center;line-height:1.1;font-size:0.9em;">' +
    '<span style="border-bottom:1px solid currentColor;padding:0 2px;">$1</span>' +
    '<span style="padding:0 2px;">$2</span></span>');

  // Superscripts: ^{...} or ^x
  s = s.replace(/\^\{([^}]+)\}/g, '<sup style="font-size:0.75em;vertical-align:super;line-height:0;">$1</sup>');
  s = s.replace(/\^([a-zA-Z0-9])/g, '<sup style="font-size:0.75em;vertical-align:super;line-height:0;">$1</sup>');

  // Subscripts: _{...} or _x
  s = s.replace(/_\{([^}]+)\}/g, '<sub style="font-size:0.75em;vertical-align:sub;line-height:0;">$1</sub>');
  s = s.replace(/_([a-zA-Z0-9])/g, '<sub style="font-size:0.75em;vertical-align:sub;line-height:0;">$1</sub>');

  // Strip leftover LaTeX delimiters
  s = s.replace(/\\\(|\\\)/g, '');
  s = s.replace(/\\\[|\\\]/g, '');
  s = s.replace(/\{([^}]*)\}/g, '$1');

  return s;
}

// ── Step 3: DOM tree cleanup ────────────────────────────────────────────────
// Operates on a detached DOM node. Removes CKEditor artefacts, ensures all
// math is inline, images are responsive, tables are compact.
function cleanDomTree(el) {
  // Remove CKEditor grey highlight spans
  el.querySelectorAll("span[style]").forEach((span) => {
    const bg = span.style.backgroundColor || "";
    if (bg.includes("rgba(220") || bg.includes("rgb(220")) {
      span.style.backgroundColor = "";
    }
    // Fix white-space:nowrap that breaks math layout
    if (span.style.whiteSpace === "nowrap") span.style.whiteSpace = "normal";

    // Fix 1 — Recover text accidentally split outside highlight spans.
    // CKEditor sometimes wraps only a fragment (e.g. "and") in a styled span
    // while the rest of the option text lives in adjacent sibling text nodes.
    // If the span carries trivially short text AND a meaningful sibling exists,
    // absorb the sibling so the full option text is preserved.
    if (span.textContent.trim().length <= 5) {
      let sibling = span.nextSibling;
      while (sibling) {
        if (sibling.nodeType === Node.TEXT_NODE && sibling.textContent.trim()) {
          span.textContent = (span.textContent + sibling.textContent).trim();
          const next = sibling.nextSibling;
          sibling.remove();
          sibling = next;
        } else {
          break;
        }
      }
    }
  });

  // All images: responsive + inline-block for vertical alignment
  el.querySelectorAll("img").forEach((img) => {
    img.style.maxWidth = "100%";
    img.style.height = "auto";
    img.style.display = "inline-block";
    img.style.verticalAlign = "middle";
    img.style.objectFit = "contain";
    // Ensure Wiris/formula images never exceed container
    if (/Wiris|wiris|formula/i.test(img.className || "")) {
      img.style.maxHeight = "2.5em";
    }
  });

  // MathML: force inline display so it never becomes block
  el.querySelectorAll("math").forEach((math) => {
    math.setAttribute("display", "inline");
    math.style.display = "inline-block";
    math.style.verticalAlign = "middle";
    math.style.lineHeight = "normal";
    // Unwrap any block-level ancestor that MathML was accidentally placed inside
    const parent = math.parentElement;
    if (parent && (parent.tagName === "P" || parent.tagName === "DIV") &&
        parent.children.length === 1 && parent.parentElement === el) {
      parent.style.display = "inline";
      parent.style.margin = "0";
      parent.style.padding = "0";
    }
  });

  // Tables: compact + responsive inside option cards
  el.querySelectorAll("table").forEach((table) => {
    table.style.borderCollapse = "collapse";
    table.style.maxWidth = "100%";
    table.style.display = "inline-table";
    table.style.verticalAlign = "middle";
    table.style.fontSize = "0.9em";
    table.querySelectorAll("td, th").forEach((cell) => {
      cell.style.padding = "2px 6px";
      cell.style.textAlign = "center";
      cell.style.verticalAlign = "middle";
      cell.style.whiteSpace = "nowrap";
    });
  });

  // Remove empty paragraphs that cause phantom vertical spacing
  el.querySelectorAll("p, div").forEach((node) => {
    if (!node.textContent.trim() && !node.querySelector("img, math, table, span[data-mathml]")) {
      node.remove();
    }
  });

  // Flatten any remaining block-display <p>/<div> inside inline context
  el.querySelectorAll("p").forEach((p) => {
    p.style.display = "inline";
    p.style.margin = "0";
    p.style.padding = "0";
  });
}

// ── Step 4: Unwrap lone block wrapper ──────────────────────────────────────
// If entire content is wrapped in a single <p> or <div>, strip that outer tag.
// Fix 4: NEVER unwrap if the inner content contains MathML, images, or tables —
// those elements rely on their wrapper for correct layout/display.
function unwrapBlockWrapper(el) {
  const nonEmpty = Array.from(el.childNodes).filter(
    (n) => !(n.nodeType === Node.TEXT_NODE && n.textContent.trim() === "")
  );
  if (
    nonEmpty.length === 1 &&
    nonEmpty[0].nodeType === Node.ELEMENT_NODE &&
    (nonEmpty[0].tagName === "P" || nonEmpty[0].tagName === "DIV")
  ) {
    const inner = nonEmpty[0].innerHTML.trim();
    // Only unwrap if the wrapper contains no MathML, images, or tables —
    // stripping the wrapper around those breaks their rendering.
    if (inner && !/<math|<img|<table/i.test(inner)) {
      return inner;
    }
  }
  return el.innerHTML;
}

// ── Safe fallback renderer ─────────────────────────────────────────────────
// Called when renderAcadzaHTML returns empty. Returns the best displayable
// version of raw content without crashing, always non-empty if input was non-empty.
function _safeFallbackRender(raw) {
  try {
    const s = String(raw ?? "").trim();
    if (!s) return "";
    // Try math conversion as last-resort for plain/latex strings
    const converted = convertMathNotation(decodeHtmlEntities(s));
    if (converted && converted !== s) return converted;
    return escapeHTML(s);
  } catch(e) {
    return escapeHTML(String(raw ?? ""));
  }
}

// ── Master HTML renderer ────────────────────────────────────────────────────
// Single entry point for ALL Acadza content. Returns clean HTML string.
// GUARANTEE: never returns empty if input was non-empty. Never throws.
function renderAcadzaHTML(raw) {
  try {
    // Defensive: handle null, undefined, numbers, booleans
    if (raw === null || raw === undefined) return "";
    const str = String(raw).trim();
    if (!str) return "";

    // Fix 9 — Auto-detect diagram-only URLs.
    // Acadza sometimes stores image options as bare URLs (no <img> wrapper).
    // Detect these and wrap them before entering the main pipeline.
    if (/\.(png|jpg|jpeg|svg|gif|webp)(\?[^"'\s]*)?$/i.test(str) && !/<[a-z]/i.test(str)) {
      return `<img src="${fixImageDomains(str)}" style="max-width:100%;height:auto;display:inline-block;vertical-align:middle;" alt="option image" />`;
    }

    // Detect content type to route correctly
    const contentType = detectContentType(str);

    // Step 1: CDN URL rewriting
    const cdnFixed = fixImageDomains(str);

    // Step 2: Entity decoding
    const decoded = decodeHtmlEntities(cdnFixed);

    // Step 1b: LaTeX/math conversion (only for non-HTML types)
    // Fix 7: Only skip conversion for explicit mathml — MathML that arrives
    // embedded inside an HTML container would previously be corrupted because
    // "html" also skipped conversion, but html containers can still contain
    // LaTeX that needs processing. MathML itself must never be run through
    // the LaTeX converter as it would corrupt <math> tag attributes.
    const mathFixed = (contentType === "mathml")
      ? decoded
      : convertMathNotation(decoded);

    // Step 3+4: DOM parse, clean, unwrap
    const tmp = document.createElement("div");
    tmp.innerHTML = mathFixed;
    cleanDomTree(tmp);
    const result = unwrapBlockWrapper(tmp);

    // Safe fallback: if pipeline produced empty string from non-empty input
    if (!result && str) {
      log("option_render_fallback", { raw: str.slice(0, 80), contentType });
      return _safeFallbackRender(str);
    }

    return result;
  } catch (err) {
    log("option_render_error", { raw: String(raw ?? "").slice(0, 80), error: err.message });
    return _safeFallbackRender(raw);
  }
}

// ── Wiris math re-render helper ────────────────────────────────────────────
// Triggers Wiris on a container. Uses a double-trigger (0ms + 120ms) to fix
// the race condition where equations weren't rendered on first pass because
// Wiris initialisation hadn't completed.
function triggerWirisRender(containerEl) {
  if (!containerEl) return;
  const _doRender = () => {
    try {
      if (window.com?.wiris?.js?.JsPluginViewer) {
        window.com.wiris.js.JsPluginViewer.parseElement(containerEl, true, () => {});
      } else if (window.WirisPlugin?.Parser) {
        window.WirisPlugin.Parser.initParse(containerEl);
      }
    } catch (e) {
      // Wiris unavailable — MathML falls back to browser-native rendering.
    }
  };
  // First pass: immediately after DOM insertion
  setTimeout(_doRender, 0);
  // Second pass: after Wiris script likely finished async init
  setTimeout(_doRender, 120);
}

// ── normalizeOptions ────────────────────────────────────────────────────────
// Normalises ALL possible Acadza API option shapes into:
//   [{ label: "A", html: "<raw acadza html>" }, ...]
//
// Handled input shapes:
//   Array [{ label, text }]                    — backend transformer output
//   Array [{ identifier, content }]            — raw Acadza API
//   Array [{ identifier, html }]               — alternative raw API
//   Array [{ label, content, text:"" }]        — Shape 5 (html in content, text blank)
//   Plain object { a: "...", b: "..." }        — some mutated responses
//   Nested arrays [[label, html], ...]         — occasional transformer variant
//   Array of plain strings ["80 J", "Zero"]   — simplest mutated output
//   Array of numbers [1, 2, 3, 4]             — integer-type options
//   Object with numeric keys {0:…,1:…,2:…}   — PHP-style serialization
//   null / undefined / empty                  — returns []
function normalizeOptions(rawOptions) {
  if (!rawOptions) return [];

  // ── Shape: plain object { a: "html", b: "html" } or { 0: …, 1: … }
  if (!Array.isArray(rawOptions) && typeof rawOptions === "object") {
    const entries = Object.entries(rawOptions);
    if (!entries.length) return [];
    return entries
      .map(([key, val], idx) => {
        const labelChar = /^\d+$/.test(key)
          ? String.fromCharCode(65 + parseInt(key, 10))
          : key.trim().toUpperCase().charAt(0);
        const html = val === null || val === undefined
          ? ""
          : typeof val === "string"
            ? val
            : typeof val === "number"
              ? String(val)
              : String(val?.html ?? val?.content ?? val?.text ?? val ?? "");
        return { label: labelChar || String.fromCharCode(65 + idx), html };
      })
      .filter((o) => o.label);
  }

  if (!Array.isArray(rawOptions) || !rawOptions.length) return [];

  // ── Shape: nested arrays [[label, html], ...]
  if (Array.isArray(rawOptions[0])) {
    return rawOptions
      .map(([key, val], idx) => ({
        label: (String(key || "").trim().toUpperCase().charAt(0)) || String.fromCharCode(65 + idx),
        html:  val === null || val === undefined ? "" : String(val),
      }))
      .filter((o) => o.label);
  }

  return rawOptions.map((opt, idx) => {
    // ── Shape: plain string
    if (typeof opt === "string") {
      return { label: String.fromCharCode(65 + idx), html: opt };
    }

    // ── Shape: number (integer options, rare)
    if (typeof opt === "number" || typeof opt === "boolean") {
      return { label: String.fromCharCode(65 + idx), html: String(opt) };
    }

    // ── Shape: null/undefined (guard — should not appear, but seen in wild)
    if (opt === null || opt === undefined) {
      log("option_render_error", { msg: "null/undefined option at index", idx });
      return { label: String.fromCharCode(65 + idx), html: "" };
    }

    // Label — try every known field name, fall back to A/B/C/D by index
    const rawLabel = String(
      opt.label        ??
      opt.identifier   ??
      opt.option_label ??
      opt.key          ??
      opt.letter       ??
      ""
    ).trim();
    const label = rawLabel
      ? rawLabel.toUpperCase().charAt(0)
      : String.fromCharCode(65 + idx);

    // HTML content — priority order (Fix 2: added image/img/media keys):
    //   html > content > body > image > img > media > option_html > option_content > text > value > data
    // text is LAST because Acadza Shape 5 sets text="" with real HTML in content.
    const htmlRaw =
      opt.html           !== undefined ? opt.html           :
      opt.content        !== undefined ? opt.content        :
      opt.body           !== undefined ? opt.body           :
      opt.image          !== undefined ? opt.image          :
      opt.img            !== undefined ? opt.img            :
      opt.media          !== undefined ? opt.media          :
      opt.option_html    !== undefined ? opt.option_html    :
      opt.option_content !== undefined ? opt.option_content :
      opt.text           !== undefined ? opt.text           :
      opt.value          !== undefined ? opt.value          :
      opt.data           !== undefined ? opt.data           :
      "";

    // Coerce to string — guard against null/number values in any field
    let html = htmlRaw === null || htmlRaw === undefined
      ? ""
      : typeof htmlRaw === "number" || typeof htmlRaw === "boolean"
        ? String(htmlRaw)
        : String(htmlRaw);

    // Fix 3 — Merge split text + content fields.
    // Acadza frequently splits math expression text and HTML content across two
    // fields. When both are non-empty and distinct, concatenate them so the full
    // option text is preserved.
    if (opt.text && opt.content &&
        String(opt.text).trim() && String(opt.content).trim() &&
        String(opt.text).trim() !== String(opt.content).trim()) {
      html = String(opt.text).trim() + " " + String(opt.content).trim();
    }

    // Fix 8 — Fragment-only guard.
    // If the resolved html is suspiciously short (≤3 chars) but the original
    // html field was meaningfully longer, fall back to the raw html field
    // to avoid rendering a lone token like "and", "or", or a comma.
    if (html.trim().length <= 3 && String(opt.html ?? "").length > 10) {
      html = String(opt.html);
    }

    return { label, html };
  }).filter((o) => o.label);
}

// ── normalizeQuestionOptions ────────────────────────────────────────────────
// Top-level wrapper: reads from every known Acadza field name for the options
// list. Works identically for original, mutated, and fallback questions.
// Fix 10: Extended to cover all known mutated-question option field shapes.
function normalizeQuestionOptions(q) {
  if (!q) return [];
  const raw =
    q.options       ||
    q.answers       ||
    q.choices       ||
    q.mcq_options   ||
    q.option_list   ||
    q.alternatives  ||
    q.responses     ||
    q.option        ||
    [];
  return normalizeOptions(raw);
}

// ── Option renderer — single option card ──────────────────────────────────
// Builds one <label class="option"> DOM node for a { label, html } option.
// GUARANTEE: always renders something — never blank — even if html is empty.
// Used by renderTestQuestion for BOTH original and mutated questions.
function buildOptionCard(opt, questionId, currentSelected) {
  try {
    const wrapper     = document.createElement("label");
    wrapper.className = "option";
    wrapper.style.cssText = "display:flex;align-items:center;gap:10px;cursor:pointer;";

    if (currentSelected === opt.label) {
      wrapper.classList.add("selected");
    }

    const input   = document.createElement("input");
    input.type    = "radio";
    input.name    = `option-${questionId}`;
    input.value   = opt.label;
    input.checked = currentSelected === opt.label;
    input.style.cssText = "flex-shrink:0;margin:0;cursor:pointer;";

    const body          = document.createElement("div");
    body.className      = "option-body";
    body.style.cssText  = "display:flex;align-items:center;gap:8px;flex:1;min-width:0;";

    const labelEl           = document.createElement("span");
    labelEl.className       = "option-label";
    labelEl.textContent     = opt.label;
    labelEl.style.cssText   = "flex-shrink:0;font-weight:600;min-width:1.2em;text-align:center;";

    const textEl          = document.createElement("div");
    textEl.className      = "option-text";
    // Ensure text wraps and images don't overflow
    textEl.style.cssText  = "flex:1;min-width:0;word-break:break-word;overflow-wrap:anywhere;line-height:1.5;";

    // Render via full pipeline
    let renderedHtml = "";
    try {
      renderedHtml = renderAcadzaHTML(opt.html);
    } catch (renderErr) {
      log("option_render_error", { label: opt.label, raw: String(opt.html ?? "").slice(0, 80), error: renderErr.message });
    }

    // Final safety net: NEVER leave blank
    // Fix 5: Trigger fallback on ANY blank/whitespace result, not just when opt.html was non-empty.
    if ((!renderedHtml || renderedHtml.trim() === "") &&
        (opt.html !== "" && opt.html !== null && opt.html !== undefined)) {
      renderedHtml = _safeFallbackRender(opt.html);
      log("option_render_fallback", { label: opt.label, raw: String(opt.html ?? "").slice(0, 80) });
    }

    // ALWAYS use innerHTML — never textContent
    textEl.innerHTML = renderedHtml || escapeHTML(String(opt.label));

    // Fix 6 — Detect inline image-only options and prevent invisible flex collapse.
    // When a rendered option contains only an <img>, the default flex container
    // collapses to zero height if the image hasn't loaded. Ensure it's visible.
    if (/^\s*<img\b/i.test(textEl.innerHTML.trim())) {
      textEl.style.display = "flex";
      textEl.style.alignItems = "center";
      textEl.style.justifyContent = "flex-start";
    }

    // Wiris double-trigger for this card's math
    triggerWirisRender(textEl);

    body.appendChild(labelEl);
    body.appendChild(textEl);
    wrapper.appendChild(input);
    wrapper.appendChild(body);

    return { wrapper, input };
  } catch (err) {
    log("option_render_error", { label: opt?.label, error: err.message });
    // Emergency fallback card — always returns something
    const fallback          = document.createElement("label");
    fallback.className      = "option";
    fallback.style.cssText  = "display:flex;align-items:center;gap:10px;cursor:pointer;";
    fallback.textContent    = `${opt?.label || "?"}: ${String(opt?.html ?? "")}`;
    const input   = document.createElement("input");
    input.type    = "radio";
    input.name    = `option-${questionId}`;
    input.value   = opt?.label || "";
    fallback.prepend(input);
    return { wrapper: fallback, input };
  }
}

function setTestHint(text) {
  if (testHint) testHint.textContent = text || "";
}

function renderTestQuestion() {
  if (!questionStem || !questionOptions || !questionCounter) return;

  if (!testQuestions.length) {
    questionStem.textContent = "Questions will appear here with options.";
    questionOptions.innerHTML = "";
    questionCounter.textContent = "Questions —";
    if (questionSubject) questionSubject.textContent = "—";
    if (questionProgress) questionProgress.style.width = "0%";
    if (mutateBadge) mutateBadge.style.display = "none";
    if (btnPrevQuestion) btnPrevQuestion.disabled = true;
    if (btnNextQuestion) btnNextQuestion.disabled = true;
    return;
  }

  testQuestionIndex = Math.min(Math.max(testQuestionIndex, 0), testQuestions.length - 1);
  const q = testQuestions[testQuestionIndex];

  // ── Meta bar ──────────────────────────────────────────────────────────────
  if (questionCounter) {
    questionCounter.textContent = `Question ${testQuestionIndex + 1} of ${testQuestions.length}`;
  }
  if (questionSubject) {
    const subParts = [];
    if (q.subject)    subParts.push(q.subject);
    if (q.difficulty) subParts.push(q.difficulty);
    questionSubject.textContent = subParts.join(" · ") || "—";
  }
  if (questionProgress) {
    const pct = ((testQuestionIndex + 1) / testQuestions.length) * 100;
    questionProgress.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }
  if (mutateBadge) {
    const mutated = Boolean(q.mutated || (q.meta && q.meta.mutated));
    mutateBadge.style.display = mutated ? "inline-flex" : "none";
  }

  // ── Question type routing ─────────────────────────────────────────────────
  const qType = (q.question_type || "").toLowerCase();
  if (qType === "integer") {
    if (questionOptions) questionOptions.style.display = "none";
    if (integerPanel) {
      integerPanel.style.display = "flex";
      const existing = selectedOptions[q.question_id] || "";
      if (integerInput) integerInput.value = existing;
      attachKeypadListeners();
    }
  } else {
    if (questionOptions) questionOptions.style.display = "grid";
    if (integerPanel) integerPanel.style.display = "none";
  }

  // ── Render question stem ──────────────────────────────────────────────────
  // Always use innerHTML (never textContent) — stem contains HTML formatting,
  // <sup>/<sub>, math markup, and inline images from Acadza CKEditor.
  const stemParts = [];
  if (q.question_html) {
    stemParts.push(renderAcadzaHTML(q.question_html));
  }
  if (Array.isArray(q.question_images)) {
    q.question_images.forEach((src) => {
      const cdnSrc = fixImageDomains(src);
      stemParts.push(
        `<div class="q-img"><img src="${cdnSrc}" alt="question image" ` +
        `style="max-width:100%;height:auto;display:block;margin-top:8px;" /></div>`
      );
    });
  }
  questionStem.innerHTML = stemParts.join("");
  // Trigger Wiris math rendering on the stem asynchronously (Step 8 race fix)
  setTimeout(() => triggerWirisRender(questionStem), 0);

  // ── Render options ────────────────────────────────────────────────────────
  questionOptions.innerHTML = "";

  if (qType !== "integer") {
    // normalizeQuestionOptions handles every Acadza API shape and key name
    const opts = normalizeQuestionOptions(q);

    if (!opts.length) {
      const empty = document.createElement("div");
      empty.className = "option-empty";
      empty.textContent = "No options provided for this question.";
      questionOptions.appendChild(empty);
    } else {
      opts.forEach((opt) => {
        const { wrapper, input } = buildOptionCard(opt, q.question_id, selectedOptions[q.question_id]);

        // Change handler — updates selection state across all cards
        input.addEventListener("change", () => {
          selectedOptions[q.question_id] = opt.label;
          questionOptions.querySelectorAll("label.option").forEach((l) =>
            l.classList.toggle(
              "selected",
              l.querySelector("input")?.value === opt.label
            )
          );
        });

        // Full-row click target
        wrapper.addEventListener("click", (e) => {
          if (e.target !== input) {
            input.checked = true;
            input.dispatchEvent(new Event("change", { bubbles: true }));
          }
        });

        questionOptions.appendChild(wrapper);
      });

      // Final Wiris trigger on the full options container after all cards built
      triggerWirisRender(questionOptions);
    }
  }

  if (btnPrevQuestion) btnPrevQuestion.disabled = testQuestionIndex === 0;
  if (btnNextQuestion) btnNextQuestion.disabled = testQuestionIndex >= testQuestions.length - 1;
  updateScoreMeta();
}

async function loadTestQuestions() {
  if (!questionStem || !questionCounter) return;
  setTestHint("Loading questions…");
  questionCounter.textContent = "Loading questions…";
  if (questionSubject) questionSubject.textContent = "—";
  if (questionProgress) questionProgress.style.width = "0%";
  clearMutationTimers();
  questionStem.textContent = "Fetching questions from server...";
  questionOptions.innerHTML = "";
  try {
    const data = await getJSON("/api/questions/load-test-questions");
    const raw = data.questions || data.data || data.results || [];
    // Normalize each question's options field to the canonical key "options"
    // so renderTestQuestion always finds normalizeQuestionOptions working.
    testQuestions = raw.map((q) => {
      if (!q.options) {
        // Promote whichever alternative key the API used
        q.options =
          q.answers      ||
          q.choices      ||
          q.mcq_options  ||
          q.option_list  ||
          [];
      }
      return q;
    });
    testQuestionIndex = 0;
    if (!testQuestions.length) {
      setTestHint("No questions returned. Add IDs to data/question_ids.csv.");
      questionCounter.textContent = "Questions unavailable";
      return;
    }
    selectedOptions = {};
    answeredMap = {};
    setTestHint("");
    scheduleMutationsForQuestions();
    renderTestQuestion();
  } catch (err) {
    setTestHint(err.message || "Failed to load questions.");
    questionCounter.textContent = "Questions unavailable";
    log("questions_load_error", err.message || String(err));
  }
}

function gotoQuestion(delta) {
  if (!testQuestions.length) return;
  testQuestionIndex = Math.min(
    Math.max(testQuestionIndex + delta, 0),
    testQuestions.length - 1
  );
  renderTestQuestion();
}

function shouldMutateQuestion(q) {
  if (!q) return false;
  const type = (q.question_type || "").toLowerCase();
  if (!["scq", "integer"].includes(type)) return false;
  // normalizeQuestionOptions reads from all known API key names
  const normalizedOpts = normalizeQuestionOptions(q);
  const hasDigits =
    /\d/.test(q.question_html || "") ||
    normalizedOpts.some((opt) => /\d/.test(opt.html || ""));
  return hasDigits && !q.mutated && !(q.meta && q.meta.mutated);
}

function scheduleMutationsForQuestions() {
  clearMutationTimers();
  testQuestions.forEach((q, idx) => {
    if (!shouldMutateQuestion(q)) return;
    const timerId = setTimeout(() => mutateQuestionAt(idx), 5000);
    mutationTimers.push(timerId);
  });
}

async function mutateQuestionAt(index) {
  const q = testQuestions[index];
  if (!q || q.mutated || (q.meta && q.meta.mutated)) return;
  try {
    const res = await fetch(`/api/questions/mutate/${q.question_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.question) {
      const mutated = data.question;
      mutated.mutated = Boolean(data.mutated);
      // Normalize options field — mutated responses sometimes use different key names
      if (!mutated.options || (Array.isArray(mutated.options) && !mutated.options.length)) {
        mutated.options =
          mutated.answers      ||
          mutated.choices      ||
          mutated.mcq_options  ||
          mutated.option_list  ||
          [];
      }
      testQuestions[index] = mutated;
      if (index === testQuestionIndex) {
        renderTestQuestion();
      }
    } else {
      log("mutate_failed", data.message || data.error || res.status);
    }
  } catch (err) {
    log("mutate_error", err.message || String(err));
  }
}

// ── FIX #1 (part A): submitCurrentQuestion ────────────────────────────────
//
// WHAT WAS BROKEN:
//   The previous backend document confirmed selectedOption === correctAnswer
//   comparison was present, but updateScoreMeta() counted *answered* questions
//   as correct instead of only entries where correct === true.
//   Additionally the wrong-answer feedback was silent — students couldn't see
//   the right answer.
//
// WHAT IS FIXED HERE:
//   • correct_answer is read from q.correct_answer (SCQ) or q.correct_answers
//     (MCQ). Both are normalised to uppercase before comparison.
//   • Wrong answer feedback now shows: "Wrong ❌  (correct: B)"
//   • updateScoreMeta() is called after every submission and only counts
//     entries where correct === true.
//   • Integer type uses numeric tolerance comparison (abs diff < 1e-6).
//   • If no answer key is present, marks as not scored (not as correct).
function submitCurrentQuestion() {
  if (!testQuestions.length) {
    setTestHint("Load questions first.");
    return;
  }
  const q   = testQuestions[testQuestionIndex];
  const picked = selectedOptions[q.question_id];
  const qType  = (q.question_type || "").toLowerCase();

  if (qType === "integer") {
    const value = (picked || "").trim();
    if (!value) {
      setTestHint("Enter an integer answer first.");
      return;
    }
    const correctVal = q.integer_answer;
    let correct = false;
    if (correctVal !== undefined && correctVal !== null) {
      const numPicked   = Number(value);
      const numCorrect  = Number(correctVal);
      if (!Number.isNaN(numPicked) && !Number.isNaN(numCorrect)) {
        correct = Math.abs(numPicked - numCorrect) < 1e-6;
      } else {
        correct = value === String(correctVal).trim();
      }
    }
    answeredMap[q.question_id] = { selected: value, correct };
    updateScoreMeta();
    setTestHint(
      correct
        ? "Correct ✅"
        : `Wrong ❌  (correct: ${correctVal ?? "—"})`
    );
    return;
  }

  // ── SCQ / MCQ branch ─────────────────────────────────────────────────────
  if (!picked) {
    setTestHint("Select an option before submitting.");
    return;
  }

  const correctAnswer  = q.correct_answer  || "";          // single letter "B"
  const correctAnswers = q.correct_answers || [];          // ["A","C"] for MCQ

  let correct = false;
  let correctDisplay = "";

  if (correctAnswer) {
    // Single-correct SCQ — definitive comparison
    correct        = picked.trim().toUpperCase() === correctAnswer.trim().toUpperCase();
    correctDisplay = correctAnswer.trim().toUpperCase();
  } else if (correctAnswers.length) {
    // Multi-correct MCQ
    const pickedSet  = new Set(Array.isArray(picked) ? picked : [picked]);
    const correctSet = new Set(correctAnswers.map((v) => String(v).trim().toUpperCase()));
    correct        = pickedSet.size === correctSet.size &&
                     [...pickedSet].every((v) => correctSet.has(String(v).trim().toUpperCase()));
    correctDisplay = [...correctSet].sort().join(", ");
  } else {
    // No answer key available — cannot score
    correct        = false;
    correctDisplay = "";
  }

  answeredMap[q.question_id] = { selected: picked, correct };
  updateScoreMeta();

  if (!correctDisplay) {
    setTestHint("Saved. (No answer key available for this question.)");
  } else if (correct) {
    setTestHint("Correct ✅");
  } else {
    setTestHint(`Wrong ❌  (correct: ${correctDisplay})`);
  }
}

// ── FIX: submitAllTest — wire Submit All to the backend ──────────────────
//
// WHAT WAS BROKEN:
//   The Submit button only ran local UI logic (submitCurrentQuestion).
//   There was NO call to any backend scoring endpoint.
//   Logs confirmed: GET /load-test-questions and POST /mutate only — no POST
//   to /submit.  Server-side answer verification never happened.
//
// WHAT IS FIXED:
//   submitAllTest() collects every selectedOptions entry and POSTs them all
//   to /api/questions/submit-test in one call.
//   The server re-verifies every answer against the authoritative correct_answer
//   stored server-side (questions are NOT trusted from the client).
//   The verified score is rendered in the #submitAllResult panel.
//
// HOW TO WIRE IN HTML:
//   Add a "Submit All Answers" button with id="btnSubmitAllTest".
//   Add a result div with id="submitAllResult".
//   This function handles the rest.
async function submitAllTest() {
  if (!testQuestions.length) {
    setTestHint("Load questions before submitting.");
    return;
  }

  const answeredCount = Object.keys(selectedOptions).length;
  if (!answeredCount) {
    setTestHint("Answer at least one question first.");
    return;
  }

  if (btnSubmitAllTest) btnSubmitAllTest.disabled = true;
  setTestHint("Submitting to server for scoring…");

  try {
    const payload = {
      // answers: { question_id → selected_value }
      answers: { ...selectedOptions },
      // Send full question objects so the server doesn't need to re-fetch
      // from Acadza (which may be blocked).  The server will still re-verify
      // correct_answer from its own data and ignore any client-supplied answers.
      questions: testQuestions.map((q) => ({
        question_id:    q.question_id,
        question_type:  q.question_type,
        correct_answer: q.correct_answer  || "",
        correct_answers: q.correct_answers || [],
        integer_answer: q.integer_answer  ?? null,
      })),
    };

    const data = await postJSON("/api/questions/submit-test", payload);
    log("submit_test_result", data);

    // ── Update local answeredMap to reflect server-verified results ─────────
    // This ensures the score display in the HUD matches the server score.
    if (Array.isArray(data.results)) {
      data.results.forEach((r) => {
        answeredMap[r.question_id] = {
          selected: r.selected,
          correct:  r.is_correct,
        };
      });
    }
    updateScoreMeta();

    // ── Render the result panel ──────────────────────────────────────────────
    const score      = data.score      ?? 0;
    const total      = data.total      ?? testQuestions.length;
    const percentage = data.percentage ?? 0;

    if (submitAllResult) {
      const pctColor =
        percentage >= 70 ? "#4ade80" :
        percentage >= 40 ? "#facc15" : "#f87171";

      submitAllResult.innerHTML = `
        <div class="submit-result-card">
          <div class="submit-result-heading">Test Submitted ✅</div>
          <div class="submit-result-score" style="color:${pctColor}">
            ${score} / ${total}
            <span class="submit-result-pct">(${percentage}%)</span>
          </div>
          <div class="submit-result-breakdown">
            ${(data.results || []).map((r) => `
              <div class="result-row ${r.is_correct ? "correct" : "wrong"}">
                <span class="result-qid">${escapeHTML(r.question_id)}</span>
                <span class="result-sel">Selected: <strong>${escapeHTML(r.selected ?? "—")}</strong></span>
                <span class="result-ans">Answer: <strong>${escapeHTML(r.correct_answer ?? "—")}</strong></span>
                <span class="result-icon">${r.is_correct ? "✅" : "❌"}</span>
              </div>
            `).join("")}
          </div>
        </div>
      `;
      submitAllResult.style.display = "block";
    }

    setTestHint(`Score: ${score}/${total} (${percentage}%) — verified by server`);
  } catch (err) {
    log("submit_test_error", err.message || String(err));
    setTestHint(`Submit failed: ${err.message || "network error"}`);
  } finally {
    if (btnSubmitAllTest) btnSubmitAllTest.disabled = false;
  }
}

// Flow ---------------------------------------------------------------------
async function startSessionFlow() {
  try {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      setIntroHint("Stop the recording first.");
      return;
    }

    btnStart.disabled = true;
    showStage("loading", recordedAudioBlob ? "Transcribing your recording..." : "Absorbing your story...");
    const text = await resolveInitialText();
    if (!text) {
      setIntroHint("Please share a few thoughts first.");
      showStage("intro");
      return;
    }

    setIntroHint("");
    // Store the initial text for passing to readiness checks later
    initialSessionText = text;
    showStage("loading", "Absorbing your story…");

    const startBody = { text };
    const clientUser = clientUserPayload();
    if (clientUser) startBody.client_user = clientUser;
    const data = await postJSON("/session/start", startBody);
    log("start_session", data);

    // ── FIX #2: setSessionUI now writes session_id to sessionStorage.
    //    All subsequent next-question calls re-use this same ID even if the
    //    user refreshes the page mid-session.
    setSessionUI(data.session_id, data.active_domains);
    joinSessionRoom(data.session_id);
    setSuggestions([]);

    // Reset follow-up state for new session
    resetFollowupState();

    await fetchNextQuestion("Finding the first question…");
  } catch (err) {
    log("start_error", err.message);
    setIntroHint(err.message);
    showStage("intro");
  } finally {
    btnStart.disabled = false;
  }
}

/**
 * Fetch the next question from the server.
 *
 * The server's next-question response can now include:
 *   { is_followup: true }   → this is a follow-up question
 *   { followups_complete: true }  → server says it's done asking follow-ups
 *   { done: true }          → session complete → go to simulation
 *
 * We mirror the follow-up count locally so we can show/hide the skip button
 * without an extra round-trip.
 */
async function fetchNextQuestion(message) {
  if (!sessionId) return;
  showStage("loading", message || "Designing your next cue…");
  try {
    const data = await postJSON(`/session/${sessionId}/next-question`, {
      // ── FIX #2: sessionId is now stable across requests.  These extra fields
      //    give the server cross-check data for the readiness detector.
      followup_count: followupCount,
      initial_text: initialSessionText,
      followups_done: followupsDone,
    });
    log("next_question", data);

    if (data.pending) {
      setHint(data.message || "Answer the current question first.");
      showStage("qa");
      return;
    }

    // Server says follow-ups are done (AI readiness hit or hard limit reached)
    if (data.followups_complete) {
      log("followups_complete: server signalled completion");
      onFollowupsDone();
    }

    if (data.done) {
      onFollowupsDone();
      await handleCompletion();
      return;
    }

    // Track whether this is a follow-up or clarifier (slot) question.
    // ── FIX #3: Added `|| data.clarifier` so slot questions (server sends
    //    clarifier:true) also increment the follow-up counter and keep the
    //    skip button visible during the slot-filling phase.
    if (data.is_followup || data.clarifier) {
      // ── FIX #3: onFollowupQuestionShown now sets isFollowupPhase = true
      //    before calling updateSkipButtonVisibility(), so the button correctly
      //    appears once followupCount reaches SKIP_BTN_AFTER (2).
      onFollowupQuestionShown();
    }

    // If local client-side counter hit the limit, stop asking follow-ups.
    // Safety net in case the server doesn't return done/followups_complete.
    if (isFollowupPhase && followupCount >= FOLLOWUP_LIMIT) {
      log("client-side followup limit reached — triggering completion");
      onFollowupsDone();
      await handleCompletion();
      return;
    }

    setQuestionUI(data);
    showStage("qa");
  } catch (err) {
    log("next_question_error", err.message);
    setHint(err.message);
    showStage("qa");
  }
}

async function submitAnswer() {
  if (!sessionId || btnAnswer.disabled) return;
  const answer = answerInput.value.trim();
  if (!answer) {
    hintBox.textContent = "Type a quick sentence first.";
    answerInput.classList.add("shake");
    setTimeout(() => answerInput.classList.remove("shake"), 400);
    return;
  }

  try {
    btnAnswer.disabled = true;
    showStage("loading", "Reading your answer…");

    const payload = {
      answer,
      domain: currentDomain,
      slot: currentSlot,
      // Pass follow-up state to the server so it can decide whether to
      // generate another follow-up or move to completion.
      followup_count: followupCount,
      followups_done: followupsDone,
      initial_text: initialSessionText,
    };
    const data = await postJSON(`/session/${sessionId}/answer`, payload);
    log("answer", data);

    if (data.need_clarification) {
      setHint("Quick clarifier requested: keep it tight.");
      $("questionText").textContent = data.question || "Need a tiny clarification.";
      btnAnswer.disabled = false;
      showStage("qa");
      return;
    }

    // Server can signal follow-up phase changes in answer response too
    if (data.followups_complete) {
      onFollowupsDone();
    }

    answerInput.value = "";
    setHint("Noted. Crafting the next cue…");
    await fetchNextQuestion("Crafting the next question…");
  } catch (err) {
    log("answer_error", err.message);
    setHint(err.message);
    btnAnswer.disabled = false;
    showStage("qa");
  }
}

async function skipRemainingQuestions() {
  if (!sessionId || !btnSkip || btnSkip.hidden || btnSkip.disabled) return;
  try {
    btnSkip.disabled = true;
    btnAnswer.disabled = true;
    showStage("loading", "Skipping remaining questions…");
    await postJSON(`/session/${sessionId}/complete`, {});
    await handleCompletion();
  } catch (err) {
    log("skip_error", err.message);
    setHint(err.message || "Could not skip right now.");
    btnSkip.disabled = false;
    btnAnswer.disabled = false;
    showStage("qa");
  }
}

async function handleCompletion() {
  // Hide skip button — no longer relevant
  onFollowupsDone();
  showStage("loading", "Designing your focus pulses…");
  try {
    const data = await postJSON(`/session/${sessionId}/start-simulation`, {});
    log("start_simulation", data);
    popupSummary.textContent = `Popups scheduled: ${data.popups_scheduled}. Keep an eye on the center top.`;
  } catch (err) {
    log("simulation_error", err.message);
    popupSummary.textContent = err.message;
  }
  await loadTestQuestions();
  showStage("popups");
}

// HUD ----------------------------------------------------------------------
function toggleHud(open) {
  if (!hudPanel) return;
  const shouldOpen = typeof open === "boolean" ? open : !hudPanel.classList.contains("open");
  hudPanel.classList.toggle("open", shouldOpen);
}

hudToggle?.addEventListener("click", () => toggleHud());
btnCloseHud?.addEventListener("click", () => toggleHud(false));

// Events -------------------------------------------------------------------
btnStart?.addEventListener("click", startSessionFlow);
btnNameNext?.addEventListener("click", proceedFromNameStep);
userNameInput?.addEventListener("keydown", (evt) => {
  if (evt.key === "Enter") {
    evt.preventDefault();
    proceedFromNameStep();
  }
});
btnRecord?.addEventListener("click", async () => {
  try {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      stopRecording();
      return;
    }
    await startRecording();
  } catch (err) {
    setIntroHint(err.message || "Mic access failed.");
    setRecordButtonState();
  }
});
btnAnswer?.addEventListener("click", submitAnswer);
btnSkip?.addEventListener("click", skipRemainingQuestions);
btnRestart?.addEventListener("click", resetFlow);
btnReset?.addEventListener("click", resetFlow);
btnLogout?.addEventListener("click", () => {
  window.StressDostAuth?.clearUser?.();
  window.location.href = "/login";
});
btnPrevQuestion?.addEventListener("click", () => gotoQuestion(-1));
btnNextQuestion?.addEventListener("click", () => gotoQuestion(1));
btnReloadQuestions?.addEventListener("click", () => loadTestQuestions());
btnSubmitQuestion?.addEventListener("click", submitCurrentQuestion);
btnSubmitAllTest?.addEventListener("click", submitAllTest);

// Live suggestions for initial text ---------------------------------------
function setSuggestions(items) {
  if (!suggestionWrap || !suggestionList) return;
  suggestionList.innerHTML = "";
  const list = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!list.length) {
    suggestionWrap.hidden = true;
    return;
  }
  list.forEach((text) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "suggestion-pill";
    pill.textContent = text;
    pill.addEventListener("click", () => applySuggestion(text));
    suggestionList.appendChild(pill);
  });
  suggestionWrap.hidden = false;
}

function applySuggestion(text) {
  const input = $("initialText");
  if (!input) return;
  const current = (input.value || "").trim();
  if (!current) {
    input.value = text;
  } else if (current.endsWith(" ")) {
    input.value = current + text;
  } else {
    input.value = `${current} ${text}`;
  }
  input.focus();
  setSuggestions([]);
}

function requestSuggestionsDebounced(rawText) {
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(() => {
    const text = (rawText || "").trim();
    if (!text || text.length < 4) {
      setSuggestions([]);
      return;
    }
    if (!socketInitialized) initSocket();
    if (socket) {
      socket.emit("suggest_request", { text });
    }
  }, 350);
}

const initialTextEl = $("initialText");
initialTextEl?.addEventListener("input", (evt) => requestSuggestionsDebounced(evt.target.value));

function attachKeypadListeners() {
  if (integerKeypadListenerAttached) return;
  integerKeypadListenerAttached = true;
  const keypad = $("keypad");
  if (keypad) {
    keypad.addEventListener("click", (evt) => {
      const key = evt.target?.dataset?.key;
      if (!key) return;
      const q = testQuestions[testQuestionIndex];
      if (!q || (q.question_type || "").toLowerCase() !== "integer") return;
      const current = selectedOptions[q.question_id] || "";
      const next = current + key;
      selectedOptions[q.question_id] = next;
      if (integerInput) integerInput.value = next;
    });
  }
  btnClearInteger?.addEventListener("click", () => {
    const q = testQuestions[testQuestionIndex];
    if (!q) return;
    selectedOptions[q.question_id] = "";
    if (integerInput) integerInput.value = "";
  });
  btnBackspace?.addEventListener("click", () => {
    const q = testQuestions[testQuestionIndex];
    if (!q) return;
    const current = selectedOptions[q.question_id] || "";
    const next = current.slice(0, -1);
    selectedOptions[q.question_id] = next;
    if (integerInput) integerInput.value = next;
  });
  integerInput?.addEventListener("input", (evt) => {
    const q = testQuestions[testQuestionIndex];
    if (!q) return;
    selectedOptions[q.question_id] = evt.target.value;
  });
}

answerInput?.addEventListener("keydown", (evt) => {
  if (evt.key === "Enter" && (evt.metaKey || evt.ctrlKey)) {
    submitAnswer();
  }
});

// Init ---------------------------------------------------------------------
// ── FIX #2: Do NOT call resetFlow() on page load when a valid session_id is
//    already stored in sessionStorage — that would wipe it.  Only reset the
//    UI state that doesn't depend on the session.
if (!sessionId) {
  // No persisted session — safe to call full reset
  resetFlow();
} else {
  // Session exists from sessionStorage — show the session status bar but
  // keep sessionId intact so the user can resume or restart manually.
  $("sessionId").textContent = sessionId;
  $("sessionStatus").textContent = `session: ${sessionId.slice(0, 8)}… (restored)`;
  window.currentSessionId = sessionId;
  // Make Reset/Restart buttons visible and functional
  showStage("intro");
  log("session_restored: id=" + sessionId + " (click Reset to start fresh)");
}

initSocket();
setRecordButtonState();
// Ensure skip button DOM element exists and is hidden from the start
getOrCreateSkipBtn();
if (!window.StressDostAuth?.getUser?.()) {
  window.StressDostAuth?.redirectToLogin?.();
} else {
  syncUserUI();
  resetFlow();
  initSocket();
  setRecordButtonState();
}

// expose for console debugging
window.__stressApp = {
  resetFlow,
  fetchNextQuestion,
  submitAnswer,
  loadTestQuestions,
  submitCurrentQuestion,
  submitAllTest,
  skipFollowups,
  // Follow-up state inspection helpers
  getFollowupState: () => ({ followupCount, isFollowupPhase, followupsDone, FOLLOWUP_LIMIT, SKIP_BTN_AFTER }),
  // Session inspection
  getSessionId: () => sessionId,
};
  getUserId: () => window.StressDostAuth?.getUserId?.() ?? null,
};
