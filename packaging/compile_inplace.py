"""In-place Nuitka --module compilation for the customer portable tree.

Compiles each .py to a sibling .pyd so Path(__file__) asset layout stays valid.
Uses a full CPython (with headers) as the build interpreter; the portable
embeddable runtime only loads the resulting .pyd files.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
MANIFEST_DIR = PACKAGING_DIR / "manifests"
PORTABLE_DIR = REPO_ROOT / "release" / "portable" / "ManmabotV1"

_PYD_RE = re.compile(r"^(?P<stem>.+)\.cp\d+.*\.pyd$", re.I)


def _read_list(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        out.append(text.replace("\\", "/"))
    return out


def load_compile_packages() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in _read_list(MANIFEST_DIR / "compile_packages.txt"):
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"bad compile_packages line: {line}")
        rows.append((parts[0], parts[1]))
    return rows


def load_keep_scripts() -> set[str]:
    return set(_read_list(MANIFEST_DIR / "keep_scripts.txt"))


def detect_build_python() -> Path:
    env = os.environ.get("MANMABOT_BUILD_PYTHON", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path
        raise RuntimeError(f"MANMABOT_BUILD_PYTHON not found: {env}")

    candidates = [
        Path(r"C:\Users\Condra\AppData\Local\Python\pythoncore-3.14-64\python.exe"),
        Path(os.environ.get("LocalAppData", ""))
        / "Python"
        / "pythoncore-3.14-64"
        / "python.exe",
    ]
    for path in candidates:
        if path.is_file() and (path.parent / "include" / "Python.h").is_file():
            return path
    raise RuntimeError(
        "Full CPython 3.14 with headers not found. Set MANMABOT_BUILD_PYTHON "
        "to a python.exe that has include/Python.h (embeddable python\\ cannot "
        "compile with Nuitka)."
    )


def ensure_nuitka(build_python: Path) -> None:
    probe = subprocess.run(
        [str(build_python), "-c", "import nuitka"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return
    req = PACKAGING_DIR / "requirements-build.txt"
    print(f"Installing build deps into {build_python} ...")
    subprocess.check_call(
        [str(build_python), "-m", "pip", "install", "-r", str(req)]
    )


def list_compile_targets(
    *,
    only_packages: set[str] | None = None,
) -> list[Path]:
    keep = load_keep_scripts()
    targets: list[Path] = []
    for parent, package in load_compile_packages():
        if only_packages and package not in only_packages:
            continue
        root = PORTABLE_DIR / parent / package
        if not root.is_dir():
            raise RuntimeError(f"missing package in portable tree: {root}")
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            # Nuitka rejects compiling __init__.py as a standalone --module file.
            # Keep thin package inits as .py shims; compile real modules to .pyd.
            if path.name == "__init__.py":
                continue
            # Prefer leaving __main__.py runnable for `python -m package`.
            if path.name == "__main__.py":
                continue
            rel = path.relative_to(PORTABLE_DIR).as_posix()
            if rel in keep:
                continue
            targets.append(path)
    return targets


def expected_pyd_for(py_file: Path) -> Path | None:
    parent = py_file.parent
    stem = py_file.stem
    matches = [
        p
        for p in parent.glob(f"{stem}.*.pyd")
        if _PYD_RE.match(p.name) and _PYD_RE.match(p.name).group("stem") == stem
    ]
    matches += list(parent.glob(f"{stem}.pyd"))
    return matches[0] if matches else None


def compile_one(build_python: Path, py_file: Path, *, dry_run: bool) -> Path:
    out_dir = py_file.parent
    if dry_run:
        print(f"[dry-run] nuitka --module {py_file}")
        return out_dir / f"{py_file.stem}.pyd"

    cmd = [
        str(build_python),
        "-m",
        "nuitka",
        "--module",
        str(py_file),
        f"--output-dir={out_dir}",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--nofollow-imports",
        "--python-flag=no_docstrings",
    ]
    print(f"COMPILE {py_file.relative_to(PORTABLE_DIR).as_posix()}")
    proc = subprocess.run(cmd, cwd=str(PORTABLE_DIR))
    if proc.returncode != 0:
        raise RuntimeError(f"Nuitka failed for {py_file} (exit {proc.returncode})")
    pyd = expected_pyd_for(py_file)
    if pyd is None:
        raise RuntimeError(f"Nuitka produced no .pyd for {py_file}")
    return pyd


def strip_sources(compiled: list[Path], *, dry_run: bool) -> int:
    removed = 0
    keep = load_keep_scripts()
    for pyd in compiled:
        # map foo.cp314-win_amd64.pyd -> foo.py
        m = _PYD_RE.match(pyd.name)
        stem = m.group("stem") if m else pyd.stem
        py = pyd.parent / f"{stem}.py"
        if not py.is_file():
            continue
        rel = py.relative_to(PORTABLE_DIR).as_posix()
        if rel in keep:
            continue
        if dry_run:
            print(f"[dry-run] delete {rel}")
        else:
            py.unlink()
        removed += 1
        pyi = pyd.parent / f"{stem}.pyi"
        if pyi.is_file() and not dry_run:
            pyi.unlink()
    return removed


def compile_inplace(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    only_packages: set[str] | None = None,
    strip: bool = True,
) -> dict:
    if not PORTABLE_DIR.is_dir():
        raise RuntimeError(
            f"portable tree missing: {PORTABLE_DIR}. Run --stage 1 first."
        )
    build_python = detect_build_python()
    if not dry_run:
        ensure_nuitka(build_python)
    targets = list_compile_targets(only_packages=only_packages)
    if limit is not None:
        targets = targets[: max(0, limit)]

    started = time.time()
    compiled: list[Path] = []
    failed: list[str] = []
    for py_file in targets:
        try:
            pyd = compile_one(build_python, py_file, dry_run=dry_run)
            compiled.append(pyd)
        except Exception as exc:  # noqa: BLE001 - collect and continue/report
            failed.append(f"{py_file.relative_to(PORTABLE_DIR).as_posix()}: {exc}")
            break  # stop on first failure for safer Stage 2

    removed = strip_sources(compiled, dry_run=dry_run) if strip and not failed else 0
    return {
        "build_python": str(build_python),
        "targets": len(targets),
        "compiled": len(compiled),
        "stripped_py": removed,
        "failed": failed,
        "elapsed_s": round(time.time() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--packages",
        default="",
        help="Comma-separated package names (e.g. session,i18n)",
    )
    parser.add_argument("--no-strip", action="store_true")
    args = parser.parse_args(argv)
    only = {p.strip() for p in args.packages.split(",") if p.strip()} or None
    result = compile_inplace(
        dry_run=args.dry_run,
        limit=args.limit,
        only_packages=only,
        strip=not args.no_strip,
    )
    print(result)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
