"""Accuracy checks for pipeline remodel (S0–S6 contracts).

Run:  python scripts/pipeline_accuracy.py
No live Purple/game required — uses fakes + real position_dict ratios.
Optional live probe: --live (attach Purple if running).
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot")
sys.path.insert(0, BOT)

PASS = []
FAIL = []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print("PASS ", name)
    except Exception as e:
        FAIL.append((name, e))
        print("FAIL ", name, ":", repr(e))


# ---------- helpers ----------
class Rect:
    def __init__(self, w, h, left=0, top=0):
        self.width, self.height = w, h
        self.left, self.top = left, top
        self.center = (left + w // 2, top + h // 2)


class FakeWin:
    def __init__(self, w, h, hwnd=1):
        self.rect = Rect(w, h)
        self.client_rect = Rect(w, h)
        self.valid = True
        self.hwnd = hwnd
        self.title = "PURPLE"


class FakeBotBase:
    username = "u@test.com"
    password = "secret"
    game_path = ""
    _interception_ready = True
    _use_interception = True
    _purple_logged_in = False
    purple = None
    game = None
    phase = None
    flow = None
    cfg = {"lang_policy": "L0", "require_interception": True}
    _auth_relaunch_used = False
    _auth_relaunch_count = 0
    _shake_after_relaunch = False
    learn = False
    positions = None
    session_backup_dir = None
    launched = 0
    attach_ok = False
    process_running = False

    def tick(self):
        pass

    def launch_purple(self):
        self.launched += 1

    def _purple_process_running(self):
        return self.process_running

    def _any_purple_window_exists(self):
        return self.process_running

    def _try_attach_running_purple(self):
        if self.attach_ok and self.purple and self.purple.valid:
            return True
        return False

    def _restore_hidden_purple(self):
        return False

    def _game_process_alive(self):
        return False

    def has_launcher_toast(self):
        return False

    def dismiss_launcher_toast(self):
        return False


def test_s1_missing_launches_once():
    from pipeline import PipelineContext, PipelineRunner
    from pipeline.exceptions_reg import build_default_registry
    from pipeline.result import StageStatus

    bot = FakeBotBase()
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    runner = PipelineRunner(ctx, registry=build_default_registry())
    # S0
    r0 = runner.tick()
    assert r0.status == StageStatus.OK, r0
    # S1 missing -> launch, blocked waiting
    r1 = runner.tick()
    assert r1.stage_id == "S1"
    assert r1.status == StageStatus.BLOCKED, r1
    assert bot.launched == 1
    # Cooldown: second tick within 8s must NOT launch again
    r1b = runner.tick()
    assert bot.launched == 1, "double launch"
    assert r1b.status == StageStatus.BLOCKED


def test_s1_tiny_shell_blocks_not_launch():
    from pipeline.stages.s1_window_gate import WindowGateStage
    from pipeline import PipelineContext
    from pipeline.result import StageStatus
    from pipeline.exceptions_reg import build_default_registry

    bot = FakeBotBase()
    bot.purple = FakeWin(200, 150)
    bot.attach_ok = True
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    stage = WindowGateStage()
    snap = stage.snapshot(ctx)
    assert snap["purple_too_small"] is True
    assert snap.get("purple_missing") is False
    reg = build_default_registry()
    handled = reg.dispatch(ctx, "S1", snap)
    assert handled is not None
    assert handled.status == StageStatus.BLOCKED
    assert bot.launched == 0


def test_s1_login_card_is_usable():
    from pipeline.stages.s1_window_gate import WindowGateStage
    from pipeline import PipelineContext
    from pipeline.result import StageStatus
    from pipeline.exceptions_reg import build_default_registry

    bot = FakeBotBase()
    bot.purple = FakeWin(450, 773)
    bot.attach_ok = True
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    stage = WindowGateStage()
    snap = stage.snapshot(ctx)
    assert snap["purple_too_small"] is False
    assert build_default_registry().dispatch(ctx, "S1", snap) is None
    result = stage.run(ctx)
    assert result.status == StageStatus.OK, result


def test_s1_wide_shell_ok():
    from pipeline.stages.s1_window_gate import WindowGateStage
    from pipeline import PipelineContext
    from pipeline.result import StageStatus

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.attach_ok = True
    bot._purple_logged_in = True
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    r = WindowGateStage().run(ctx)
    assert r.status == StageStatus.OK, r
    assert ctx.purple_logged_in is True


def test_wrong_purple_ignores_missing():
    from pipeline.exceptions_reg import build_default_registry
    from pipeline import PipelineContext

    ctx = PipelineContext(bot=FakeBotBase(), cfg={})
    reg = build_default_registry()
    assert reg.dispatch(ctx, "S1", {
        "stage_id": "S1", "purple_missing": True, "purple_too_small": False
    }) is None
    # legacy bug shape: missing + too_small must still ignore when missing True
    assert reg.dispatch(ctx, "S1", {
        "stage_id": "S1", "purple_missing": True, "purple_too_small": True
    }) is None


def test_ratio_scale_accuracy():
    from positions import PositionStore

    store = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed", "game_click_mode": "fixed",
             "lang_policy": "L0", "position_dict_writable": False})
    assert store.lookup("purple", "purple_id_field")
    assert store.lookup("purple", "purple_login")
    assert store.lookup("purple", "purple_start_game")

    # Golden window 1642x1026 → recorded cx/cy
    win = FakeWin(1642, 1026)
    id_xy = store.client_xy("purple", "purple_id_field", win)
    login_xy = store.client_xy("purple", "purple_login", win)
    assert id_xy == (673, 317), id_xy
    assert login_xy == (820, 428), login_xy

    # Proportional scale to another same-layout size
    win2 = FakeWin(821, 513)  # ~half
    id2 = store.client_xy("purple", "purple_id_field", win2)
    # rx=0.4099 * 821 ≈ 336.5
    assert abs(id2[0] - int(0.4099 * 821)) <= 1, id2
    assert abs(id2[1] - int(0.309 * 513)) <= 1, id2

    assert store.writable is False
    before = dict(store.data["purple"]["purple_id_field"])
    store.record_client("purple", "purple_id_field", win, 1, 1)
    assert store.data["purple"]["purple_id_field"] == before


def test_s2_uses_fixed_when_shell_forced():
    """With familiar fixed shell size, S2 should drive fixed credential clicks."""
    from pipeline.stages.s2_purple_login import PurpleLoginStage
    from pipeline import PipelineContext
    from pipeline.result import StageStatus
    from positions import PositionStore, MODE_FIXED
    from base import Phase

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.phase = Phase.ENTER_CREDENTIALS
    bot.cfg["purple_force_size"] = True
    bot.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed", "lang_policy": "L0",
             "position_dict_writable": False, "purple_force_size": True})
    assert bot.positions.purple_mode == MODE_FIXED
    calls = []

    def _fixed():
        calls.append("fixed")
        bot._purple_logged_in = True

    bot._fixed_purple_login = _fixed
    bot._normalize_purple_shell_size = lambda *a, **k: True
    bot._maybe_fallback_purple_dynamic = lambda *a, **k: False
    bot._arm_purple_fixed_watch = lambda *a, **k: None
    bot.tick = lambda: calls.append("tick")
    bot._is_purple_login_screen = lambda *a, **k: True
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    r = PurpleLoginStage().run(ctx)
    assert "fixed" in calls, calls
    assert r.status in (StageStatus.OK, StageStatus.RETRY), r


def test_fixed_stall_falls_back_to_dynamic():
    """After purple_fixed_timeout_sec with no progress, switch to dynamic."""
    from positions import PositionStore, MODE_FIXED, MODE_DYNAMIC
    from base import Phase
    from pipeline.exceptions_reg import build_default_registry
    from pipeline import PipelineContext
    from pipeline.result import StageStatus

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.phase = Phase.ENTER_CREDENTIALS
    bot.cfg["purple_fixed_timeout_sec"] = 1.0
    bot.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed", "purple_fixed_timeout_sec": 1.0})
    assert bot.positions.purple_mode == MODE_FIXED
    # Bind real helpers from Bot if FakeBotBase lacks them — patch methods
    from base import Bot
    bot._purple_fixed_progress_key = lambda: Bot._purple_fixed_progress_key(bot)
    bot._purple_fixed_timeout_sec = lambda: Bot._purple_fixed_timeout_sec(bot)
    bot._arm_purple_fixed_watch = lambda: Bot._arm_purple_fixed_watch(bot)
    bot._purple_fixed_stalled = lambda: Bot._purple_fixed_stalled(bot)
    bot._fallback_purple_to_dynamic = (
        lambda reason="": Bot._fallback_purple_to_dynamic(bot, reason))
    bot._maybe_fallback_purple_dynamic = (
        lambda reason="": Bot._maybe_fallback_purple_dynamic(bot, reason))
    bot._purple_fixed_watch_at = 0.0
    bot._purple_fixed_progress = None
    bot._purple_fixed_fallback_done = False

    bot._arm_purple_fixed_watch()
    assert not bot._purple_fixed_stalled()
    bot._purple_fixed_watch_at -= 2.0  # simulate stall
    assert bot._purple_fixed_stalled()
    assert bot._maybe_fallback_purple_dynamic(reason="unit")
    assert bot.positions.purple_mode == MODE_DYNAMIC
    assert bot._purple_fixed_fallback_done

    # Exception rule also handles stall for S2
    bot2 = FakeBotBase()
    bot2.purple = FakeWin(1642, 1026)
    bot2.phase = Phase.ENTER_CREDENTIALS
    bot2.cfg["purple_fixed_timeout_sec"] = 1.0
    bot2.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed"})
    bot2._purple_fixed_stalled = lambda: True
    bot2._fallback_purple_to_dynamic = lambda reason="": setattr(
        bot2.positions, "purple_mode", MODE_DYNAMIC) or True
    bot2._purple_fixed_fallback_done = False
    reg = build_default_registry()
    ctx = PipelineContext(bot=bot2, cfg=bot2.cfg, lang_policy="L0")
    r = reg.dispatch(ctx, "S2", {"stage_id": "S2", "purple_fixed_stalled": True})
    assert r is not None and r.status == StageStatus.HANDLED, r
    assert bot2.positions.purple_mode == MODE_DYNAMIC


def test_s0_requires_password_and_freezes_dict():
    from pipeline.stages.s0_preflight import PreflightStage
    from pipeline import PipelineContext
    from pipeline.result import StageStatus
    from positions import PositionStore

    bot = FakeBotBase()
    bot.password = ""
    ctx = PipelineContext(bot=bot, cfg=bot.cfg, lang_policy="L0")
    r = PreflightStage().run(ctx)
    assert r.status == StageStatus.FAILED

    bot.password = "x"
    bot.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "dynamic", "position_dict_writable": True})
    assert bot.positions.writable is True
    ctx = PipelineContext(bot=bot, cfg={"require_interception": True},
                          lang_policy="L0")
    r = PreflightStage().run(ctx)
    assert r.status == StageStatus.OK, r
    assert bot.positions.writable is False


def test_auth_cap_and_toast_handlers():
    from pipeline.exceptions_reg import build_default_registry
    from pipeline import PipelineContext
    from pipeline.result import StageStatus

    bot = FakeBotBase()
    bot.dismissed = False

    def dismiss():
        bot.dismissed = True
        return True

    bot.dismiss_launcher_toast = dismiss
    ctx = PipelineContext(bot=bot, cfg={})
    reg = build_default_registry()

    h = reg.dispatch(ctx, "S3", {"stage_id": "S3", "launcher_toast": True})
    assert h.status == StageStatus.HANDLED
    assert bot.dismissed is True

    ctx.auth_relaunch_used = True
    f = reg.dispatch(ctx, "S5", {"stage_id": "S5", "auth_choice": True})
    assert f.status == StageStatus.FAILED


def test_gameflow_l0_disables_lang_auto():
    # Mirror GameFlow.__init__ policy without needing a real window
    for policy, expect_auto in (("L0", False), ("", True), ("L1", True)):
        p = str(policy or "").strip().upper()
        auto = p not in ("L0", "LOCK", "FIXED")
        assert auto is expect_auto, (policy, auto)


def test_s5_auth_repeat_snapshot():
    from pipeline.stages.s5_game_login import GameLoginStage
    from pipeline import PipelineContext

    bot = FakeBotBase()
    bot._auth_relaunch_count = 2
    bot._auth_relaunch_used = True

    class Flow:
        state = "PURPLE_AUTH"
        done = False
        error = None
        restart_requested = False

    bot.flow = Flow()
    ctx = PipelineContext(bot=bot, cfg={"auth_relaunch_max": 2},
                          auth_relaunch_used=True, auth_relaunch_count=2)
    snap = GameLoginStage().snapshot(ctx)
    assert snap["auth_choice"] is True


def test_purple_screen_classify():
    from purple_state import PurpleScreen, classify_blob, fingerprint_changed

    assert classify_blob("ID or E-mail  Next  Keep me signed in  QR code") \
        == PurpleScreen.LOGIN_EMAIL
    assert classify_blob("用户名/电子邮箱 下一步") == PurpleScreen.LOGIN_EMAIL
    assert classify_blob("電子郵件 密碼 保持登錄狀態 登錄 免費註冊 二維碼登錄") \
        == PurpleScreen.LOGIN_EMAIL
    assert classify_blob("Email  Password  Keep me signed in") \
        == PurpleScreen.LOGIN_EMAIL
    assert classify_blob("Password  Login  Reset Password  Another account") \
        == PurpleScreen.LOGIN_PASSWORD
    assert classify_blob("Logging in") == PurpleScreen.LOGGING_IN
    assert classify_blob("登录中") == PurpleScreen.LOGGING_IN
    assert classify_blob("我的游戏  安装的游戏  Lineage Classic") \
        == PurpleScreen.LAUNCHER
    assert classify_blob("Lineage Classic  运行游戏  游戏设置") \
        == PurpleScreen.START_READY
    assert classify_blob("Username or password is incorrect") \
        == PurpleScreen.LOGIN_ERROR
    assert classify_blob("") == PurpleScreen.UNKNOWN
    assert classify_blob("please wait") == PurpleScreen.UNKNOWN
    # Unknown must never look like a login click target
    assert classify_blob("random chrome") not in (
        PurpleScreen.LOGIN_EMAIL, PurpleScreen.LOGIN_PASSWORD)

    a = bytes([0] * 100)
    b = bytes([1] * 100)
    assert fingerprint_changed(a, b, min_bits=70)
    assert not fingerprint_changed(a, a, min_bits=70)


def test_unknown_screen_does_not_click():
    from pipeline.exceptions_reg import build_default_registry
    from pipeline import PipelineContext
    from pipeline.result import StageStatus

    ctx = PipelineContext(bot=FakeBotBase(), cfg={})
    reg = build_default_registry()
    r = reg.dispatch(ctx, "S3", {"stage_id": "S3", "purple_screen": "unknown"})
    assert r is not None and r.status == StageStatus.BLOCKED, r
    assert "no click" in (r.message or "").lower() or "unclassified" in (
        r.message or "").lower()
    # S2 must still run so saved-ratio login can fire when OCR is empty.
    r2 = reg.dispatch(ctx, "S2", {"stage_id": "S2", "purple_screen": "unknown"})
    assert r2 is None, r2


def test_login_form_on_s3_jumps_to_s2():
    from pipeline.exceptions_reg import build_default_registry
    from pipeline import PipelineContext
    from pipeline.result import StageStatus
    from base import Phase

    bot = FakeBotBase()
    bot.phase = Phase.FIND_LINEAGE
    bot._set_phase = lambda p: setattr(bot, "phase", p)
    ctx = PipelineContext(bot=bot, cfg={}, purple_logged_in=True)
    reg = build_default_registry()
    r = reg.dispatch(ctx, "S3", {"stage_id": "S3", "login_form": True})
    assert r is not None
    assert r.status == StageStatus.HANDLED
    assert r.next_stage_id == "S2"
    assert ctx.purple_logged_in is False
    assert bot.phase == Phase.WAIT_LOGIN_FORM


def test_gated_login_waits_for_password_screen():
    """_fixed_purple_login must not click password while still on email form."""
    from base import Bot, Phase
    from purple_state import PurpleView, PurpleScreen
    from positions import PositionStore

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.phase = Phase.ENTER_CREDENTIALS
    bot.cfg = {"purple_gate_clicks": True, "lang_policy": "L0"}
    bot.username = "u@test.com"
    bot.password = "secret"
    bot.dry_run = True
    bot._email_entered = False
    bot._password_entered = False
    bot.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed", "lang_policy": "L0",
             "position_dict_writable": False})
    clicks = []

    def _view(force=False, img=None, blob=None):
        return PurpleView(screen=PurpleScreen.LOGIN_EMAIL, blob="ID or E-mail Next")

    def _click(key, expected=None, cef=False, allow_fixed=True):
        clicks.append(key)
        return True

    def _wait(screens, timeout=6.0, interval=0.22):
        return PurpleView(screen=PurpleScreen.LOGIN_EMAIL, blob="still email")

    bot._read_purple_view = _view
    bot._gated_purple_click = _click
    bot._wait_purple_screens = _wait
    bot._paste_once = lambda text, kind: True
    bot._set_phase = lambda p: setattr(bot, "phase", p)
    bot._mark_purple_logged_in = lambda: setattr(bot, "_purple_logged_in", True)
    bot._enter_email_then_next = Bot._enter_email_then_next.__get__(bot, Bot)
    bot._email_ready_for_next = Bot._email_ready_for_next.__get__(bot, Bot)
    bot._normalize_purple_shell_size = lambda reason="": True
    bot._login_template_dir = lambda: os.path.join(BOT, "data", "purple")
    bot._purple_watcher = lambda: type("W", (), {"templates": type("T", (), {"reload": lambda self: None})()})()
    bot._ensure_login_email_templates = lambda force=False: True
    bot._template_click_login = lambda key, cef=True: clicks.append(key) or True
    bot._maybe_click_email_tab = lambda: False
    bot._click_email_next = lambda: clicks.append("purple_next") or True
    Bot._fixed_purple_login(bot)
    assert "purple_address" not in clicks, clicks
    assert "purple_password" not in clicks, clicks
    assert "purple_login" not in clicks, clicks
    assert "purple_id_field" in clicks, clicks
    assert "purple_next" in clicks, clicks
    assert clicks.index("purple_id_field") < clicks.index("purple_next"), clicks
    assert clicks[0] == "purple_id_field", clicks


def test_email_next_requires_paste():
    """Next must not fire when the email paste did not land."""
    from base import Bot, Phase
    from purple_state import PurpleView, PurpleScreen

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.phase = Phase.ENTER_CREDENTIALS
    bot.username = "u@test.com"
    bot.dry_run = True
    bot._email_entered = False
    clicks = []

    bot._read_purple_view = lambda force=False, img=None, blob=None: PurpleView(
        screen=PurpleScreen.LOGIN_EMAIL, blob="ID or E-mail Next")
    bot._normalize_purple_shell_size = lambda reason="": True
    bot._login_template_dir = lambda: os.path.join(BOT, "data", "purple")
    bot._purple_watcher = lambda: type(
        "W", (), {"templates": type("T", (), {"reload": lambda self: None})()}
    )()
    bot._ensure_login_email_templates = lambda force=False: True
    bot._template_click_login = lambda key, cef=True: clicks.append(key) or True
    bot._paste_once = lambda text, kind: False
    bot._email_ready_for_next = lambda: True
    bot._click_email_next = lambda: clicks.append("purple_next") or True
    bot._enter_combined_login = lambda: clicks.append("combined")
    Bot._enter_email_then_next(bot)
    assert "purple_id_field" in clicks, clicks
    assert "purple_next" not in clicks, clicks
    assert "combined" not in clicks, clicks
    assert bot._email_entered is False


def test_email_next_blocked_when_field_empty():
    """Placeholder still on the form must not submit Next."""
    from base import Bot, Phase
    from purple_state import PurpleView, PurpleScreen

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.phase = Phase.ENTER_CREDENTIALS
    bot.username = "u@test.com"
    bot.dry_run = False
    bot._email_entered = False
    clicks = []

    bot._read_purple_view = lambda force=False, img=None, blob=None: PurpleView(
        screen=PurpleScreen.LOGIN_EMAIL, blob="ID or E-mail Next")
    bot._normalize_purple_shell_size = lambda reason="": True
    bot._login_template_dir = lambda: os.path.join(BOT, "data", "purple")
    bot._purple_watcher = lambda: type(
        "W", (), {"templates": type("T", (), {"reload": lambda self: None})()}
    )()
    bot._ensure_login_email_templates = lambda force=False: True
    bot._template_click_login = lambda key, cef=True: clicks.append(key) or True
    bot._paste_once = lambda text, kind: True
    bot._email_ready_for_next = lambda: False
    bot._click_email_next = lambda: clicks.append("purple_next") or True
    bot._enter_combined_login = lambda: clicks.append("combined")
    Bot._enter_email_then_next(bot)
    assert "purple_next" not in clicks, clicks
    assert "combined" not in clicks, clicks
    assert bot._email_entered is False


def test_address_coords_must_not_click_next():
    """Saved Address tab must not fire when it sits on the Next button."""
    from base import Bot
    from positions import PositionStore

    bot = FakeBotBase()
    bot.purple = FakeWin(1642, 1026)
    bot.positions = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"purple_click_mode": "fixed", "lang_policy": "L0",
             "position_dict_writable": False})
    bot.cfg = {}
    bot._purple_saved_xy = Bot._purple_saved_xy.__get__(bot, Bot)
    bot._address_collides_with_next = Bot._address_collides_with_next.__get__(bot, Bot)
    assert bot._address_collides_with_next() is True
    bot._template_click_login = lambda key, cef=True: False
    bot._maybe_click_email_tab = Bot._maybe_click_email_tab.__get__(bot, Bot)
    assert bot._maybe_click_email_tab() is False


def test_harvest_login_email_templates():
    import tempfile
    import numpy as np
    from purple_state import harvest_login_email_templates

    img = np.full((1026, 1642, 3), 245, dtype=np.uint8)
    # Blue Next in the login-card lower area (BGR)
    img[430:472, 700:960] = (220, 90, 40)
    tmp = tempfile.mkdtemp(prefix="purple_tpl_")
    written = harvest_login_email_templates(img, tmp)
    assert "next" in written, written
    assert "id_field" in written, written
    assert "address_tab" in written, written


def test_first_step_template_match_locates_controls():
    """Harvested crops must locate Next / email field on the same image."""
    import tempfile
    import numpy as np
    from purple_state import harvest_login_email_templates, PurpleTemplates

    img = np.full((1026, 1642, 3), 245, dtype=np.uint8)
    img[430:472, 700:960] = (220, 90, 40)
    tmp = tempfile.mkdtemp(prefix="purple_tpl_")
    written = harvest_login_email_templates(img, tmp)
    assert "next" in written and "id_field" in written, written
    tpls = PurpleTemplates(tmp)
    hit_next = tpls.match(img, ("next", "next_btn"), thresh=0.72,
                          roi=(0.22, 0.12, 0.78, 0.72))
    hit_id = tpls.match(img, ("id_field", "email_field"), thresh=0.72,
                        roi=(0.22, 0.12, 0.78, 0.72))
    assert hit_next is not None, "Next template miss"
    assert hit_id is not None, "email field template miss"
    assert abs(hit_next.cx - 830) < 90, hit_next
    assert hit_id.cy < hit_next.cy, (hit_id.cy, hit_next.cy)


def live_probe():
    """Optional: see if a real Purple shell is attachable right now."""
    print("\n--- live probe ---")
    try:
        from base import Bot
    except Exception as e:
        print("skip live (import):", e)
        return
    # Minimal: only exercise attach helpers without full Bot.__init__
    # which needs config. Use WindowFinder via a throwaway if config exists.
    cfg = os.path.join(BOT, "purple_login.json")
    if not os.path.isfile(cfg):
        print("skip live: no purple_login.json")
        return
    try:
        # Avoid full login run — just construct and attach
        bot = Bot.__new__(Bot)
        bot.cfg = {"lang_policy": "L0"}
        bot.purple = None
        bot._purple_logged_in = False
        # Bind real methods
        bot._purple_pids = Bot._purple_pids.__get__(bot, Bot)
        bot._purple_process_running = Bot._purple_process_running.__get__(bot, Bot)
        bot._any_purple_window_exists = Bot._any_purple_window_exists.__get__(bot, Bot)
        bot._restore_hidden_purple = Bot._restore_hidden_purple.__get__(bot, Bot)
        bot._try_attach_running_purple = Bot._try_attach_running_purple.__get__(bot, Bot)
        # Need _find_purple_window / find_main_launcher — may fail without full init
        running = bot._purple_process_running()
        print("Purple process running:", running)
        if running:
            # Full Bot init is safer for attach
            pass
    except Exception as e:
        print("live process check error:", repr(e))

    try:
        from bot2 import Bot2
        b = Bot2(cfg)
        attached = bool(b.purple and b.purple.valid)
        w = b.purple.rect.width if attached else 0
        print("Bot2 attach: valid=%s width=%s phase=%s logged_in=%s" % (
            attached, w, getattr(b.phase, "name", b.phase),
            getattr(b, "_purple_logged_in", None)))
        store = getattr(b, "positions", None)
        if store:
            print("positions purple_mode=%s writable=%s id_field=%s" % (
                store.purple_mode, store.writable,
                bool(store.lookup("purple", "purple_id_field"))))
        print("cfg lang_policy=%s use_pipeline=%s" % (
            b.cfg.get("lang_policy"), b.cfg.get("use_pipeline")))
    except Exception as e:
        print("live Bot2 probe failed:", repr(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="also probe running Purple via Bot2")
    args = ap.parse_args()

    check("S1 missing launches once (no double)", test_s1_missing_launches_once)
    check("S1 tiny shell blocks via exception", test_s1_tiny_shell_blocks_not_launch)
    check("S1 login card is usable", test_s1_login_card_is_usable)
    check("S1 wide shell OK", test_s1_wide_shell_ok)
    check("wrong_purple ignores missing", test_wrong_purple_ignores_missing)
    check("ratio scale + read-only dict", test_ratio_scale_accuracy)
    check("S2 uses fixed when shell forced", test_s2_uses_fixed_when_shell_forced)
    check("fixed stall falls back to dynamic", test_fixed_stall_falls_back_to_dynamic)
    check("S0 password + freeze dict", test_s0_requires_password_and_freezes_dict)
    check("toast / AUTH exception handlers", test_auth_cap_and_toast_handlers)
    check("GameFlow L0 lang_auto policy", test_gameflow_l0_disables_lang_auto)
    check("S5 AUTH repeat snapshot", test_s5_auth_repeat_snapshot)
    check("Purple screen classify", test_purple_screen_classify)
    check("unknown Purple screen blocks clicks", test_unknown_screen_does_not_click)
    check("login form on S3 jumps to S2", test_login_form_on_s3_jumps_to_s2)
    check("gated login waits for password screen", test_gated_login_waits_for_password_screen)
    check("email Next requires paste", test_email_next_requires_paste)
    check("email Next blocked when field empty", test_email_next_blocked_when_field_empty)
    check("Address coords must not click Next", test_address_coords_must_not_click_next)
    check("harvest login email templates", test_harvest_login_email_templates)
    check("first-step template match locates controls",
          test_first_step_template_match_locates_controls)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    if args.live:
        live_probe()
    if FAIL:
        for name, e in FAIL:
            print(" -", name, ":", e)
        sys.exit(1)
    print("ALL ACCURACY CHECKS PASSED")


if __name__ == "__main__":
    main()
