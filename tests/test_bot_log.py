"""bot_log UI sink and session file."""
from __future__ import annotations

from pathlib import Path

from app.bot_log import configure, get_logger, reset, session_path


def test_ui_sink_receives_info_lines(tmp_path: Path) -> None:
    reset()
    seen: list[str] = []
    path = configure(
        log_dir=tmp_path,
        console=False,
        level="INFO",
        ui_sink=seen.append,
    )
    try:
        get_logger("decision").info("mode=farming action=attack")
        get_logger("shop").warning("shop landing timeout")
        assert path == session_path()
        assert any("decision" in line and "mode=farming" in line for line in seen)
        assert any("shop" in line and "landing timeout" in line for line in seen)
        text = path.read_text(encoding="utf-8")
        assert "mode=farming action=attack" in text
        assert "shop landing timeout" in text
    finally:
        reset()


def test_event_helper_hits_ui_sink(tmp_path: Path) -> None:
    reset()
    seen: list[str] = []
    configure(log_dir=tmp_path, console=False, level="INFO", ui_sink=seen.append)
    try:
        from app.bot_log import event

        event("combat", "farm branch=threat5 id=%s dist=%s", 42, 3)
        event("loot", "begin_loot_item id=%s", 7)
        event("search", "farm branch=none (wander/search next)")
        assert any("threat5" in line and "42" in line for line in seen)
        assert any("begin_loot_item" in line and "7" in line for line in seen)
        assert any("farm branch=none" in line for line in seen)
    finally:
        reset()


def test_debug_not_forwarded_when_level_info(tmp_path: Path) -> None:
    reset()
    seen: list[str] = []
    configure(log_dir=tmp_path, console=False, level="INFO", ui_sink=seen.append)
    try:
        get_logger("hp").debug("cooldown remain")
        get_logger("hp").info("begin retreat")
        assert not any("cooldown" in line for line in seen)
        assert any("begin retreat" in line for line in seen)
    finally:
        reset()
