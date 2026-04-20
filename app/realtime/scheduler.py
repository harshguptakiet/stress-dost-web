"""Background popup scheduler."""
from __future__ import annotations

import os
import random
import threading
import time

from ..extensions import socketio


_active_sessions: set[str] = set()
_active_lock = threading.Lock()


def is_popup_simulation_active(session_id: str | None = None) -> bool:
    """Return True when popup simulation is currently running."""
    with _active_lock:
        if session_id:
            return str(session_id) in _active_sessions
        return bool(_active_sessions)


def start_popup_simulation(session_id: str, popups: list[dict]) -> None:
    """Emit popup payloads sequentially into session-specific room."""

    max_popups = max(1, min(200, int(os.getenv("SIM_MAX_POPUPS", "18"))))
    interval_min = max(2.0, float(os.getenv("SIM_POPUP_INTERVAL_MIN_S", "7.0")))
    interval_max = max(interval_min, float(os.getenv("SIM_POPUP_INTERVAL_MAX_S", "11.0")))

    def run() -> None:
        room = str(session_id)
        with _active_lock:
            _active_sessions.add(room)
        try:
            for popup in list(popups or [])[:max_popups]:
                socketio.emit("popup", popup, room=room)
                time.sleep(random.uniform(interval_min, interval_max))
        finally:
            with _active_lock:
                _active_sessions.discard(room)

    threading.Thread(target=run, daemon=True).start()


__all__ = ["start_popup_simulation", "is_popup_simulation_active"]
