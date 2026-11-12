"""Party monitor UI — role dashboard + small live etview + socket message log."""

from __future__ import annotations

import time
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from session.bot_controller import BotController
from ui_qt.debug.party_buff_lines import party_buff_lines
from ui_qt.debug.party_dashboard import PartyDashboard, split_messages
from ui_qt.debug.party_etview import PartyEtView, capture_lc_client


def _fmt(v: Any, fallback: str = "—") -> str:
    if v is None:
        return fallback
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _fmt_xy(xy: Any) -> str:
    if not xy:
        return "—"
    try:
        return f"{int(xy[0])},{int(xy[1])}"
    except Exception:
        return str(xy)


def _fill_members(table: QTableWidget, party: dict[str, Any] | None, farming: bool) -> None:
    members = list((party or {}).get("members") or []) if party else []
    table.setRowCount(len(members))
    for row, m in enumerate(members):
        if not isinstance(m, dict):
            continue
        vals = [
            str(m.get("name") or ""),
            "Y" if m.get("is_leader") else "",
            _fmt(m.get("hp")),
            _fmt(m.get("mp")),
            _fmt(m.get("level")),
            f"{_fmt(m.get('x'))},{_fmt(m.get('y'))}",
            _fmt(m.get("map_id")),
            str(m.get("guid") or ""),
        ]
        for col, text in enumerate(vals):
            item = QTableWidgetItem(text)
            if m.get("is_leader"):
                item.setForeground(QColor("#ffffff"))
                item.setBackground(QColor("#1a7f37" if farming else "#2563eb"))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            table.setItem(row, col, item)


def _message_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    view.setFont(font)
    view.setStyleSheet(
        "QPlainTextEdit {"
        " background:#111827; color:#e5e7eb;"
        " border:1px solid #374151; border-radius:4px;"
        " padding:6px;"
        "}"
    )
    return view


def _fill_messages(view: QPlainTextEdit, lines: list[Any]) -> None:
    text = "\n".join(str(line) for line in (lines or []) if str(line).strip())
    if view.toPlainText() == text:
        return
    bar = view.verticalScrollBar()
    at_end = bar.value() >= max(0, bar.maximum() - 4)
    view.setPlainText(text)
    if at_end:
        bar.setValue(bar.maximum())


def _fill_buffs(table: QTableWidget, rows: Any, now: float, empty: str) -> None:
    lines = party_buff_lines(rows, now)
    if not lines:
        lines = [("—", empty, "—")]
    signature = tuple(lines)
    if getattr(table, "_buff_sig", None) == signature:
        return
    table._buff_sig = signature
    table.setRowCount(len(lines))
    for index, (name, buffs, age) in enumerate(lines):
        table.setItem(index, 0, QTableWidgetItem(name))
        table.setItem(index, 1, QTableWidgetItem(buffs))
        table.setItem(index, 2, QTableWidgetItem(age))


def _socket_banner(snap: dict[str, Any]) -> tuple[str, str]:
    """Return ``(text, stylesheet)`` for the WebSocket connection strip."""
    sock = snap.get("socket") if isinstance(snap.get("socket"), dict) else {}
    role = str(sock.get("role") or "none")
    state = str(sock.get("state") or "off")
    err = str(sock.get("error") or "").strip()
    ok_style = "background:#1a7f37; color:#ffffff; border-radius:4px; padding:4px 8px;"
    wait_style = "background:#2563eb; color:#ffffff; border-radius:4px; padding:4px 8px;"
    warn_style = "background:#b45309; color:#ffffff; border-radius:4px; padding:4px 8px;"
    bad_style = "background:#b91c1c; color:#ffffff; border-radius:4px; padding:4px 8px;"
    off_style = "background:#6b7280; color:#ffffff; border-radius:4px; padding:4px 8px;"

    if role == "server":
        port = sock.get("port")
        advertise = sock.get("advertise") or "—"
        bind = sock.get("bind_host") or "0.0.0.0"
        clients = sock.get("clients")
        ids = sock.get("client_ids") or []
        id_txt = ",".join(str(x) for x in ids[:4]) if ids else "—"
        if state == "listening":
            text = (
                f"WS SERVER  LISTENING  bind={bind}:{port}  "
                f"LAN={advertise}  clients={_fmt(clients, '0')}  ids={id_txt}"
            )
            return text, ok_style
        if state in ("starting", "idle"):
            text = (
                f"WS SERVER  {state.upper()}  LAN={advertise}:{port}  "
                f"{err or 'waiting for Start'}"
            )
            return text, wait_style if state == "starting" else warn_style
        text = (
            f"WS SERVER  DOWN  LAN={advertise}:{port}  "
            f"{err or 'not listening'}"
        )
        return text, bad_style

    if role == "client":
        uri = sock.get("uri") or (
            f"ws://{sock.get('host') or '?'}:{sock.get('port') or '?'}/"
        )
        if state == "connected":
            return f"WS CLIENT  CONNECTED  {uri}", ok_style
        if state in ("connecting", "idle"):
            text = f"WS CLIENT  {state.upper()}  {uri}  {err or ''}".rstrip()
            return text, wait_style if state == "connecting" else warn_style
        text = f"WS CLIENT  DOWN  {uri}  {err or 'not connected'}"
        return text, bad_style

    return "WS  OFF  (Enable party on the Party tab)", off_style


