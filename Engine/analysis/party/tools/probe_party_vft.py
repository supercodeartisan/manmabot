"""Probe the party vfts for the running LC build (run elevated, LC.exe open).

    python Engine/analysis/party/tools/probe_party_vft.py

Prints, per vft delta vs registry/PARTY_SEC17.txt, whether PartySubsystem
resolves (``subs_ok`` — works outside a party) and the party it reads.
Being in a party additionally checks PARTY_VFT_RC / RC_PLAYER (members listed).
Read-only, same DLL path as the bot.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE))

from app._01_perception.party_listen_reader import (  # noqa: E402
    CALIBRATION_DELTAS,
    PartyListenReader,
    merged_registry_path,
)


def main() -> int:
    out = Path(__file__).resolve().parent / "_probe_registry.txt"
    hits = []
    for delta in CALIBRATION_DELTAS:
        reg = merged_registry_path(delta, out=out)
        reader = PartyListenReader(registry_path=reg)
        if not reader.dll_loaded:
            print("party_listen.dll missing")
            return 2
        snap = reader.snapshot()
        reader.close()
        if snap is None:
            print(f"{delta:+#07x}  no snapshot (LC not running / not elevated / anchor failed)")
            continue
        members = [m.get("name") for m in snap.get("members") or []]
        print(
            f"{delta:+#07x}  subs_ok={snap.get('subs_ok')} in_party={snap.get('in_party')} "
            f"count={snap.get('count')} leader={snap.get('leader_name')!r} members={members}"
        )
        if snap.get("subs_ok"):
            hits.append((delta, snap))
    if not hits:
        print("\nNo delta resolved PartySubsystem — party vfts need a fresh RTTI lookup.")
        return 1
    delta, snap = hits[0]
    print(f"\nUse delta {delta:+#x}" + (" (members verified)" if snap.get("members") else
                                     " (join a party to verify RC / RC_PLAYER too)"))
    print(json.dumps(snap, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
