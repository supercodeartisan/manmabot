from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import manmabot_v1.autologin_service as service


def make_install(root: Path, *, include_captcha: bool = True) -> None:
    bot = root / "bot"
    (bot / "win").mkdir(parents=True)
    (bot / "data" / "character").mkdir(parents=True)
    (bot / "bot2.py").write_text("# test entry\n", encoding="utf-8")
    for relative in (
        "win/interception.dll",
        "data/yolov8n.onnx",
        "data/recorded_clicks.json",
    ):
        path = bot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    if include_captcha:
        (bot / "data" / "f.onnx").write_bytes(b"x")
    purple = root / "Purple.exe"
    purple.write_bytes(b"x")
    (root / "launcher_config.json").write_text(json.dumps({
        "use_pipeline": True,
        "login": {
            "game_path": str(purple),
            "interception_dll": "win/interception.dll",
            "yolo_model": "data/yolov8n.onnx",
            "captcha_model": "data/f.onnx",
            "click_map": "data/recorded_clicks.json",
            "character_dir": "data/character",
        },
    }), encoding="utf-8")


class FinishedProcess:
    def __init__(self, code: int = 0):
        self.code = code

    def poll(self):
        return self.code

    def terminate(self):
        self.code = service.EXIT_CANCELLED


class CancelAwareProcess:
    def __init__(self, cancel_path: Path):
        self.cancel_path = cancel_path
        self.terminated = False

    def poll(self):
        if self.cancel_path.exists():
            return service.EXIT_CANCELLED
        return None

    def terminate(self):
        self.terminated = True


class HungProcess:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return service.EXIT_CANCELLED if self.terminated else None

    def terminate(self):
        self.terminated = True