class PartyMonitorPanel(QWidget):
    """Compact party status for Debug → Party (no etview canvas)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        t: dict[str, str] | None = None,
        show_headline: bool = True,
    ) -> None:
        super().__init__(parent)
        self.t = t or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.headline = QLabel(self.t.get("party_monitor_title", "Party"))
        font = QFont(self.headline.font())
        font.setBold(True)
        self.headline.setFont(font)
        if show_headline:
            layout.addWidget(self.headline)
        else:
            self.headline.hide()

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self.status)

        # Kept for older Debug-tab tests that assert .meta / .leader / .latest
        self.meta = self.status
        self.leader = self.status
        self.leader_banner = self.status
        self.self_row = self.status
        self.latest = self.status

        self.members = QTableWidget(0, 8)
        self.members.setHorizontalHeaderLabels(
            [
                self.t.get("party_mon_col_name", "Name"),
                self.t.get("party_mon_col_leader", "Leader"),
                self.t.get("party_mon_col_hp", "HP"),
                self.t.get("party_mon_col_mp", "MP"),
                self.t.get("party_mon_col_lv", "Lv"),
                self.t.get("party_mon_col_xy", "XY"),
                self.t.get("party_mon_col_map", "Map"),
                self.t.get("party_mon_col_guid", "GUID"),
            ]
        )
        self.members.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.members.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.members.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.members.setMaximumHeight(140)
        layout.addWidget(self.members)

        self.conn_status = QLabel("")
        self.conn_status.setWordWrap(True)
        self.conn_status.setContentsMargins(8, 6, 8, 6)
        layout.addWidget(self.conn_status)

        layout.addWidget(
            QLabel(self.t.get("party_messages", "Messages"))
        )
        self.messages = _message_view()
        layout.addWidget(self.messages, stretch=1)

    def apply(self, snap: dict[str, Any]) -> None:
        info = _status_bits(snap)
        self.headline.setText(info["headline"])
        self.status.setText(info["status_text"])
        self.status.setStyleSheet(info["status_style"])
        conn_text, conn_style = _socket_banner(snap)
        self.conn_status.setText(conn_text)
        self.conn_status.setStyleSheet(conn_style)
        _fill_members(self.members, snap.get("party") if isinstance(snap.get("party"), dict) else None, info["farming"])
        _fill_messages(self.messages, list(snap.get("messages") or []))


def _status_bits(snap: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(snap.get("enabled"))
    profile_on = bool(snap.get("profile_party_enabled"))
    dll_ok = bool(snap.get("dll_loaded"))
    probe_err = str(snap.get("probe_error") or "")
    status = snap.get("status") or {}
    party = snap.get("party") if isinstance(snap.get("party"), dict) else None
    action = snap.get("action") or {}
    self_info = snap.get("self") or {}
    note = _fmt(snap.get("note"), "")
    in_party = bool(party.get("in_party")) if party else False
    count = party.get("count") if party else None
    leader_name = ""
    leader_block = None
    if party:
        leader_name = str(party.get("leader_name") or "")
        leader_block = party.get("leader")
        if isinstance(leader_block, dict) and not leader_name:
            leader_name = str(leader_block.get("name") or "")

    if not dll_ok or "dll_missing" in note:
        headline = "NO PARTY READ (DLL missing)"
    elif in_party:
        headline = f"IN PARTY ×{_fmt(count, '?')}  leader={leader_name or '—'}"
    elif enabled:
        headline = "PARTY SESSION ON — not in party"
    elif profile_on:
        headline = "party checkbox ON — Start to run member brain"
    else:
        headline = "probe only (Hunt→Run as party member is off)"

    leader_hp = status.get("leader_hp")
    leader_mp = status.get("leader_mp")
    leader_xy = "—"
    if isinstance(leader_block, dict):
        if leader_hp is None:
            leader_hp = leader_block.get("hp")
        if leader_mp is None:
            leader_mp = leader_block.get("mp")
        try:
            leader_xy = f"{int(leader_block.get('x'))},{int(leader_block.get('y'))}"
        except Exception:
            leader_xy = "—"

    seen = str(status.get("leader_name_seen") or leader_name or "").strip()
    farming = bool(status.get("leader_farming"))
    ent_vis = bool(status.get("leader_entity_visible"))
    same_map = status.get("leader_same_map")
    if same_map is None:
        same_map = True
    else:
        same_map = bool(same_map)
    local_mid = status.get("local_map_id")
    leader_mid = status.get("leader_map_id")
    tgt = str(status.get("leader_target_name") or status.get("assist_name") or "").strip()
    if farming and tgt:
        activity = f"ATK→{tgt}"
    elif farming:
        activity = "FARMING"
    elif ent_vis:
        activity = "IN_UI"
    elif seen or in_party:
        activity = "OFF_UI"
    else:
        activity = "NO LOCK"
    map_tag = "SAME_MAP" if same_map else "OTHER_MAP"
    if local_mid is None or leader_mid is None:
        map_tag = "MAP?"

    kind = _fmt(status.get("last_kind"))
    reason = _fmt(status.get("last_reason"))
    status_text = (
        f"LEADER  {seen or '—'}  [{activity}|{map_tag}]  "
        f"hp={_fmt(leader_hp)}  mp={_fmt(leader_mp)}  xy={leader_xy}  "
        f"dist={_fmt(status.get('leader_dist'))}  "
        f"maps={_fmt(local_mid)}→{_fmt(leader_mid)}  "
        f"assist={_fmt(status.get('assist_src'))}:{_fmt(status.get('assist_name') or status.get('assist_track_id'))}\n"
        f"SELF  {str(self_info.get('name') or '—')}  "
        f"xy={_fmt_xy(self_info.get('xy'))}  "
        f"hp={_fmt(self_info.get('hp'))}  mp={_fmt(self_info.get('mp'))}  "
        f"kind={kind}  action={_fmt(action.get('name'))}  "
        f"why={reason}  "
        f"dll={'OK' if dll_ok else 'MISSING'}  "
        f"bot={_fmt(snap.get('bot_state'), '?')}  "
        f"probe={probe_err or 'ok'}"
    )
    if farming:
        style = "background:#1a7f37; color:#ffffff; border-radius:4px;"
    elif ent_vis:
        style = "background:#2563eb; color:#ffffff; border-radius:4px;"
    elif not same_map and (seen or in_party):
        style = "background:#b45309; color:#ffffff; border-radius:4px;"
    elif seen or in_party:
        style = "background:#876800; color:#ffffff; border-radius:4px;"
    else:
        style = "background:#6b7280; color:#ffffff; border-radius:4px;"
    # Tests look for these substrings on .meta / .leader
    status_text = (
        f"dll={'OK' if dll_ok else 'MISSING'}  in_party={in_party}  "
        f"leader={leader_name or seen or '—'}\n"
        + status_text
    )
    return {
        "headline": headline,
        "status_text": status_text,
        "status_style": style,
        "farming": farming,
        "seen": seen,
        "leader_name": leader_name,
        "leader_hp": leader_hp,
        "leader_mp": leader_mp,
        "leader_xy": leader_xy,
        "activity": activity,
        "map_tag": map_tag,
        "tgt": tgt,
        "kind": kind,
        "reason": reason,
        "dll_ok": dll_ok,
        "in_party": in_party,
        "same_map": same_map,
        "ent_vis": ent_vis,
    }


_LIVE_W = 360
_LIVE_H = 240
_RIGHT_W = _LIVE_W + 60


def _log_title(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def _log_titles(role: str) -> tuple[str, str]:
    if role == "member":
        return "Leader → this member (IN)", "This member → leader (OUT)"
    return "Leader → members (OUT · chat typing)", "Members → leader (IN)"


class PartyMonitorWindow(QMainWindow):
    """Party dashboard (left) + small live view and socket log (right)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: BotController,
        t: dict[str, str] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._on_close = on_close
        self._closing = False
        self._capture_tick = 0
        self._sized_to_client = False
        self.t = t or {}
        self.setWindowTitle(self.t.get("party_monitor_title", "Party monitor"))
        self.resize(1320, 860)
        self.setMinimumSize(960, 600)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        self.live_on = QCheckBox(self.t.get("party_live_view", "Live view"))
        self.live_on.setChecked(True)
        self.live_on.toggled.connect(self._on_live_toggled)
        top.addWidget(self.live_on)
        self.capture_bg = QCheckBox(
            self.t.get("etview_capture", "Game capture (BitBlt)")
        )
        self.capture_bg.setChecked(True)
        top.addWidget(self.capture_bg)
        top.addStretch(1)
        self.topmost = QCheckBox(self.t.get("always_on_top", "Always on top"))
        self.topmost.setChecked(True)
        self.topmost.toggled.connect(self._on_topmost)
        top.addWidget(self.topmost)
        layout.addLayout(top)

        manual = QHBoxLayout()
        manual.setSpacing(6)
        name_lbl = QLabel(self.t.get("party_ui_mon_name", "Name"))
        manual.addWidget(name_lbl)
        self.manual_name = QLineEdit()
        self.manual_name.setPlaceholderText(
            self.t.get("party_ui_mon_name_hint", "character name")
        )
        self.manual_name.setClearButtonEnabled(True)
        self.manual_name.setFixedWidth(180)
        self.manual_name.setToolTip(
            self.t.get(
                "party_ui_mon_invite_tip",
                "Invite line is /초대 <name>, one space before the name",
            )
        )
        manual.addWidget(self.manual_name)
        self.invite_btn = QPushButton(self.t.get("party_ui_mon_invite", "Invite"))
        self.invite_btn.setToolTip(
            self.t.get(
                "party_ui_mon_invite_tip",
                "Queue /초대 <name> on the bot worker (same path as automatic invite)",
            )
        )
        self.invite_btn.clicked.connect(self._on_invite_clicked)
        manual.addWidget(self.invite_btn)
        self.y_btn = QPushButton("Y+Enter")
        self.y_btn.setToolTip(
            self.t.get(
                "party_ui_mon_accept_tip",
                "Queue Y then Enter on the bot worker (same path as automatic accept)",
            )
        )
        self.y_btn.clicked.connect(self._on_y_clicked)
        manual.addWidget(self.y_btn)
        self.manual_status = QLabel("")
        self.manual_status.setWordWrap(True)
        manual.addWidget(self.manual_status, stretch=1)
        layout.addLayout(manual)
        self._chat_shown = ""
        self._topmost_dropped = False

        main = QSplitter(Qt.Orientation.Horizontal)

        # ---- left: role-aware dashboard ----
        self.dashboard = PartyDashboard(t=self.t)
        self.dashboard.member_picked.connect(self.manual_name.setText)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self.dashboard)
        scroll.setMinimumWidth(480)
        main.addWidget(scroll)

        # ---- right: small live view + leader / member message logs ----
        right = QWidget()
        right.setMinimumWidth(_RIGHT_W)
        right.setMaximumWidth(_RIGHT_W + 220)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)
        self.etview = PartyEtView()
        self.etview.setMinimumSize(_LIVE_W, _LIVE_H)
        self.etview.setFixedSize(_LIVE_W, _LIVE_H)
        right_l.addWidget(self.etview, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.buff_title = _log_title(self.t.get("party_buffs_title", "Received buffs"))
        self.buff_title.setToolTip(
            self.t.get(
                "party_buffs_tip",
                "The party_buffs list this bot received from the leader. Open this monitor on the mage.",
            )
        )
        right_l.addWidget(self.buff_title)
        self.buffs = QTableWidget(0, 3)
        self.buffs.setHorizontalHeaderLabels(
            [
                self.t.get("party_buffs_col_name", "Name"),
                self.t.get("party_buffs_col_buffs", "Buffs"),
                self.t.get("party_buffs_col_age", "Age"),
            ]
        )
        self.buffs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.buffs.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.buffs.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.buffs.verticalHeader().setVisible(False)
        self.buffs.setFixedHeight(120)
        self.buffs.setToolTip(self.buff_title.toolTip())
        right_l.addWidget(self.buffs)

        logs = QSplitter(Qt.Orientation.Vertical)
        logs.setChildrenCollapsible(False)
        top_box = QWidget()
        top_l = QVBoxLayout(top_box)
        top_l.setContentsMargins(0, 0, 0, 0)
        top_l.setSpacing(2)
        self.out_title = _log_title("")
        top_l.addWidget(self.out_title)
        self.out_messages = _message_view()
        top_l.addWidget(self.out_messages, stretch=1)
        bottom_box = QWidget()
        bottom_l = QVBoxLayout(bottom_box)
        bottom_l.setContentsMargins(0, 0, 0, 0)
        bottom_l.setSpacing(2)
        self.in_title = _log_title("")
        bottom_l.addWidget(self.in_title)
        self.in_messages = _message_view()
        bottom_l.addWidget(self.in_messages, stretch=1)
        logs.addWidget(top_box)
        logs.addWidget(bottom_box)
        logs.setSizes([300, 300])
        right_l.addWidget(logs, stretch=1)
        # Older callers read ``.messages``; it is the leader-side log.
        self.messages = self.out_messages
        main.addWidget(right)

        self._splitter = main
        main.setChildrenCollapsible(False)
        main.setStretchFactor(0, 1)
        main.setStretchFactor(1, 0)
        main.setSizes([1320 - _RIGHT_W - 40, _RIGHT_W + 40])
        layout.addWidget(main, stretch=1)

        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._on_poll)
        self._poll.start(100)
        self._on_poll()

    def _on_invite_clicked(self) -> None:
        name = self.manual_name.text().strip()
        if not name:
            self.manual_status.setText("Enter a character name")
            return
        self._queue_party_chat("invite", name)

    def _on_y_clicked(self) -> None:
        self._queue_party_chat("accept", "")

    def _queue_party_chat(self, kind: str, name: str) -> None:
        submit = getattr(self.controller, "submit_party_chat", None)
        if not callable(submit):
            self.manual_status.setText("rejected: bot has no party chat queue")
            return
        try:
            text = str(submit(kind, name) or "")
        except Exception as exc:
            text = f"rejected: {exc}"
        self._chat_shown = text
        self.manual_status.setText(text)
        if text.startswith("rejected") or text.startswith("Enter a character"):
            return
        self._yield_focus_to_game()

    def _yield_focus_to_game(self) -> None:
        """The click is on this window. Move LC to the foreground before keys.

        Always-on-top would stay the focused window, so Interception would type
        here. Drop that flag for this action, then focus the game on this
        thread — it just received the click, so Windows allows the switch.
        """
        if self.topmost.isChecked():
            self._topmost_dropped = True
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.show()
        self._focus_game()
        QTimer.singleShot(0, self._focus_game)

    def _focus_game(self) -> None:
        try:
            from session.probes import bring_game_to_front, probe_game

            hwnd = int(getattr(probe_game(), "hwnd", 0) or 0)
        except Exception:
            return
        if hwnd:
            bring_game_to_front(hwnd)

    def _restore_topmost(self, chat: dict) -> None:
        if not self._topmost_dropped:
            return
        if str(chat.get("state") or "") not in ("done", "failed"):
            return
        self._topmost_dropped = False
        if self.topmost.isChecked():
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.show()

    def _on_topmost(self, checked: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        self.show()

    def _on_live_toggled(self, checked: bool) -> None:
        self.etview.setVisible(bool(checked))
        self.capture_bg.setEnabled(bool(checked))
        if not checked:
            self.etview.clear_background()

    def _on_poll(self) -> None:
        if self._closing:
            return
        try:
            snap = self.controller.party_monitor_snapshot()
        except Exception as exc:
            snap = {"probe_error": f"snapshot failed: {exc}"}
        try:
            from session.party_probe import probe_party_live

            live = probe_party_live()
            snap = dict(snap or {})
            snap["dll_path"] = live.get("dll_path") or snap.get("dll_path", "")
            snap["dll_loaded"] = bool(live.get("dll_loaded"))
            snap["probe_error"] = str(
                live.get("error") or snap.get("probe_error") or ""
            )
            if isinstance(live.get("party"), dict):
                snap["party"] = live["party"]
        except Exception as exc:
            snap = dict(snap or {})
            snap.setdefault("dll_loaded", False)
            snap["probe_error"] = str(exc)

        self.dashboard.apply(snap)
        chat = snap.get("chat_action") if isinstance(snap.get("chat_action"), dict) else {}
        self._restore_topmost(chat)
        chat_text = str(chat.get("text") or "")
        if chat_text and chat_text != self._chat_shown:
            self._chat_shown = chat_text
            self.manual_status.setText(chat_text)
        session = snap.get("session") if isinstance(snap.get("session"), dict) else {}
        role = str(session.get("role") or "leader")
        top_title, bottom_title = _log_titles(role)
        if self.out_title.text() != top_title:
            self.out_title.setText(top_title)
            self.in_title.setText(bottom_title)
        top, bottom = split_messages(list(snap.get("messages") or []), role)
        _fill_messages(self.out_messages, top)
        _fill_messages(self.in_messages, bottom)
        _fill_buffs(
            self.buffs,
            snap.get("party_buffs"),
            time.time(),
            self.t.get("party_buffs_empty", "none received"),
        )
        if self.live_on.isChecked():
            self._refresh_etview(snap, _status_bits(snap))

    def _refresh_etview(self, snap: dict[str, Any], info: dict[str, Any]) -> None:
        status = snap.get("status") if isinstance(snap.get("status"), dict) else {}
        party = snap.get("party") if isinstance(snap.get("party"), dict) else {}
        leader_block = (
            party.get("leader") if isinstance(party.get("leader"), dict) else {}
        )
        leader_name = str(
            status.get("leader_name_seen")
            or party.get("leader_name")
            or leader_block.get("name")
            or info.get("seen")
            or ""
        )
        leader_guid = str(
            status.get("leader_guid") or leader_block.get("guid") or ""
        )
        target_name = str(
            status.get("leader_target_name") or status.get("assist_name") or ""
        )
        target_guid = str(status.get("leader_target_guid") or "")

        et: dict[str, Any] = {}
        try:
            from session.etview_probe import probe_etview_live

            et = probe_etview_live()
        except Exception as exc:
            et = {"error": str(exc), "entities": [], "attacks": []}

        bg = None
        self._capture_tick += 1
        if self.capture_bg.isChecked() and (self._capture_tick % 2) == 0:
            try:
                bg = capture_lc_client()
            except Exception:
                bg = None
        elif not self.capture_bg.isChecked():
            self.etview.clear_background()

        n_ent = len(et.get("entities") or [])
        n_atk = len(et.get("attacks") or [])
        err = str(et.get("error") or "").strip()
        hud = f"etview  ents={n_ent}  atk={n_atk}"
        if leader_name:
            hud += f"  leader={leader_name}"
        if target_name:
            hud += f"  tgt={target_name}"
        if err:
            hud += f"  ({err})"

        client_w = float(et.get("client_w") or 800)
        client_h = float(et.get("client_h") or 600)
        self.etview.set_frame(
            entities=list(et.get("entities") or []),
            attacks=list(et.get("attacks") or []),
            client_w=client_w,
            client_h=client_h,
            leader_name=leader_name,
            leader_guid=leader_guid,
            target_name=target_name,
            target_guid=target_guid,
            status=hud,
            background=bg,
        )
        # Keep the preview at the game aspect inside the small fixed box.
        cw, ch = self.etview.client_size()
        if cw > 1 and ch > 1:
            h = max(120, min(_LIVE_H + 60, int(round(_LIVE_W * ch / cw))))
            if self.etview.height() != h:
                self.etview.setFixedSize(_LIVE_W, h)

    def closeEvent(self, event) -> None:
        if self._closing:
            event.accept()
            return
        self._closing = True
        self._poll.stop()
        callback = self._on_close
        event.accept()
        if callback is not None:
            callback()
