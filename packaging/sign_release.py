"""Optional Authenticode signing for the customer portable tree.

Never stores certificates or passwords in the repository.
Enable only via environment variables on the build machine.

Required to actually sign:
  MANMABOT_SIGN=1

Certificate (one of):
  MANMABOT_SIGN_PFX=C:\\secure\\codeSign.pfx
  MANMABOT_SIGN_PASSWORD=...          # optional if PFX has no password
  -- or --
  MANMABOT_SIGN_THUMBPRINT=AABBCC...  # cert already in CurrentUser/LocalMachine store

Optional:
  MANMABOT_SIGNTOOL=C:\\Path\\signtool.exe
  MANMABOT_SIGN_TIMESTAMP=http://timestamp.digicert.com
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PORTABLE_DIR = REPO_ROOT / "release" / "portable" / "ManmabotV1"


def signing_enabled() -> bool:
    return os.environ.get("MANMABOT_SIGN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def find_signtool() -> Path | None:
    env = os.environ.get("MANMABOT_SIGNTOOL", "").strip()
    if env:
        path = Path(env)
        return path if path.is_file() else None
    which = shutil.which("signtool")
    if which:
        return Path(which)
    # Common Windows SDK locations
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits.is_dir():
        candidates = sorted(kits.glob(r"*\x64\signtool.exe"), reverse=True)
        if candidates:
            return candidates[0]
    return None


def default_sign_targets(portable: Path = PORTABLE_DIR) -> list[Path]:
    """Executables customers launch / install — not every .pyd."""
    targets: list[Path] = []
    for name in (
        "Bot_ManmabotV1.exe",
        "python/python.exe",
        "python/pythonw.exe",
    ):
        path = portable / name
        if path.is_file():
            targets.append(path)
    drivers = portable / "Drivers"
    if drivers.is_dir():
        for path in drivers.rglob("*.exe"):
            targets.append(path)
    # Unique preserve order
    seen: set[Path] = set()
    out: list[Path] = []
    for path in targets:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _sign_args(signtool: Path, target: Path) -> list[str]:
    timestamp = os.environ.get(
        "MANMABOT_SIGN_TIMESTAMP", "http://timestamp.digicert.com"
    ).strip()
    args = [
        str(signtool),
        "sign",
        "/fd",
        "sha256",
        "/td",
        "sha256",
        "/tr",
        timestamp,
    ]
    pfx = os.environ.get("MANMABOT_SIGN_PFX", "").strip()
    thumb = os.environ.get("MANMABOT_SIGN_THUMBPRINT", "").strip()
    if pfx:
        args += ["/f", pfx]
        password = os.environ.get("MANMABOT_SIGN_PASSWORD", "")
        if password:
            args += ["/p", password]
    elif thumb:
        args += ["/sha1", thumb]
    else:
        raise RuntimeError(
            "Set MANMABOT_SIGN_PFX or MANMABOT_SIGN_THUMBPRINT when MANMABOT_SIGN=1"
        )
    args.append(str(target))
    return args


def sign_targets(
    targets: list[Path] | None = None, *, dry_run: bool = False
) -> dict:
    if not signing_enabled():
        return {
            "enabled": False,
            "signed": 0,
            "skipped": 0,
            "message": "MANMABOT_SIGN not set — checksum-only Stage 4",
        }
    signtool = find_signtool()
    if signtool is None:
        raise RuntimeError(
            "signtool.exe not found. Install Windows SDK or set MANMABOT_SIGNTOOL."
        )
    files = targets if targets is not None else default_sign_targets()
    signed = 0
    failed: list[str] = []
    for path in files:
        if dry_run:
            print(f"[dry-run] signtool sign {path}")
            signed += 1
            continue
        cmd = _sign_args(signtool, path)
        # Do not print password-bearing command lines.
        print(f"SIGN {path.relative_to(PORTABLE_DIR).as_posix()}")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            failed.append(f"{path.name}: {err[:300]}")
            continue
        signed += 1
    return {
        "enabled": True,
        "signtool": str(signtool),
        "signed": signed,
        "failed": failed,
        "targets": [str(p) for p in files],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = sign_targets(dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(result)
    if result.get("failed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
