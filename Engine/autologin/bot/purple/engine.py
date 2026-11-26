"""Purple engine — the state machine for the S1-S3 execution path.

This runs entirely on live UIA observation and live clicks. It replaces the
old fixed-coordinate / resize / template flows. It does NOT touch the game
process and does NOT manage accounts; it only drives the Purple launcher from
the window gate through PlayButton.

Handoff contract (S4+ consumes):
    - bot.game  (GLFW30 window) set
    - bot._game_window_ready() == True
    - bot.phase == Phase.GAME_LOGIN
    - bot._purple_logged_in == True
    - bot._game_proc_seen == True
    - ctx.purple_logged_in == True
    - bot.purple kept
"""
from __future__ import annotations

import time
import logging

import psutil
import win32gui
import win32process

from . import act
from .contract import PurpleContract
from .observe import (
    S_CARD, S_EMAIL, S_FAILED, S_GAME_READY, S_HANDOFF, S_LAUNCHER,
    S_LOGGING_IN, S_PASSWORD, S_STARTING,
)
from .uia_session import PurpleSession

# A game-process webview may be present during several screens. Its class alone
# does not confirm AUTH; GameFlow owns confirmation and relaunch decisions.
AUTH_WEBVIEW_CLASS = "NcPlatformSdk_Webview"
GAME_IMAGES = ("lc.exe", "lineageclassic.exe")
log = logging.getLogger(__name__)
# Explicit localized titles already used by the legacy launcher. Exact
# matches only: never click another Lineage title based on a partial name.
GAME_CARD_TITLES = (
    "리니지 클래식", "Lineage Classic", "天堂经典", "天堂經典",
    "天堂经典版", "天堂經典版", "天堂 : 經典版", "天堂 : 经典版",
)


def _game_pids() -> set[int]:
    out: set[int] = set()
    try:
        for p in psutil.process_iter(["name", "pid"]):
            if (p.info.get("name") or "").lower() in GAME_IMAGES:
                out.add(p.info["pid"])
    except Exception:
        pass
    return out


