"""Party monitor workflow steps (leader start and member start).

Pure functions over the monitor snapshot pieces; no game or socket access.
Step ``state``: done | active | wait | bad | off.
"""
from __future__ import annotations


def _ago(ts, now) -> str:
    try:
        return f"{max(0, int(float(now) - float(ts)))}s ago"
    except (TypeError, ValueError):
        return "—"


def _step(key: str, label: str, state: str, detail: str) -> dict:
    return {"key": key, "label": label, "state": state, "detail": detail}


def leader_workflow(*, sock, roster, policy, invite, rally, phase, now) -> list:
    """Leader start: server → connect → policy → confirm → invite → rally → hunt."""
    n = len(roster)
    sock_state = str(sock.get("state") or "off")
    clients = int(sock.get("clients") or 0)
    listening = sock_state == "listening"
    steps = [
        _step(
            "server",
            "Server",
            "done" if listening else ("wait" if sock_state in ("idle", "starting") else "bad"),
            f"{sock.get('advertise') or '—'}:{sock.get('port') or '—'} {sock_state}"
            f" · session {policy.get('session') or '—'}",
        )
    ]

    if not listening:
        conn = "off"
    elif n and clients >= n:
        conn = "done"
    else:
        conn = "active" if clients else "wait"
    steps.append(_step("connect", "Connect", conn, f"{clients}/{n} member socket(s)"))

    sent = int(policy.get("sent") or 0)
    at = policy.get("at")
    if not at:
        pol, pdetail = ("wait" if conn in ("active", "done") else "off"), "not sent yet"
    elif sent > 0:
        pol = "done"
        pdetail = f"→{sent} client(s) · {_ago(at, now)} · id {policy.get('policy_id') or '—'}"
    else:
        pol, pdetail = "wait", f"no socket to send to · {_ago(at, now)}"
    steps.append(_step("policy", "Policy", pol, pdetail))

    acked = [r for r in roster if r.get("policy_acked")]
    if n and len(acked) >= n:
        ack = "done"
    elif acked:
        ack = "active"
    else:
        ack = "wait" if pol == "done" else "off"
    adetail = f"{len(acked)}/{n} confirmed"
    if acked:
        adetail += ": " + ", ".join(str(r.get("name") or "") for r in acked)
    steps.append(_step("ack", "Confirm", ack, adetail))

    joined = [r for r in roster if r.get("in_party")]
    typed = sum(int(r.get("invites") or 0) for r in roster)
    failed = sum(int(r.get("invite_failed") or 0) for r in roster)
    istate = str(invite.get("state") or "")
    if n and len(joined) >= n:
        inv = "done"
    elif istate == "expired" or (failed and not typed):
        inv = "bad"
    elif typed or acked:
        inv = "active"
    else:
        inv = "off"
    notices = sum(int(r.get("invite_notices") or 0) for r in roster)
    idetail = f"{len(joined)}/{n} joined · {typed} /초대 typed · {notices} accept notice(s)"
    if failed:
        idetail += f" · {failed} failed"
    if istate == "expired":
        idetail += " · window over"
    steps.append(_step("invite", "Invite", inv, idetail))

    rstate = str(rally.get("state") or "off")
    expected = list(rally.get("expected") or [])
    arrived = list(rally.get("arrived") or [])
    rmap = {"done": "done", "waiting": "active", "hold_at": "active", "await_plan": "active"}
    steps.append(
        _step(
            "rally",
            "Rally",
            rmap.get(rstate, "off"),
            f"{rstate} · {len(arrived)}/{len(expected)} arrived · stage {rally.get('stage') or '—'}",
        )
    )
    hunting = phase == "hunting"
    steps.append(_step("hunt", "Hunt", "done" if hunting else "off", phase))
    return steps


def member_workflow(*, sock, policy, party, orders, accept, now) -> list:
    """Member start: connect → policy → apply → confirm → accept → in party → rally."""
    sock_state = str(sock.get("state") or "off")
    connected = sock_state == "connected"
    steps = [
        _step(
            "connect",
            "Connect",
            "done" if connected else ("wait" if sock_state in ("connecting", "reconnecting", "idle") else "bad"),
            f"{sock.get('uri') or '—'} {sock_state} · leader session "
            f"{policy.get('session') or '—'}"
            + (
                f" (reset {int(policy.get('session_resets') or 0)}×)"
                if int(policy.get("session_resets") or 0) > 1
                else ""
            ),
        )
    ]
    received = bool(policy.get("received"))
    steps.append(
        _step(
            "policy",
            "Policy",
            "done" if received else ("wait" if connected else "off"),
            "received from leader" if received else "waiting for leader policy",
        )
    )
    applied = bool(policy.get("overlay"))
    steps.append(
        _step(
            "apply",
            "Apply",
            "done" if applied else ("wait" if received else "off"),
            (
                f"temporary overlay as {policy.get('as_name') or '—'} · {_ago(policy.get('applied_at'), now)}"
                if applied
                else "own profile"
            ),
        )
    )
    acked_at = policy.get("acked_at")
    steps.append(
        _step(
            "ack",
            "Confirm",
            "done" if acked_at else ("wait" if applied else "off"),
            (
                f"sent {int(policy.get('acks') or 0)}× · {_ago(acked_at, now)} · id {policy.get('acked_id') or '—'}"
                if acked_at
                else "not sent"
            ),
        )
    )
    in_party = bool(isinstance(party, dict) and party.get("in_party"))
    pressed_at = accept.get("pressed_at")
    if accept.get("pending"):
        due = accept.get("due_in_s")
        acc = "active"
        adetail = f"invite for {accept.get('to') or '—'} · Y in {int(due or 0)}s"
    elif accept.get("error"):
        acc, adetail = "bad", f"Y failed: {accept.get('error')}"
    elif pressed_at:
        missed = int(accept.get("join_missed") or 0)
        acc = "done" if in_party else ("bad" if missed else "active")
        adetail = f"Y pressed {int(accept.get('presses') or 0)}× · {_ago(pressed_at, now)}"
        if missed and not in_party:
            adetail += f" · no join after {missed} press(es)"
    elif accept.get("skipped"):
        acc, adetail = ("done" if in_party else "wait"), str(accept.get("skipped"))
    else:
        acc, adetail = ("done" if in_party else ("wait" if acked_at else "off")), "no invite notice yet"
    steps.append(_step("accept", "Accept", acc, adetail))
    steps.append(
        _step(
            "party",
            "In party",
            "done" if in_party else ("wait" if acked_at else "off"),
            "joined" if in_party else "waiting for /초대",
        )
    )
    stage = str(orders.get("gather_stage") or "")
    if not stage:
        rst, rdetail = "off", "no rally order"
    elif orders.get("arrived"):
        rst, rdetail = "done", f"{stage} · arrived"
    else:
        rst, rdetail = "active", f"{stage} · walking"
    steps.append(_step("rally", "Rally", rst, rdetail))
    return steps


__all__ = ["leader_workflow", "member_workflow"]
