"""Update an existing customer folder from changed source files only.

The full Stage 1–5 rebuild stays the first release. After
``release/portable/ManmabotV1`` exists, this command is the update path.

It does not use ``git diff``. Every shippable file is hashed, including
gitignored images, DLLs, EXEs, and batch files. Changed files are copied
or recompiled. Unchanged modules stay as they are.

Dev tree is never modified. Image encryption is unchanged: ``Engine/data``
stays a plain folder.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
if str(PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGING_DIR))

from build_release import PORTABLE_DIR, sha256_file, stage4  # noqa: E402
from compile_inplace import compile_one, detect_build_python, expected_pyd_for  # noqa: E402
from pack_assets import _engine_on_sys_path, _should_pack_analysis_file  # noqa: E402
from prune_python import (  # noqa: E402
    DST_PYTHON,
    SRC_PYTHON,
    _win_long,
    copy_python_pruned,
    iter_pruned_python_files,
    verify_runtime_imports,
)
from release_snapshot import (  # noqa: E402
    GENERATED_PORTABLE_NAMES,
    PLAN_PATH,
    collect_shippable,
    gitignored_paths,
    load_snapshot,
    write_input_snapshot,
)

_PYD_RE = re.compile(r"^(?P<stem>.+)\.cp\d+.*\.pyd$", re.I)
_ANALYSIS_PREFIX = "Engine/analysis/"
_VCVARS = Path(
    r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)


def _stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return os.stat(_win_long(path))


def pyds_for(py_rel: str) -> list[Path]:
    dest = PORTABLE_DIR / py_rel
    parent = dest.parent
    stem = dest.stem
    if not parent.is_dir():
        return []
    found: list[Path] = []
    for path in parent.glob(stem + "*.pyd"):
        if path.name == f"{stem}.pyd":
            found.append(path)
            continue
        match = _PYD_RE.match(path.name)
        if match and match.group("stem") == stem:
            found.append(path)
    return found


def _source_newer_than_pyd(src: Path, pyds: list[Path]) -> bool:
    if not pyds:
        return True
    newest = max(_stat(path).st_mtime for path in pyds)
    return src.stat().st_mtime > newest + 0.001


def _analysis_key(rel: str) -> str:
    return rel[len(_ANALYSIS_PREFIX) :]


def analysis_pack_matches(files: dict[str, dict]) -> bool:
    """True when portable analysis_text.pack matches current source texts."""
    pack = PORTABLE_DIR / "Engine" / "analysis_text.pack"
    if not pack.is_file():
        return False
    expected = {
        _analysis_key(rel): REPO_ROOT / rel
        for rel, info in files.items()
        if info["role"] == "analysis_text"
    }
    _engine_on_sys_path()
    from session.asset_pack_format import load_pack_bytes

    packed = load_pack_bytes(pack)
    if set(packed) != set(expected):
        return False
    for key, path in expected.items():
        if packed[key] != path.read_bytes():
            return False
    return True


def python_needs_recopy() -> list[str]:
    """Gitignored python\\ files whose size or mtime differ from the portable copy."""
    if not (DST_PYTHON / "python.exe").is_file():
        return ["python/python.exe missing"]
    changed: list[str] = []
    for src in iter_pruned_python_files():
        rel = "python/" + src.relative_to(SRC_PYTHON).as_posix()
        dst = DST_PYTHON / src.relative_to(SRC_PYTHON)
        if not dst.is_file():
            changed.append(rel)
            continue
        src_stat = src.stat()
        dst_stat = _stat(dst)
        if src_stat.st_size != dst_stat.st_size:
            changed.append(rel)
            continue
        if abs(src_stat.st_mtime - dst_stat.st_mtime) > 0.001:
            changed.append(rel)
    return changed


def _portable_copy_rels() -> list[str]:
    """Plain files in the customer tree that came from source (not generated)."""
    rels: list[str] = []
    roots = ["Engine", "UI", "Drivers"]
    for root_name in roots:
        base = PORTABLE_DIR / root_name
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in {"__pycache__", ".pytest_cache"}
            ]
            for filename in filenames:
                path = Path(dirpath) / filename
                if path.suffix.lower() == ".pyd":
                    continue
                rel = path.relative_to(PORTABLE_DIR).as_posix()
                if rel in {"Engine/analysis_text.pack", "Engine/data.pack"}:
                    continue
                rels.append(rel)
    for path in PORTABLE_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name in GENERATED_PORTABLE_NAMES:
            continue
        rels.append(path.name)
    return rels


def _py_rel_for_pyd(path: Path) -> str | None:
    match = _PYD_RE.match(path.name)
    stem = match.group("stem") if match else Path(path.name).stem if path.suffix.lower() == ".pyd" else None
    if stem is None:
        return None
    rel_py = path.relative_to(PORTABLE_DIR).with_name(stem + ".py")
    return rel_py.as_posix()


def build_plan(files: dict[str, dict], snapshot: dict | None) -> dict:
    snap_files = (snapshot or {}).get("files") or {}
    have_snapshot = bool(snap_files)
    copy_updates: list[str] = []
    script_updates: list[str] = []
    compile_updates: list[str] = []
    analysis_updates: list[str] = []
    removals: list[str] = []

    for rel, info in files.items():
        role = info["role"]
        src = REPO_ROOT / rel
        prev = snap_files.get(rel)
        if role == "analysis_text":
            if have_snapshot and prev and prev.get("sha256") == info["sha256"]:
                continue
            if have_snapshot:
                analysis_updates.append(rel)
            continue
        if role == "compile":
            pyds = pyds_for(rel)
            if have_snapshot:
                if not prev or prev.get("sha256") != info["sha256"] or not pyds:
                    compile_updates.append(rel)
            elif not pyds or _source_newer_than_pyd(src, pyds):
                compile_updates.append(rel)
            continue
        dest = PORTABLE_DIR / rel
        source_changed = not dest.is_file() or sha256_file(dest) != info["sha256"]
        if source_changed:
            if role == "script":
                script_updates.append(rel)
            else:
                copy_updates.append(rel)

    if have_snapshot:
        for rel, prev in snap_files.items():
            if rel not in files:
                removals.append(rel)
    else:
        current = set(files)
        for rel in _portable_copy_rels():
            if rel in current:
                continue
            if rel.startswith(_ANALYSIS_PREFIX):
                full = PORTABLE_DIR / rel
                analysis_root = PORTABLE_DIR / "Engine" / "analysis"
                if full.is_file() and _should_pack_analysis_file(full, analysis_root):
                    continue
            removals.append(rel)
        for path in (PORTABLE_DIR / "Engine").rglob("*.pyd"):
            py_rel = _py_rel_for_pyd(path)
            if py_rel and py_rel not in files:
                removals.append(path.relative_to(PORTABLE_DIR).as_posix())
        for path in (PORTABLE_DIR / "UI").rglob("*.pyd"):
            py_rel = _py_rel_for_pyd(path)
            if py_rel and py_rel not in files:
                removals.append(path.relative_to(PORTABLE_DIR).as_posix())

    text_removed = [
        rel
        for rel in removals
        if (snap_files.get(rel) or {}).get("role") == "analysis_text"
        or (
            rel.startswith(_ANALYSIS_PREFIX)
            and Path(rel).suffix.lower() in {".json", ".txt", ".yaml", ".yml", ".md", ".bak"}
        )
    ]
    if text_removed:
        analysis_updates.extend(text_removed)
        removals = [rel for rel in removals if rel not in set(text_removed)]

    pack_missing = not (PORTABLE_DIR / "Engine" / "analysis_text.pack").is_file()
    if have_snapshot:
        if pack_missing and not analysis_updates:
            analysis_updates = [
                rel for rel, info in files.items() if info["role"] == "analysis_text"
            ]
    elif not analysis_pack_matches(files):
        analysis_updates = [
            rel for rel, info in files.items() if info["role"] == "analysis_text"
        ]

    python_updates = python_needs_recopy()
    watched = copy_updates + script_updates + compile_updates + analysis_updates
    watched += [rel for rel in removals if not rel.endswith(".pyd")]
    watched += python_updates
    ignored = gitignored_paths(watched)
    return {
        "copy": sorted(copy_updates),
        "script": sorted(script_updates),
        "compile": sorted(compile_updates),
        "analysis": sorted(set(analysis_updates)),
        "remove": sorted(set(removals)),
        "python": python_updates,
        "gitignored": sorted(ignored),
    }


def _print_plan(plan: dict) -> None:
    groups = (
        ("copy", "복사"),
        ("script", "스크립트 유지"),
        ("compile", "다시 컴파일"),
        ("analysis", "analysis_text.pack"),
        ("remove", "릴리스에서 제거"),
        ("python", "python 런타임"),
    )
    lines = ["증분 릴리스 계획", ""]
    for key, label in groups:
        rows = plan[key]
        lines.append(f"[{label}] {len(rows)}")
        shown = rows if key != "python" or len(rows) <= 30 else rows[:30]
        for rel in shown:
            mark = "git-ignored" if rel in plan["gitignored"] else "tracked"
            lines.append(f"  {mark}  {rel}")
        if key == "python" and len(rows) > 30:
            lines.append(f"  ... 외 {len(rows) - 30}개. python 트리를 통째로 다시 복사합니다.")
        lines.append("")
    ignored_hits = [rel for rel in plan["gitignored"] if _plan_contains(plan, rel)]
    lines.append(f"git diff에 안 나오는 변경 {len(ignored_hits)}개 — 바뀌었으면 릴리스에 반영")
    text = "\n".join(lines) + "\n"
    print(text)
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(text, encoding="utf-8")
    print(f"계획 파일: {PLAN_PATH}")


def _plan_contains(plan: dict, rel: str) -> bool:
    return any(rel in plan[key] for key in ("copy", "script", "compile", "analysis", "remove", "python"))


def plan_is_empty(plan: dict) -> bool:
    return not any(plan[key] for key in ("copy", "script", "compile", "analysis", "remove", "python"))


def _ensure_msvc(compile_needed: bool) -> None:
    if not compile_needed or os.environ.get("MANMABOT_VCVARS") == "1":
        return
    if shutil.which("cl"):
        return
    if not _VCVARS.is_file():
        raise SystemExit("ERROR: cl.exe is not on PATH. Open the x64 Native Tools prompt.")
    script = Path(__file__).resolve()
    quoted = " ".join(f'"{arg}"' if " " in arg else arg for arg in sys.argv[1:])
    command = f'call "{_VCVARS}" && set MANMABOT_VCVARS=1 && "{sys.executable}" "{script}" {quoted}'
    raise SystemExit(subprocess.call(command, shell=True))


def _apply_copy(rel: str) -> None:
    src = REPO_ROOT / rel
    dest = PORTABLE_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)


def _apply_compile(rel: str, build_python: Path) -> None:
    dest = PORTABLE_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / rel, dest)
    try:
        produced = compile_one(build_python, dest, dry_run=False)
    finally:
        if dest.is_file():
            dest.unlink()
    for old in pyds_for(rel):
        if old.resolve() != produced.resolve():
            old.unlink()


def _apply_removal(rel: str) -> None:
    path = PORTABLE_DIR / rel
    if path.is_file():
        path.unlink()
    elif path.suffix.lower() == ".py":
        for pyd in pyds_for(rel):
            pyd.unlink()


def _rebuild_analysis_pack() -> None:
    _engine_on_sys_path()
    from session.asset_pack_format import build_pack

    analysis = REPO_ROOT / "Engine" / "analysis"
    pack_path = PORTABLE_DIR / "Engine" / "analysis_text.pack"
    with tempfile.TemporaryDirectory(prefix="manmabot_analysis_pack_") as tmp:
        staging = Path(tmp) / "analysis"
        staging.mkdir()
        count = 0
        for path in sorted(analysis.rglob("*")):
            if not _should_pack_analysis_file(path, analysis):
                continue
            rel = path.relative_to(analysis)
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            count += 1
        info = build_pack(staging, pack_path)
    removed = 0
    portable_analysis = PORTABLE_DIR / "Engine" / "analysis"
    if portable_analysis.is_dir():
        for path in list(portable_analysis.rglob("*")):
            if path.is_file() and _should_pack_analysis_file(path, portable_analysis):
                path.unlink()
                removed += 1
    print(f"  analysis_text.pack files={info.get('files', count)} removed_plain={removed}")


def _run_verify_shims() -> int:
    proc = subprocess.run(
        [sys.executable, str(PACKAGING_DIR / "verify_shims.py")],
        cwd=REPO_ROOT,
    )
    return proc.returncode


def reset_portable_userdata() -> int:
    """Drop this PC's accounts, logs, and schedules from the customer folder.

    The development ``UserData`` tree is not touched. ``defaults`` is kept.
    """
    userdata = PORTABLE_DIR / "UserData"
    if not userdata.is_dir():
        return 0
    removed = 0
    keep_dirs = {"defaults"}
    for path in list(userdata.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(userdata)
        if rel.parts and rel.parts[0] in keep_dirs:
            continue
        path.unlink()
        removed += 1
    for name in ("logs", "schedules", "trial", "maps"):
        (userdata / name).mkdir(parents=True, exist_ok=True)
    return removed


def apply_plan(plan: dict, *, zip_release: bool) -> int:
    if plan["script"] or plan["compile"]:
        if _run_verify_shims() != 0:
            return 1
    _ensure_msvc(bool(plan["compile"]))
    build_python = None
    if plan["compile"]:
        build_python = detect_build_python()
        from compile_inplace import ensure_nuitka

        ensure_nuitka(build_python)

    for rel in plan["remove"]:
        print(f"REMOVE {rel}")
        _apply_removal(rel)
    for rel in plan["copy"] + plan["script"]:
        print(f"COPY {rel}")
        _apply_copy(rel)
    for rel in plan["compile"]:
        print(f"COMPILE {rel}")
        assert build_python is not None
        _apply_compile(rel, build_python)
        produced = expected_pyd_for(PORTABLE_DIR / rel)
        if produced is None:
            print(f"ERROR: no .pyd for {rel}", file=sys.stderr)
            return 1
    if plan["analysis"]:
        print("PACK analysis_text")
        _rebuild_analysis_pack()
    if plan["python"]:
        print(f"PYTHON recopy ({len(plan['python'])} files differ)")
        result = copy_python_pruned(dry_run=False)
        print(f"  python files={result['copied_files']} mb={result['bytes_copied_mb']}")
        errors = verify_runtime_imports()
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print("  runtime import verify OK")

    removed_userdata = reset_portable_userdata()
    if removed_userdata:
        print(f"USERDATA cleared {removed_userdata} local files from the customer folder")
    code = stage4(dry_run=False, skip_sign=True)
    if code != 0:
        return code
    if zip_release:
        _write_zip()
    print("증분 릴리스 OK")
    print("  development tree was not modified")
    return 0


def _write_zip() -> None:
    import zipfile

    dest = REPO_ROOT / "release" / "ManmabotV1.zip"
    if dest.is_file():
        dest.unlink()
    print(f"ZIP {dest}")
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PORTABLE_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(PORTABLE_DIR).as_posix())
    print(f"  zip_bytes={dest.stat().st_size}")


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the change check, including gitignored files, and do not write the release",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="After a real update, write release\\ManmabotV1.zip next to the folder",
    )
    args = parser.parse_args(argv)

    if not PORTABLE_DIR.is_dir() or not (PORTABLE_DIR / "python" / "python.exe").is_file():
        print(
            "ERROR: no customer folder yet. The first release is the full playbook "
            "(build_release.py stages 1, 2, 3, 5, unpack, smoke, 4).",
            file=sys.stderr,
        )
        return 1

    print("증분 릴리스 — 소스 해시 비교 (git diff 사용 안 함)")
    files = collect_shippable()
    snapshot = load_snapshot()
    if snapshot is None:
        print("  기준 스냅샷 없음 — 고객 폴더의 파일·DLL·PNG와 .pyd 시각으로 비교")
    else:
        print(f"  기준 스냅샷 {snapshot.get('built_at_utc')} files={snapshot.get('file_count')}")
    plan = build_plan(files, snapshot)
    _print_plan(plan)
    if plan_is_empty(plan):
        if snapshot is None and not args.dry_run:
            path = write_input_snapshot(files)
            print(f"변경 없음. 기준 스냅샷을 기록했습니다: {path}")
        else:
            print("변경 없음. 고객 폴더는 그대로입니다.")
        return 0
    if args.dry_run:
        print("dry-run: 고객 폴더는 바꾸지 않았습니다.")
        return 0
    return apply_plan(plan, zip_release=args.zip)


if __name__ == "__main__":
    raise SystemExit(main())
