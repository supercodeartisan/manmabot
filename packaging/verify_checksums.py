"""Verify release/checksums/SHA256SUMS against the portable tree."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "release" / "portable" / "ManmabotV1"
SUMS = ROOT / "release" / "checksums" / "SHA256SUMS"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not SUMS.is_file():
        print(f"missing {SUMS}", file=sys.stderr)
        return 1
    if not PORTABLE.is_dir():
        print(f"missing {PORTABLE}", file=sys.stderr)
        return 1

    expected: dict[str, str] = {}
    for line in SUMS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, rel = line.partition("  ")
        if not rel:
            digest, _, rel = line.partition(" *")
        expected[rel.replace("\\", "/")] = digest.lower()

    errors: list[str] = []
    checked = 0
    for rel, digest in expected.items():
        path = PORTABLE / rel
        if not path.is_file():
            errors.append(f"missing file: {rel}")
            continue
        actual = sha256_file(path)
        checked += 1
        if actual != digest:
            errors.append(f"hash mismatch: {rel}")

    # Detect extra files not listed (warn only for top-level / small set)
    on_disk = {
        p.relative_to(PORTABLE).as_posix()
        for p in PORTABLE.rglob("*")
        if p.is_file()
    }
    # Checksum sidecar is expected and intentionally omitted from the digest list.
    on_disk.discard("SHA256SUMS.txt")
    on_disk.discard("SHA256SUMS")
    extra = sorted(on_disk - set(expected))
    if extra:
        print(f"WARN: {len(extra)} files on disk not in SHA256SUMS (first 5):")
        for rel in extra[:5]:
            print(f"  {rel}")

    if errors:
        for err in errors[:20]:
            print(f"FAIL: {err}", file=sys.stderr)
        if len(errors) > 20:
            print(f"FAIL: ... and {len(errors) - 20} more", file=sys.stderr)
        return 1
    print(f"OK — verified {checked} checksums ({SUMS})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
