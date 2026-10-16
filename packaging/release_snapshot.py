"""Shippable-input snapshot for incremental release.

Compares the development tree to the last release by file hash.
Git status is not the source of truth: ignored images, DLLs, EXEs, and
batch files are included.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

from build_release import (  # noqa: E402
    REPO_ROOT as _BUILD_ROOT,
    is_denied,
    load_manifests,
    sha256_file,
)
from compile_inplace import load_compile_packages, load_keep_scripts  # noqa: E402
from pack_assets import _should_pack_analysis_file  # noqa: E402

assert _BUILD_ROOT == REPO_ROOT

SNAPSHOT_PATH = REPO_ROOT / "release" / "version-info" / "INPUTS.json"
PLAN_PATH = REPO_ROOT / "release" / "version-info" / "incremental-plan.txt"
GENERATED_PORTABLE_NAMES = {
    "SHA256SUMS.txt",
    "README.txt",
    ".portable",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_KEEP_SCRIPTS: set[str] | None = None
_COMPILE_PREFIXES: tuple[str, ...] | None = None


def _keep_scripts() -> set[str]:
    global _KEEP_SCRIPTS
    if _KEEP_SCRIPTS is None:
        _KEEP_SCRIPTS = load_keep_scripts()
    return _KEEP_SCRIPTS


def _compile_prefixes() -> tuple[str, ...]:
    global _COMPILE_PREFIXES
    if _COMPILE_PREFIXES is None:
        _COMPILE_PREFIXES = tuple(
            f"{parent}/{package}/" for parent, package in load_compile_packages()
        )
    return _COMPILE_PREFIXES


def role_for(rel: str) -> str:
    """How a shippable source file is applied to the customer folder."""
    path = Path(rel)
    if rel.startswith("Engine/analysis/"):
        analysis_root = REPO_ROOT / "Engine" / "analysis"
        full = REPO_ROOT / rel
        if full.is_file() and _should_pack_analysis_file(full, analysis_root):
            return "analysis_text"
    if path.suffix.lower() == ".py":
        if rel in _keep_scripts() or path.name in {"__init__.py", "__main__.py"}:
            return "script"
        if rel.startswith(_compile_prefixes()):
            return "compile"
    return "copy"


def iter_shippable_paths() -> list[tuple[str, Path]]:
    """Files a full Stage 1 would copy, excluding the bundled python tree."""
    root_files, allow_roots, deny_globs = load_manifests()
    found: list[tuple[str, Path]] = []
    for name in root_files:
        rel = name.replace("\\", "/")
        if is_denied(rel, deny_globs):
            continue
        path = REPO_ROOT / name
        if path.is_file():
            found.append((rel, path))
    for root_name in allow_roots:
        if root_name == "python":
            continue
        src_root = REPO_ROOT / root_name
        if not src_root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(src_root):
            base = Path(dirpath)
            keep_dirs: list[str] = []
            for dirname in dirnames:
                rel_dir = (base / dirname).relative_to(REPO_ROOT).as_posix()
                if is_denied(rel_dir, deny_globs) or is_denied(rel_dir + "/", deny_globs):
                    continue
                if dirname in {"__pycache__", ".pytest_cache", ".git", ".cursor"}:
                    continue
                keep_dirs.append(dirname)
            dirnames[:] = keep_dirs
            for filename in filenames:
                src = base / filename
                rel = src.relative_to(REPO_ROOT).as_posix()
                if is_denied(rel, deny_globs):
                    continue
                found.append((rel, src))
    return found


def collect_shippable() -> dict[str, dict]:
    """Hash every shippable source file. This includes gitignored bytes."""
    files: dict[str, dict] = {}
    paths = iter_shippable_paths()
    total = len(paths)
    for index, (rel, path) in enumerate(paths, start=1):
        if index == 1 or index % 400 == 0 or index == total:
            print(f"  hashing source {index}/{total}")
        files[rel] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "role": role_for(rel),
        }
    return files


def gitignored_paths(rels: list[str]) -> set[str]:
    """Return the subset of ``rels`` that git would not show in diff."""
    if not rels:
        return set()
    payload = ("\n".join(rels) + "\n").encode("utf-8")
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", "check-ignore", "--stdin"],
            input=payload,
            capture_output=True,
            cwd=REPO_ROOT,
            check=False,
        )
    except OSError as exc:
        print(f"WARN: git check-ignore failed: {exc}")
        return set()
    ignored: set[str] = set()
    text = proc.stdout.decode("utf-8", "replace").replace("\r", "")
    for line in text.split("\n"):
        item = line.strip().strip('"').replace("\\", "/")
        if item:
            ignored.add(item)
    return ignored


def load_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.is_file():
        return None
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def write_input_snapshot(files: dict[str, dict] | None = None) -> Path:
    from prune_python import SRC_PYTHON, iter_pruned_python_files

    if files is None:
        files = collect_shippable()
    rows: list[str] = []
    for src in iter_pruned_python_files():
        rel = src.relative_to(SRC_PYTHON).as_posix()
        st = src.stat()
        rows.append(f"{rel}|{st.st_size}|{st.st_mtime_ns}")
    rows.sort()
    fingerprint = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    payload = {
        "version": 1,
        "built_at_utc": _utc_now(),
        "source_root": str(REPO_ROOT),
        "python_fingerprint": fingerprint,
        "file_count": len(files),
        "files": files,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return SNAPSHOT_PATH
