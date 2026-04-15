(function () {
  var form = document.getElementById("loginForm");
  var hint = document.getElementById("loginHint");
  var loginStage = document.getElementById("loginStage");
  var welcomeStage = document.getElementById("welcomeStage");
  var btnGuest = document.getElementById("btnGuest");

  if (!form || !window.StressDostAuth) return;

  if (window.StressDostAuth.getUser()) {
    window.location.replace("/");
    return;
  }

  var MOOD_MESSAGES = {
    overwhelmed: "Let's untangle what's on your plate.",
    anxious: "Take a breath — we'll work through it together.",
    scattered: "Let's get you focused, one thing at a time.",
    "burned-out": "You've got this. Small steps from here.",
    "just-checking": "Good to see you. Ready when you are.",
    "": "Ready to vent? The session is all yours.",
  };

  function showWelcome(name, moodKey) {
    var mood = moodKey || "";
    var heading = document.getElementById("welcomeHeading");
    var msg = document.getElementById("welcomeMessage");
    if (heading) heading.textContent = name ? "Hey, " + name : "Hey there";
    if (msg) msg.textContent = MOOD_MESSAGES[mood] || MOOD_MESSAGES[""];
    if (loginStage) {
      loginStage.classList.remove("is-active");
      loginStage.hidden = true;
    }
    if (welcomeStage) {
      welcomeStage.hidden = false;
      welcomeStage.classList.add("is-active");
    }
  }

  function persistMood(mood) {
    try {
      if (mood) localStorage.setItem("sd_mood", mood);
      else localStorage.removeItem("sd_mood");
    } catch (_) {}
  }

  function submitProfile(opts) {
    opts = opts || {};
    if (hint) hint.textContent = "";
    var display_name = opts.display_name != null ? opts.display_name : (document.getElementById("displayName") || {}).value || "";
    var user_id = opts.user_id != null ? opts.user_id : (document.getElementById("userId") || {}).value || "";
    var mood = opts.mood != null ? opts.mood : (document.getElementById("mood") || {}).value || "";
    try {
      window.StressDostAuth.setUser({
        user_id: user_id,
        display_name: display_name,
        mood: mood,
      });
      persistMood(mood);
      var trimmedName = String(display_name || "").trim();
      showWelcome(trimmedName || "", mood);
    } catch (err) {
      if (hint) hint.textContent = err.message || "Could not continue.";
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    submitProfile({});
  });

  if (btnGuest) {
    btnGuest.addEventListener("click", function () {
      var dn = document.getElementById("displayName");
      var uid = document.getElementById("userId");
      var moodEl = document.getElementById("mood");
      if (dn) dn.value = "";
      if (uid) uid.value = "";
      if (moodEl) moodEl.value = "";
      submitProfile({ display_name: "", user_id: "", mood: "" });
    });
  }
})();