def detect_auth_webview() -> int | None:
    """Return the hwnd of the Purple 간편 인증 popup, or None."""
    pids = _game_pids()
    if not pids:
        return None
    found: list[int] = []

    def _cb(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids:
                return
            if win32gui.GetClassName(hwnd) != AUTH_WEBVIEW_CLASS:
                return
            if win32gui.IsWindowVisible(hwnd):
                found.append(hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        pass
    return found[0] if found else None


class PurpleEngine:
    def __init__(self, contract: PurpleContract, email: str = "", password: str = ""):
        self.contract = contract
        self.session = PurpleSession(contract)
        self.email = email
        self.password = password
        self.state = S_FAILED
        self._hwnd: int | None = None
        self.last_error = ""

    # -- info --------------------------------------------------------------
    def login_fields_ok(self) -> bool:
        return bool(self.email) and bool(self.password)

    # -- window gate --------------------------------------------------------
    def find_primary_window(self, timeout: float = 30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = self.session.windows()
            if rows:
                rows.sort(key=lambda r: -((r.get("rect") or [0, 0, 0, 0])[2]
                                          - (r.get("rect") or [0, 0, 0, 0])[0]))
                return rows[0]
            time.sleep(0.5)
        return None

    # -- helpers ------------------------------------------------------------
    def _seed(self, state: str, seed: str) -> str:
        return self.contract.element(state, seed).get("automation_id", seed)

    # -- high-level flow ----------------------------------------------------
    def run(self, timeout_total: float = 360.0) -> str:
        budgets = self.contract.budgets_sec

        row = self.find_primary_window(timeout=budgets.get("window", 30))
        if row is None:
            self.last_error = "no Purple window"
            self.state = S_FAILED
            return self.state
        self._hwnd = row["hwnd"]

        deadline = time.time() + timeout_total
        while time.time() < deadline:
            # GLFW visible means the game shell exists. Hand off immediately so
            # S5/GameFlow can catch AUTH / boot-status UI. Do NOT bury a long
            # blocking wait inside this poll loop.
            if self._game_hwnd_visible():
                self.state = S_GAME_READY
                return S_HANDOFF

            # Every poll re-scans all on-screen Purple windows so the email
            # card (a separate, smaller window) is always seen alongside the
            # main shell/launcher. Each action finds its element across all
            # windows and clicks whichever window owns it.
            scanned = self.session.scan_all()
            if not scanned:
                time.sleep(0.5)
                continue

            # ---- classify which stage we are on across all windows ----
            if self._find_all("current-account", require_enabled=True):
                self._do_email()
                continue
            if self._find_all("current-password", require_enabled=True):
                self._do_password()
                continue

            if self._find_all(self._seed("gate", "NcSignInButton"),
                              require_enabled=True):
                self._click_gate()
                continue

            if self._find_all("PlayingButton"):
                # Start already in flight — next loop's GLFW check hands off.
                time.sleep(0.35)
                continue

            if self._find_all("PlayButton", require_enabled=True):
                self._press_play()
                continue

            card = self._find_game_card(scanned)
            if card:
                if not self._find_all("PlayButton"):
                    self._open_game_card(card)
                continue

            # Launcher nav visible but not on the game card / start view.
            if self._nav_visible(scanned):
                time.sleep(0.4)  # No recognized card yet; re-observe safely.
                continue

            # Transcript / unknown: wait for the launcher to settle.
            time.sleep(0.4)

        self.last_error = "total timeout elapsed"
        self.state = S_FAILED
        return self.state

    # -- window-aware find --------------------------------------------------
    def _find_all(self, aid: str, require_enabled: bool = False):
        for row, state, flags, nodes in self.session.scan_all():
            hit = (self.session.find_enabled if require_enabled else self.session.find)(
                nodes, aid)
            if hit is not None:
                self._hwnd = row["hwnd"]
                return row, hit
        return None

    def _find_game_card(self, scanned=None):
        """Find exactly one visible, enabled game card by localized UIA text."""
        titles = {" ".join(str(title).split()).casefold() for title in
                  (*GAME_CARD_TITLES, self._seed("launcher", "game_card"))}
        matches = []
        for row, _state, _flags, nodes in (scanned if scanned is not None
                                            else self.session.scan_all()):
            for node in nodes:
                if (not node.get("onscreen") or not node.get("enabled")
                        or node.get("ct") != "ListItemControl"):
                    continue
                values = (node.get("aid") or "", node.get("name") or "")
                if any(" ".join(value.split()).casefold() in titles for value in values):
                    matches.append((row, node))
        if len(matches) != 1:
            if len(matches) > 1:
                log.warning("multiple matching game cards; refusing ambiguous click")
            return None
        self._hwnd = matches[0][0]["hwnd"]
        return matches[0]

    def _nav_visible(self, scanned) -> bool:
        for row, state, flags, nodes in scanned:
            for n in nodes:
                if n["onscreen"] and n["aid"] in (
                        "Store", "Community", "Lounge", "PurpleOn",
                        "Game", "MyPage", "UpdateCenter", "Setting",
                        "GnbOpenButton"):
                    self._hwnd = row["hwnd"]
                    return True
        return False

    # -- sub-steps ----------------------------------------------------------
    def _click_gate(self) -> None:
        hit = self._find_all(self._seed("gate", "NcSignInButton"),
                             require_enabled=True)
        if hit:
            act.click_node(hit[0]["hwnd"], hit[1], "gate")
            time.sleep(1.2)

    def _do_email(self) -> None:
        if not self.email:
            self.last_error = "no email"
            return
        field = self._find_all(self._seed("login_email", "current-account"),
                               require_enabled=True)
        submit = self._find_all(self._seed("login_email", "btn-login-email"),
                                require_enabled=True)
        if field and submit:
            act.type_into(field[0]["hwnd"], field[1], self.email, "email")
            time.sleep(0.4)
            act.click_node(submit[0]["hwnd"], submit[1], "email-submit")
            time.sleep(1.2)

    def _do_password(self) -> None:
        if not self.password:
            self.last_error = "no password"
            return
        field = self._find_all(self._seed("login_password", "current-password"),
                               require_enabled=True)
        submit = self._find_all(self._seed("login_password", "btn-login-email"),
                                require_enabled=True)
        if field and submit:
            act.type_into(field[0]["hwnd"], field[1], self.password, "password")
            time.sleep(0.4)
            act.click_node(submit[0]["hwnd"], submit[1], "password-submit")
            time.sleep(1.5)

    def _open_game_card(self, hit=None) -> None:
        hit = hit or self._find_game_card()
        if hit:
            log.info("opening localized game card: %s", hit[1].get("aid") or hit[1].get("name"))
            act.click_node(hit[0]["hwnd"], hit[1], "game-card")
            time.sleep(1.5)

    def _press_play(self) -> None:
        hit = self._find_all("PlayButton", require_enabled=True)
        if hit:
            act.click_node(hit[0]["hwnd"], hit[1], "play")
            time.sleep(0.5)

    def _game_hwnd_visible(self) -> bool:
        """True when a visible GLFW game window exists (single non-blocking poll).

        The outer ``run`` loop owns retries. A nested multi-minute wait here
        used to swallow the AUTH boot-status UI before S5 could shake.
        """
        game_names = {"lc.exe", "lineageclassic.exe"}
        pids: set[int] = set()
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                if (proc.info.get("name") or "").lower() in game_names:
                    pids.add(proc.info["pid"])
        except Exception:
            return False
        if not pids:
            return False
        found: list[int] = []

        def cb(hwnd, _):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return
                cls = (win32gui.GetClassName(hwnd) or "").upper()
                if "GLFW" in cls and win32gui.IsWindowVisible(hwnd):
                    found.append(hwnd)
            except Exception:
                pass

        try:
            win32gui.EnumWindows(cb, None)
        except Exception:
            return False
        return bool(found)

    def _game_ready(self, timeout: float = 0.0) -> bool:
        """Compatibility wrapper: single poll, or brief wait if timeout > 0."""
        if timeout <= 0:
            return self._game_hwnd_visible()
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if self._game_hwnd_visible():
                return True
            time.sleep(0.35)
        return False

    # -- debug/status -------------------------------------------------------
    def status(self) -> dict:
        return {
            "state": self.state,
            "hwnd": ("0x%08X" % self._hwnd) if self._hwnd else None,
            "last_error": self.last_error,
            "email_set": bool(self.email),
            "password_set": bool(self.password),
        }
