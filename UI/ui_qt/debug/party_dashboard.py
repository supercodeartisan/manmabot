"""Party dashboard — role-aware status badges, link metrics, roster / overlay.

Pure view over ``BotController.party_monitor_snapshot()``. No engine calls.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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


class BadgeRow(QWidget):
    def __init__(self, labels: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.badges: dict[str, Badge] = {}
        for label in labels:
            badge = Badge(label, self)
            self.badges[label] = badge
            lay.addWidget(badge)
        lay.addStretch(1)

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


# ---------------------------------------------------------------------------


class PartyDashboard(QWidget):
    """Header flags + communication + role card + in-game party table."""

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
        self.roster = _table(
            ["Name", "Seat", "Loot", "Invites", "In party", "At rally", "Status"], 150
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
        if role == "leader":
            self._apply_leader(session, now)
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
        err = start_err or str(snap.get("probe_error") or "").strip()
        self.note.setText(err)
        self.note.setStyleSheet(
            "color:#f87171;font-weight:600;" if start_err else "color:#9ca3af;"
        )
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
        excluded = list(phase.get("excluded") or [])
        not_arrived = list(phase.get("not_arrived") or [])
        if pname == "forming":
            f["PHASE"].set(f"FORMING {left_txt}", "warn", "Inviting the roster; window closes at 0")
        elif pname == "rally":
            f["PHASE"].set(f"RALLY {left_txt}", "warn", "Gathering; hunt starts when all arrive or at 0")
        elif pname == "hunting":
            short = excluded or not_arrived
            f["PHASE"].set(
                "HUNTING" + (f" −{len(excluded) + len(not_arrived)}" if short else ""),
                "warn" if short else "ok",
                ("excluded: " + ", ".join(excluded) if excluded else "")
                + ("  not arrived: " + ", ".join(not_arrived) if not_arrived else ""),
            )
        else:
            f["PHASE"].set("OFF", "off")

        istate = str(invite.get("state") or "")
        irows = [r for r in (invite.get("rows") or []) if isinstance(r, dict)]
        names = list(invite.get("names") or [])
        sent_lines = [s for s in (invite.get("sent") or []) if str(s).startswith("/")]
        joined = sum(1 for r in irows if r.get("joined"))
        if istate == "forming":
            f["INVITE"].set(f"{joined}/{len(irows)} JOINED", "info", f"{len(sent_lines)} invite(s) sent")
        elif istate == "formed":
            f["INVITE"].set(f"{joined}/{len(irows)} FORMED", "ok")
        elif istate == "expired":
            f["INVITE"].set(f"{joined}/{len(irows)} EXPIRED", "warn", "excluded: " + (", ".join(excluded) or "—"))
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
        self.lead_metrics.set(
            [
                ("Roster", f"{len(roster)} member(s), {in_party} in party"),
                ("Party size (yard)", _fmt(policy.get("party_size"))),
                ("Policy last sent", _age(policy.get("at"), now) if policy.get("at") else "—"),
                ("Policy sends", _fmt(policy.get("sends"), "0")),
                ("Phase", f"{pname} — {left_txt} left" if left is not None else pname),
                ("Invites", f"{len(sent_lines)} sent, {joined}/{len(names)} joined" if names else "—"),
                ("Invite every", f"{_fmt(invite.get('every_s'))}s, window {_duration(invite.get('window_s')) if invite.get('window_s') else '—'}"),
                ("Excluded", ", ".join(excluded) or "—"),
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
            n_inv = int(r.get("invites") or 0)
            ago = r.get("invite_ago_s")
            inv_txt = f"{n_inv}" + (f" ({_duration(ago)} ago)" if ago is not None and n_inv else "")
            self.roster.setItem(row, 3, _cell(inv_txt if n_inv else "—", "info" if n_inv else "off"))
            self.roster.setItem(row, 4, _cell("YES" if r.get("in_party") else "NO",
                                              "ok" if r.get("in_party") else "bad"))
            at = r.get("at_rally")
            self.roster.setItem(row, 5, _cell("YES" if at else ("…" if rally.get("armed") else "—"),
                                              "ok" if at else ("warn" if rally.get("armed") else "off")))
            st = str(r.get("state") or "pending")
            self.roster.setItem(row, 6, _cell(
                {"ready": "READY", "joined": "JOINED", "invited": "INVITED", "pending": "PENDING",
                 "excluded": "EXCLUDED", "not_arrived": "NOT ARRIVED"}.get(st, st.upper()),
                {"ready": "ok", "joined": "ok", "invited": "warn", "pending": "off",
                 "excluded": "bad", "not_arrived": "warn"}.get(st, "off"),
            ))

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
        self.mem_metrics.set(
            [
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


__all__ = ["Badge", "BadgeRow", "Metrics", "PartyDashboard", "message_counts"]
