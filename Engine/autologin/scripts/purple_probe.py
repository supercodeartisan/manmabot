"""P0 read-only UIA contract probe for the Purple launcher.

Purpose
-------
Freeze the actual UI Automation contract of Purple before the S1-S3 execution
engine is replaced. This tool only *reads* the accessibility tree. It never
clicks, types, resizes, focuses, or kills anything.

What it produces (under scripts/probe_out/<run>/):
    run.json          environment + arguments + window list + blockers
    samples.jsonl     one line per sample (state, counts, seed presence)
    tree_*.json       full UIA tree snapshots on state changes
    shots/win_*.png   optional window screenshots for human reference
    catalog.json      aggregated element catalog with presence/stability
    summary.md        human-readable seed matrix + warnings

Usage (run elevated, Purple open on the login card or launcher):
    & "D:\\...\\python\\python.exe" Engine\\autologin\\scripts\\purple_probe.py
    ... --once
    ... --list
    ... --duration 180 --interval 0.6 --snapshot-every 5

Exit codes: 0 ok, 1 error, 2 no Purple window, 3 not elevated.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from trace_common import (  # noqa: E402
    append_jsonl,
    maybe_reexec,
    redact,
    write_json,
)

# --- seed identifiers (observed by purple-login-monitor, to be verified) ----
SEED_EMAIL = "current-account"
SEED_PASSWORD = "current-password"
SEED_SUBMIT = "btn-login-email"
SEED_GATE = "NcSignInButton"
SEED_PLAY = "PlayButton"
SEED_PLAYING = "PlayingButton"

SEED_ORDER = (
    SEED_EMAIL,
    SEED_PASSWORD,
    SEED_SUBMIT,
    SEED_GATE,
    SEED_PLAY,
    SEED_PLAYING,
)

SEED_ROLES = {
    SEED_EMAIL: "login_email_field",
    SEED_PASSWORD: "login_password_field",
    SEED_SUBMIT: "login_submit",
    SEED_GATE: "login_gate_button",
    SEED_PLAY: "start_button",
    SEED_PLAYING: "start_running_button",
}

LAUNCHER_NAV = (
    "Store",
    "Community",
    "Lounge",
    "PurpleOn",
    "Game",
    "MyPage",
    "UpdateCenter",
    "Setting",
)

SIGNING_IN_NAMES = (
    "signing in",
    "로그인 중",
    "登录中",
    "登入中",
    "サインイン中",
)

PURPLE_IMAGES = ("purple.exe", "purplelauncher.exe")


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------
def _reconfigure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _dpi_aware_early() -> str:
    """Set per-monitor DPI awareness before any geometry is read.

    uiautomation also does this on import, but we want it explicit and ordered
    so the probe's rectangles match what the bot will see.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor (explicit)"
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return "system (fallback)"
        except Exception:
            return "unknown"


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# window discovery (by process image, never by title)
# ---------------------------------------------------------------------------
def enumerate_purple_windows() -> list[dict]:
    import psutil
    import win32gui
    import win32process

    pids: set[int] = set()
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name in PURPLE_IMAGES:
                pids.add(proc.pid)
    except Exception:
        pass

    rows: list[dict] = []

    def cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids:
                return
            cls = win32gui.GetClassName(hwnd) or ""
            title = win32gui.GetWindowText(hwnd) or ""
            try:
                rect = list(win32gui.GetWindowRect(hwnd))
            except Exception:
                rect = None
            rows.append(
                {
                    "hwnd": int(hwnd),
                    "hwnd_hex": "0x%08X" % hwnd,
                    "pid": int(pid),
                    "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    "iconic": bool(win32gui.IsIconic(hwnd)),
                    "title": redact(title)[:200],
                    "class": cls[:160],
                    "rect": rect,
                }
            )
        except Exception:
            pass

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        pass

    rows.sort(key=lambda r: (not r["visible"], r["iconic"], r["pid"], r["hwnd_hex"]))
    return rows


def _area(rect) -> int:
    if not rect or len(rect) != 4:
        return 0
    w = int(rect[2]) - int(rect[0])
    h = int(rect[3]) - int(rect[1])
    return max(0, w) * max(0, h)


def pick_window(rows: list[dict], want_hwnd: int | None = None) -> dict | None:
    if want_hwnd:
        for row in rows:
            if row["hwnd"] == want_hwnd:
                return row
        return None

    def score(row: dict) -> tuple:
        rect = row.get("rect")
        onscreen = bool(
            rect
            and len(rect) == 4
            and rect[2] > rect[0]
            and rect[3] > rect[1]
            and rect[0] > -30000
        )
        class_bonus = 1 if ("HwndWrapper" in row["class"] or "Chrome_WidgetWin" in row["class"]) else 0
        return (
            1 if row["visible"] else 0,
            1 if not row["iconic"] else 0,
            1 if onscreen else 0,
            class_bonus,
            _area(rect),
        )

    candidates = [r for r in rows if _area(r.get("rect")) >= 100 * 100]
    if not candidates:
        candidates = rows
    return max(candidates, key=score) if candidates else None


def _virtual_screen() -> tuple[int, int, int, int]:
    import win32api

    x = win32api.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    y = win32api.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    w = win32api.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    h = win32api.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return x, y, x + w, y + h


