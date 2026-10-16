"""Copy/prune the bundled python\\ tree into the customer portable folder."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path


PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
MANIFEST_DIR = PACKAGING_DIR / "manifests"
PORTABLE_DIR = REPO_ROOT / "release" / "portable" / "ManmabotV1"
SRC_PYTHON = REPO_ROOT / "python"
DST_PYTHON = PORTABLE_DIR / "python"


def _read_list(path: Path) -> list[str]:
    rows: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        rows.append(text)
    return rows


def load_prune_names() -> set[str]:
    return set(_read_list(MANIFEST_DIR / "prune_site_packages.txt"))


def is_pruned_name(name: str, prune: set[str]) -> bool:
    if name in prune:
        return True
    lower = name.lower()
    for raw in prune:
        p = raw.lower()
        if lower == p:
            return True
        if lower.startswith(p + "-") or lower.startswith(p + "."):
            return True
    return False


def _should_skip_dir(name: str) -> bool:
    return name in {"__pycache__", ".pytest_cache", "test", "tests", "idlelib", "turtledemo"}


def _win_long(path: Path) -> str:
    """Extended-length path so copies survive a deep release folder name."""
    text = os.path.abspath(os.fspath(path))
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\" + text


def iter_pruned_python_files():
    """Source files Stage 3 copies. Same skip rules as the customer runtime."""
    prune = load_prune_names()
    site = Path("Lib") / "site-packages"
    for dirpath, dirnames, filenames in os.walk(SRC_PYTHON):
        src_dir = Path(dirpath)
        rel_dir = src_dir.relative_to(SRC_PYTHON)
        if rel_dir == site:
            dirnames[:] = [
                d
                for d in dirnames
                if not is_pruned_name(d, prune) and not _should_skip_dir(d)
            ]
            filenames = [name for name in filenames if not is_pruned_name(name, prune)]
        else:
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        parts = rel_dir.parts
        if (
            len(parts) >= 3
            and parts[0] == "Lib"
            and parts[1] == "site-packages"
            and is_pruned_name(parts[2], prune)
        ):
            dirnames[:] = []
            continue
        for name in filenames:
            if name.endswith((".pyc", ".pyo")):
                continue
            src = src_dir / name
            rel = src.relative_to(SRC_PYTHON)
            if (
                len(rel.parts) == 3
                and rel.parts[0] == "Lib"
                and rel.parts[1] == "site-packages"
                and is_pruned_name(rel.parts[2], prune)
            ):
                continue
            yield src


def copy_python_pruned(*, dry_run: bool = False) -> dict:
    if not PORTABLE_DIR.is_dir():
        raise RuntimeError(f"portable tree missing: {PORTABLE_DIR}")
    if not SRC_PYTHON.is_dir():
        raise RuntimeError(f"source python tree missing: {SRC_PYTHON}")

    started = time.time()
    copied = 0
    bytes_copied = 0

    if DST_PYTHON.exists():
        if dry_run:
            print(f"[dry-run] rmtree {DST_PYTHON}")
        else:
            shutil.rmtree(_win_long(DST_PYTHON))

    for src in iter_pruned_python_files():
        rel = src.relative_to(SRC_PYTHON)
        dst = DST_PYTHON / rel
        if dry_run:
            copied += 1
            continue
        os.makedirs(_win_long(dst.parent), exist_ok=True)
        shutil.copy2(_win_long(src), _win_long(dst))
        copied += 1
        try:
            bytes_copied += src.stat().st_size
        except OSError:
            pass

    return {
        "copied_files": copied,
        "skipped_packages": 0,
        "skipped_other": 0,
        "bytes_copied": bytes_copied,
        "bytes_copied_mb": round(bytes_copied / (1024 * 1024), 1),
        "prune_rule_count": len(load_prune_names()),
        "elapsed_s": round(time.time() - started, 2),
        "destination": str(DST_PYTHON),
    }


def verify_runtime_imports() -> list[str]:
    """Import critical modules with the portable interpreter."""
    exe = DST_PYTHON / "python.exe"
    if not exe.is_file():
        return [f"missing {exe}"]
    code = (
        "import PySide6, numpy, cv2, yaml, mss, keyboard, interception, "
        "PIL, onnxruntime, psutil, scipy; "
        "import rapidocr_onnxruntime; "
        "print('imports_ok')"
    )
    import subprocess

    proc = subprocess.run([str(exe), "-c", code], capture_output=True, text=True)
    if proc.returncode != 0:
        return [f"import check failed: {proc.stderr.strip() or proc.stdout.strip()}"]
    # torch/ultralytics must be gone
    neg = subprocess.run(
        [str(exe), "-c", "import torch"],
        capture_output=True,
        text=True,
    )
    if neg.returncode == 0:
        return ["torch still importable after prune"]
    return []


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args(argv)
    result = copy_python_pruned(dry_run=args.dry_run)
    print(result)
    if args.dry_run or args.no_verify:
        return 0
    errors = verify_runtime_imports()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("OK — pruned python runtime imports verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
