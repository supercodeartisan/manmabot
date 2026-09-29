"""S0 Preflight — refuse unsupported / incomplete environments early."""
from __future__ import annotations

import os

from ..context import PipelineContext
from ..result import StageResult
from .base_stage import Stage


def _dpi_scale() -> float:
    """Best-effort primary monitor scale (1.0 = 100%)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        try:
            # Per-monitor awareness helps GetDpiForSystem on Win10+
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        dpi = 96
        try:
            dpi = int(ctypes.windll.user32.GetDpiForSystem())
        except Exception:
            try:
                hdc = user32.GetDC(0)
                dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))  # LOGPIXELSX
                user32.ReleaseDC(0, hdc)
            except Exception:
                pass
        return float(dpi) / 96.0
    except Exception:
        return 1.0


def _is_elevated() -> bool:
    try:
        import ctypes
        return bool(ctypes.WinDLL("shell32").IsUserAnAdmin())
    except Exception:
        return False


class PreflightStage(Stage):
    id = "S0"

    def snapshot(self, ctx: PipelineContext):
        snap = {"stage_id": self.id}
        bot = ctx.bot
        if bot is not None:
            snap["has_credentials"] = bool(
                getattr(bot, "username", None)
                and getattr(bot, "password", None))
            snap["interception"] = bool(
                getattr(bot, "_interception_ready", False)
                or getattr(bot, "_use_interception", False))
            snap["has_game_path"] = bool(getattr(bot, "game_path", None))
            snap["elevated"] = _is_elevated()
        return snap

    def run(self, ctx: PipelineContext) -> StageResult:
        bot = ctx.bot
        if bot is None:
            return StageResult.failed(self.id, "no bot on context")
        if not getattr(bot, "username", None):
            return StageResult.failed(self.id, "missing account userID")
        if not getattr(bot, "password", None):
            return StageResult.failed(self.id, "missing account password")

        require_ix = bool(ctx.cfg.get("require_interception", True))
        ready = bool(getattr(bot, "_interception_ready", False)
                     or getattr(bot, "_use_interception", False))
        if require_ix and not ready:
            return StageResult.failed(
                self.id,
                "Interception driver not ready — install/run as admin",
                interception=False)

        elevated = _is_elevated()
        ctx.extras["elevated"] = elevated
        # Game/Purple are elevated; without matching integrity, focus/UIPI fails.
        require_elev = bool(ctx.cfg.get("require_elevation", False))
        if require_elev and not elevated:
            return StageResult.failed(
                self.id,
                "not elevated — run as Administrator (required for game focus)",
                elevated=False)
        if not elevated:
            ctx.extras["elevation_warned"] = True

        path = getattr(bot, "game_path", None) or ""
        if path and not os.path.isfile(path):
            if bool(ctx.cfg.get("require_game_path", False)):
                return StageResult.failed(
                    self.id, "game_path missing on disk: %s" % path)
            ctx.extras["game_path_missing"] = path

        scale = _dpi_scale()
        ctx.extras["dpi_scale"] = scale
        if scale > 1.25 and bool(ctx.cfg.get("require_dpi_100", False)):
            return StageResult.failed(
                self.id,
                "DPI scale %.0f%% unsupported (require 100%%)" % (scale * 100),
                dpi_scale=scale)
        if scale > 1.25:
            ctx.extras["dpi_warned"] = True

        store = getattr(bot, "positions", None)
        if store is not None:
            writable = bool(ctx.cfg.get("position_dict_writable", False))
            learn = bool(getattr(bot, "learn", False))
            if not writable and not learn:
                store.set_writable(False)

        return StageResult.ok(
            self.id, "preflight passed",
            interception=ready, dpi_scale=scale, elevated=elevated)
