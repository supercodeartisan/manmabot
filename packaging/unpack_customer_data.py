"""Put portable Engine/data back on disk and remove data.pack.

Run this after Stage 5 and verify_stage5, and before Stage 4.
The development tree is not modified. analysis_text.pack is left in place.

    python\\python.exe packaging\\unpack_customer_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"
ENGINE = PORTABLE / "Engine"


def main() -> int:
    if not ENGINE.is_dir():
        print(f"ERROR: portable engine is missing: {ENGINE}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(ROOT / "Engine"))
    from session.asset_pack_format import extract_pack

    pack = ENGINE / "data.pack"
    dest = ENGINE / "data"
    skills = dest / "catalog" / "skills_names.json"

    if not pack.is_file():
        if skills.is_file():
            print(f"OK already unpacked: {skills}")
            return 0
        print(f"ERROR: no data.pack and no {skills}", file=sys.stderr)
        return 1

    info = extract_pack(pack, dest)
    maps = list((dest / "maps").rglob("meta.yaml")) if (dest / "maps").is_dir() else []
    if not skills.is_file():
        print(f"ERROR: extract missed {skills}", file=sys.stderr)
        return 1
    if not maps:
        print(f"ERROR: extract missed map meta under {dest / 'maps'}", file=sys.stderr)
        return 1

    pack.unlink()
    if pack.exists():
        print(f"ERROR: data.pack still present: {pack}", file=sys.stderr)
        return 1

    print(
        f"OK unpacked files={info.get('files')} maps={len(maps)} "
        f"skills={skills.stat().st_size}"
    )
    print(f"  removed {pack}")
    print(f"  analysis_text.pack kept: {(ENGINE / 'analysis_text.pack').is_file()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