class AutoLoginServiceTests(unittest.TestCase):
    def test_missing_captcha_model_is_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_install(root, include_captcha=False)
            request = service.AutoLoginRequest("user", "secret", "Server")
            _template, assets = service.validate_autologin(root, request)
            self.assertFalse(assets["captcha_model"].exists())

    def test_missing_required_asset_is_actionable_config_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_install(root)
            (root / "bot" / "data" / "yolov8n.onnx").unlink()
            request = service.AutoLoginRequest("user", "secret", "Server")
            with self.assertRaises(service.AutoLoginValidationError) as caught:
                service.validate_autologin(root, request)
            text = str(caught.exception)
            self.assertIn("yolo_model", text)
            self.assertIn("launcher_config.json", text)
            self.assertIn("yolov8n.onnx", text)

    def test_transient_config_contains_ciphertext_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            run_dir = Path(tmp) / "run"
            run_dir.mkdir(parents=True)
            make_install(root)
            request = service.AutoLoginRequest(
                "account@example.com", "plain-secret", "오렌", 2
            )
            template, assets = service.validate_autologin(root, request)
            path = service.build_transient_config(
                root, run_dir, request, template, assets,
                protect=lambda value: "encrypted-value",
            )
            raw = path.read_text(encoding="utf-8")
            config = json.loads(raw)
            self.assertNotIn("plain-secret", raw)
            self.assertNotIn("password", config)
            self.assertEqual(config["password_enc"], "encrypted-value")
            self.assertEqual(config["words"]["server_name"], ["오렌"])

    def test_selected_account_paths_override_template_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            make_install(root)
            selected_purple = Path(tmp) / "SelectedPurple.exe"
            selected_game = Path(tmp) / "LC.exe"
            selected_purple.write_bytes(b"x")
            selected_game.write_bytes(b"x")
            request = service.AutoLoginRequest(
                "account@example.com",
                "secret",
                "Server",
                purple_launcher_path=str(selected_purple),
                game_path=str(selected_game),
                click_mode="hybrid",
            )

            template, assets = service.validate_autologin(root, request)
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            config_path = service.build_transient_config(
                root,
                run_dir,
                request,
                template,
                assets,
                protect=lambda _value: "ciphertext",
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config["game_path"], str(selected_purple.resolve()))
            self.assertEqual(config["lineage_path"], str(selected_game.resolve()))
            self.assertEqual(config["click_mode"], "hybrid")

    def test_success_requires_real_game_readiness_and_cleans_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            userdata = Path(tmp) / "userdata"
            make_install(root)
            captured = {}

            def launch(_python, args, _cwd):
                config_path = Path(args[1])
                captured["config"] = json.loads(
                    config_path.read_text(encoding="utf-8")
                )
                result_path = Path(args[args.index("--result-path") + 1])
                result_path.write_text(json.dumps({
                    "exit_code": 0, "state": "success", "detail": ""
                }), encoding="utf-8")
                return FinishedProcess()

            with mock.patch.object(service, "USERDATA", userdata):
                runner = service.AutoLoginService(
                    root=root, game_ready=lambda: True, launcher=launch,
                    password_protector=lambda _value: "ciphertext",
                )
                result = runner.run(
                    service.AutoLoginRequest("user", "secret", "Server")
                )

            self.assertTrue(result.succeeded)
            self.assertFalse((result.run_dir / "autologin.json").exists())
            self.assertTrue((result.run_dir / "result.json").exists())
            self.assertEqual(captured["config"]["password_enc"], "ciphertext")

    def test_zero_exit_without_result_file_is_success_when_game_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            make_install(root)

            def launch(_python, _args, _cwd):
                return FinishedProcess(0)

            with mock.patch.object(service, "USERDATA", Path(tmp) / "userdata"):
                runner = service.AutoLoginService(
                    root=root, game_ready=lambda: True, launcher=launch,
                    password_protector=lambda _value: "ciphertext",
                )
                result = runner.run(
                    service.AutoLoginRequest("user", "secret", "Server")
                )
            self.assertTrue(result.succeeded)
            self.assertEqual(result.exit_code, service.EXIT_SUCCESS)

    def test_zero_exit_without_ready_lc_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            make_install(root)

            def launch(_python, args, _cwd):
                result_path = Path(args[args.index("--result-path") + 1])
                result_path.write_text(
                    '{"exit_code": 0, "state": "success"}', encoding="utf-8"
                )
                return FinishedProcess()

            with mock.patch.object(service, "USERDATA", Path(tmp) / "userdata"):
                runner = service.AutoLoginService(
                    root=root, game_ready=lambda: False, launcher=launch,
                    password_protector=lambda _value: "ciphertext",
                )
                result = runner.run(
                    service.AutoLoginRequest("user", "secret", "Server")
                )
            self.assertEqual(result.exit_code, service.EXIT_FAILED)
            self.assertFalse(result.succeeded)
            self.assertIn("LC.exe", result.detail)

    def test_cancellation_uses_run_marker_and_returns_130(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            make_install(root)
            captured = {}

            def launch(_python, args, _cwd):
                cancel_path = Path(args[args.index("--cancel-path") + 1])
                captured["process"] = CancelAwareProcess(cancel_path)
                return captured["process"]

            cancel = threading.Event()
            cancel.set()
            with mock.patch.object(service, "USERDATA", Path(tmp) / "userdata"):
                runner = service.AutoLoginService(
                    root=root, game_ready=lambda: False, launcher=launch,
                    password_protector=lambda _value: "ciphertext",
                )
                result = runner.run(
                    service.AutoLoginRequest("user", "secret", "Server"),
                    cancel_event=cancel,
                )

            self.assertEqual(result.exit_code, service.EXIT_CANCELLED)
            self.assertEqual(result.state, "cancelled")
            self.assertFalse(captured["process"].terminated)
            self.assertFalse((result.run_dir / "cancel").exists())
            persisted = json.loads(
                (result.run_dir / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["exit_code"], service.EXIT_CANCELLED)

    def test_hung_owned_process_is_terminated_as_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "autologin"
            make_install(root)
            process = HungProcess()

            with (
                mock.patch.object(service, "USERDATA", Path(tmp) / "userdata"),
                mock.patch.object(
                    service, "_SUPERVISOR_STARTUP_GRACE_SECONDS", 0.0
                ),
                mock.patch.object(service, "_TERMINATE_GRACE_SECONDS", 0.0),
            ):
                runner = service.AutoLoginService(
                    root=root, game_ready=lambda: False,
                    launcher=lambda _python, _args, _cwd: process,
                    password_protector=lambda _value: "ciphertext",
                )
                result = runner.run(service.AutoLoginRequest(
                    "user", "secret", "Server", timeout_seconds=0.01
                ))

            self.assertTrue(process.terminated)
            self.assertEqual(result.exit_code, service.EXIT_TIMEOUT)
            self.assertEqual(result.state, "timeout")


if __name__ == "__main__":
    unittest.main()