def _visible_fraction(rect, screen) -> float:
    """How much of a window rectangle actually lies on the virtual screen."""
    area = _area(rect)
    if area <= 0:
        return 0.0
    ix = min(rect[2], screen[2]) - max(rect[0], screen[0])
    iy = min(rect[3], screen[3]) - max(rect[1], screen[1])
    if ix <= 0 or iy <= 0:
        return 0.0
    return (ix * iy) / float(area)


def sampleable_windows(rows: list[dict]) -> list[dict]:
    """Every on-screen Purple window the user can actually see.

    Purple keeps hidden login cards parked above the screen (e.g. y=-789). They
    are technically `IsWindowVisible`, so sampling them would fabricate states.
    """
    screen = _virtual_screen()
    out: list[dict] = []
    for row in rows:
        rect = row.get("rect")
        if not row.get("visible") or row.get("iconic") or not rect:
            continue
        if _area(rect) < 100 * 100:
            continue
        if _visible_fraction(rect, screen) < 0.5:
            continue
        out.append(row)
    out.sort(key=lambda r: (r["pid"], r["hwnd"]))
    return out


# ---------------------------------------------------------------------------
# UIA tree walk
# ---------------------------------------------------------------------------
def _rect_tuple(control) -> tuple[int, int, int, int] | None:
    try:
        r = control.BoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return None


def _has_method(control, name: str) -> bool:
    """True when the control implements the named UIA pattern method."""
    try:
        fn = getattr(control, name)
    except Exception:
        return False
    try:
        fn()
        return True
    except Exception:
        return False


def _patterns(control, ctype: str) -> list[str]:
    found: list[str] = []
    if ctype == "EditControl":
        if _has_method(control, "GetValuePattern"):
            found.append("value")
    elif ctype == "ButtonControl":
        if _has_method(control, "GetInvokePattern"):
            found.append("invoke")
        if _has_method(control, "GetTogglePattern"):
            found.append("toggle")
    elif ctype in ("CheckBoxControl", "RadioButtonControl"):
        if _has_method(control, "GetTogglePattern"):
            found.append("toggle")
        if _has_method(control, "GetSelectionItemPattern"):
            found.append("selection")
    elif ctype == "ComboBoxControl":
        if _has_method(control, "GetExpandCollapsePattern"):
            found.append("expand")
        if _has_method(control, "GetValuePattern"):
            found.append("value")
    elif ctype == "ListItemControl":
        if _has_method(control, "GetSelectionItemPattern"):
            found.append("selection")
    elif ctype == "DocumentControl":
        if _has_method(control, "GetTextPattern"):
            found.append("text")
    elif ctype == "ScrollBarControl":
        if _has_method(control, "GetScrollPattern"):
            found.append("scroll")
    return found


def _value_info(control, is_password: bool, include_values: bool) -> tuple[int | None, str | None]:
    if is_password:
        return None, None
    try:
        value = control.GetValuePattern().Value
    except Exception:
        return None, None
    if value is None:
        return None, None
    if include_values:
        return len(value), redact(value)[:200]
    return len(value), None


