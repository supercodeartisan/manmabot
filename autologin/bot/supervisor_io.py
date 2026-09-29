"""Supervisor contract for Manmabot: flags, status files, exit codes."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_CONFIG = 78
EXIT_CANCELLED = 130


@dataclass(frozen=True)
class SupervisorArgs:
    config: str
    timeout: float
    status_path: str
    result_path: str
    cancel_path: str
    no_self_elevate: bool
    elevated_relaunch: bool


def parse_supervisor_args(argv: list[str], *, default_config: str) -> SupervisorArgs:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("config", nargs="?", default=default_config)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--status-path", default="")
    parser.add_argument("--result-path", default="")
    parser.add_argument("--cancel-path", default="")
    parser.add_argument("--no-self-elevate", action="store_true")
    parser.add_argument("--elevated-relaunch", action="store_true")
    parser.add_argument("--bot2", action="store_true")
    parsed, _unknown = parser.parse_known_args(argv)
    timeout = float(parsed.timeout)
    if timeout <= 0:
        timeout = 600.0
    return SupervisorArgs(
        config=str(parsed.config or default_config),
        timeout=timeout,
        status_path=str(parsed.status_path or ""),
        result_path=str(parsed.result_path or ""),
        cancel_path=str(parsed.cancel_path or ""),
        no_self_elevate=bool(parsed.no_self_elevate),
        elevated_relaunch=bool(parsed.elevated_relaunch),
    )


def write_run_payload(path: str, *, state: str, exit_code: int, detail: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "state": state,
        "exit_code": int(exit_code),
        "detail": str(detail or ""),
        "finished_at": time.time(),
    }
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def cancel_requested(cancel_path: str) -> bool:
    return bool(cancel_path) and Path(cancel_path).is_file()


def exit_code_for(state: str) -> int:
    return {
        "success": EXIT_SUCCESS,
        "timeout": EXIT_TIMEOUT,
        "cancelled": EXIT_CANCELLED,
        "config_error": EXIT_CONFIG,
    }.get(state, EXIT_FAILED)


def publish_run(
    args: SupervisorArgs, *, state: str, detail: str = ""
) -> int:
    code = exit_code_for(state)
    payload = {"state": state, "exit_code": code, "detail": detail}
    write_run_payload(args.status_path, **payload)
    write_run_payload(args.result_path, **payload)
    return code
