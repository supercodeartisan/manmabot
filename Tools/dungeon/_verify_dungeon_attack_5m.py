"""Headless 5-minute Gludio dungeon attack verification (Start Dungeon Combat path)."""
from __future__ import annotations

import re
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.bootstrap import bootstrap

bootstrap()

from dungeon.dungeon_combat_gui import (  # noqa: E402
    _CombatPatches,
    _dungeon_skip_species,
    _finalize_dungeon_hp_actions,
    _load_dungeon_hp_actions,
    _reset_dungeon_tp_ladder,
)
from session.bot_controller import BotController, RunState  # noqa: E402
from session.probes import list_patrol_entries  # noqa: E402
from settings.profile import load_profile  # noqa: E402

MAP_ID = "gludio_dungeon_F1"
DURATION_S = 5 * 60
LOG_DIR = ROOT / "Engine" / "logs"


def _latest_log() -> Path | None:
    logs = sorted(LOG_DIR.glob("bot-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _count(path: Path, pattern: str) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return len(re.findall(pattern, text))


def main() -> int:
    if not list_patrol_entries(MAP_ID):
        print(f"FAIL: no patrol points for {MAP_ID}")
        return 2

    base = load_profile()
    blocked = list(base.species_blacklist or [])
    for key in _dungeon_skip_species():
        if key not in blocked:
            blocked.append(key)
    hp_actions = _finalize_dungeon_hp_actions(_load_dungeon_hp_actions())
    profile = replace(
        base,
        active_map=MAP_ID,
        map_style="dungeon",
        selected_farms=[],
        species_filter_mode="blacklist",
        species_blacklist=blocked,
        loot_mode=getattr(base, "loot_mode", None) or "adena_only",
        item_pickup_mode="all",
        item_pickup_names=[],
        loot_adena_weight_ratio=0.95,
        hp_actions=hp_actions,
    )

    patches = _CombatPatches()
    def _log(msg: str) -> None:
        try:
            print(f"[bot] {msg}", flush=True)
        except UnicodeEncodeError:
            print(f"[bot] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)

    controller = BotController(on_log=_log)
    _reset_dungeon_tp_ladder()
    patches.install()
    before = _latest_log()
    err = controller.start(profile, unattended=True)
    if err:
        patches.restore()
        print(f"FAIL: start failed: {err}")
        return 3

    # Wait for a new session log.
    log_path: Path | None = None
    for _ in range(50):
        cand = _latest_log()
        if cand is not None and (before is None or cand != before or cand.stat().st_size > 200):
            if cand.name != (before.name if before else ""):
                log_path = cand
                break
            # same file growing after restart rare; accept if recent
            if time.time() - cand.stat().st_mtime < 10:
                log_path = cand
                break
        time.sleep(0.2)
    if log_path is None:
        log_path = _latest_log()
    print(f"VERIFY start map={MAP_ID} duration={DURATION_S}s log={log_path}", flush=True)

    t0 = time.time()
    last_report = t0
    try:
        while time.time() - t0 < DURATION_S:
            if controller.state == RunState.STOPPED:
                print("VERIFY bot stopped early", flush=True)
                break
            time.sleep(10.0)
            now = time.time()
            if log_path and log_path.is_file() and now - last_report >= 30:
                last_report = now
                attacks = _count(log_path, r"action=attack")
                screen = _count(log_path, r"farm branch=screen_combat")
                sticky = _count(log_path, r"farm branch=sticky")
                none = _count(log_path, r"farm branch=none")
                sweep_fail = _count(log_path, r"Entity sweep failed")
                print(
                    f"t={int(now - t0):3d}s attacks={attacks} screen={screen} "
                    f"sticky={sticky} none={none} sweep_fail={sweep_fail}",
                    flush=True,
                )
    finally:
        try:
            controller.stop(reason="verify 5m done")
            controller.wait_stopped(timeout=10.0)
        except Exception as exc:
            print(f"stop warn: {exc}", flush=True)
        try:
            patches.restore()
        except Exception:
            pass

    if log_path is None or not log_path.is_file():
        print("FAIL: no log")
        return 4

    attacks = _count(log_path, r"action=attack")
    screen = _count(log_path, r"farm branch=screen_combat")
    sticky = _count(log_path, r"farm branch=sticky")
    none = _count(log_path, r"farm branch=none")
    engage = _count(log_path, r"combat\s+engage id=")
    give_up = _count(log_path, r"give-up id=")
    path_cap_m = _count(log_path, r"path cap skip id=\d+ kind=monster")
    sweep_fail = _count(log_path, r"Entity sweep failed")
    elapsed = int(time.time() - t0)
    print("---- VERIFY RESULT ----", flush=True)
    print(f"log={log_path}", flush=True)
    print(f"elapsed_s={elapsed}", flush=True)
    print(f"action=attack={attacks}", flush=True)
    print(f"screen_combat={screen}", flush=True)
    print(f"sticky={sticky}", flush=True)
    print(f"none={none}", flush=True)
    print(f"engage={engage}", flush=True)
    print(f"give-up={give_up}", flush=True)
    print(f"path_cap_monster={path_cap_m}", flush=True)
    print(f"entity_sweep_fail={sweep_fail}", flush=True)

    # Pass if we engaged/attacked multiple times over the window.
    ok = attacks >= 5 and engage >= 3 and sweep_fail == 0
    print("PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
