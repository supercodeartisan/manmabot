"""Seed UserData with code defaults without wiping existing operator files."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _product_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "run.py").is_file() and (parent / "Engine").is_dir():
            return parent
    return here.parents[2]


ROOT = _product_root()
ENGINE = ROOT / "Engine"
UI_ROOT = ROOT / "UI"
for path in (ROOT, ENGINE, UI_ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
os.environ["MANMABOT_ROOT"] = str(ENGINE)

from session.paths import (  # noqa: E402
    ACCOUNTS_PATH,
    PROFILE_PATH,
    USERDATA,
    ensure_userdata,
)
from settings.profile import Profile, save_profile  # noqa: E402
from settings.schedule import ScheduleStore  # noqa: E402
def main() -> int:
    ensure_userdata()
    defaults_dir = USERDATA / "defaults"
    defaults_dir.mkdir(parents=True, exist_ok=True)

    default_profile = Profile()
    defaults_path = defaults_dir / "profile.defaults.json"
    defaults_path.write_text(
        json.dumps(default_profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {defaults_path}")

    if not PROFILE_PATH.is_file():
        save_profile(default_profile)
        print(f"seeded {PROFILE_PATH}")
    else:
        print(f"keep existing {PROFILE_PATH}")

    if not ACCOUNTS_PATH.is_file():
        ACCOUNTS_PATH.write_text(
            json.dumps({"version": 1, "accounts": []}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        print(f"seeded {ACCOUNTS_PATH}")
    else:
        print(f"keep existing {ACCOUNTS_PATH}")

    store = ScheduleStore()
    tasks = store.load()
    store.save(tasks)
    print(f"ensured {store.path} ({len(tasks)} tasks)")

    for sub in ("maps", "logs", "profiles", "autologin_runs"):
        (USERDATA / sub).mkdir(parents=True, exist_ok=True)
    readme = USERDATA / "README.txt"
    if not readme.is_file():
        readme.write_text(
            "UserData — operator settings written by the UI.\n"
            "defaults/profile.defaults.json mirrors Profile() code defaults.\n"
            "NPC behaviors (buy, sell, warehouse, teleporter) live in Engine/data/npc_behaviors.yaml.\n"
            "Do not store bot source here.\n",
            encoding="utf-8",
        )
    print("UserData seed complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
