"""Qty-path diagnostics: separate monitor (confirm) vs input (enter_chat)."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_PATH = LOG_DIR / "qty_diag.log"

LogFn = Callable[[str], None]


def _fg_info() -> dict[str, Any]:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return {"fg_hwnd": 0, "fg_title": ""}
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {
            "fg_hwnd": hex(hwnd),
            "fg_pid": int(pid.value),
            "fg_title": buf.value[:120],
        }
    except Exception as exc:
        return {"fg_error": type(exc).__name__}


def append_event(event: dict[str, Any], *, log: Optional[LogFn] = None) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    line = json.dumps(event, ensure_ascii=False)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    if log is not None:
        verdict = event.get("verdict") or event.get("phase") or "qty"
        brief = event.get("brief") or event.get("message") or ""
        log(f"[qty_diag] {verdict} {brief}".strip())
    return LOG_PATH


def verdict_after_type(
    *,
    pre_qty_open: bool,
    post_qty_open: bool,
    enter_ok: bool,
    enter_status: Optional[int],
    enter_chars: int,
    enter_keys: int,
    enter_failed: int,
    bag_before: Optional[int],
    bag_after: Optional[int],
    want: int,
) -> tuple[str, str]:
    """Return (verdict_code, human brief)."""
    bag_drop = None
    if bag_before is not None and bag_after is not None:
        bag_drop = int(bag_before) - int(bag_after)

    if not enter_ok or (enter_status is not None and int(enter_status) != 0):
        return (
            "INPUT_CLI_FAIL",
            f"enter_chat ok={enter_ok} status={enter_status} "
            f"chars={enter_chars} keys={enter_keys} failed={enter_failed}",
        )
    if enter_chars <= 0 and enter_keys <= 0:
        return (
            "INPUT_CLI_EMPTY",
            f"enter_chat reported ok but sent nothing "
            f"(chars={enter_chars} keys={enter_keys})",
        )
    if bag_drop is not None and bag_drop >= max(1, int(want)):
        return (
            "INPUT_OK_BAG",
            f"bag dropped {bag_drop} (want={want}); prompt "
            f"{'still open' if post_qty_open else 'closed'}",
        )
    if pre_qty_open and not post_qty_open:
        return (
            "INPUT_OK_PROMPT_CLOSED",
            f"qty prompt closed after type; bag_drop={bag_drop}",
        )
    if pre_qty_open and post_qty_open and (bag_drop is None or bag_drop <= 0):
        return (
            "INPUT_NO_EFFECT",
            "enter_chat ok/keys>0 but qty prompt still open and bag unchanged "
            "→ keys likely not accepted by LC qty field (focus/IME/wrong target), "
            "not a confirm-monitor false positive",
        )
    if not pre_qty_open:
        return (
            "MONITOR_NO_PROMPT",
            "typed without qty_prompt_open; monitor may have missed or raced",
        )
    return (
        "INPUT_UNCERTAIN",
        f"enter_ok prompt {pre_qty_open}->{post_qty_open} bag_drop={bag_drop}",
    )


def snapshot_monitor() -> dict[str, Any]:
    from supply.confirm_reader import describe, last_error, qty_prompt_open, snapshot
    from supply import windows as ui

    snap = snapshot()
    return {
        "qty_prompt_open": bool(qty_prompt_open(snap)),
        "confirm_describe": describe(snap),
        "confirm_err": last_error(),
        "confirm_raw_n": (snap or {}).get("n") if isinstance(snap, dict) else None,
        "uidialog": ui.describe(),
        **_fg_info(),
    }


def run_typed_quantity(
    want: int,
    *,
    bag_before: Optional[int] = None,
    log: Optional[LogFn] = None,
) -> dict[str, Any]:
    """Type qty with full before/after logging. Does not raise on enter_chat fail."""
    from supply.input_ops import type_quantity

    pre = snapshot_monitor()
    pre["bag_qty"] = bag_before
    append_event(
        {
            "phase": "pre_type",
            "want": int(want),
            "monitor": pre,
            "brief": pre.get("confirm_describe"),
        },
        log=log,
    )

    t0 = time.time()
    enter_payload: dict[str, Any] = {}
    enter_exc: Optional[str] = None
    try:
        enter_payload = (
            type_quantity(int(want), return_payload=True, raise_on_fail=False) or {}
        )
        if not enter_payload.get("ok", False):
            enter_exc = str(enter_payload.get("message") or "enter_chat not ok")
    except Exception as exc:
        enter_exc = f"{type(exc).__name__}: {exc}"
        enter_payload = {"ok": False, "status": -1, "message": enter_exc}

    post = snapshot_monitor()
    # bag_after filled by caller if available
    event = {
        "phase": "post_type",
        "want": int(want),
        "elapsed_s": round(time.time() - t0, 3),
        "enter_chat": enter_payload,
        "enter_exc": enter_exc,
        "monitor_pre": {
            "qty_prompt_open": pre.get("qty_prompt_open"),
            "confirm_describe": pre.get("confirm_describe"),
            "fg_title": pre.get("fg_title"),
            "bag_qty": bag_before,
        },
        "monitor_post": {
            "qty_prompt_open": post.get("qty_prompt_open"),
            "confirm_describe": post.get("confirm_describe"),
            "fg_title": post.get("fg_title"),
        },
    }
    code, brief = verdict_after_type(
        pre_qty_open=bool(pre.get("qty_prompt_open")),
        post_qty_open=bool(post.get("qty_prompt_open")),
        enter_ok=bool(enter_payload.get("ok")),
        enter_status=enter_payload.get("status"),
        enter_chars=int(enter_payload.get("chars") or 0),
        enter_keys=int(enter_payload.get("keys") or 0),
        enter_failed=int(enter_payload.get("failed") or 0),
        bag_before=bag_before,
        bag_after=None,
        want=int(want),
    )
    event["verdict"] = code
    event["brief"] = brief
    append_event(event, log=log)
    event["monitor_post_full"] = post
    return event
