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


def leader_workflow(*, sock, roster, policy, invite, rally, phase, now, party_mem="ok") -> list:
    """Leader start: server → connect → policy → confirm → invite → rally → hunt.

    Joined comes from either side's party memory (``in_party_src``); with the
    leader's own party memory blind, member reports still count.
    """
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
    reporting = [r for r in roster if r.get("state_fresh")]
    steps.append(
        _step(
            "connect",
            "Connect",
            conn,
            f"{clients}/{n} member socket(s) · {len(reporting)}/{n} reporting state",
        )
    )

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
    elif failed and not typed:
        inv = "bad"
    elif typed or acked:
        inv = "active"
    else:
        inv = "off"
    notices = sum(int(r.get("invite_notices") or 0) for r in roster)
    idetail = f"{len(joined)}/{n} joined · {typed} /초대 typed · {notices} accept notice(s)"
    by_report = [r for r in joined if r.get("in_party_src") == "member report"]
    if by_report:
        idetail += f" · {len(by_report)} by member report"
    holds = [f"{r.get('name')} {r.get('invite_hold')}" for r in roster if r.get("invite_hold")]
    if holds:
        idetail += " · holding: " + ", ".join(holds)
    if failed:
        idetail += f" · {failed} failed"
    if istate == "open":
        idetail += " · start wait over, still inviting late members"
    if party_mem != "ok":
        idetail += " · leader party memory unreadable"
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


def roster_member_steps(row: dict, *, phase: str) -> list:
    """Leader view of one roster member: connect → policy → invite → accept → party → rally/follow."""
    fresh = bool(row.get("state_fresh"))
    age = row.get("state_age_s")
    seen = age is not None
    steps = [
        _step(
            "connect",
            "Connect",
            "done" if fresh else ("bad" if seen else "wait"),
            (
                f"reporting · last {age}s ago · {int(row.get('state_frames') or 0)} frame(s)"
                if fresh
                else (f"silent {age}s — member bot stopped or socket down" if seen else "never connected")
            ),
        )
    ]
    acked = bool(row.get("policy_acked"))
    steps.append(
        _step(
            "policy",
            "Policy",
            "done" if acked else ("wait" if fresh else "off"),
            "confirmed current policy" if acked else "waiting for the member to confirm",
        )
    )
    joined = bool(row.get("in_party"))
    invites = int(row.get("invites") or 0)
    hold = str(row.get("invite_hold") or "")
    if joined:
        ist, idetail = "done", f"{invites} /초대 typed"
    elif not acked:
        ist, idetail = "off", "after policy confirm"
    else:
        ist = "active"
        ago = row.get("invite_ago_s")
        idetail = f"{invites} /초대 typed" + (f" · last {ago}s ago" if ago is not None else "")
        if hold:
            idetail += f" · holding: {hold}"
    if int(row.get("invite_failed") or 0):
        idetail += f" · {int(row.get('invite_failed'))} failed"
    if row.get("late") and not joined:
        idetail += " · late (start wait over)"
    steps.append(_step("invite", "Invite", ist, idetail))
    mphase = str(row.get("state_invite") or "").partition(":")[2] or "idle"
    amap = {"waiting": "active", "pressed": "active", "joined": "done", "failed": "bad", "missed": "bad"}
    steps.append(
        _step(
            "accept",
            "Accept",
            "done" if joined else amap.get(mphase, "off"),
            f"member reports {mphase}",
        )
    )
    left = int(row.get("left") or 0)
    if joined:
        pst = "done"
        pdetail = f"joined · {row.get('in_party_src') or '—'}"
        if row.get("leaving_s") is not None:
            pst, pdetail = "active", f"reports out of party for {row.get('leaving_s')}s"
    else:
        pst, pdetail = ("wait" if acked else "off"), "not in the party"
    if left:
        pdetail += f" · left {left}×"
    steps.append(_step("party", "In party", pst, pdetail))
    live = row.get("live") or {}
    if row.get("at_rally"):
        rst, rdetail = "done", "at the rally point"
    elif joined and phase == "hunting":
        rst = "active"
        rdetail = f"following the leader · {live.get('kind') or '—'}"
    elif joined and phase == "rally":
        rst, rdetail = "active", f"walking to the rally ({live.get('rally') or '—'})"
    else:
        rst, rdetail = "off", "—"
    steps.append(_step("rally", "Rally / follow", rst, rdetail))
    return steps


