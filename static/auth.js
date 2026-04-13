/* Shared client auth: localStorage user profile for Stress Dost. */
(function () {
  var KEY = "stress_dost_user_v1";

  function safeParse(raw) {
    try {
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function getUser() {
    var u = safeParse(localStorage.getItem(KEY));
    if (!u || typeof u !== "object") return null;
    if (!u.user_id) return null;
    return u;
  }

  function getUserId() {
    var u = getUser();
    return u ? u.user_id : null;
  }

  /** No password — saves profile locally for future features (e.g. past queries). */
  function setUser(profile) {
    var user_id = String(profile.user_id || "").trim();
    var display_name = String(profile.display_name || "").trim() || "Guest";
    if (!user_id) user_id = crypto.randomUUID();
    var mood = String(profile.mood || "").trim();
    var rec = {
      user_id: user_id,
      display_name: display_name,
      logged_in_at: new Date().toISOString(),
    };
    if (mood) rec.mood = mood.slice(0, 80);
    localStorage.setItem(KEY, JSON.stringify(rec));
    return rec;
  }

  function clearUser() {
    localStorage.removeItem(KEY);
  }

  function redirectToLogin() {
    window.location.href = "/login";
  }

  window.StressDostAuth = {
    STORAGE_KEY: KEY,
    getUser: getUser,
    getUserId: getUserId,
    setUser: setUser,
    clearUser: clearUser,
    redirectToLogin: redirectToLogin,
  };
})();
