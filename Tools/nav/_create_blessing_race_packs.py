"""One-shot: create 20 race field packs that share base-season nav."""
from __future__ import annotations

import subprocess
from pathlib import Path

MAPS = Path(__file__).resolve().parents[2] / "Engine" / "data" / "maps"

SEASONS = [
    ("polluted_land_of_blessing", 244, "Polluted Land of Blessing"),
    ("corrupted_land_of_blessing_spring", 2450, "Corrupted Land of Blessing - Spring"),
    ("corrupted_land_of_blessing_summer", 245, "Corrupted Land of Blessing - Summer"),
    ("corrupted_land_of_blessing_autumn", 2452, "Corrupted Land of Blessing - Autumn"),
    ("corrupted_land_of_blessing_winter", 2454, "Corrupted Land of Blessing - Winter"),
]
RACES = [
    ("fairy", "Fairy Land"),
    ("human", "Human Land"),
    ("orch", "Orch Land"),
    ("spirit", "Spirit Land"),
]


def main() -> None:
    created: list[str] = []
    for base, mid, en_base in SEASONS:
        base_dir = MAPS / base
        if not (base_dir / "nav.png").is_file():
            raise SystemExit(f"missing nav: {base}")
        if not (base_dir / "nav_prebuild").is_dir():
            raise SystemExit(f"missing nav_prebuild: {base}")
        for race, en_race in RACES:
            pid = f"{base}_{race}"
            d = MAPS / pid
            d.mkdir(parents=True, exist_ok=True)
            meta = "\n".join(
                [
                    f"id: {pid}",
                    f'name: "{en_base} / {en_race}"',
                    f"# Race field variant. Live mapId {mid} owned by {base}.",
                    "# raw_map omitted so map_id_to_pack_id stays unique on the base pack.",
                    "origin_x: 32640",
                    "origin_y: 32768",
                    "pixel_scale: 1",
                    f"terrain: ../{base}/nav.png",
                    "farms: farms.yaml",
                    "default_region: blessing_land",
                    f"race: {race}",
                    f"nav_source_pack: {base}",
                    "",
                ]
            )
            (d / "meta.yaml").write_text(meta, encoding="utf-8")
            (d / "farms.yaml").write_text(
                "# Areas (nav tiles). region selects vision models (not the map pack id).\n"
                "areas: []\n",
                encoding="utf-8",
            )
            pre = d / "nav_prebuild"
            if pre.is_symlink() or pre.exists():
                # Junction/dir already present — leave it.
                pass
            else:
                src = str((base_dir / "nav_prebuild").resolve())
                dst = str(pre)
                r = subprocess.run(
                    ["cmd", "/c", "mklink", "/J", dst, src],
                    capture_output=True,
                    text=True,
                )
                if r.returncode != 0:
                    raise SystemExit(
                        f"junction failed {pid}: {r.stdout} {r.stderr}"
                    )
            created.append(pid)
    print(f"created {len(created)}")
    for p in created:
        print(p)


if __name__ == "__main__":
    main()
