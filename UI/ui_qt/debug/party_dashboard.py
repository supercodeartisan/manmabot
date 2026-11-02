"""Party dashboard — role-aware status badges, link metrics, roster / overlay.

Pure view over ``BotController.party_monitor_snapshot()``. No engine calls.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

TONES = {
    "ok": "#1a7f37",
    "info": "#2563eb",
    "warn": "#b45309",
    "bad": "#b91c1c",
    "off": "#4b5563",
    "accent": "#7c3aed",
}


def _fmt(v: Any, fallback: str = "—") -> str:
    if v is None or v == "":
        return fallback
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def _age(ts: Any, now: float | None = None) -> str:
    try:
        sec = max(0.0, float(now or time.time()) - float(ts))
    except (TypeError, ValueError):
        return "—"
    if sec < 60:
        return f"{int(sec)}s ago"
    if sec < 3600:
        return f"{int(sec // 60)}m {int(sec % 60)}s ago"
    return f"{int(sec // 3600)}h {int(sec % 3600 // 60)}m ago"


def _duration(sec: Any) -> str:
    try:
        s = int(float(sec))
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


class Badge(QLabel):
    """Rounded status pill: ``LABEL value`` in a tone colour."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = label
        font = QFont(self.font())
        font.setBold(True)
        font.setPointSize(max(8, font.pointSize() - 1))
        self.setFont(font)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set("—", "off")

    def set(self, value: str, tone: str = "off", tip: str = "") -> None:
        color = TONES.get(tone, TONES["off"])
        text = f"{self._label}  {value}" if self._label else str(value)
        if self.text() != text:
            self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ background:{color}; color:#ffffff; border-radius:9px;"
            " padding:3px 10px; }"
        )
        self.setToolTip(tip)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps to a new line instead of widening the parent."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[Any] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _place(self, rect: QRect, *, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x > rect.x() and x + hint.width() > rect.right() + 1:
                x = rect.x()
                y += line_h + gap
                line_h = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class BadgeRow(QWidget):
    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = FlowLayout(self, spacing=6)
        self.badges: dict[str, Badge] = {}
        for label in labels:
            badge = Badge(label, self)
            self.badges[label] = badge
            lay.addWidget(badge)

    def __getitem__(self, label: str) -> Badge:
        return self.badges[label]


