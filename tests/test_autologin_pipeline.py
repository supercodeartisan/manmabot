from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
AUTOLOGIN_BOT = ROOT / "autologin" / "bot"
if str(AUTOLOGIN_BOT) not in sys.path:
    sys.path.insert(0, str(AUTOLOGIN_BOT))

from pipeline.context import PipelineContext
from pipeline.result import StageStatus
from pipeline.runner import PipelineRunner
from pipeline.stages.s6_device_tag import DeviceTagStage
from gameflow import CHAR_HANDOFF_SECONDS
from supervisor_io import (
    EXIT_SUCCESS,
    parse_supervisor_args,
    publish_run,
)


class PipelineRecoveryTests(unittest.TestCase):
    def test_backward_jump_resets_stage_retries_but_not_auth_cap(self) -> None:
        context = PipelineContext(bot=object(), auth_relaunch_count=1)
        context.retries.update({"S3": 3, "S4": 4, "S5": 5, "other": 2})
        runner = PipelineRunner(
            context,
            stages={"unused": object()},
            order=("S3", "S4", "S5"),
            registry=object(),
        )
        runner.index = 2

        runner._jump("S3")

        self.assertEqual(runner.index, 0)
        self.assertNotIn("S3", context.retries)
        self.assertNotIn("S4", context.retries)
        self.assertNotIn("S5", context.retries)
        self.assertEqual(context.retries["other"], 2)
        self.assertEqual(context.auth_relaunch_count, 1)


class CharacterHandoffTests(unittest.TestCase):
    def test_farm_bot_handoff_waits_five_seconds_after_char_click(self) -> None:
        self.assertEqual(CHAR_HANDOFF_SECONDS, 5.0)

    def test_device_tag_empty_does_not_delay_handoff(self) -> None:
        fake = types.ModuleType("devicetag")
        fake.read_device_tag = lambda: ""
        fake.backup_device_tag = lambda _base: False
        fake.restore_device_tag = lambda _base: ""
        ctx = PipelineContext(bot=types.SimpleNamespace(session_backup_dir="."))
        with mock.patch.dict(sys.modules, {"devicetag": fake, "bot.devicetag": fake}):
            result = DeviceTagStage().run(ctx)
        self.assertEqual(result.status, StageStatus.OK)
        self.assertIn("continue to farm bot", result.message)


class SupervisorContractTests(unittest.TestCase):
    def test_parse_supervisor_flags(self) -> None:
        flags = parse_supervisor_args(
            [
                "login.json",
                "--timeout", "90",
                "--status-path", "s.json",
                "--result-path", "r.json",
                "--cancel-path", "cancel",
                "--no-self-elevate",
            ],
            default_config="purple_login.json",
        )
        self.assertEqual(flags.config, "login.json")
        self.assertEqual(flags.timeout, 90.0)
        self.assertEqual(flags.status_path, "s.json")
        self.assertEqual(flags.result_path, "r.json")
        self.assertEqual(flags.cancel_path, "cancel")
        self.assertTrue(flags.no_self_elevate)

    def test_publish_run_writes_result_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.json"
            result = Path(tmp) / "result.json"
            flags = parse_supervisor_args(
                ["cfg.json", "--status-path", str(status), "--result-path", str(result)],
                default_config="purple_login.json",
            )
            code = publish_run(flags, state="success", detail="pipeline success")
            self.assertEqual(code, EXIT_SUCCESS)
            payload = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(payload["exit_code"], 0)
            self.assertEqual(payload["state"], "success")
            self.assertEqual(
                json.loads(status.read_text(encoding="utf-8"))["state"], "success"
            )


if __name__ == "__main__":
    unittest.main()