def walk_tree(root, win_rect: tuple[int, int, int, int] | None,
              max_depth: int, max_controls: int,
              include_values: bool) -> tuple[list[dict], int]:
    """Return (nodes, visited_count). Nodes are already redacted."""
    wx1, wy1, wx2, wy2 = win_rect or (0, 0, 0, 0)
    nodes: list[dict] = []
    visited = 0
    order = 0

    # Recursive walk keeps the depth-first order stable, which matters when
    # comparing two dumps of the same animated page.
    def add(control, depth: int) -> None:
        nonlocal visited, order
        if depth > max_depth or len(nodes) >= max_controls:
            return
        visited += 1
        try:
            children = control.GetChildren() or []
        except Exception:
            children = []

        try:
            ctype = control.ControlTypeName or ""
        except Exception:
            ctype = ""
        try:
            name = redact(control.Name or "")[:200]
        except Exception:
            name = ""
        try:
            aid = (control.AutomationId or "")[:160]
        except Exception:
            aid = ""
        try:
            cls = (control.ClassName or "")[:160]
        except Exception:
            cls = ""
        try:
            framework = (control.FrameworkId or "")[:60]
        except Exception:
            framework = ""
        try:
            enabled = bool(control.IsEnabled)
        except Exception:
            enabled = False
        try:
            offscreen = bool(control.IsOffscreen)
        except Exception:
            offscreen = True
        is_password = False
        if ctype == "EditControl":
            try:
                is_password = bool(control.IsPassword)
            except Exception:
                is_password = False

        rect = _rect_tuple(control)
        onscreen = False
        rel = None
        center = None
        rel_center = None
        size = None
        if rect:
            x1, y1, x2, y2 = rect
            w, h = x2 - x1, y2 - y1
            size = [w, h]
            center = [(x1 + x2) // 2, (y1 + y2) // 2]
            rel = [x1 - wx1, y1 - wy1, x2 - wx1, y2 - wy1]
            rel_center = [center[0] - wx1, center[1] - wy1]
            intersects = (
                wx2 > wx1
                and wy2 > wy1
                and x2 > wx1
                and x1 < wx2
                and y2 > wy1
                and y1 < wy2
            )
            onscreen = (not offscreen) and w > 0 and h > 0 and intersects

        value_len, value = (None, None)
        if ctype == "EditControl":
            value_len, value = _value_info(control, is_password, include_values)

        rec = {
            "i": order,
            "depth": depth,
            "ct": ctype,
            "aid": aid,
            "cls": cls,
            "name": name,
            "fw": framework,
            "enabled": enabled,
            "offscreen": offscreen,
            "password": is_password,
            "onscreen": onscreen,
            "rect": list(rect) if rect else None,
            "rel": rel,
            "center": center,
            "rel_center": rel_center,
            "size": size,
            "patterns": _patterns(control, ctype),
            "value_len": value_len,
            "value": value,
        }
        order += 1
        nodes.append(rec)

        for child in children:
            if len(nodes) >= max_controls:
                break
            add(child, depth + 1)

    add(root, 0)
    return nodes, visited


# ---------------------------------------------------------------------------
# provisional state label (probe-only; not the production classifier)
# ---------------------------------------------------------------------------
def classify_probe(nodes: list[dict]) -> tuple[str, dict]:
    onscreen = [n for n in nodes if n["onscreen"]]
    ids = {n["aid"] for n in onscreen if n["aid"]}
    edits = [n for n in onscreen if n["ct"] == "EditControl"]
    password_edits = [n for n in edits if n["password"]]
    buttons = [n for n in onscreen if n["ct"] == "ButtonControl"]
    progress = [n for n in onscreen if n["ct"] == "ProgressBarControl"]
    docs = [n for n in onscreen if n["ct"] == "DocumentControl"]

    has_email = SEED_EMAIL in ids
    has_password = SEED_PASSWORD in ids
    has_submit = SEED_SUBMIT in ids
    has_gate = SEED_GATE in ids
    has_play = SEED_PLAY in ids
    has_playing = SEED_PLAYING in ids
    has_nav = any(aid in ids for aid in LAUNCHER_NAV)
    signing_in = any(
        "SigningIn" in (n["aid"] + n["cls"])
        or any(s in (n["name"] or "").lower() for s in SIGNING_IN_NAMES)
        for n in onscreen
    )

    if has_play or has_playing:
        label = "launcher_start"
    elif has_nav:
        label = "launcher"
    elif has_email and has_password:
        label = "login_both"
    elif has_password:
        label = "login_password"
    elif has_email:
        label = "login_email"
    elif has_gate:
        label = "gate"
    elif signing_in:
        label = "signing_in"
    elif password_edits:
        label = "password_guess"
    elif len(edits) >= 2 and buttons:
        label = "login_form_guess"
    else:
        label = "unknown"

    flags = {
        "has_email": has_email,
        "has_password": has_password,
        "has_submit": has_submit,
        "has_gate": has_gate,
        "has_play": has_play,
        "has_playing": has_playing,
        "has_launcher_nav": has_nav,
        "signing_in": bool(signing_in),
        "edit_count": len(edits),
        "password_edit_count": len(password_edits),
        "button_count": len(buttons),
        "progress_count": len(progress),
        "document_count": len(docs),
    }
    return label, flags


# ---------------------------------------------------------------------------
# catalog aggregation
# ---------------------------------------------------------------------------
class Stats:
    __slots__ = ("n", "mean", "m2")

    def __init__(self) -> None:
        self.n = 0
        self.mean = [0.0, 0.0]
        self.m2 = [0.0, 0.0]

    def add(self, x: float, y: float) -> None:
        self.n += 1
        for i, v in enumerate((x, y)):
            delta = v - self.mean[i]
            self.mean[i] += delta / self.n
            self.m2[i] += delta * (v - self.mean[i])

    def std(self) -> list[float]:
        if self.n < 2:
            return [0.0, 0.0]
        return [round(math.sqrt(self.m2[i] / (self.n - 1)), 2) for i in range(2)]

    def mean_rounded(self) -> list[float]:
        return [round(self.mean[0], 1), round(self.mean[1], 1)]


def element_key(node: dict, window_tag: str = "") -> str:
    if node["aid"]:
        base = "aid:%s" % node["aid"]
    else:
        base = "raw:%s|%s|%s" % (node["ct"], node["cls"], node["name"])
    return ("win:%s|%s" % (window_tag, base)) if window_tag else base


def role_of(entry: dict) -> str:
    aid = entry["aid"]
    if aid in SEED_ROLES:
        return SEED_ROLES[aid]
    if aid in LAUNCHER_NAV:
        return "launcher_nav"
    blob = (aid + " " + " ".join(entry["classes"])).lower()
    if "password" in blob:
        return "password_field_candidate"
    ctype = entry["ct"]
    if ctype == "EditControl":
        return "edit"
    if ctype == "ButtonControl":
        return "button"
    if ctype == "ProgressBarControl":
        return "progress"
    if ctype == "DocumentControl":
        return "document"
    if ctype == "ImageControl":
        return "image"
    if ctype == "TextControl":
        return "text"
    return "other"


class Catalog:
    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}
        self.state_ticks: Counter = Counter()
        self.state_ticks_by_window: dict[str, Counter] = {}

    def add(self, state: str, nodes: list[dict], window_tag: str = "") -> None:
        self.state_ticks[state] += 1
        self.state_ticks_by_window.setdefault(window_tag, Counter())[state] += 1
        seen_keys: set[str] = set()
        for node in nodes:
            key = element_key(node, window_tag)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            entry = self.entries.get(key)
            if entry is None:
                entry = {
                    "key": key,
                    "aid": node["aid"],
                    "window": window_tag,
                    "ct": node["ct"],
                    "classes": [],
                    "names": [],
                    "patterns": set(),
                    "present": 0,
                    "onscreen": 0,
                    "enabled": 0,
                    "states": Counter(),
                    "rect": Stats(),
                    "rect_by_state": {},
                    "size": Stats(),
                    "depth": node["depth"],
                    "value_len": None,
                }
                self.entries[key] = entry
            entry["present"] += 1
            entry["states"][state] += 1
            if node["onscreen"]:
                entry["onscreen"] += 1
                if node["rel_center"]:
                    entry["rect"].add(node["rel_center"][0], node["rel_center"][1])
                    state_stats = entry["rect_by_state"].get(state)
                    if state_stats is None:
                        state_stats = Stats()
                        entry["rect_by_state"][state] = state_stats
                    state_stats.add(node["rel_center"][0], node["rel_center"][1])
                if node["size"]:
                    entry["size"].add(node["size"][0], node["size"][1])
            if node["enabled"]:
                entry["enabled"] += 1
            if node["cls"] and node["cls"] not in entry["classes"]:
                if len(entry["classes"]) < 6:
                    entry["classes"].append(node["cls"])
            if node["name"] and node["name"] not in entry["names"]:
                if len(entry["names"]) < 6:
                    entry["names"].append(node["name"])
            for p in node["patterns"]:
                entry["patterns"].add(p)
            if entry["value_len"] is None and node["value_len"] is not None:
                entry["value_len"] = node["value_len"]

    def to_json(self) -> dict:
        rows = []
        for entry in self.entries.values():
            presence = {}
            window_ticks = self.state_ticks_by_window.get(
                entry.get("window", ""), self.state_ticks)
            for state, ticks in window_ticks.items():
                if ticks <= 0:
                    continue
                count = entry["states"].get(state, 0)
                if count:
                    presence[state] = round(count / ticks, 3)
            row = {
                "key": entry["key"],
                "aid": entry["aid"],
                "window": entry.get("window", ""),
                "ct": entry["ct"],
                "classes": entry["classes"],
                "names": entry["names"],
                "patterns": sorted(entry["patterns"]),
                "role": role_of(entry),
                "depth": entry["depth"],
                "present": entry["present"],
                "onscreen": entry["onscreen"],
                "enabled": entry["enabled"],
                "presence_by_state": presence,
                "rel_center_mean": entry["rect"].mean_rounded(),
                "rel_center_std": entry["rect"].std(),
                "rel_center_by_state": {
                    st: {
                        "mean": stats.mean_rounded(),
                        "std": stats.std(),
                        "n": stats.n,
                    }
                    for st, stats in entry["rect_by_state"].items()
                    if stats.n
                },
                "size_mean": entry["size"].mean_rounded(),
                "value_len": entry["value_len"],
            }
            rows.append(row)

        def rank(row: dict) -> tuple:
            order = list(SEED_ROLES.values()) + ["launcher_nav", "progress", "edit", "button", "document", "image", "text", "password_field_candidate", "other"]
            try:
                role_rank = order.index(row["role"])
            except ValueError:
                role_rank = len(order)
            max_presence = max(row["presence_by_state"].values(), default=0.0)
            return (role_rank, -max_presence, row["key"])

        rows.sort(key=rank)
        return {
            "state_ticks": dict(self.state_ticks),
            "state_ticks_by_window": {
                win: dict(counter)
                for win, counter in self.state_ticks_by_window.items()
            },
            "element_count": len(rows),
            "elements": rows,
        }


