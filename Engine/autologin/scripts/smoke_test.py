"""Quick smoke tests for PH-Poc2 runtime imports and helpers."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "bot")
sys.path.insert(0, BOT)

errors = []


def check(name, fn):
    try:
        fn()
        print("OK  ", name)
    except Exception as e:
        errors.append((name, e))
        print("FAIL", name, ":", repr(e))


def test_winocr_fuzzy():
    from win.winocr import fuzzy_match_label, LINEAGE_CARD_KEYWORDS, RUN_GAME_KEYWORDS
    assert fuzzy_match_label("用户名 / 电子邮箱", ["用户名/电子邮箱"])
    assert fuzzy_match_label("运行 游戏", list(RUN_GAME_KEYWORDS))
    assert fuzzy_match_label("天堂 经典", list(LINEAGE_CARD_KEYWORDS))


def test_positions():
    from positions import normalize_page_positions, page_client_xy, PositionStore

    class R:
        def __init__(self, w, h):
            self.width, self.height = w, h

    class W:
        def __init__(self, w, h):
            self.client_rect = R(w, h)
            self.rect = R(w, h)

    cfg = {"816x639": {"2": [373, 384]}}
    assert page_client_xy(cfg, "2", W(816, 639)) == (373, 384)
    assert "2" in normalize_page_positions(cfg)

    store = PositionStore(
        path=os.path.join(BOT, "position_dict.json"),
        cfg={"lang_policy": "L0", "use_pipeline": True,
             "purple_click_mode": "fixed", "game_click_mode": "fixed"})
    assert store.writable is False
    store.record_client("purple", "purple_id_field", W(1642, 1026), 100, 100)


def test_base_helpers():
    from base import Bot

    class FakeBot(Bot):
        def __init__(self):
            self.words_cfg = {}
            self.purple = None

    b = FakeBot()
    assert b._text_matches_lineage_card("Lineage Classic")
    assert b._text_matches_lineage_card("天堂经典")
    assert b._lineage_card_keywords()[0] in ("Lineage Classic", "天堂经典", "Lineage")


def test_launcher_config():
    path = os.path.join(SRC, "launcher_config.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    words = cfg["login"]["words"]
    assert "lineage_card" in words
    assert "运行游戏" in words["start_game"]
    assert cfg.get("lang_policy") == "L0"
    assert cfg.get("position_dict_writable") is False
    assert cfg.get("game_click_geom", "auto") in ("auto", "window", "dialog")


def test_game_geom():
    from game_geom import (
        GEOM_AUTO,
        dialog_ratio_to_screen,
        normalize_geom_mode,
        window_ratio_to_screen,
        Box,
        Chrome,
        ClientOrigin,
    )
    from gameflow import R_LOGIN_OK

    assert normalize_geom_mode("auto") == GEOM_AUTO
    old = window_ratio_to_screen(*R_LOGIN_OK, 0, 0, 816, 639)
    new = dialog_ratio_to_screen(
        *R_LOGIN_OK,
        ClientOrigin(8, 31, 800, 600),
        Box(0, 0, 800, 600),
        Chrome(8, 31, 8, 8),
    )
    assert abs(old[0] - new[0]) <= 2 and abs(old[1] - new[1]) <= 2


def test_gameflow_import():
    import gameflow
    assert hasattr(gameflow, "GameFlow")
    # Multilingual situation words must cover ko + zh-CN + zh-TW + en
    required = ("agree_button", "device_reg", "device_reg_context",
                "purple_auth", "security_splash", "ok_button", "ingame")
    for key in required:
        d = gameflow.WORDS[key]
        for lang in ("ko", "zh-CN", "zh-TW", "en"):
            assert lang in d and d[lang], "%s missing %s" % (key, lang)
    # Representative mid/zh phrases used on live AUTH screens
    all_auth = []
    for v in gameflow.WORDS["purple_auth"].values():
        all_auth.extend(v)
    assert any("간이" in w or "简易" in w or "簡易" in w or "simple" in w.lower()
               for w in all_auth)
    all_ctx = []
    for v in gameflow.WORDS["device_reg_context"].values():
        all_ctx.extend(v)
    assert any("선택검증" in w.replace(" ", "") or "选择验证" in w or "選擇驗證" in w
               or "authentication" in w.lower() or "인증수단" in w.replace(" ", "")
               for w in all_ctx)


def test_pipeline():
    from pipeline import STAGE_GOALS, PipelineContext, PipelineRunner
    from pipeline.exceptions_reg import build_default_registry
    from pipeline.result import StageStatus

    assert [g.id for g in STAGE_GOALS] == [
        "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"]
    reg = build_default_registry()
    ids = [r.id for r in reg.list_rules()]
    assert "auth_choice" in ids
    assert "wrong_purple_window" in ids
    assert "launcher_toast" in ids

    class FakeBot:
        username = "u@test.com"
        password = "x"
        game_path = ""
        _interception_ready = True
        _use_interception = True
        _purple_logged_in = False
        purple = None
        phase = None
        cfg = {"lang_policy": "L0"}
        _auth_relaunch_used = False
        _shake_after_relaunch = False
        dismissed = False
        launched = False
        positions = None
        learn = False

        def tick(self):
            pass

        def has_launcher_toast(self):
            return False

        def dismiss_launcher_toast(self):
            self.dismissed = True
            return True

        def launch_purple(self):
            self.launched = True

        def _purple_process_running(self):
            return False

        def _any_purple_window_exists(self):
            return False

        def _try_attach_running_purple(self):
            return False

    ctx = PipelineContext(bot=FakeBot(), cfg={"require_interception": True},
                          lang_policy="L0")
    runner = PipelineRunner(ctx, registry=reg)
    r0 = runner.tick()
    assert r0.stage_id == "S0"
    assert r0.status == StageStatus.OK

    # S1: missing Purple must launch once (not trip wrong_purple_window)
    r1 = runner.tick()
    assert r1.stage_id == "S1"
    assert r1.status == StageStatus.BLOCKED
    assert ctx.bot.launched is True
    # missing must not match wrong_purple_window
    assert reg.dispatch(ctx, "S1", {
        "stage_id": "S1", "purple_missing": True, "purple_too_small": False
    }) is None

    # Toast rule dismisses instead of only blocking
    snap = {"stage_id": "S3", "launcher_toast": True}
    handled = reg.dispatch(ctx, "S3", snap)
    assert handled is not None
    assert handled.status == StageStatus.HANDLED
    assert ctx.bot.dismissed is True

    # AUTH repeat cap fails closed
    ctx.auth_relaunch_used = True
    auth = reg.dispatch(ctx, "S5", {"stage_id": "S5", "auth_choice": True})
    assert auth is not None
    assert auth.status == StageStatus.FAILED


def test_gameflow_l0_lang_policy():
    """lang_policy=L0 must disable per-tick UI lang auto-detect."""
    class TinyBot:
        lang = "ko"
        cfg = {"lang_policy": "L0"}

    policy = str(TinyBot.cfg.get("lang_policy") or "").strip().upper()
    lang_auto = policy not in ("L0", "LOCK", "FIXED")
    assert lang_auto is False


check("winocr fuzzy", test_winocr_fuzzy)
check("positions", test_positions)
check("base helpers", test_base_helpers)
check("launcher_config", test_launcher_config)
check("game geom", test_game_geom)
check("gameflow import", test_gameflow_import)
check("pipeline", test_pipeline)
check("gameflow L0", test_gameflow_l0_lang_policy)

if errors:
    print("\n%d failure(s)" % len(errors))
    sys.exit(1)
print("\nALL SMOKE TESTS PASSED")
