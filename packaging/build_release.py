"""Build customer release artifacts without modifying the development tree.

Stage 0: validate manifests + write release/version-info/BUILD.json
Stage 1: clean portable copy under release/portable/ManmabotV1/
Stage 2: in-place Nuitka --module compile inside the portable tree
Stage 3: prune/copy python runtime
Stage 4: checksums + optional Authenticode signing
Stage 5: obfuscated Engine/data (+ analysis text) packs; strip plain assets
         (run after Stage 3, before Stage 4 so checksums match final bits)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable


PRODUCT_NAME = "ManmabotV1"
PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent
MANIFEST_DIR = PACKAGING_DIR / "manifests"
TEMPLATE_DIR = PACKAGING_DIR / "templates"
RELEASE_DIR = REPO_ROOT / "release"
PORTABLE_DIR = RELEASE_DIR / "portable" / PRODUCT_NAME
CHECKSUMS_DIR = RELEASE_DIR / "checksums"
VERSION_DIR = RELEASE_DIR / "version-info"


def _read_list(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        lines.append(text.replace("\\", "/"))
    return lines


def load_manifests() -> tuple[list[str], list[str], list[str]]:
    root_files = _read_list(MANIFEST_DIR / "root_files.txt")
    allow_roots = _read_list(MANIFEST_DIR / "allow_roots.txt")
    deny_globs = _read_list(MANIFEST_DIR / "deny_globs.txt")
    return root_files, allow_roots, deny_globs


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_denied(rel: str, deny_globs: list[str]) -> bool:
    """Return True if relative path (posix) should not be shipped."""
    name = Path(rel).name
    parts = rel.split("/")
    for pattern in deny_globs:
        p = pattern.replace("\\", "/")
        if p.endswith("/"):
            prefix = p.rstrip("/")
            if prefix.startswith("**/"):
                token = prefix[3:]
                if token in parts:
                    return True
                continue
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
            continue
        if any(ch in p for ch in "*?["):
            if fnmatch(rel, p) or fnmatch(name, p):
                return True
            if p.startswith("**/"):
                rest = p[3:]
                if fnmatch(name, rest) or fnmatch(rel, p):
                    return True
                # Match "*.ext" against basename when pattern is "**/*.ext"
                if rest.startswith("*.") and fnmatch(name, rest):
                    return True
            continue
        if rel == p or rel.startswith(p.rstrip("/") + "/"):
            return True
    return False


def validate_manifests(
    root_files: list[str], allow_roots: list[str], deny_globs: list[str]
) -> list[str]:
    errors: list[str] = []
    for name in root_files:
        if not (REPO_ROOT / name).exists():
            errors.append(f"missing root file: {name}")
    for name in allow_roots:
        if not (REPO_ROOT / name).is_dir():
            errors.append(f"missing allow root dir: {name}")
    if "Tools" in allow_roots:
        errors.append("Tools must not be in allow_roots (customer pack excludes Tools)")
    tool_bats = [n for n in root_files if n.startswith("Tool_")]
    if tool_bats:
        errors.append(f"Tool bats must not be in root_files: {tool_bats}")
    if not deny_globs:
        errors.append("deny_globs.txt is empty")
    return errors


def write_version_info(stage: int, *, extra: dict | None = None) -> Path:
    VERSION_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "product": PRODUCT_NAME,
        "stage": stage,
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_root": str(REPO_ROOT),
        "packaging": {
            "compile": "nuitka-module-in-place",
            "tools_in_customer_pack": False,
            "preserve_dev_tree": True,
        },
        "output": {
            "portable": str(PORTABLE_DIR),
            "checksums": str(CHECKSUMS_DIR),
        },
    }
    if extra:
        payload.update(extra)
    out = VERSION_DIR / "BUILD.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _win_long(path: Path) -> str:
    """``\\\\?\\`` prefix so deep PySide trees delete on Windows."""
    text = str(path.resolve())
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\" + text


def clean_portable(*, dry_run: bool) -> None:
    if PORTABLE_DIR.exists():
        if dry_run:
            print(f"[dry-run] rmtree {PORTABLE_DIR}")
            return
        # Long paths under portable/python/.../PySide6/qml can fail plain rmtree
        # with WinError 145; extended paths match prune_python.py.
        shutil.rmtree(_win_long(PORTABLE_DIR))


def copy_file(src: Path, dst: Path, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] copy file {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # prune denied directory names early for speed
        base = Path(dirpath)
        keep: list[str] = []
        for d in dirnames:
            rel = rel_posix(base / d, REPO_ROOT)
            # temporary deny check on dir path with trailing semantics
            if is_denied(rel, _ACTIVE_DENY) or is_denied(rel + "/", _ACTIVE_DENY):
                continue
            if d in {"__pycache__", ".pytest_cache", ".git", ".cursor"}:
                continue
            keep.append(d)
        dirnames[:] = keep
        for name in filenames:
            yield base / name


_ACTIVE_DENY: list[str] = []


def copy_tree_filtered(
    src_root: Path,
    dst_root: Path,
    deny_globs: list[str],
    *,
    dry_run: bool,
    stats: dict[str, int],
) -> None:
    global _ACTIVE_DENY
    _ACTIVE_DENY = deny_globs
    for src in iter_files(src_root):
        rel = rel_posix(src, REPO_ROOT)
        if is_denied(rel, deny_globs):
            stats["denied"] += 1
            continue
        dst = dst_root / src.relative_to(src_root)
        if dry_run:
            stats["files"] += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        stats["files"] += 1


def seed_userdata(*, dry_run: bool) -> None:
    """Create empty UserData skeleton; copy defaults if present."""
    dst = PORTABLE_DIR / "UserData"
    defaults_src = REPO_ROOT / "UserData" / "defaults"
    if dry_run:
        print(f"[dry-run] seed UserData under {dst}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "logs").mkdir(exist_ok=True)
    (dst / "schedules").mkdir(exist_ok=True)
    (dst / "trial").mkdir(exist_ok=True)
    (dst / "maps").mkdir(exist_ok=True)
    if defaults_src.is_dir():
        shutil.copytree(defaults_src, dst / "defaults", dirs_exist_ok=True)


def write_customer_readme(*, dry_run: bool) -> None:
    src = TEMPLATE_DIR / "CUSTOMER_README.txt"
    dst = PORTABLE_DIR / "README.txt"
    if dry_run:
        print(f"[dry-run] write {dst}")
        return
    shutil.copy2(src, dst)


def write_portable_marker(*, dry_run: bool) -> None:
    dst = PORTABLE_DIR / ".portable"
    if dry_run:
        print(f"[dry-run] write {dst}")
        return
    dst.write_text("1\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_checksums(*, dry_run: bool) -> Path | None:
    if dry_run:
        print(f"[dry-run] checksums -> {CHECKSUMS_DIR / 'SHA256SUMS'}")
        return None
    if not PORTABLE_DIR.is_dir():
        raise RuntimeError(f"portable tree missing: {PORTABLE_DIR}")
    CHECKSUMS_DIR.mkdir(parents=True, exist_ok=True)
    out = CHECKSUMS_DIR / "SHA256SUMS"
    lines: list[str] = []
    count = 0
    for path in sorted(PORTABLE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PORTABLE_DIR).as_posix()
        # Avoid hashing the checksum file itself (rewritten below).
        if rel in {"SHA256SUMS.txt", "SHA256SUMS"}:
            continue
        lines.append(f"{sha256_file(path)}  {rel}")
        count += 1
    body = "\n".join(lines) + ("\n" if lines else "")
    out.write_text(body, encoding="utf-8")
    # Customer-facing copy inside the portable folder.
    (PORTABLE_DIR / "SHA256SUMS.txt").write_text(body, encoding="utf-8")
    meta = CHECKSUMS_DIR / "SHA256SUMS.meta.json"
    meta.write_text(
        json.dumps(
            {
                "algorithm": "SHA256",
                "file_count": count,
                "portable": str(PORTABLE_DIR),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"  checksums: {count} files -> {out}")
    return out


def stage5(*, dry_run: bool, checksums: bool) -> int:
    from pack_assets import pack_portable_assets

    if not PORTABLE_DIR.is_dir():
        print(f"ERROR: portable tree missing: {PORTABLE_DIR}", file=sys.stderr)
        return 1

    print(f"Stage 5 — obfuscated asset packs -> {PORTABLE_DIR / 'Engine'}")
    try:
        result = pack_portable_assets(dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: asset pack failed: {exc}", file=sys.stderr)
        return 1

    data = result.get("data") or {}
    analysis = result.get("analysis_text") or {}
    if data.get("skipped"):
        print(f"  data: skipped ({data.get('reason')})")
    elif data.get("dry_run"):
        print(f"  data: dry-run files={data.get('files')}")
    else:
        print(
            f"  data: files={data.get('files')} pack_bytes={data.get('pack_bytes')} "
            f"removed_plain={data.get('removed_plain')}"
        )
    if analysis.get("skipped"):
        print(f"  analysis_text: skipped ({analysis.get('reason')})")
    elif analysis.get("dry_run"):
        print(f"  analysis_text: dry-run files={analysis.get('files')}")
    else:
        print(
            f"  analysis_text: files={analysis.get('files')} "
            f"pack_bytes={analysis.get('pack_bytes')} "
            f"removed_plain_files={analysis.get('removed_plain_files')}"
        )

    if not dry_run:
        data_pack = PORTABLE_DIR / "Engine" / "data.pack"
        analysis_pack = PORTABLE_DIR / "Engine" / "analysis_text.pack"
        if not data_pack.is_file():
            print("ERROR: Engine/data.pack missing after Stage 5", file=sys.stderr)
            return 1
        if not analysis_pack.is_file():
            print(
                "ERROR: Engine/analysis_text.pack missing after Stage 5",
                file=sys.stderr,
            )
            return 1

    write_version_info(5, extra={"asset_packs": result})
    if checksums and not dry_run:
        write_checksums(dry_run=False)
    print("Stage 5 OK")
    print("  development tree was not modified")
    return 0


def stage4(*, dry_run: bool, skip_sign: bool) -> int:
    from sign_release import sign_targets

    if not PORTABLE_DIR.is_dir():
        print(f"ERROR: portable tree missing: {PORTABLE_DIR}", file=sys.stderr)
        return 1

    print(f"Stage 4 — checksums + optional signing -> {PORTABLE_DIR}")
    sign_result: dict = {"enabled": False, "skipped": True}
    if not skip_sign:
        try:
            sign_result = sign_targets(dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: signing failed: {exc}", file=sys.stderr)
            return 1
        if sign_result.get("failed"):
            for item in sign_result["failed"]:
                print(f"ERROR: {item}", file=sys.stderr)
            return 1
        print(f"  signing: {sign_result.get('message') or sign_result}")
    else:
        print("  signing: skipped (--skip-sign)")

    # Always hash AFTER signing so digests match the final bits.
    checksum_path = write_checksums(dry_run=dry_run)
    write_version_info(
        4,
        extra={
            "signing": sign_result,
            "checksums": str(checksum_path) if checksum_path else None,
        },
    )
    print("Stage 4 OK")
    print("  development tree was not modified")
    return 0


def stage0(deny_ok: bool = True) -> int:
    root_files, allow_roots, deny_globs = load_manifests()
    errors = validate_manifests(root_files, allow_roots, deny_globs)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    out = write_version_info(
        0,
        extra={
            "manifest": {
                "root_files": root_files,
                "allow_roots": allow_roots,
                "deny_rule_count": len(deny_globs),
            }
        },
    )
    print(f"Stage 0 OK — manifests valid")
    print(f"  wrote {out}")
    print(f"  root_files={len(root_files)} allow_roots={allow_roots}")
    print(f"  deny_rules={len(deny_globs)} deny_ok={deny_ok}")
    return 0


def stage1(*, dry_run: bool, skip_python: bool, checksums: bool) -> int:
    root_files, allow_roots, deny_globs = load_manifests()
    errors = validate_manifests(root_files, allow_roots, deny_globs)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if skip_python:
        allow_roots = [r for r in allow_roots if r != "python"]

    started = time.time()
    print(f"Stage 1 — portable copy -> {PORTABLE_DIR}")
    if dry_run:
        print("  mode: dry-run")
    if skip_python:
        print("  skip-python: yes")

    clean_portable(dry_run=dry_run)
    if not dry_run:
        PORTABLE_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"files": 0, "denied": 0, "root": 0}

    for name in root_files:
        src = REPO_ROOT / name
        if not src.exists():
            print(f"WARN: skip missing {name}", file=sys.stderr)
            continue
        if is_denied(name.replace("\\", "/"), deny_globs):
            stats["denied"] += 1
            continue
        copy_file(src, PORTABLE_DIR / name, dry_run=dry_run)
        stats["root"] += 1

    for root_name in allow_roots:
        src_root = REPO_ROOT / root_name
        dst_root = PORTABLE_DIR / root_name
        print(f"  copying {root_name}\\ ...")
        copy_tree_filtered(
            src_root, dst_root, deny_globs, dry_run=dry_run, stats=stats
        )

    seed_userdata(dry_run=dry_run)
    write_customer_readme(dry_run=dry_run)
    write_portable_marker(dry_run=dry_run)

    checksum_path = None
    if checksums and not dry_run:
        print("  writing checksums...")
        checksum_path = write_checksums(dry_run=False)

    write_version_info(
        1,
        extra={
            "stats": stats,
            "skip_python": skip_python,
            "dry_run": dry_run,
            "checksums": str(checksum_path) if checksum_path else None,
            "elapsed_s": round(time.time() - started, 2),
        },
    )

    print(
        f"Stage 1 OK — files={stats['files']} root={stats['root']} "
        f"denied={stats['denied']} elapsed={time.time() - started:.1f}s"
    )
    if not dry_run:
        print(f"  portable: {PORTABLE_DIR}")
        print("  development tree was not modified")
    return 0


def stage2(
    *,
    dry_run: bool,
    limit: int | None,
    packages: str,
    no_strip: bool,
    checksums: bool,
) -> int:
    # Local helper (folder name "packaging" must not be confused with PyPI packaging).
    from compile_inplace import compile_inplace

    only = {p.strip() for p in packages.split(",") if p.strip()} or None
    print(f"Stage 2 — in-place Nuitka compile -> {PORTABLE_DIR}")
    result = compile_inplace(
        dry_run=dry_run,
        limit=limit,
        only_packages=only,
        strip=not no_strip,
    )
    write_version_info(2, extra={"compile": result})
    if result.get("failed"):
        for item in result["failed"]:
            print(f"ERROR: {item}", file=sys.stderr)
        return 1
    if checksums and not dry_run:
        write_checksums(dry_run=False)
    print(
        f"Stage 2 OK — compiled={result['compiled']} "
        f"stripped_py={result['stripped_py']} elapsed={result['elapsed_s']}s"
    )
    print("  development tree was not modified")
    return 0


def stage3(*, dry_run: bool, checksums: bool, no_verify: bool) -> int:
    from prune_python import copy_python_pruned, verify_runtime_imports

    print(f"Stage 3 — prune/copy python runtime -> {PORTABLE_DIR / 'python'}")
    result = copy_python_pruned(dry_run=dry_run)
    write_version_info(3, extra={"python_prune": result})
    print(
        f"Stage 3 copy OK — files={result['copied_files']} "
        f"mb={result['bytes_copied_mb']} skipped_pkg={result['skipped_packages']} "
        f"elapsed={result['elapsed_s']}s"
    )
    if dry_run:
        return 0
    if not no_verify:
        errors = verify_runtime_imports()
        if errors:
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        print("  runtime import verify OK")
    if checksums:
        write_checksums(dry_run=False)
    print("  development tree was not modified")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manmabot customer release builder (dev tree preserved)."
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=(0, 1, 2, 3, 4, 5),
        default=0,
        help=(
            "0=validate; 1=copy; 2=compile; 3=prune python; "
            "5=asset packs; 4=checksums/sign (run 5 before 4)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing portable payload",
    )
    parser.add_argument(
        "--skip-python",
        action="store_true",
        help="Do not copy the bundled python\\ tree (faster smoke test)",
    )
    parser.add_argument(
        "--no-checksums",
        action="store_true",
        help="Skip SHA256SUMS generation on stages that support it",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stage 2: compile at most N modules (smoke test)",
    )
    parser.add_argument(
        "--packages",
        default="",
        help="Stage 2: comma-separated package names (e.g. session,i18n)",
    )
    parser.add_argument(
        "--no-strip",
        action="store_true",
        help="Stage 2: keep .py after producing .pyd",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Stage 3: skip import verification",
    )
    parser.add_argument(
        "--skip-sign",
        action="store_true",
        help="Stage 4: never attempt Authenticode signing",
    )
    args = parser.parse_args(argv)

    if args.stage == 0:
        return stage0()
    if args.stage == 1:
        return stage1(
            dry_run=args.dry_run,
            skip_python=args.skip_python,
            checksums=not args.no_checksums,
        )
    if args.stage == 2:
        return stage2(
            dry_run=args.dry_run,
            limit=args.limit,
            packages=args.packages,
            no_strip=args.no_strip,
            checksums=not args.no_checksums,
        )
    if args.stage == 3:
        return stage3(
            dry_run=args.dry_run,
            checksums=not args.no_checksums,
            no_verify=args.no_verify,
        )
    if args.stage == 5:
        return stage5(dry_run=args.dry_run, checksums=not args.no_checksums)
    return stage4(dry_run=args.dry_run, skip_sign=args.skip_sign)


if __name__ == "__main__":
    # Make `import compile_inplace` work when run as a script.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
