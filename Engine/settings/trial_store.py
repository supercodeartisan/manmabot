"""Trial workspace: run with current settings+routine, no timeline, no account."""
from __future__ import annotations

import copy
from typing import Any

from session.paths import (
    APP_PATH,
    TRIAL_DIR,
    TRIAL_ROUTINE_PATH,
    TRIAL_SETTINGS_PATH,
    assert_userdata_write,
    atomic_write_json,
    ensure_userdata,
)
from settings.farm_schedule import normalize_routine
from settings.settings_sections import (
    empty_settings,
    merge_settings_routine,
    normalize_settings,
    read_json_list,
    read_json_object,
    split_settings_routine,
)

RUN_MODE_TRIAL = "trial"
RUN_MODE_SCHEDULE = "schedule"


def load_app_state() -> dict[str, Any]:
    ensure_userdata()
    raw = read_json_object(APP_PATH) or {}
    mode = str(raw.get("last_run_mode") or RUN_MODE_TRIAL).strip().lower()
    if mode not in (RUN_MODE_TRIAL, RUN_MODE_SCHEDULE):
        mode = RUN_MODE_TRIAL
    return {
        "last_run_mode": mode,
        "armed_schedule_id": (
            str(raw["armed_schedule_id"]).strip()
            if raw.get("armed_schedule_id")
            else None
        ),
        "language": str(raw.get("language") or "").strip() or None,
        "wizard_completed": bool(raw.get("wizard_completed", False)),
        "always_on_top": bool(raw.get("always_on_top", False)),
        "input_backend": str(raw.get("input_backend") or "").strip() or None,
        "pico_com": str(raw.get("pico_com") or "").strip(),
        "pico_baud": raw.get("pico_baud"),
    }


def save_app_state(state: dict[str, Any]) -> None:
    ensure_userdata()
    cur = load_app_state()
    cur.update({k: v for k, v in state.items() if v is not None or k in state})
    mode = str(cur.get("last_run_mode") or RUN_MODE_TRIAL).strip().lower()
    if mode not in (RUN_MODE_TRIAL, RUN_MODE_SCHEDULE):
        mode = RUN_MODE_TRIAL
    payload = {
        "schema_version": 1,
        "last_run_mode": mode,
        "armed_schedule_id": cur.get("armed_schedule_id"),
        "language": cur.get("language"),
        "wizard_completed": bool(cur.get("wizard_completed", False)),
        "always_on_top": bool(cur.get("always_on_top", False)),
        "input_backend": cur.get("input_backend"),
        "pico_com": str(cur.get("pico_com") or "").strip(),
        "pico_baud": cur.get("pico_baud"),
    }
    atomic_write_json(assert_userdata_write(APP_PATH), payload)


def load_trial() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return (settings, routine) for the trial workspace."""
    ensure_userdata()
    settings_raw = read_json_object(TRIAL_SETTINGS_PATH)
    routine_raw = read_json_list(TRIAL_ROUTINE_PATH)
    settings = normalize_settings(settings_raw or empty_settings())
    if routine_raw is None and settings_raw and isinstance(settings_raw.get("move"), dict):
        # Tolerate mistaken embed.
        _settings, routine = split_settings_routine(settings_raw)
        return _settings, routine
    return settings, normalize_routine(routine_raw or [])


def save_trial(
    settings: dict[str, Any] | None = None,
    routine: list | None = None,
) -> None:
    ensure_userdata()
    TRIAL_DIR.mkdir(parents=True, exist_ok=True)
    if settings is not None and routine is None:
        settings, routine = split_settings_routine(settings)
    elif settings is not None:
        settings, _ignored = split_settings_routine(settings)
    else:
        settings, existing = load_trial()
        if routine is None:
            routine = existing
    settings = normalize_settings(settings)
    routine = normalize_routine(routine or [])
    atomic_write_json(assert_userdata_write(TRIAL_SETTINGS_PATH), settings)
    atomic_write_json(assert_userdata_write(TRIAL_ROUTINE_PATH), routine)


def trial_as_embedded_settings() -> dict[str, dict[str, Any]]:
    settings, routine = load_trial()
    return merge_settings_routine(settings, routine)


def mark_trial_run() -> None:
    save_app_state({"last_run_mode": RUN_MODE_TRIAL, "armed_schedule_id": None})


def mark_schedule_run(schedule_id: str) -> None:
    save_app_state(
        {
            "last_run_mode": RUN_MODE_SCHEDULE,
            "armed_schedule_id": str(schedule_id or "").strip() or None,
        }
    )


def apply_trial_to_profile(profile: Any) -> list[str]:
    """Load trial into ``profile`` (no account). Returns changed keys."""
    from settings.schedule import ScheduleTask
    from settings.task_runtime import apply_runtime_settings

    settings = trial_as_embedded_settings()
    char = str((settings.get("magic") or {}).get("class") or "mage")
    task = ScheduleTask(
        settings=copy.deepcopy(settings), account_id=None, character=char
    )
    changed = apply_runtime_settings(task, profile)
    profile.selected_account_id = None
    return list(changed or [])
