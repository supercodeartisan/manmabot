"""Verify keep-scripts and package ``__init__.py`` stay thin for release.

Run from product root (dev tree or after Stage 1 portable copy)::

    python\\python.exe packaging\\verify_shims.py
    python\\python.exe packaging\\verify_shims.py --portable

Fails if a keep-script or tracked ``__init__.py`` grows past the policy limits
(logic must live in sibling modules that Stage 2 compiles to ``.pyd``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
PORTABLE_DIR = REPO_ROOT / "release" / "portable" / "ManmabotV1"
MANIFEST_DIR = PACKAGING_DIR / "manifests"

# Soft ceilings — keep-scripts must remain readable stubs only.
KEEP_SCRIPT_MAX_LINES = 80
INIT_SHIM_MAX_LINES = 25

# Package roots whose __init__.py must stay thin (compile_packages + fonts).
INIT_PACKAGE_DIRS = (
    "Engine/app",
    "Engine/session",
    "Engine/settings",
    "Engine/shop",
    "Engine/hotbar",
    "Engine/i18n",
    "Engine/login",
    "Engine/autologin",
    "Engine/tool",
    "UI/ui",
    "UI/ui_qt",
)


def _read_list(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        out.append(text.replace("\\", "/"))
    return out


def _line_count(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portable",
        action="store_true",
        help="Check release/portable/ManmabotV1 instead of the dev tree",
    )
    args = parser.parse_args()
    root = PORTABLE_DIR if args.portable else REPO_ROOT
    if not root.is_dir():
        print(f"FAIL: missing root {root}", file=sys.stderr)
        return 1

    errors: list[str] = []

    for rel in _read_list(MANIFEST_DIR / "keep_scripts.txt"):
        path = root / rel
        if not path.is_file():
            errors.append(f"missing keep-script: {rel}")
            continue
        n = _line_count(path)
        if n > KEEP_SCRIPT_MAX_LINES:
            errors.append(
                f"keep-script too large ({n}>{KEEP_SCRIPT_MAX_LINES} lines): {rel} "
                f"— move logic into a sibling module compiled by Stage 2"
            )

    # Required bodies that Stage 2 must compile (dev tree names).
    required_bodies = (
        "Engine/session/run_entry.py",
        "Engine/autologin/bot/bot2_core.py",
    )
    for rel in required_bodies:
        if not (root / rel).is_file():
            errors.append(f"missing compiled body for keep-script: {rel}")

    for pkg in INIT_PACKAGE_DIRS:
        base = root / pkg
        if not base.is_dir():
            continue
        for init in base.rglob("__init__.py"):
            if "__pycache__" in init.parts:
                continue
            n = _line_count(init)
            if n > INIT_SHIM_MAX_LINES:
                rel = init.relative_to(root).as_posix()
                errors.append(
                    f"__init__.py too large ({n}>{INIT_SHIM_MAX_LINES} lines): {rel} "
                    f"— move exports/logic to _public.py (or loader.py) for Stage 2"
                )

    if errors:
        print("verify_shims FAIL:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("verify_shims OK")
    print(f"  root={root}")
    print(f"  keep_script_max={KEEP_SCRIPT_MAX_LINES} init_max={INIT_SHIM_MAX_LINES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
