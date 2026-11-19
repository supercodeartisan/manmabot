"""Purple state classifier — the human-readable states the engine drives.

This maps the probe's provisional labels plus live observation onto the
engine's state machine. It is the single place that decides "where are we".
"""
from __future__ import annotations


# Engine states (subset of the contract's state machine that concerns Purple).
S_WINDOW_SEARCH = "WINDOW_SEARCH"
S_WINDOW_ATTACH = "WINDOW_ATTACH"
S_CLASSIFY = "CLASSIFY"
S_EMAIL = "LOGIN_EMAIL"
S_PASSWORD = "LOGIN_PASSWORD"
S_LOGGING_IN = "LOGGING_IN"
S_LAUNCHER = "LAUNCHER_READY"
S_CARD = "LAUNCHER_GAME_CARD"
S_STARTING = "GAME_STARTING"
S_GAME_READY = "GAME_READY"
S_HANDOFF = "HANDOFF"
S_FAILED = "FAILED"


def infer_probe(label: str, flags: dict) -> str:
    """Map the probe's provisional label to an engine state."""
    has_pw = flags.get("has_password")
    has_email = flags.get("has_email")
    has_gate = flags.get("has_gate")
    has_play = flags.get("has_play")
    has_playing = flags.get("has_playing")
    has_nav = flags.get("has_launcher_nav")
    signing = flags.get("signing_in")

    if label == "launcher_start":
        return S_STARTING if has_playing else S_CARD
    if label == "launcher":
        return S_LAUNCHER
    if label == "login_password" or has_pw:
        return S_PASSWORD
    if label == "login_email" or has_email:
        return S_EMAIL
    if label == "login_both":
        return S_PASSWORD
    if label == "gate" or has_gate:
        return S_CLASSIFY
    if signing:
        return S_LOGGING_IN
    return S_CLASSIFY


def classify_real(session, hwnd: int) -> tuple[str, dict, list]:
    """Live classify from a session and hwnd: (engine_state, flags, nodes)."""
    label, flags, nodes = session.observe(hwnd)
    return infer_probe(label, flags), flags, nodes
