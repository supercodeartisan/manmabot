"""One-shot migration: profile.json + schedules.json → timeline + schedules/ + trial/."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from session.paths import (
    LEGACY_SCHEDULES_PATH,
    PROFILE_PATH,
    PROFILES_DIR,
    SCHEDULES_DIR,
    TIMELINE_PATH,
    TRIAL_DIR,
    TRIAL_ROUTINE_PATH,
    TRIAL_SETTINGS_PATH,
    USERDATA,
    ensure_userdata,
    schedule_dir,
)
from settings.farm_schedule import normalize_routine
from settings.settings_sections import (
    normalize_settings,
    split_settings_routine,
)
from settings.timeline import TimelineDocument, TimelineEntry, save_timeline

_MIGRATED_FLAG = USERDATA / ".ops_layout_v1"


def ops_layout_ready() -> bool:
    """True when new layout is present (or empty fresh install after ensure)."""
    if _MIGRATED_FLAG.is_file():
        return True
    if TIMELINE_PATH.is_file() and TRIAL_SETTINGS_PATH.is_file():
        return True
    if SCHEDULES_DIR.is_dir() and any(SCHEDULES_DIR.iterdir()):
        return True
    return False


def _bak(path: Path) -> None:
    if not path.is_file():
        return
    dest = path.with_suffix(path.suffix + ".bak")
    if dest.is_file():
        dest = path.with_suffix(path.suffix + ".bak2")
    try:
        shutil.move(str(path), str(dest))
    except OSError:
        pass


def _write_schedule_files(
    schedule_id: str,
    *,
    meta: dict[str, Any],
    settings: dict[str, Any],
    routine: list[Any],
) -> None:
    from session.paths import atomic_write_json, assert_userdata_write

    root = schedule_dir(schedule_id)
    root.mkdir(parents=True, exist_ok=True)
    settings = normalize_settings(settings)
    routine = normalize_routine(routine)
    atomic_write_json(assert_userdata_write(root / "meta.json"), meta)
    atomic_write_json(assert_userdata_write(root / "settings.json"), settings)
    atomic_write_json(assert_userdata_write(root / "routine.json"), routine)


def migrate_userdata_ops_layout(*, force: bool = False) -> bool:
    """Migrate legacy files if needed. Returns True when migration ran."""
    ensure_userdata()
    if ops_layout_ready() and not force:
        if not _MIGRATED_FLAG.is_file():
            _MIGRATED_FLAG.write_text("1\n", encoding="utf-8")
        return False

    from settings.profile import Profile
    from settings.schedule import ScheduleTask, profile_snapshot

    legacy_path = LEGACY_SCHEDULES_PATH
    tasks: list[ScheduleTask] = []
    randomize_enabled = False
    randomize_minutes = 0
    if legacy_path.is_file():
        try:
            raw = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            randomize_enabled = bool(raw.get("randomize_enabled"))
            try:
                randomize_minutes = max(0, min(120, int(raw.get("randomize_minutes") or 0)))
            except (TypeError, ValueError):
                randomize_minutes = 0
            for row in raw.get("tasks") or []:
                if isinstance(row, dict):
                    tasks.append(ScheduleTask.from_dict(row))

    # Trial from profile.json (raw — do not recurse through load_profile).
    if PROFILE_PATH.is_file():
        try:
            pdata = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pdata = None
        profile = (
            Profile.from_dict(pdata)
            if isinstance(pdata, dict)
            else Profile()
        )
    else:
        profile = Profile()
    snap = profile_snapshot(profile)
    trial_settings, trial_routine = split_settings_routine(snap)
    # Prefer profile.routine if present
    if getattr(profile, "routine", None):
        trial_routine = normalize_routine(profile.routine)

    from session.paths import atomic_write_json, assert_userdata_write

    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(assert_userdata_write(TRIAL_SETTINGS_PATH), trial_settings)
    atomic_write_json(assert_userdata_write(TRIAL_ROUTINE_PATH), trial_routine)

    from settings.trial_store import save_app_state

    save_app_state(
        {
            "last_run_mode": "trial",
            "armed_schedule_id": None,
            "language": profile.language,
            "wizard_completed": bool(profile.wizard_completed),
            "always_on_top": bool(profile.always_on_top),
        }
    )

    timeline = TimelineDocument(
        randomize_enabled=randomize_enabled,
        randomize_minutes=randomize_minutes,
        entries=[],
    )
    for task in tasks:
        sid = str(task.id or "").strip()
        if not sid:
            continue
        settings, routine = split_settings_routine(task.settings)
        meta = {
            "id": sid,
            "name": str(task.name or "New task")[:80],
            "enabled": bool(task.enabled),
            "account_id": task.account_id,
            "character": str(task.character or "mage"),
            "character_slot": int(task.character_slot or 1),
            "server": str(task.server or ""),
            "role": str(task.role or ""),
        }
        _write_schedule_files(sid, meta=meta, settings=settings, routine=routine)
        timeline.entries.append(
            TimelineEntry(
                schedule_id=sid,
                enabled=bool(task.enabled),
                time_mode=str(task.time_mode or "window"),
                start_time=str(task.start_time or "00:00:00"),
                end_time=str(task.end_time or "23:59:59"),
                duration_minutes=int(task.duration_minutes or 90),
                weekdays=list(task.weekdays or list(range(7))),
                repeat_daily=bool(task.repeat_daily),
            )
        )

    # Named presets → schedules/_preset_{name}
    if PROFILES_DIR.is_dir():
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            try:
                named = Profile.from_dict(data)
            except Exception:
                continue
            sid = f"_preset_{path.stem}"
            settings, routine = split_settings_routine(profile_snapshot(named))
            if named.routine:
                routine = normalize_routine(named.routine)
            _write_schedule_files(
                sid,
                meta={
                    "id": sid,
                    "name": path.stem[:80],
                    "enabled": False,
                    "account_id": None,
                    "character": named.character,
                    "character_slot": 1,
                    "server": "",
                    "role": "preset",
                },
                settings=settings,
                routine=routine,
            )

    save_timeline(timeline)
    _bak(legacy_path)
    _bak(PROFILE_PATH)
    try:
        _MIGRATED_FLAG.write_text("1\n", encoding="utf-8")
    except OSError:
        pass
    return True


def ensure_ops_layout() -> None:
    ensure_userdata()
    if not ops_layout_ready():
        migrate_userdata_ops_layout()
    else:
        TRIAL_DIR.mkdir(parents=True, exist_ok=True)
        SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
        if not TRIAL_SETTINGS_PATH.is_file():
            from session.paths import atomic_write_json, assert_userdata_write

            atomic_write_json(
                assert_userdata_write(TRIAL_SETTINGS_PATH), normalize_settings({})
            )
            atomic_write_json(assert_userdata_write(TRIAL_ROUTINE_PATH), [])
        if not TIMELINE_PATH.is_file():
            save_timeline(TimelineDocument())
        if not _MIGRATED_FLAG.is_file():
            try:
                _MIGRATED_FLAG.write_text("1\n", encoding="utf-8")
            except OSError:
                pass
