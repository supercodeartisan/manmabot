"""Server replay: member reports invite phase ``missed``, leader resends.

The member frame and the 20s clock are injected. Each ``/초대`` the leader
decides to send is typed into the live ``LC.exe`` window through
``send_chat_line``. A ``popup`` report still blocks that line.
"""
from __future__ import annotations

from app._06_party.invite import INVITE_EVERY_S, LeaderInvites, invite_command
from app._06_party.sync import ACCEPT_HOLD_S, InviteHold, MemberStates

LEADER = "매력여기사"
MEMBER = "콘러드"
SNAP = {"subs_ok": True, "in_party": False, "members": []}


def _frame(seq: int, phase: str, invite_id: str = "09de2ec3") -> dict:
    return {
        "from": MEMBER,
        "seq": seq,
        "session": "befe0ce7",
        "policy_id": "168fecb88a",
        "party": {"mem": "ok", "in_party": False, "leader": "", "names": []},
        "invite": {"id": invite_id, "phase": phase} if phase else {},
    }


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _game_send(sent: list, clock: _Clock):
    """Type the leader line into the game. False when the game did not take it."""
    from app._05_action.chat.sender import send_chat_line

    def send(line: str) -> bool:
        result = send_chat_line(line)
        ok = bool(result.ok) and int(result.failed or 0) == 0
        row = (
            clock.t,
            line,
            ok,
            int(result.chars),
            int(result.keys),
            bool(result.enter_pressed),
            result.describe(),
        )
        sent.append(row)
        print(
            f"game t={clock.t:.0f}s {line!r} ok={ok} "
            f"chars={result.chars} keys={result.keys} enter={int(bool(result.enter_pressed))} "
            f"{result.describe()}"
        )
        return ok

    return send


def _server(*, live: bool):
    clock = _Clock()
    states = MemberStates(clock=clock)
    sent: list = []

    def policy_acked(name: str) -> bool:
        return not states.awaiting_fresh(name)

    if live:
        send_chat = _game_send(sent, clock)
    else:
        send_chat = lambda line: sent.append((clock.t, line, True, 0, 0, False, "stub")) or True

    invites = LeaderInvites(
        policy_acked=policy_acked,
        hold=InviteHold(states, clock=clock),
        reported_joined=lambda name: states.joined(name, LEADER),
        reported_out=lambda name: states.out_of_party(name, LEADER),
        send_chat=send_chat,
        wait=lambda _s: None,
        log=lambda _m: None,
        clock=clock,
        start_wait_s=0.0,
    )
    assert invites.start([MEMBER], snapshot=SNAP, self_name=LEADER)
    return clock, states, invites, sent


def _tick(invites: LeaderInvites) -> str:
    return invites.tick(SNAP, last_action=None) or ""


def _is_admin() -> bool:
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _relaunch_elevated() -> int:
    """LC.exe is elevated. Chat focus fails from a medium-integrity process."""
    import ctypes
    import os
    import sys
    import time

    log_path = os.path.join(os.path.dirname(__file__), "_live_invite.log")
    try:
        os.remove(log_path)
    except OSError:
        pass
    code = (
        "import runpy,sys; "
        f"sys.stdout=sys.stderr=open({log_path!r},'w',encoding='utf-8',buffering=1); "
        "runpy.run_module('app._06_party.tests.sim_missed_reinvite', run_name='__main__')"
    )
    params = '-c "' + code.replace('"', '\\"') + '"'
    ret = int(
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, os.getcwd(), 0
        )
        or 0
    )
    if ret <= 32:
        raise SystemExit(f"elevation refused ({ret})")
    deadline = time.time() + 90.0
    while time.time() < deadline:
        time.sleep(0.5)
        if not os.path.isfile(log_path):
            continue
        text = open(log_path, encoding="utf-8", errors="replace").read()
        if "OK" in text or "Traceback" in text or "SystemExit" in text:
            print(text.rstrip())
            return 0 if text.rstrip().endswith("OK") else 1
    raise SystemExit("elevated replay produced no result")


def main() -> None:
    if not _is_admin():
        raise SystemExit(_relaunch_elevated())

    from app._05_action.chat.sender import GAME_PROCESS, _find_game_hwnd

    hwnd = _find_game_hwnd()
    if not hwnd:
        raise SystemExit(f"{GAME_PROCESS} window not found")

    clock, states, invites, sent = _server(live=True)
    line = invite_command(MEMBER)

    assert _tick(invites) == line
    assert sent[0][1] == line and sent[0][2] is True

    states.note(MEMBER, _frame(12, "popup"), [MEMBER], session="befe0ce7")
    clock.t = 5.0
    assert _tick(invites) == ""
    assert [row[1] for row in sent] == [line]

    states.note(MEMBER, _frame(13, "missed"), [MEMBER], session="befe0ce7")
    clock.t = 19.0
    states.note(MEMBER, _frame(14, "missed"), [MEMBER], session="befe0ce7")
    assert states.invite_phase(MEMBER) == ("09de2ec3", "missed")
    assert _tick(invites) == ""

    clock.t = INVITE_EVERY_S
    assert states.invite_phase(MEMBER) == ("09de2ec3", "missed")
    assert _tick(invites) == line
    assert [row[0] for row in sent] == [0.0, INVITE_EVERY_S]
    assert all(row[1] == line and row[2] is True for row in sent)

    clock.t = INVITE_EVERY_S + 5.0
    states.note(MEMBER, _frame(14, "missed"), [MEMBER], session="befe0ce7")
    assert _tick(invites) == ""

    held_clock, held_states, held, held_sent = _server(live=False)
    assert _tick(held) == line
    held_states.note(MEMBER, _frame(12, "popup"), [MEMBER], session="befe0ce7")
    held_clock.t = INVITE_EVERY_S
    held_states.note(MEMBER, _frame(13, "popup"), [MEMBER], session="befe0ce7")
    assert held_states.invite_phase(MEMBER)[1] == "popup"
    assert _tick(held) == ""
    held_clock.t = INVITE_EVERY_S + ACCEPT_HOLD_S
    held_states.note(MEMBER, _frame(14, "popup"), [MEMBER], session="befe0ce7")
    assert _tick(held) == line
    assert held_sent[-1][0] == INVITE_EVERY_S + ACCEPT_HOLD_S
    assert held_sent[-1][1] == line

    print("missed, resend at +{:.0f}s: {}".format(INVITE_EVERY_S, sent))
    print(
        "popup still blocking at +{:.0f}s, resend at +{:.0f}s: {}".format(
            INVITE_EVERY_S, INVITE_EVERY_S + ACCEPT_HOLD_S, held_sent
        )
    )
    print("OK")


if __name__ == "__main__":
    main()