def member_workflow(*, sock, policy, party, orders, accept, now, sync=None) -> list:
    """Member start: connect → policy → apply → confirm → sync → accept → in party → rally.

    ``party`` None = party memory unreadable: "In party" is unknown, never failed.
    """
    sync = sync or {}
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
    sent_at = sync.get("sent_at")
    if sent_at:
        stale = float(now) - float(sent_at) > 7.0
        steps.append(
            _step(
                "sync",
                "Sync",
                "wait" if stale or not connected else "done",
                f"state → leader #{int(sync.get('seq') or 0)} · {_ago(sent_at, now)}",
            )
        )
    else:
        steps.append(
            _step(
                "sync",
                "Sync",
                "wait" if connected else "off",
                "no state sent yet (waiting for a leader frame)",
            )
        )

    mem_ok = isinstance(party, dict)
    in_party = bool(mem_ok and party.get("in_party"))
    phase = str(accept.get("phase") or "idle")
    pressed_at = accept.get("pressed_at")
    presses = int(accept.get("presses") or 0)
    tag = f" · id {accept.get('invite_id')}" if accept.get("invite_id") else ""
    if phase == "waiting":
        acc = "active"
        adetail = f"invite for {accept.get('to') or '—'} · Y in {int(accept.get('due_in_s') or 0)}s"
    elif phase == "failed":
        acc, adetail = "bad", f"Y failed: {accept.get('error')}"
    elif phase == "pressed":
        acc, adetail = "active", f"Y pressed {presses}× · {_ago(pressed_at, now)} · checking join"
    elif phase == "joined":
        acc = "done"
        adetail = (
            f"Y pressed {presses}× · {_ago(pressed_at, now)} · joined"
            if pressed_at
            else str(accept.get("skipped") or "joined")
        )
    elif phase == "unverified":
        acc = "active"
        adetail = f"Y pressed {presses}× · {_ago(pressed_at, now)} · party memory unreadable"
    elif phase == "missed":
        missed = int(accept.get("join_missed") or 0)
        acc = "bad"
        adetail = (
            f"Y pressed {presses}× · {_ago(pressed_at, now)} · no join after "
            f"{missed} press(es) — waiting for the next /초대"
        )
    elif phase == "skipped":
        acc, adetail = "wait", str(accept.get("skipped"))
    else:
        acc, adetail = ("done" if in_party else ("wait" if acked_at else "off")), "no invite notice yet"
    steps.append(_step("accept", "Accept", acc, adetail + tag))

    if not mem_ok:
        pst = "active" if pressed_at else ("wait" if acked_at else "off")
        pdetail = "unknown — party memory unreadable (registry / not elevated)"
    elif in_party:
        lead = str(party.get("leader_name") or "")
        if isinstance(party.get("leader"), dict):
            lead = str(party["leader"].get("name") or lead)
        pst, pdetail = "done", f"joined · leader {lead or '—'} · {int(party.get('count') or 0)} in party"
    else:
        pst, pdetail = ("wait" if acked_at else "off"), "not in a party · waiting for /초대"
    steps.append(_step("party", "In party", pst, pdetail))
    stage = str(orders.get("gather_stage") or "")
    if not stage:
        rst, rdetail = "off", "no rally order"
    elif orders.get("arrived"):
        rst, rdetail = "done", f"{stage} · arrived"
    else:
        rst, rdetail = "active", f"{stage} · walking"
    steps.append(_step("rally", "Rally", rst, rdetail))
    return steps


__all__ = ["leader_workflow", "member_workflow", "roster_member_steps"]