# ---------------------------------------------------------------------------
# P0 gate
# ---------------------------------------------------------------------------
GATE_PRESENCE = 0.90
GATE_STD_PX = 3.0


def evaluate_gate(catalog: dict, run: dict) -> dict:
    """Mechanical P0 gate: can the new engine rely on these elements?"""
    states = catalog.get("state_ticks", {})
    elements = catalog.get("elements", [])
    by_aid: dict[str, list[dict]] = {}
    for entry in elements:
        if entry.get("aid"):
            by_aid.setdefault(entry["aid"], []).append(entry)

    def presence(aid: str, state: str) -> float:
        entries = by_aid.get(aid) or []
        if not entries:
            return 0.0
        return max(
            float(e["presence_by_state"].get(state, 0.0)) for e in entries
        )

    login_states = [s for s in ("login_email", "login_both", "login_password") if states.get(s)]
    launcher_seen = bool(states.get("launcher") or states.get("launcher_start"))
    start_states = [s for s in ("launcher_start",) if states.get(s)]

    def best(aid: str) -> float:
        return max([presence(aid, s) for s in login_states] or [0.0])

    email = best(SEED_EMAIL)
    password = best(SEED_PASSWORD)
    submit = best(SEED_SUBMIT)
    # PlayButton and PlayingButton are mutually exclusive: before the launch the
    # first is onscreen, after the click the second replaces it. Their presence
    # ratios add up to the fraction of start-view samples that expose a start
    # control at all.
    play = max([presence(SEED_PLAY, s) for s in start_states] or [0.0])
    playing = max([presence(SEED_PLAYING, s) for s in start_states] or [0.0])
    start_ratio = min(1.0, play + playing)

    seed_entries = [
        e for e in elements
        if e.get("aid") in SEED_ROLES and e.get("onscreen", 0) > 0
    ]
    # Stability is per state: btn-login-email legitimately moves between the
    # email step (y=261) and the password step (y=302). Mixing states would
    # report drift that the engine will never see inside one screen.
    relevant_states = set(login_states) | {"launcher", "launcher_start"}
    max_std = 0.0
    for entry in seed_entries:
        for state, stats in (entry.get("rel_center_by_state") or {}).items():
            if state in relevant_states:
                max_std = max(max_std, max(stats["std"]))

    checks = {
        "login_email": {"value": round(email, 3), "threshold": GATE_PRESENCE,
                        "ok": email >= GATE_PRESENCE},
        "login_password": {"value": round(password, 3), "threshold": GATE_PRESENCE,
                           "ok": password >= GATE_PRESENCE},
        "login_submit": {"value": round(submit, 3), "threshold": GATE_PRESENCE,
                         "ok": submit >= GATE_PRESENCE},
        "start_button": {"value": round(start_ratio, 3),
                         "threshold": GATE_PRESENCE,
                         "ok": start_ratio >= GATE_PRESENCE,
                         "detail": {"PlayButton": round(play, 3),
                                    "PlayingButton": round(playing, 3)}},
        "seed_rect_stability": {"value": round(max_std, 2), "limit_px": GATE_STD_PX,
                                "ok": max_std <= GATE_STD_PX},
    }

    blockers: list[str] = []
    if not login_states:
        blockers.append("login state was never observed")
    if not launcher_seen:
        blockers.append("launcher state was never observed")
    if not start_states:
        blockers.append("start view (PlayButton/PlayingButton) was never observed")
    if login_states and not checks["login_email"]["ok"]:
        blockers.append("email field presence below %.2f" % GATE_PRESENCE)
    if login_states and not checks["login_password"]["ok"]:
        blockers.append("password field presence below %.2f" % GATE_PRESENCE)
    if login_states and not checks["login_submit"]["ok"]:
        blockers.append("submit button presence below %.2f" % GATE_PRESENCE)
    if launcher_seen and not checks["start_button"]["ok"]:
        blockers.append("start/playing button presence below %.2f" % GATE_PRESENCE)
    if seed_entries and not checks["seed_rect_stability"]["ok"]:
        blockers.append("seed element drift above %.1fpx" % GATE_STD_PX)

    if not login_states or not launcher_seen:
        status = "incomplete"
    elif blockers:
        status = "fail"
    else:
        status = "pass"

    notes: list[str] = []
    if states.get("login_both"):
        notes.append(
            "login_both observed %d sample(s): email and password coexist. "
            "A password-first classifier would skip email."
            % states["login_both"]
        )
    if not seed_entries:
        notes.append("no seed element was onscreen; stability not evaluated")
    if "PURPLE" not in (run.get("title") or "").upper():
        notes.append("window title lacks PURPLE; title-based discovery would miss it")

    return {
        "status": status,
        "thresholds": {"presence": GATE_PRESENCE, "std_px": GATE_STD_PX},
        "checks": checks,
        "states": states,
        "blockers": blockers,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
def write_summary(path: Path, run: dict, catalog: dict, gate: dict | None = None) -> None:
    states = catalog["state_ticks"]
    elements = catalog["elements"]
    lines: list[str] = []
    lines.append("# Purple UIA probe summary\n")
    lines.append("| field | value |")
    lines.append("|---|---|")
    lines.append("| run | `%s` |" % run["run_id"])
    lines.append("| python | `%s` |" % run["python"].splitlines()[0])
    lines.append("| elevated | %s |" % run["admin"])
    lines.append("| hwnd | `%s` |" % run["hwnd_hex"])
    lines.append("| title | %s |" % (run["title"] or "(empty)"))
    lines.append("| samples | %s |" % run["samples"])
    lines.append("| duration_sec | %.1f |" % run["duration_sec"])
    lines.append("| states | %s |" % json.dumps(states, ensure_ascii=False))
    lines.append("")

    lines.append("## Seed identifier matrix (presence ratio)\n")
    state_names = [s for s, _ in Counter(states).most_common()]
    header = "| seed | role | " + " | ".join(state_names) + " |"
    sep = "|---" * (len(state_names) + 2) + "|"
    lines.append(header)
    lines.append(sep)
    by_aid: dict[str, list[dict]] = {}
    for e in elements:
        if e["aid"]:
            by_aid.setdefault(e["aid"], []).append(e)
    for aid in SEED_ORDER:
        entries = by_aid.get(aid)
        role = SEED_ROLES.get(aid, "")
        if not entries:
            cells = ["0.00"] * len(state_names)
        else:
            cells = [
                "%.2f" % max(
                    float(e["presence_by_state"].get(s, 0.0)) for e in entries)
                for s in state_names
            ]
        lines.append("| `%s` | %s | %s |" % (aid, role, " | ".join(cells)))
    lines.append("")

    lines.append("## Interactive elements (top 30)\n")
    lines.append("| role | window | automation id | control type | names | presence | rel center | std |")
    lines.append("|---|---|---|---|---|---|---|---|")
    interactive = [
        e for e in elements
        if e["role"] not in ("other", "text", "image")
    ][:30]
    for e in interactive:
        presence = max(e["presence_by_state"].values(), default=0.0)
        lines.append(
            "| %s | `%s` | `%s` | %s | %s | %.2f | %s | %s |"
            % (
                e["role"],
                e.get("window") or "-",
                e["aid"] or "-",
                e["ct"],
                ", ".join(e["names"])[:80] or "-",
                presence,
                e["rel_center_mean"],
                e["rel_center_std"],
            )
        )
    lines.append("")

    # findings
    lines.append("## Findings\n")
    if states.get("login_both"):
        lines.append(
            "- **login_both observed %d time(s).** The email and password fields are "
            "visible in the same snapshot. A classifier that checks password first and "
            "returns immediately would skip the email field." % states["login_both"]
        )
    if not (states.get("launcher") or states.get("launcher_start")):
        lines.append("- **launcher state not observed.** Run the probe on the logged-in launcher too.")
    if not any(e["aid"] == SEED_EMAIL for e in elements):
        lines.append("- `%s` was not exposed in this run." % SEED_EMAIL)
    if not any(e["aid"] == SEED_PASSWORD for e in elements):
        lines.append("- `%s` was not exposed in this run." % SEED_PASSWORD)
    if not any(e["aid"] in (SEED_PLAY, SEED_PLAYING) for e in elements):
        lines.append("- Start button (`%s`/`%s`) was not exposed in this run." % (SEED_PLAY, SEED_PLAYING))

    seed_seen = [
        e for e in elements
        if e.get("aid") in SEED_ROLES and e.get("onscreen", 0) > 0
    ]
    if not seed_seen:
        lines.append("- No seed element was onscreen; rectangle stability not evaluated.")
    else:
        drifting = [e for e in seed_seen if max(e["rel_center_std"]) > GATE_STD_PX]
        if drifting:
            lines.append(
                "- **Seed elements drift more than %.1fpx** between samples: %s"
                % (GATE_STD_PX, ", ".join("`%s`" % e["aid"] for e in drifting))
            )
        else:
            lines.append(
                "- Seed element rectangles were stable (<= %.1fpx std) in this run."
                % GATE_STD_PX
            )

    if "PURPLE" not in (run.get("title") or "").upper():
        lines.append(
            "- Window title does not contain `PURPLE`; a title-based window filter "
            "would miss this window. Discovery must use the process image name."
        )

    if gate is not None:
        lines.append("")
        lines.append("## P0 gate\n")
        lines.append("**status: %s**\n" % gate["status"].upper())
        lines.append("| check | value | threshold | ok |")
        lines.append("|---|---|---|---|")
        for name, check in gate["checks"].items():
            limit = check.get("threshold", check.get("limit_px"))
            lines.append(
                "| %s | %s | %s | %s |"
                % (name, check["value"], limit, "yes" if check["ok"] else "no")
            )
        if gate["blockers"]:
            lines.append("")
            lines.append("Blockers:")
            for item in gate["blockers"]:
                lines.append("- %s" % item)
        if gate["notes"]:
            lines.append("")
            lines.append("Notes:")
            for item in gate["notes"]:
                lines.append("- %s" % item)

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# screenshots
# ---------------------------------------------------------------------------
def grab_window(rect, path: Path) -> bool:
    if not rect or len(rect) != 4:
        return False
    try:
        from PIL import ImageGrab

        l, t, r, b = (int(v) for v in rect)
        if r <= l or b <= t:
            return False
        img = ImageGrab.grab(bbox=(l, t, r, b), all_screens=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only UIA contract probe for Purple (P0)",
    )
    parser.add_argument("--list", action="store_true", help="list Purple windows and exit")
    parser.add_argument("--once", action="store_true", help="take one snapshot and exit")
    parser.add_argument("--duration", type=float, default=180.0, help="watch seconds")
    parser.add_argument("--interval", type=float, default=0.6, help="sample interval seconds")
    parser.add_argument("--snapshot-every", type=float, default=5.0,
                        help="full tree snapshot interval even without a state change")
    # CEF login fields live ~16 levels deep (Document -> groups -> Edit).
    # A shallower walk silently misses current-account / current-password.
    parser.add_argument("--all-windows", action="store_true",
                        help="sample every visible on-screen Purple window each tick "
                             "(gate + login card coexist)")
    parser.add_argument("--max-depth", type=int, default=24)
    parser.add_argument("--max-controls", type=int, default=2000)
    parser.add_argument("--out", default="", help="output directory")
    parser.add_argument("--hwnd", default="", help="pin to a window handle (0x...)")
    parser.add_argument("--no-shots", action="store_true", help="disable screenshots")
    parser.add_argument("--include-values", action="store_true",
                        help="record redacted edit values (never passwords)")
    parser.add_argument("--restore", action="store_true",
                        help="restore a minimized Purple window before sampling")
    parser.add_argument("--allow-unelevated", action="store_true",
                        help="continue without admin (UIA may return nothing)")
    parser.add_argument("--stop-file", default="",
                        help="finish cleanly (and write results) when this file appears")
    parser.add_argument("--wait-window", type=float, default=0.0,
                        help="wait up to N seconds for a Purple window to appear")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    _reconfigure_console()
    args = parse_args(argv)

    code = maybe_reexec()
    if code is not None:
        return code

    dpi_mode = _dpi_aware_early()

    try:
        import uiautomation as uia
    except Exception as exc:
        print("[probe] FATAL: uiautomation import failed: %r" % exc)
        return 1

    try:
        import win32gui  # noqa: F401
        import psutil  # noqa: F401
    except Exception as exc:
        print("[probe] FATAL: win32/psutil import failed: %r" % exc)
        return 1

    admin = _is_admin()
    if not admin and not args.allow_unelevated:
        print("[probe] FATAL: not elevated. Purple runs at high integrity;")
        print("        run this from an elevated shell (or pass --allow-unelevated).")
        return 3

    if args.list:
        rows = enumerate_purple_windows()
        if not rows:
            print("[probe] no Purple windows found")
            return 2
        for row in rows:
            print(
                "%s pid=%s visible=%s iconic=%s class=%s rect=%s title=%s"
                % (row["hwnd_hex"], row["pid"], row["visible"], row["iconic"],
                   row["class"], row["rect"], row["title"])
            )
        return 0

    if args.wait_window > 0:
        deadline = time.time() + args.wait_window
        while time.time() < deadline:
            if enumerate_purple_windows():
                break
            time.sleep(0.5)

    pinned = 0
    if args.hwnd:
        try:
            pinned = int(args.hwnd, 0)
        except ValueError:
            print("[probe] FATAL: bad --hwnd %r" % args.hwnd)
            return 1

    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else (SCRIPT_DIR / "probe_out" / run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    tree_dir = out_dir / "trees"
    shots_dir = out_dir / "shots"
    samples_path = out_dir / "samples.jsonl"

    window_rows = enumerate_purple_windows()
    if not window_rows:
        print("[probe] no Purple window found. Open Purple (or use --wait-window).")
        return 2

    selected = pick_window(window_rows, pinned or None)
    if selected is None:
        print("[probe] pinned hwnd not found among Purple windows.")
        return 2

    if args.restore:
        try:
            if selected["iconic"]:
                win32gui.ShowWindow(selected["hwnd"], 9)  # SW_RESTORE
                time.sleep(0.6)
        except Exception:
            pass

    uia.SetGlobalSearchTimeout(0.8)

    catalog = Catalog()
    samples = 0
    state_counts: Counter = Counter()
    last_report = 0.0
    t0_mono = time.monotonic()
    frame_durations: list[float] = []
    window_switches: list[dict] = []
    errors: list[str] = []

    def attach(hwnd: int):
        try:
            return uia.ControlFromHandle(int(hwnd))
        except Exception as exc:
            errors.append("ControlFromHandle(0x%X): %r" % (hwnd, exc))
            return None

    if args.all_windows and not pinned:
        targets = sampleable_windows(window_rows)
        if not targets:
            print("[probe] no sampleable Purple window "
                  "(visible, on-screen, >= 100x100).")
            return 2
        primary = max(targets, key=lambda r: _area(r.get("rect")))
    else:
        targets = [selected]
        primary = selected

    roots: dict[int, object] = {}
    win_last_state: dict[int, str | None] = {}
    win_last_snapshot: dict[int, float] = {}
    for row in targets:
        root = attach(row["hwnd"])
        if root is not None:
            roots[row["hwnd"]] = root
            win_last_state[row["hwnd"]] = None
            win_last_snapshot[row["hwnd"]] = 0.0

    if not roots:
        print("[probe] FATAL: UIA root unavailable for every candidate window")
        return 1

    def snapshot(win: dict, rect, nodes: list[dict], visited: int,
                 label: str, flags: dict, seq: int, suffix: str = "") -> str:
        """Persist the tree that was already walked for this sample."""
        base = "tree_%04d_%s%s" % (seq, label, suffix)
        write_json(
            tree_dir / (base + ".json"),
            {
                "seq": seq,
                "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed": round(time.monotonic() - t0_mono, 3),
                "state": label,
                "flags": flags,
                "hwnd": win["hwnd_hex"],
                "pid": win["pid"],
                "title": win["title"],
                "class": win["class"],
                "win_rect": rect,
                "visited": visited,
                "nodes": nodes,
            },
        )
        if not args.no_shots:
            grab_window(rect, shots_dir / (base + ".png"))
        return base

    # A re-used --out directory must not append to a previous run's samples.
    samples_path.write_text("", encoding="utf-8")

    print("[probe] run=%s out=%s" % (run_id, out_dir))
    print("[probe] python=%s" % sys.version.splitlines()[0])
    print("[probe] elevated=%s dpi=%s" % (admin, dpi_mode))
    print("[probe] mode=%s windows=%d"
          % ("all-windows" if args.all_windows and not pinned else "single",
             len(targets)))
    for row in targets:
        print("[probe] target=%s class=%s rect=%s title=%s"
              % (row["hwnd_hex"], row["class"], row["rect"], row["title"]))

    def ensure_root(row: dict) -> None:
        hwnd = row["hwnd"]
        if hwnd in roots:
            return
        root = attach(hwnd)
        if root is None:
            return
        roots[hwnd] = root
        win_last_state[hwnd] = None
        win_last_snapshot[hwnd] = 0.0
        window_switches.append(
            {
                "elapsed": round(time.monotonic() - t0_mono, 3),
                "to": row["hwnd_hex"],
                "class": row["class"],
                "title": row["title"],
            }
        )

    try:
        while True:
            now = time.monotonic()
            if args.stop_file and Path(args.stop_file).exists():
                break
            if not args.once and (now - t0_mono) >= args.duration:
                break
            frame_start = time.monotonic()

            # ---- which windows to sample on this tick -----------------
            if pinned:
                tick_targets = [pick_window(window_rows, pinned) or selected]
            elif args.all_windows:
                tick_targets = sampleable_windows(enumerate_purple_windows())
                live = {r["hwnd"] for r in tick_targets}
                for hwnd in list(roots):
                    if hwnd not in live:
                        roots.pop(hwnd, None)
                        win_last_state.pop(hwnd, None)
                        win_last_snapshot.pop(hwnd, None)
            else:
                tick_targets = [pick_window(enumerate_purple_windows(), None) or selected]

            for row in tick_targets:
                ensure_root(row)

            for win in tick_targets:
                hwnd = win["hwnd"]
                root = roots.get(hwnd)
                if root is None:
                    continue
                rect = win.get("rect")
                nodes, visited = walk_tree(
                    root,
                    tuple(rect) if rect else None,
                    args.max_depth,
                    args.max_controls,
                    args.include_values,
                )
                label, flags = classify_probe(nodes)
                catalog.add(label, nodes, win["hwnd_hex"])
                samples += 1
                state_counts[label] += 1

                fg = False
                try:
                    fg = win32gui.GetForegroundWindow() == hwnd
                except Exception:
                    pass

                state_changed = label != win_last_state.get(hwnd)
                due_snapshot = (
                    time.monotonic() - win_last_snapshot.get(hwnd, 0.0)
                ) >= args.snapshot_every
                suffix = "_%04X" % (hwnd & 0xFFFF) if len(tick_targets) > 1 else ""
                snapshot_name = ""
                if args.once or state_changed or due_snapshot:
                    snapshot_name = snapshot(
                        win, rect, nodes, visited, label, flags, samples, suffix)
                    win_last_state[hwnd] = label
                    win_last_snapshot[hwnd] = time.monotonic()

                digest = hashlib.sha1(
                    json.dumps(
                        [
                            (n["ct"], n["aid"], n["cls"], n["name"],
                             tuple(n["rel_center"] or ()))
                            for n in nodes
                        ],
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()[:12]

                append_jsonl(
                    samples_path,
                    {
                        "seq": samples,
                        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "elapsed": round(time.monotonic() - t0_mono, 3),
                        "state": label,
                        "flags": flags,
                        "hwnd": win["hwnd_hex"],
                        "foreground": fg,
                        "iconic": win["iconic"],
                        "win_rect": rect,
                        "controls": len(nodes),
                        "visited": visited,
                        "tree_ms": round(
                            (time.monotonic() - frame_start) * 1000.0, 1),
                        "tree_hash": digest,
                        "snapshot": snapshot_name,
                    },
                )

                if state_changed or (time.monotonic() - last_report) >= 5.0:
                    print(
                        "[probe] t=%5.1fs %s hwnd=%s state=%-17s ctrl=%-4d "
                        "edits=%d(pw=%d) buttons=%-4d snap=%s"
                        % (
                            time.monotonic() - t0_mono,
                            "multi" if len(tick_targets) > 1 else "single",
                            win["hwnd_hex"],
                            label,
                            len(nodes),
                            flags["edit_count"],
                            flags["password_edit_count"],
                            flags["button_count"],
                            snapshot_name or "-",
                        )
                    )
                    last_report = time.monotonic()

            elapsed = time.monotonic() - frame_start
            frame_durations.append(round(elapsed * 1000.0, 1))

            if args.once:
                break

            sleep_for = max(0.0, args.interval - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        print("\n[probe] interrupted; writing results")
    except Exception as exc:
        errors.append("main loop: %r" % exc)
        print("[probe] ERROR: %r" % exc)

    duration = time.monotonic() - t0_mono
    catalog_json = catalog.to_json()
    write_json(out_dir / "catalog.json", catalog_json)

    run = {
        "run_id": run_id,
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.version,
        "executable": sys.executable,
        "admin": admin,
        "dpi_mode": dpi_mode,
        "mode": "all-windows" if args.all_windows and not pinned else "single",
        "hwnd": primary["hwnd"],
        "hwnd_hex": primary["hwnd_hex"],
        "pid": primary["pid"],
        "class": primary["class"],
        "title": primary["title"],
        "windows_sampled": [row["hwnd_hex"] for row in targets],
        "samples": samples,
        "duration_sec": round(duration, 1),
        "state_counts": dict(state_counts),
        "window_switches": window_switches,
        "frame_ms": {
            "min": min(frame_durations) if frame_durations else 0.0,
            "max": max(frame_durations) if frame_durations else 0.0,
            "avg": round(sum(frame_durations) / len(frame_durations), 1)
            if frame_durations else 0.0,
        },
        "windows": window_rows,
        "errors": errors,
        "args": {
            "duration": args.duration,
            "interval": args.interval,
            "snapshot_every": args.snapshot_every,
            "max_depth": args.max_depth,
            "max_controls": args.max_controls,
            "all_windows": args.all_windows,
            "stop_file": bool(args.stop_file),
            "include_values": args.include_values,
            "shots": not args.no_shots,
        },
    }
    write_json(out_dir / "run.json", run)

    gate = evaluate_gate(catalog_json, run)
    write_json(out_dir / "gate.json", gate)
    write_summary(out_dir / "summary.md", run, catalog_json, gate)

    print("[probe] done samples=%d duration=%.1fs states=%s"
          % (samples, duration, dict(state_counts)))
    print("[probe] gate: %s" % gate["status"].upper())
    for item in gate["blockers"]:
        print("[probe]   blocker: %s" % item)
    print("[probe] summary: %s" % (out_dir / "summary.md"))
    print("[probe] catalog: %s" % (out_dir / "catalog.json"))
    print("[probe] gate:    %s" % (out_dir / "gate.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
