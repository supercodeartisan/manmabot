"""Load capture settings from this folder's settings.json."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from paths import SETTINGS_PATH

PIPE_NAME = r"\\.\pipe\realtime_monitor"


@dataclass
class Settings:
    window_process: str = "LC.exe"
    window_title: Optional[str] = None
    region: Optional[dict[str, int]] = None
    fps: int = 20
    content_aspect: tuple[int, int] = (4, 3)
    pipe: str = PIPE_NAME


def _aspect(value: Any) -> tuple[int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    if isinstance(value, str) and ":" in value:
        a, b = value.split(":", 1)
        return int(a), int(b)
    return (4, 3)


def load_settings() -> Settings:
    data: dict[str, Any] = {}
    if SETTINGS_PATH.is_file():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    title = data.get("window_title")
    region = data.get("region")
    return Settings(
        window_process=str(data.get("window_process") or "LC.exe"),
        window_title=None if title in (None, "", "null") else str(title),
        region=region if isinstance(region, dict) else None,
        fps=int(data.get("fps") or 20),
        content_aspect=_aspect(data.get("content_aspect")),
        pipe=str(data.get("pipe") or PIPE_NAME),
    )
