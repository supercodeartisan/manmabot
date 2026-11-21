"""Non-interactive regression tests; never launch a game or open a driver."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT.parent / "login"))

from base import Phase
from gameflow import GameFlow
from pipeline.context import PipelineContext
from pipeline.result import StageStatus
from pipeline.stages.s1_window_gate import WindowGateStage
from pipeline.stages.s3_start_game import StartGameStage
from pipeline.stages.s5_game_login import GameLoginStage
from purple.engine import PurpleEngine
from purple.handoff import apply_handoff
from config import load_config
from win import interception


class InputRegressionTests(unittest.TestCase):
    def test_driver_constants_match_interception_header(self):
        self.assertEqual(interception._STATE_WHEEL, 0x400)
        self.assertEqual(interception._STATE_RIGHT_BUTTON_UP, 0x008)
        self.assertEqual(interception._STATE_MIDDLE_BUTTON_UP, 0x020)

    def test_neutralize_never_sends_right_button_down(self):
        states = []
        with patch.object(interception, "_ctx", 1), \
             patch.object(interception, "_lib", object()), \
             patch.object(interception, "_mouse_device", 11), \
             patch.object(interception, "_cursor_pos", return_value=(100, 100)), \
             patch.object(interception, "_send", side_effect=lambda state, x, y: states.append(state)), \
             patch.object(interception, "key_up"):
            interception.neutralize()
        self.assertEqual(states, [0x002, 0x008, 0x020])
        self.assertTrue(all(not state & 0x004 for state in states))


class AuthRegressionTests(unittest.TestCase):
    def test_late_shake_rejected_after_server_selection(self):
        flow = GameFlow.__new__(GameFlow)
        flow.bot = SimpleNamespace(_shake_after_relaunch=True, game=None)
        flow.state = "SERVER_SELECT"
        flow._boot_shake_done = False
        flow._boot_hunt_expired = True
        flow._security_passed = True
        flow._agreement_seen = True
        flow._match_boot_shake_status = Mock()
        self.assertFalse(flow._maybe_post_relaunch_boot_shake("test", object()))
        flow._match_boot_shake_status.assert_not_called()

    def test_boot_shake_rejects_server_dialog_false_positive(self):
        flow = GameFlow.__new__(GameFlow)
        flow.bot = SimpleNamespace(_shake_after_relaunch=True, game=None)
        flow.state = "SECURITY"
        flow._boot_shake_done = False
        flow._boot_hunt_expired = False
        flow._security_passed = False
        flow._agreement_seen = False
        flow._boot_hunt_since = 0
        flow._shell_is_familiar = Mock(return_value=True)
        flow._match_boot_shake_status = Mock(return_value={"score": 0.723, "kind": "security", "name": "x", "w": 10, "h": 10, "scale": 1.0})
        flow._match_anchor = Mock(side_effect=lambda img, name:
                                  {"score": 0.9} if name == "server_title" else None)
        flow._shake_game_window = Mock()
        self.assertFalse(flow._maybe_post_relaunch_boot_shake("test", object()))
        flow._shake_game_window.assert_not_called()

    def test_auth_detected_after_boot_hunt_even_when_shake_armed(self):
        flow = GameFlow.__new__(GameFlow)
        flow.bot = SimpleNamespace(_shake_after_relaunch=True)
        flow._boot_shake_done = False
        flow._boot_hunt_since = 0
        flow._boot_hunt_expired = True
        flow._security_passed = False
        flow._buttons_en_only = False
        flow._char_login_committed = Mock(return_value=False)
        flow._match_boot_shake_status = Mock(return_value=None)
        flow._match_anchor = Mock(return_value=None)
        flow._auth_choice_screen = Mock(return_value=True)
        flow._purple_auth_screen = Mock(return_value=False)
        self.assertEqual(flow._detect(object()), "PURPLE_AUTH")

    def test_relaunch_remains_bounded_when_armed(self):
        flow = GameFlow.__new__(GameFlow)
        flow.bot = SimpleNamespace(_shake_after_relaunch=False, _set_phase=Mock())
        flow._restart_requested = False
        flow._auth_choice_screen = Mock(return_value=True)
        flow._purple_auth_screen = Mock(return_value=False)
        flow._auth_relaunch_exhausted = Mock(return_value=True)
        flow._auth_relaunch_max = Mock(return_value=2)
        flow.error = None
        flow._h_purple_auth(object())
        self.assertIn("budget", flow.error)
        flow.bot._set_phase.assert_called_once_with(Phase.ERROR)

    def test_shake_disarm_not_rearmed_by_pipeline(self):
        bot = SimpleNamespace(phase=Phase.GAME_LOGIN, _shake_after_relaunch=True,
                              _auth_relaunch_count=1, _auth_relaunch_used=False,
                              cfg={}, flow=SimpleNamespace(state="SECURITY", error=None, done=False))
        bot.tick = lambda: setattr(bot, "_shake_after_relaunch", False)
        ctx = PipelineContext(bot=bot, shake_armed=True)
        result = GameLoginStage().run(ctx)
        self.assertEqual(result.status, StageStatus.RETRY)
        self.assertFalse(ctx.shake_armed)
        self.assertFalse(bot._shake_after_relaunch)

    def test_v2_auth_restart_uses_v2_launcher(self):
        bot = SimpleNamespace(phase=Phase.FIND_LINEAGE, game=None)
        ctx = PipelineContext(bot=bot, cfg={"purple_engine": "v2"}, shake_armed=True)
        engine = SimpleNamespace(state="GAME_READY")
        with patch("purple.facade.run_v2_engine", return_value=engine) as run, \
             patch("purple.handoff.engine_succeeded", return_value=True):
            result = StartGameStage().run(ctx)
        self.assertEqual(result.status, StageStatus.OK)
        run.assert_called_once()

    def test_s1_auth_relaunch_skips_full_engine_when_hwnd_ready(self):
        bot = SimpleNamespace(
            _shake_after_relaunch=True,
            _game_window_ready=lambda: True,
            game=SimpleNamespace(valid=True),
            _set_phase=Mock(),
            find_game=Mock(),
            _prepare_game_foreground=Mock(return_value=True),
        )
        ctx = PipelineContext(
            bot=bot, cfg={"purple_engine": "v2"}, shake_armed=True)
        with patch("purple.facade.run_v2_engine") as run:
            result = WindowGateStage().run(ctx)
        run.assert_not_called()
        self.assertEqual(result.status, StageStatus.OK)
        self.assertIn("AUTH relaunch", result.message)
        self.assertTrue(bot._shake_after_relaunch)
        self.assertTrue(ctx.shake_armed)

    def test_handoff_preserves_shake_arm(self):
        bot = SimpleNamespace(
            _shake_after_relaunch=True,
            game=SimpleNamespace(valid=True),
            find_game=Mock(),
            _prepare_game_foreground=Mock(return_value=True),
            _set_phase=Mock(),
        )
        ctx = PipelineContext(bot=bot, shake_armed=True)
        apply_handoff(bot, ctx, engine=None)
        self.assertTrue(bot._shake_after_relaunch)
        self.assertTrue(ctx.shake_armed)
        self.assertTrue(bot._purple_logged_in)

    def test_engine_game_ready_is_nonblocking_single_poll(self):
        eng = PurpleEngine.__new__(PurpleEngine)
        with patch.object(eng, "_game_hwnd_visible", return_value=False) as vis:
            t0 = __import__("time").time()
            self.assertFalse(eng._game_ready())
            self.assertLess(__import__("time").time() - t0, 0.5)
            vis.assert_called_once()


class ManmabotConfigTests(unittest.TestCase):
    def test_launcher_config_defaults_v2(self):
        path = ROOT / "launcher_config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("purple_engine"), "v2")
        self.assertEqual(cfg["login"].get("purple_engine"), "v2")
        self.assertTrue(cfg.get("use_pipeline", True))

    def test_build_transient_config_keeps_purple_engine_v2(self):
        from autologin_service import AutoLoginRequest, build_transient_config

        template = json.loads((ROOT / "launcher_config.json").read_text(encoding="utf-8"))
        req = AutoLoginRequest(
            user_id="test@example.com",
            password="secret",
            language="ko",
            server="데컨",
            character_number=1,
            click_mode="fixed",
        )
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            # Avoid DPAPI in CI/non-interactive: stub protect
            cfg_path = build_transient_config(
                ROOT, run_dir, req, template, assets={},
                protect=lambda s: "enc:" + s,
            )
            login = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(login["purple_engine"], "v2")
        self.assertTrue(login["use_pipeline"])
        self.assertEqual(login["words"]["server_name"], ["데컨"])
        self.assertEqual(login["userID"], "test@example.com")
        self.assertIn("password_enc", login)
        self.assertNotIn("password", login)


class CanonicalConfigTests(unittest.TestCase):
    def test_canonical_v2_config_loads_as_legacy_compatible_schema(self):
        path = ROOT / "bot" / "configs" / "purple_login.v2.json"
        cfg = load_config(str(path))
        self.assertEqual(cfg["purple_engine"], "v2")
        self.assertTrue(cfg["use_pipeline"])
        self.assertEqual(cfg["words"]["server_name"], ["데컨"])
        dll = Path(cfg["interception_dll"])
        if not dll.is_absolute():
            dll = (ROOT / "bot" / dll).resolve()
        self.assertTrue(dll.is_file(), "missing %s" % dll)
        self.assertNotIn("password_enc", cfg)
        self.assertEqual(cfg.get("password", ""), "")


class PurpleGameCardTests(unittest.TestCase):
    def setUp(self):
        self.engine = PurpleEngine.__new__(PurpleEngine)
        self.engine.contract = SimpleNamespace(
            element=lambda state, seed: {"automation_id": "리니지 클래식"})
        self.row = {"hwnd": 123}

    def test_localized_chinese_card(self):
        node = {"ct": "ListItemControl", "aid": "天堂 : 經典版", "name": "NGPClient.Models.GameCard.GameCardItem",
                "onscreen": True, "enabled": True}
        self.assertEqual(self.engine._find_game_card([(self.row, "launcher", {}, [node])]),
                         (self.row, node))

    def test_ambiguous_cards_are_not_clicked(self):
        nodes = [{"ct": "ListItemControl", "aid": title, "name": "",
                  "onscreen": True, "enabled": True}
                 for title in ("天堂经典", "天堂經典")]
        self.assertIsNone(self.engine._find_game_card([(self.row, "launcher", {}, nodes)]))

    def test_similar_other_game_not_selected(self):
        node = {"ct": "ListItemControl", "aid": "天堂", "name": "",
                "onscreen": True, "enabled": True}
        self.assertIsNone(self.engine._find_game_card([(self.row, "launcher", {}, [node])]))


if __name__ == "__main__":
    unittest.main()
