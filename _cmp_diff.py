"""Temporary comparison helper. Delete after review."""
import difflib
import sys
from pathlib import Path

CUR = Path(r"D:\ManmabotV1_final_final_final")
FIN = Path(r"D:\ManmabotV1_FINAL")
OUT = Path(sys.argv[1])
files = sys.argv[2:]
chunks = []
for rel in files:
    pa, pb = FIN / rel, CUR / rel
    if not pa.exists() or not pb.exists():
        chunks.append(f"\n===== MISSING {rel} final={pa.exists()} cur={pb.exists()} =====\n")
        continue
    a = pa.read_text(encoding="utf-8", errors="replace").splitlines()
    b = pb.read_text(encoding="utf-8", errors="replace").splitlines()
    diff = list(difflib.unified_diff(a, b, fromfile="FINAL/" + rel, tofile="CUR/" + rel, n=2))
    hunks = sum(1 for line in diff if line.startswith("@@"))
    chunks.append(f"\n===== {rel} hunks={hunks} difflines={len(diff)} =====\n")
    chunks.extend(line + "\n" for line in diff)
OUT.write_text("".join(chunks), encoding="utf-8")
print(f"wrote {OUT} bytes={OUT.stat().st_size}")