class Metrics(QWidget):
    """Two-column key/value grid; rows keep their order once created."""

    def __init__(self, columns: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(3)
        self._columns = max(1, int(columns))
        self._cells: dict[str, tuple[QLabel, QLabel]] = {}

    def set(self, rows: list[tuple[str, str]]) -> None:
        for key, value in rows:
            cell = self._cells.get(key)
            if cell is None:
                idx = len(self._cells)
                r, c = divmod(idx, self._columns)
                k = QLabel(key)
                k.setStyleSheet("color:#9ca3af;")
                v = QLabel()
                v.setWordWrap(True)
                v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                vf = QFont(v.font())
                vf.setBold(True)
                v.setFont(vf)
                self._grid.addWidget(k, r, c * 2)
                self._grid.addWidget(v, r, c * 2 + 1)
                self._grid.setColumnStretch(c * 2 + 1, 1)
                cell = (k, v)
                self._cells[key] = cell
            if cell[1].text() != value:
                cell[1].setText(value)


STEP_TONE = {"done": "ok", "active": "info", "wait": "warn", "bad": "bad", "off": "off"}
STEP_WORD = {
    "done": "DONE",
    "active": "IN PROGRESS",
    "wait": "WAITING",
    "bad": "FAILED",
    "off": "—",
}


class WorkflowSteps(QWidget):
    """Numbered start-up steps: pill · state word · one-line detail."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnStretch(2, 1)
        self._rows: list[tuple[Badge, QLabel, QLabel]] = []

    def set(self, steps: list[dict[str, Any]]) -> None:
        while len(self._rows) < len(steps):
            r = len(self._rows)
            pill = Badge("", self)
            pill.setMinimumWidth(120)
            word = QLabel(self)
            wf = QFont(word.font())
            wf.setBold(True)
            word.setFont(wf)
            word.setMinimumWidth(92)
            detail = QLabel(self)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(pill, r, 0)
            self._grid.addWidget(word, r, 1)
            self._grid.addWidget(detail, r, 2)
            self._rows.append((pill, word, detail))
        for i, (pill, word, detail) in enumerate(self._rows):
            shown = i < len(steps)
            for w in (pill, word, detail):
                w.setVisible(shown)
            if not shown:
                continue
            step = steps[i] if isinstance(steps[i], dict) else {}
            state = str(step.get("state") or "off")
            tone = STEP_TONE.get(state, "off")
            text = str(step.get("detail") or "")
            pill.set(f"{i + 1}  {str(step.get('label') or '').upper()}", tone, text)
            word.setText(str(step.get("word") or STEP_WORD.get(state, state.upper())))
            word.setStyleSheet(f"color:{TONES[tone]};")
            if detail.text() != text:
                detail.setText(text)


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setObjectName("partyCard")
    box.setStyleSheet(
        "QFrame#partyCard { border:1px solid #374151; border-radius:6px; }"
    )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 8, 10, 10)
    lay.setSpacing(6)
    head = QLabel(title)
    hf = QFont(head.font())
    hf.setBold(True)
    head.setFont(hf)
    lay.addWidget(head)
    return box, lay


def _table(headers: list[str], height: int) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.setFixedHeight(height)
    return table


def _cell(text: str, tone: str = "") -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if tone:
        item.setBackground(QColor(TONES.get(tone, TONES["off"])))
        item.setForeground(QColor("#ffffff"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def message_counts(lines: list[Any]) -> tuple[int, int, str]:
    """``(in, out, last_stamp)`` from traffic-log lines."""
    n_in = n_out = 0
    last = ""
    for raw in lines or []:
        line = str(raw)
        if "  OUT  " in line:
            n_out += 1
        elif "  IN   " in line:
            n_in += 1
        else:
            continue
        last = line.split(" ", 1)[0]
    return n_in, n_out, last


# Leader roster row ``state`` → (label, tone). Unknown states show upper-cased.
MEMBER_STATE = {
    "ready": ("AT RALLY", "ok"),
    "following": ("HUNTING", "ok"),
    "joined": ("JOINED", "ok"),
    "not_arrived": ("NOT ARRIVED", "warn"),
    "accepting": ("ACCEPTING", "info"),
    "inviting": ("INVITING", "info"),
    "late": ("LATE · INVITING", "warn"),
    "policy_wait": ("POLICY…", "warn"),
    "offline": ("OFFLINE", "off"),
    "late_offline": ("LATE · OFFLINE", "bad"),
}
_SETTLED = ("ready", "following", "joined")


def member_state_label(state: str) -> tuple[str, str]:
    return MEMBER_STATE.get(state, (str(state or "—").upper(), "off"))


def pick_member(roster: list[dict[str, Any]], current: str) -> str:
    """Keep the selected name; else the first member that needs attention; else the first."""
    names = [str(r.get("name") or "") for r in roster if r.get("name")]
    if current and current in names:
        return current
    for r in roster:
        if str(r.get("state") or "") not in _SETTLED and r.get("name"):
            return str(r["name"])
    return names[0] if names else ""


def member_messages(lines: list[Any], name: str, limit: int = 80) -> list[str]:
    """Traffic lines that mention ``name`` (sender, ``to``, or body), newest last."""
    key = str(name or "").strip().casefold()
    if not key:
        return []
    out = [str(l) for l in (lines or []) if key in str(l).casefold()]
    return out[-limit:]


def split_messages(lines: list[Any], role: str) -> tuple[list[str], list[str]]:
    """``(leader_side, member_side)`` traffic lines.

    Leader process: its OUT frames and local notes (chat typing) on top, member
    IN frames below. Member process: leader IN frames on top, its own OUT and
    local notes below.
    """
    top: list[str] = []
    bottom: list[str] = []
    member = str(role or "") == "member"
    for raw in lines or []:
        line = str(raw)
        if not line.strip():
            continue
        is_in = "  IN   " in line
        if member:
            (top if is_in else bottom).append(line)
        else:
            (bottom if is_in else top).append(line)
    return top, bottom


# ---------------------------------------------------------------------------


class PartyDashboard(QWidget):
    """Header flags + communication + role card + in-game party table.

    ``member_picked`` fires when the user selects a roster name. The
    dashboard still does not call the engine.
    """

    member_picked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.flags = BadgeRow(["ROLE", "BOT", "WS", "DLL", "PARTY", "MAP"])
        root.addWidget(self.flags)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#9ca3af;")
        root.addWidget(self.note)

        self.flow_box, flow_lay = card("Workflow")
        self.workflow = WorkflowSteps()
        flow_lay.addWidget(self.workflow)
        root.addWidget(self.flow_box)

        comm_box, comm_lay = card("Communication")
        self.comm = Metrics(columns=2)
        comm_lay.addWidget(self.comm)
        root.addWidget(comm_box)

        # --- leader ---
        self.leader_box, lead_lay = card("Leader — party control")
        self.lead_flags = BadgeRow(["PHASE", "MODE", "LOOT", "POLICY", "INVITE", "RALLY"])
        lead_lay.addWidget(self.lead_flags)
        self.lead_metrics = Metrics(columns=2)
        lead_lay.addWidget(self.lead_metrics)

        # Member picker (left) + the picked member's steps / live state / frames (right).
        pick_head = QLabel("Members — pick one to see its details")
        pick_head.setStyleSheet("color:#9ca3af;")
        lead_lay.addWidget(pick_head)
        pick_row = QHBoxLayout()
        pick_row.setSpacing(10)
        self.member_list = QListWidget()
        self.member_list.setFixedWidth(210)
        self.member_list.setMinimumHeight(220)
        self.member_list.currentItemChanged.connect(self._on_member_picked)
        pick_row.addWidget(self.member_list, 0)
        detail = QVBoxLayout()
        detail.setSpacing(6)
        self.member_title = QLabel("—")
        tf = QFont(self.member_title.font())
        tf.setBold(True)
        tf.setPointSize(tf.pointSize() + 1)
        self.member_title.setFont(tf)
        detail.addWidget(self.member_title)
        self.member_steps = WorkflowSteps()
        detail.addWidget(self.member_steps)
        self.member_metrics = Metrics(columns=2)
        detail.addWidget(self.member_metrics)
        self.member_log = QPlainTextEdit()
        self.member_log.setReadOnly(True)
        self.member_log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.member_log.setFixedHeight(130)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self.member_log.setFont(mono)
        self.member_log.setStyleSheet(
            "QPlainTextEdit { background:#111827; color:#e5e7eb;"
            " border:1px solid #374151; border-radius:4px; }"
        )
        detail.addWidget(self.member_log)
        pick_row.addLayout(detail, 1)
        lead_lay.addLayout(pick_row)
        self._picked = ""
        self._last_session: dict[str, Any] = {}
        self._last_messages: list[Any] = []

        over_head = QLabel("Overview")
        over_head.setStyleSheet("color:#9ca3af;")
        lead_lay.addWidget(over_head)
        self.roster = _table(
            ["Name", "Seat", "Loot", "Policy", "Invites", "In party", "At rally", "Status"], 150
        )
        lead_lay.addWidget(self.roster)
        root.addWidget(self.leader_box)

        # --- member ---
        self.member_box, mem_lay = card("Member — following leader")
        self.mem_flags = BadgeRow(
            ["POLICY", "MODE", "FARM", "SEAT", "LOOT", "LEADER", "BRAIN"]
        )
        mem_lay.addWidget(self.mem_flags)
        self.mem_metrics = Metrics(columns=2)
        mem_lay.addWidget(self.mem_metrics)
        root.addWidget(self.member_box)

        # --- solo ---
        self.solo_box, solo_lay = card("Solo")
        solo_hint = QLabel(
            "Party is off. The bot runs on its own profile; nothing is sent "
            "or received over the party socket."
        )
        solo_hint.setWordWrap(True)
        solo_lay.addWidget(solo_hint)
        root.addWidget(self.solo_box)

        party_box, party_lay = card("In-game party (memory)")
        self.members = _table(["Name", "Leader", "HP", "MP", "Lv", "XY", "Map"], 130)
        party_lay.addWidget(self.members)
        root.addWidget(party_box)
        root.addStretch(1)

    # ------------------------------------------------------------------ apply

    def apply(self, snap: dict[str, Any]) -> None:
        session = snap.get("session") if isinstance(snap.get("session"), dict) else {}
        role = str(session.get("role") or "solo")
        now = float(session.get("now") or time.time())
        party = snap.get("party") if isinstance(snap.get("party"), dict) else {}
        status = snap.get("status") if isinstance(snap.get("status"), dict) else {}

        self._apply_flags(snap, role, party, status)
        self._apply_comm(snap, now)
        self.leader_box.setVisible(role == "leader")
        self.member_box.setVisible(role == "member")
        self.solo_box.setVisible(role not in ("leader", "member"))
        steps = list(session.get("workflow") or [])
        self.flow_box.setVisible(role in ("leader", "member") and bool(steps))
        self.workflow.set(steps)
        if role == "leader":
            self._apply_leader(session, now)
            self._apply_member_picker(session, list(snap.get("messages") or []))
        elif role == "member":
            self._apply_member(snap, session, status, now)
        self._apply_members(party)

    def _apply_flags(self, snap, role, party, status) -> None:
        f = self.flags
        f["ROLE"].set(
            role.upper(),
            {"leader": "accent", "member": "info"}.get(role, "off"),
        )
        bot = str(snap.get("bot_state") or "?")
        alive = bool(snap.get("worker_alive"))
        bot_tone = "ok" if alive and bot.lower() == "running" else (
            "warn" if alive else "off"
        )
        f["BOT"].set(bot.upper(), bot_tone, str(snap.get("bot_reason") or ""))

        sock = snap.get("socket") if isinstance(snap.get("socket"), dict) else {}
        state = str(sock.get("state") or "off")
        ws_tone = {
            "listening": "ok",
            "connected": "ok",
            "starting": "info",
            "connecting": "info",
            "reconnecting": "warn",
            "idle": "warn",
            "off": "off",
        }.get(state, "bad")
        ws_text = state.upper()
        if state == "reconnecting" and sock.get("drops"):
            ws_text += f" #{sock.get('drops')}"
        f["WS"].set(ws_text, ws_tone, str(sock.get("error") or ""))

        dll_ok = bool(snap.get("dll_loaded"))
        f["DLL"].set("OK" if dll_ok else "MISSING", "ok" if dll_ok else "bad",
                     str(snap.get("probe_error") or ""))

        in_party = bool(party.get("in_party"))
        count = party.get("count") or len(party.get("members") or [])
        f["PARTY"].set(
            f"×{count}" if in_party else "NONE",
            "ok" if in_party else ("warn" if role != "solo" else "off"),
        )

        same = status.get("leader_same_map")
        lm, rm = status.get("local_map_id"), status.get("leader_map_id")
        if role != "member" or lm is None or rm is None:
            f["MAP"].set(_fmt(lm if lm is not None else (snap.get("self") or {}).get("map_id")), "off")
        else:
            f["MAP"].set(
                "SAME" if same or lm == rm else f"{lm}→{rm}",
                "ok" if same or lm == rm else "warn",
            )
        start_err = str(snap.get("start_error") or "").strip()
        wait = snap.get("start_wait") if isinstance(snap.get("start_wait"), dict) else {}
        if start_err:
            err, style = start_err, "color:#f87171;font-weight:600;"
        elif wait.get("since"):
            err = (
                f"Leader socket {wait.get('uri') or '—'} still connecting "
                f"({_duration(wait.get('waited_s'))}). "
                "Follow and combat use party memory. Policy and rally wait for the socket."
            )
            style = "color:#86efac;font-weight:600;"
        else:
            err, style = str(snap.get("probe_error") or "").strip(), "color:#9ca3af;"
        self.note.setText(err)
        self.note.setStyleSheet(style)
        self.note.setVisible(bool(err))

    def _apply_comm(self, snap, now) -> None:
        sock = snap.get("socket") if isinstance(snap.get("socket"), dict) else {}
        lines = list(snap.get("messages") or [])
        n_in, n_out, last = message_counts(lines)
        if sock.get("role") == "server":
            ids = sock.get("client_ids") or []
            link = f"{_fmt(sock.get('clients'), '0')} client(s)"
            if ids:
                link += "  [" + ", ".join(str(x) for x in ids[:6]) + "]"
            endpoint = f"{sock.get('bind_host') or '0.0.0.0'}:{_fmt(sock.get('port'))}  (LAN {_fmt(sock.get('advertise'))})"
        elif sock.get("role") == "client":
            link = str(sock.get("state") or "down")
            if not sock.get("connected") and sock.get("down_s"):
                link += f" ({float(sock.get('down_s')):.0f}s)"
            if sock.get("drops") or sock.get("restarts"):
                link += (
                    f"  drops {_fmt(sock.get('drops'), '0')}"
                    f" / restarts {_fmt(sock.get('restarts'), '0')}"
                )
            endpoint = _fmt(sock.get("uri"))
        else:
            link = "—"
            endpoint = "—"
        self.comm.set(
            [
                ("Endpoint", endpoint),
                ("Link", link),
                ("Frames in / out", f"{n_in} / {n_out}"),
                ("Last frame", last or "—"),
                ("Port", _fmt(sock.get("port"))),
                ("Error", _fmt(sock.get("error"), "none")),
            ]
        )

    def _apply_leader(self, session, now) -> None:
        settings = session.get("settings") or {}
        policy = session.get("policy") or {}
        invite = session.get("invite") or {}
        rally = session.get("rally") or {}
        roster = list(session.get("roster") or [])
        turret = session.get("turret") or {}
        line = session.get("line_wait") or {}
        f = self.lead_flags

        mode = str(settings.get("leader_mode") or "turret").upper()
        anchor = turret.get("anchor")
        if mode == "TURRET" and turret.get("on"):
            f["MODE"].set(
                "TURRET ⚓" if anchor else "TURRET …",
                "accent" if anchor else "info",
                f"anchor {anchor[0]},{anchor[1]}" if anchor else "picking anchor",
            )
        elif mode == "MOVING" and line.get("hold"):
            f["MODE"].set(
                "MOVING ⏸",
                "warn",
                f"{line.get('behind')}/{line.get('known')} members > "
                f"{line.get('lag_tiles')} tiles behind",
            )
        else:
            f["MODE"].set(mode, "accent")
        f["LOOT"].set(
            "SOLO" if settings.get("random_loot") else "RESPONSIBLE", "info"
        )
        if policy.get("at"):
            sent = int(policy.get("sent") or 0)
            f["POLICY"].set(f"→{sent}", "ok" if sent else "warn", _age(policy["at"], now))
        else:
            f["POLICY"].set("NOT SENT", "off")

        phase = session.get("phase") or {}
        pname = str(phase.get("name") or "off")
        left = phase.get("remaining_s")
        left_txt = _duration(left) if left is not None else "—"
        late = list(phase.get("late") or [])
        not_arrived = list(phase.get("not_arrived") or [])
        if pname == "forming":
            f["PHASE"].set(
                f"START WAIT {left_txt}", "warn",
                "Inviting members as they connect; the hunt starts when all are in or at 0",
            )
        elif pname == "rally":
            f["PHASE"].set(f"RALLY {left_txt}", "warn", "Gathering; hunt starts when all arrive or at 0")
        elif pname == "hunting":
            short = sorted(set(late) | set(not_arrived))
            f["PHASE"].set(
                "HUNTING" + (f" −{len(short)}" if short else ""),
                "warn" if short else "ok",
                ("late (still invited): " + ", ".join(late) if late else "")
                + ("  not arrived (following): " + ", ".join(not_arrived) if not_arrived else ""),
            )
        else:
            f["PHASE"].set("OFF", "off")

        istate = str(invite.get("state") or "")
        irows = [r for r in (invite.get("rows") or []) if isinstance(r, dict)]
        sent_lines = [s for s in (invite.get("sent") or []) if str(s).startswith("/")]
        joined = sum(1 for r in irows if r.get("joined"))
        if istate == "forming":
            f["INVITE"].set(f"{joined}/{len(irows)} JOINED", "info", f"{len(sent_lines)} invite(s) sent")
        elif istate == "formed":
            f["INVITE"].set(f"{joined}/{len(irows)} FORMED", "ok")
        elif istate == "open":
            f["INVITE"].set(
                f"{joined}/{len(irows)} OPEN", "warn",
                "Start wait over; still inviting: " + (", ".join(r.get("name") for r in irows if not r.get("joined")) or "—"),
            )
        elif istate:
            f["INVITE"].set(istate.upper(), "bad" if "fail" in istate else "info")
        else:
            f["INVITE"].set("PENDING", "off")

        rstate = str(rally.get("state") or "off")
        expected = list(rally.get("expected") or [])
        arrived = list(rally.get("arrived") or [])
        f["RALLY"].set(
            rstate.upper() if rstate != "waiting" else f"WAIT {len(arrived)}/{len(expected)}",
            {"done": "ok", "waiting": "warn", "hold_at": "info", "await_plan": "info"}.get(rstate, "off"),
        )

        in_party = sum(1 for r in roster if r.get("in_party"))
        disc = session.get("discovery") if isinstance(session.get("discovery"), dict) else {}
        pending = list(disc.get("pending") or [])
        missing = list(disc.get("missing") or [])
        unidentified = int(disc.get("unidentified_count") or 0)
        conflict = int(disc.get("conflict_count") or 0)
        pending_names = ", ".join(
            str(r.get("name") or "") for r in pending if r.get("name")
        ) or "—"
        self.lead_metrics.set(
            [
                ("Roster", f"{len(roster)} member(s), {in_party} in party"),
                (
                    "Discovery",
                    f"{len(pending)} pending · {len(missing)} missing"
                    + (f" · {unidentified} unnamed" if unidentified else "")
                    + (f" · {conflict} conflict" if conflict else "")
                    + f"  ({pending_names})",
                ),
                ("Party size (yard)", _fmt(policy.get("party_size"))),
                ("Phase", f"{pname} — {left_txt} left" if left is not None else pname),
                ("Invite every", f"{_fmt(invite.get('every_s'))}s, start wait {_duration(invite.get('start_wait_s')) if invite.get('start_wait_s') else '—'}, no cut-off"),
                ("Late", ", ".join(late) or "—"),
                ("Not arrived", ", ".join(not_arrived) or "—"),
                ("Rally stage", _fmt(rally.get("stage"))),
                ("Rally wait", _duration(rally.get("wait_s")) if rally.get("wait_s") is not None else "—"),
                ("Missing", ", ".join(rally.get("missing") or []) or "—"),
                ("Loot priority", _fmt(settings.get("loot_priority"))),
                (
                    "Turret anchor",
                    f"map{_fmt(turret.get('map_id'))} ({anchor[0]},{anchor[1]}) "
                    f"leash {_fmt(turret.get('leash'))}, "
                    f"{_fmt(turret.get('excluded'), '0')} out of zone"
                    if anchor
                    else ("picking" if turret.get("on") else "—"),
                ),
                (
                    "Line wait",
                    f"{'waiting' if line.get('hold') else _fmt(line.get('reason'))} "
                    f"{_fmt(line.get('behind'), '0')}/{_fmt(line.get('known'), '0')} "
                    f"> {_fmt(line.get('lag_tiles'))} tiles"
                    if line
                    else "—",
                ),
            ]
        )

        self.roster.setRowCount(len(roster))
        for row, r in enumerate(roster):
            self.roster.setItem(row, 0, _cell(str(r.get("name") or "")))
            self.roster.setItem(row, 1, _cell(str(r.get("role") or "mage").upper(),
                                              "accent" if r.get("role") == "shopkeeper" else "info"))
            resp = str(r.get("loot") or "none") == "responsible"
            self.roster.setItem(row, 2, _cell("RESP" if resp else "—", "ok" if resp else "off"))
            acked = bool(r.get("policy_acked"))
            self.roster.setItem(row, 3, _cell("OK" if acked else "WAIT", "ok" if acked else "warn"))
            n_inv = int(r.get("invites") or 0)
            n_fail = int(r.get("invite_failed") or 0)
            ago = r.get("invite_ago_s")
            inv_txt = f"{n_inv}" + (f" ({_duration(ago)} ago)" if ago is not None and n_inv else "")
            if n_fail:
                inv_txt = (inv_txt if n_inv else "0") + f"  ✗{n_fail}"
            self.roster.setItem(row, 4, _cell(
                inv_txt if (n_inv or n_fail) else "—",
                "bad" if n_fail and not n_inv else ("info" if n_inv else "off"),
            ))
            src = str(r.get("in_party_src") or "")
            leader_blind = str(session.get("party_mem") or "ok") != "ok"
            member_blind = not r.get("state_fresh") or str(r.get("state_mem") or "") != "ok"
            if r.get("in_party"):
                p_txt, p_tone = ("YES" if src == "leader memory" else f"YES ({src})"), "ok"
            elif leader_blind and member_blind:
                p_txt, p_tone = "?", "warn"
            else:
                p_txt, p_tone = "NO", ("bad" if not leader_blind and not member_blind else "warn")
            p_item = _cell(p_txt, p_tone)
            p_item.setToolTip(
                f"member state: {'fresh' if r.get('state_fresh') else 'none/stale'}"
                f" · mem {r.get('state_mem') or '—'} · invite {r.get('state_invite') or '—'}"
                + (f" · hold: {r.get('invite_hold')}" if r.get("invite_hold") else "")
            )
            self.roster.setItem(row, 5, p_item)
            at = r.get("at_rally")
            self.roster.setItem(row, 6, _cell("YES" if at else ("…" if rally.get("armed") else "—"),
                                              "ok" if at else ("warn" if rally.get("armed") else "off")))
            st_txt, st_tone = member_state_label(str(r.get("state") or ""))
            self.roster.setItem(row, 7, _cell(st_txt, st_tone))

    def _on_member_picked(self, current, _previous=None) -> None:
        if current is None:
            return
        name = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if not name or name == self._picked:
            return
        self._picked = name
        self._show_member(self._last_session, self._last_messages)
        self.member_picked.emit(name)

    def _apply_member_picker(self, session: dict[str, Any], messages: list[Any]) -> None:
        self._last_session = session
        self._last_messages = messages
        roster = [r for r in (session.get("roster") or []) if isinstance(r, dict)]
        self._picked = pick_member(roster, self._picked)
        lst = self.member_list
        lst.blockSignals(True)
        try:
            want = len(roster) + (1 if session.get("unnamed_member") else 0)
            while lst.count() > want:
                lst.takeItem(lst.count() - 1)
            while lst.count() < want:
                lst.addItem(QListWidgetItem())
            for i, r in enumerate(roster):
                name = str(r.get("name") or "")
                label, tone = member_state_label(str(r.get("state") or ""))
                item = lst.item(i)
                item.setText(f"{name}\n  {label}")
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setBackground(QColor(TONES.get(tone, TONES["off"])))
                item.setForeground(QColor("#ffffff"))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setToolTip(
                    " → ".join(
                        f"{s.get('label')}: {s.get('state')}" for s in (r.get("steps") or [])
                    )
                )
                if name == self._picked:
                    lst.setCurrentRow(i)
            if session.get("unnamed_member"):
                item = lst.item(len(roster))
                item.setText("? unnamed member\n  reporting, name unknown")
                item.setData(Qt.ItemDataRole.UserRole, "")
                item.setBackground(QColor(TONES["warn"]))
                item.setForeground(QColor("#ffffff"))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(
                    "A member bot sends state without its character name, and more than "
                    "one roster name is open — the leader cannot tell which one it is. "
                    "It is booked once its name is read in game."
                )
        finally:
            lst.blockSignals(False)
        self._show_member(session, messages)

    def _show_member(self, session: dict[str, Any], messages: list[Any]) -> None:
        roster = [r for r in (session.get("roster") or []) if isinstance(r, dict)]
        row = next((r for r in roster if str(r.get("name") or "") == self._picked), None)
        if row is None:
            self.member_title.setText("No roster members" if not roster else "—")
            self.member_steps.set([])
            self.member_metrics.set([])
            if self.member_log.toPlainText():
                self.member_log.setPlainText("")
            return
        label, tone = member_state_label(str(row.get("state") or ""))
        self.member_title.setText(f"{row.get('name')}  ·  {label}")
        self.member_title.setStyleSheet(f"color:{TONES.get(tone, TONES['off'])};")
        self.member_steps.set(list(row.get("steps") or []))
        live = row.get("live") if isinstance(row.get("live"), dict) else {}
        xy = live.get("xy") or []

        def _hp(cur: str, top: str) -> str:
            if live.get(cur) is None:
                return "—"
            return f"{live.get(cur)}/{live.get(top)}" if live.get(top) else str(live.get(cur))

        age = row.get("state_age_s")
        self.member_metrics.set(
            [
                ("Seat / loot", f"{_fmt(row.get('role'))} / {_fmt(row.get('loot'))}"),
                (
                    "Last report",
                    (f"{_duration(age)} ago" + ("" if row.get("state_fresh") else " (stale)"))
                    if age is not None
                    else "never",
                ),
                ("Bot", _fmt(live.get("bot"))),
                (
                    "Map / XY",
                    f"{_fmt(live.get('map_id'))} / "
                    + (f"{xy[0]},{xy[1]}" if len(xy) >= 2 else "—"),
                ),
                ("HP / MP", f"{_hp('hp', 'max_hp')} / {_hp('mp', 'max_mp')}"),
                ("Brain", f"{_fmt(live.get('kind'))} · {_fmt(live.get('reason'))}"),
                ("Party memory", f"{_fmt(row.get('state_mem'))} · in party {_fmt(row.get('state_in_party'))}"),
                ("Invite (member)", _fmt(row.get("state_invite"))),
                (
                    "Invites",
                    f"{int(row.get('invites') or 0)} typed, "
                    f"{'accepted' if row.get('invite_accepted') else 'no accept yet'}"
                    + (f", {int(row.get('invite_failed'))} failed" if row.get("invite_failed") else ""),
                ),
                (
                    "Left / late",
                    f"left {int(row.get('left') or 0)}× · {'late' if row.get('late') else 'on time'}",
                ),
            ]
        )
        text = "\n".join(member_messages(messages, str(row.get("name") or "")))
        if self.member_log.toPlainText() != text:
            self.member_log.setPlainText(text)
            bar = self.member_log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _apply_member(self, snap, session, status, now) -> None:
        policy = session.get("policy") or {}
        eff = session.get("effective") or {}
        own = session.get("own") or {}
        orders = session.get("orders") or {}
        action = snap.get("action") or {}
        f = self.mem_flags

        if policy.get("overlay"):
            f["POLICY"].set("LEADER", "ok", f"applied {_age(policy.get('applied_at'), now)}")
        elif policy.get("received"):
            f["POLICY"].set("RECEIVED", "info")
        else:
            f["POLICY"].set("OWN", "warn", "No leader policy yet — using this bot's own settings")
        f["MODE"].set(str(eff.get("leader_mode") or "—").upper(), "accent",
                      "Leader mode (from party policy)")
        f["FARM"].set(str(eff.get("farm_mode") or "—").upper(), "info",
                      "This member's own farming method")
        f["SEAT"].set(str(eff.get("seat_role") or "—").upper(), "info")
        loot = "SOLO" if eff.get("random_loot") else str(eff.get("loot_role") or "none").upper()
        f["LOOT"].set(loot, "ok" if loot in ("SOLO", "RESPONSIBLE") else "off")

        farming = bool(status.get("leader_farming"))
        visible = bool(status.get("leader_entity_visible"))
        seen = str(status.get("leader_name_seen") or "")
        if farming:
            f["LEADER"].set("FIGHTING", "ok")
        elif visible:
            f["LEADER"].set("IN VIEW", "info")
        elif seen:
            f["LEADER"].set("OFF VIEW", "warn")
        else:
            f["LEADER"].set("NO LOCK", "bad")
        kind = str(status.get("last_kind") or "—")
        f["BRAIN"].set(
            kind.upper(),
            {"assist": "ok", "close_in": "ok", "follow": "info", "hold": "info",
             "join_map": "warn", "wait": "warn", "stop": "off"}.get(kind.lower(), "off"),
            str(status.get("last_reason") or ""),
        )

        def pair(key: str) -> str:
            e, o = eff.get(key), own.get(key)
            if o is None or e == o:
                return _fmt(e)
            return f"{_fmt(e)}  (own {_fmt(o)})"

        gather = orders.get("gather_stage") or ""
        gxy = orders.get("gather_xy") or []
        gtxt = "—"
        if gather:
            gtxt = f"{gather} map{_fmt(orders.get('gather_map'))} ({_fmt(gxy[0] if gxy else None)},{_fmt(gxy[1] if len(gxy) > 1 else None)})"
            gtxt += "  ARRIVED" if orders.get("arrived") else "  walking"
        self_info = snap.get("self") if isinstance(snap.get("self"), dict) else {}
        self.mem_metrics.set(
            [
                ("Self", _fmt(self_info.get("name") or policy.get("as_name"))),
                ("Leader", seen or "—"),
                ("Distance", _fmt(status.get("leader_dist"))),
                ("Leader HP / MP", f"{_fmt(status.get('leader_hp'))} / {_fmt(status.get('leader_mp'))}"),
                ("Target", _fmt(status.get("leader_target_name") or status.get("assist_name"))),
                ("Leader mode", _fmt(eff.get("leader_mode"))),
                ("Farm (own)", _fmt(eff.get("farm_mode"))),
                ("Follow / stop", f"{pair('follow_tiles')} / {pair('stop_tiles')}"),
                ("Assist leash", _fmt(eff.get("assist_leash_tiles"))),
                ("Loot priority", _fmt(eff.get("loot_priority"))),
                ("Policy applied", _age(policy.get("applied_at"), now) if policy.get("applied_at") else "—"),
                ("Applied as", _fmt(policy.get("as_name"))),
                ("Gather order", gtxt),
                ("Recovery order", "received" if orders.get("recovery") else "—"),
                ("Action", _fmt(action.get("name"))),
                ("Why", _fmt(status.get("last_reason"))),
            ]
        )

    def _apply_members(self, party) -> None:
        members = [m for m in (party.get("members") or []) if isinstance(m, dict)]
        self.members.setRowCount(len(members))
        for row, m in enumerate(members):
            lead = bool(m.get("is_leader"))
            vals = [
                str(m.get("name") or ""),
                "★" if lead else "",
                _fmt(m.get("hp")),
                _fmt(m.get("mp")),
                _fmt(m.get("level")),
                f"{_fmt(m.get('x'))},{_fmt(m.get('y'))}",
                _fmt(m.get("map_id")),
            ]
            for col, text in enumerate(vals):
                item = _cell(text)
                if lead:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                    item.setForeground(QColor("#a78bfa"))
                self.members.setItem(row, col, item)


__all__ = [
    "Badge",
    "BadgeRow",
    "FlowLayout",
    "MEMBER_STATE",
    "Metrics",
    "PartyDashboard",
    "WorkflowSteps",
    "member_messages",
    "member_state_label",
    "message_counts",
    "pick_member",
    "split_messages",
]
