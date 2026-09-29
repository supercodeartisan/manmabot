"""Isolated, supervised adapter for the sibling autologin product."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from manmabot_v1.paths import USERDATA, app_root

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2
EXIT_CONFIG = 78
EXIT_CANCELLED = 130
_SUPERVISOR_STARTUP_GRACE_SECONDS = 10.0
_TERMINATE_GRACE_SECONDS = 5.0


def _child_exit_code(process, payload: dict) -> int:
    """Prefer the child's result file, then the real process exit code.

    ``process.poll() or EXIT_FAILED`` is wrong: a clean success (0) is
    falsy in Python and was recorded as failed.
    """
    if "exit_code" in payload:
        try:
            return int(payload["exit_code"])
        except (TypeError, ValueError):
            pass
    polled = process.poll()
    if polled is None:
        return EXIT_FAILED
    return int(polled)


class AutoLoginValidationError(RuntimeError):
    """The autologin installation or requested run is incomplete."""


@dataclass(frozen=True)
class AutoLoginRequest:
    user_id: str
    password: str
    server: str
    character_number: int = 1
    language: str = "ko"
    purple_launcher_path: str = ""
    game_path: str = ""
    click_mode: str = "dynamic"
    timeout_seconds: float = 600.0


@dataclass(frozen=True)
class AutoLoginResult:
    exit_code: int
    state: str
    detail: str
    run_dir: Path
    game_ready: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == EXIT_SUCCESS and self.game_ready


def resolve_autologin_root() -> Path:
    """Resolve only explicit or product-relative autologin installations."""
    env = os.environ.get("MANMA_AUTOLOGIN_ROOT", "").strip()
    candidates = [Path(env).expanduser()] if env else []
    root = app_root()
    candidates.extend((root / "autologin", root.parent / "autologin"))
    for candidate in candidates:
        if (candidate / "bot" / "bot2.py").is_file():
            return candidate.resolve()
    looked = ", ".join(str(p) for p in candidates)
    raise AutoLoginValidationError(
        "Autologin folder not found. Set MANMA_AUTOLOGIN_ROOT or place "
        f"'autologin' beside ManmabotV1. Checked: {looked}"
    )


def _protect_password(password: str) -> str:
    """Protect UTF-8 password bytes for the current Windows user with DPAPI."""
    if not password:
        raise AutoLoginValidationError("Purple password is required.")
    if os.name != "nt":
        raise AutoLoginValidationError("DPAPI password protection requires Windows.")

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    raw = password.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    source = DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.c_void_p))
    protected = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 0x01,
        ctypes.byref(protected)
    ):
        raise ctypes.WinError()
    try:
        return base64.b64encode(
            ctypes.string_at(protected.pbData, protected.cbData)
        ).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)


def _resolve_asset(root: Path, value: str, *, default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = root / "bot" / path
    return path.resolve()


def validate_autologin(
    root: Path, request: AutoLoginRequest
) -> tuple[dict, dict[str, Path]]:
    """Validate credentials, template, executable and every configured asset."""
    errors: list[str] = []
    if not request.user_id.strip():
        errors.append("Purple account ID/email is required.")
    if not request.password:
        errors.append("Purple password is required.")
    if not request.server.strip():
        errors.append("Lineage server name is required.")
    if not 1 <= request.character_number <= 3:
        errors.append("Character number must be from 1 to 3.")
    if request.timeout_seconds <= 0:
        errors.append("Timeout must be greater than zero.")

    entry = root / "bot" / "bot2.py"
    template_path = root / "launcher_config.json"
    if not entry.is_file():
        errors.append(f"Autologin entry point is missing: {entry}")
    template: dict = {}
    if not template_path.is_file():
        errors.append(f"Autologin template is missing: {template_path}")
    else:
        try:
            template = json.loads(template_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Autologin template is invalid: {template_path} ({exc})")

    login = dict(template.get("login") or {})
    assets = {
        "interception_dll": _resolve_asset(
            root, str(login.get("interception_dll") or ""),
            default="win/interception.dll"),
        "yolo_model": _resolve_asset(
            root, str(login.get("yolo_model") or ""),
            default="data/yolov8n.onnx"),
        "captcha_model": _resolve_asset(
            root, str(login.get("captcha_model") or ""),
            default="data/f.onnx"),
        "click_map": _resolve_asset(
            root, str(login.get("click_map") or ""),
            default="data/recorded_clicks.json"),
        "character_dir": _resolve_asset(
            root, str(login.get("character_dir") or ""),
            default="data/character"),
    }
    # CAPTCHA is deliberately optional. The solver and ONNX model are loaded
    # lazily only if CAPTCHA handling is invoked by a future login flow.
    required_assets = {
        name: path for name, path in assets.items() if name != "captcha_model"
    }
    for name, path in required_assets.items():
        expected = path.is_dir() if name == "character_dir" else path.is_file()
        if not expected:
            errors.append(
                f"Required autologin asset '{name}' is missing: {path}. "
                "Restore the asset or correct launcher_config.json."
            )

    purple_path = Path(
        request.purple_launcher_path
        or str(login.get("game_path") or template.get("purple_path") or "")
    )
    if not purple_path.is_file():
        errors.append(
            f"Purple executable is missing: {purple_path or '<not configured>'}. "
            "Correct the selected account or install NC Purple."
        )
    lineage_path = Path(request.game_path) if request.game_path else None
    if lineage_path is not None and not lineage_path.is_file():
        errors.append(
            f"Game executable is missing: {lineage_path}. "
            "Correct the selected account or install Lineage Classic."
        )
    if errors:
        raise AutoLoginValidationError("\n".join(errors))
    assets["game_path"] = purple_path.resolve()
    if lineage_path is not None:
        assets["lineage_path"] = lineage_path.resolve()
    return template, assets


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def build_transient_config(
    root: Path, run_dir: Path, request: AutoLoginRequest, template: dict,
    assets: dict[str, Path], *, protect: Callable[[str], str] = _protect_password
) -> Path:
    """Create the only secret-bearing file; password is always DPAPI ciphertext."""
    login = dict(template.get("login") or {})
    for key, path in assets.items():
        login[key] = str(path)
    login.update({
        "userID": request.user_id.strip(),
        "password_enc": protect(request.password),
        "language": request.language,
        "ocr_lang": request.language,
        "character_number": request.character_number,
        "click_mode": request.click_mode,
        "use_pipeline": bool(template.get("use_pipeline", True)),
        "lang_policy": template.get("lang_policy", "L0"),
        "position_dict_writable": False,
        "require_elevation": True,
        "require_game_path": True,
    })
    login.pop("password", None)
    words = dict(login.get("words") or {})
    words["server_name"] = [request.server.strip()]
    login["words"] = words
    config_path = run_dir / "autologin.json"
    _atomic_write_json(config_path, login)
    return config_path


class _ElevatedProcess:
    """Small Popen-like wrapper around a ShellExecuteEx process handle."""

    def __init__(self, handle: int):
        self._handle = handle

    def poll(self) -> Optional[int]:
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            raise ctypes.WinError()
        return None if code.value == 259 else int(code.value)

    def terminate(self) -> None:
        if self.poll() is None:
            ctypes.windll.kernel32.TerminateProcess(self._handle, EXIT_CANCELLED)

    def close(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = 0


def _is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _launch_elevated(executable: Path, args: list[str], cwd: Path):
    class SHELLEXECUTEINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong),
            ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
            ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
            ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
            ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
            ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
            ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p),
            ("hProcess", ctypes.c_void_p),
        ]

    info = SHELLEXECUTEINFO()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = str(executable)
    info.lpParameters = subprocess.list2cmdline(args)
    info.lpDirectory = str(cwd)
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError()
    return _ElevatedProcess(int(info.hProcess))


def _default_game_ready() -> bool:
    from manmabot_v1.probes import probe_game

    game = probe_game("LC.exe")
    return bool(game.hwnd and not game.minimized)


class AutoLoginService:
    """Create, supervise and clean one isolated autologin run."""

    def __init__(
        self, *, root: Optional[Path] = None,
        game_ready: Callable[[], bool] = _default_game_ready,
        launcher: Optional[Callable[[Path, list[str], Path], object]] = None,
        password_protector: Callable[[str], str] = _protect_password,
    ):
        self.root = (root or resolve_autologin_root()).resolve()
        self._game_ready = game_ready
        self._launcher = launcher
        self._password_protector = password_protector

    def _new_run_dir(self) -> Path:
        base = USERDATA / "autologin_runs"
        base.mkdir(parents=True, exist_ok=True)
        run_dir = base / uuid.uuid4().hex
        run_dir.mkdir()
        return run_dir

    def run(
        self, request: AutoLoginRequest,
        *, cancel_event: Optional[threading.Event] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> AutoLoginResult:
        run_dir = self._new_run_dir()
        config_path = run_dir / "autologin.json"
        status_path = run_dir / "status.json"
        result_path = run_dir / "result.json"
        cancel_path = run_dir / "cancel"
        process = None
        try:
            template, assets = validate_autologin(self.root, request)
            try:
                config_path = build_transient_config(
                    self.root, run_dir, request, template, assets,
                    protect=self._password_protector,
                )
            except AutoLoginValidationError:
                raise
            except Exception as exc:
                raise AutoLoginValidationError(
                    f"Could not protect the Purple password with DPAPI: {exc}"
                ) from exc
            python = app_root() / "python" / "python.exe"
            if not python.is_file():
                python = Path(sys.executable)
            args = [
                str(self.root / "bot" / "bot2.py"), str(config_path),
                "--timeout", str(request.timeout_seconds),
                "--status-path", str(status_path),
                "--result-path", str(result_path),
                "--cancel-path", str(cancel_path),
                "--no-self-elevate",
            ]
            if self._launcher is not None:
                process = self._launcher(python, args, self.root / "bot")
            elif os.name == "nt" and not _is_elevated():
                process = _launch_elevated(python, args, self.root / "bot")
            else:
                process = subprocess.Popen(
                    [str(python), *args], cwd=str(self.root / "bot"),
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )

            deadline = (
                time.monotonic() + request.timeout_seconds
                + _SUPERVISOR_STARTUP_GRACE_SECONDS
            )
            cancel_sent = False
            timed_out = False
            last_status = ""
            while process.poll() is None:
                if on_status is not None and status_path.is_file():
                    try:
                        status = json.loads(status_path.read_text(encoding="utf-8"))
                        rendered = " · ".join(
                            part for part in (
                                str(status.get("state") or ""),
                                str(status.get("phase") or ""),
                                str(status.get("detail") or ""),
                            ) if part
                        )
                        if rendered and rendered != last_status:
                            last_status = rendered
                            on_status(rendered)
                    except (OSError, json.JSONDecodeError):
                        pass
                if cancel_event is not None and cancel_event.is_set():
                    cancel_path.touch(exist_ok=True)
                    cancel_sent = True
                if time.monotonic() >= deadline:
                    cancel_path.touch(exist_ok=True)
                    timed_out = True
                    break
                time.sleep(0.1)

            if process.poll() is None:
                grace = time.monotonic() + _TERMINATE_GRACE_SECONDS
                while process.poll() is None and time.monotonic() < grace:
                    time.sleep(0.1)
            if process.poll() is None:
                # Terminate only the exact process handle created for this run.
                process.terminate()

            payload = {}
            if result_path.is_file():
                try:
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    payload = {}
            code = _child_exit_code(process, payload)
            if timed_out:
                code = EXIT_TIMEOUT
            elif cancel_sent:
                code = EXIT_CANCELLED
            ready = code == EXIT_SUCCESS and self._game_ready()
            if code == EXIT_SUCCESS and not ready:
                code = EXIT_FAILED
                detail = "Autologin exited successfully, but no ready LC.exe game window was found."
            else:
                detail = str(payload.get("detail") or "")
            state = {
                EXIT_SUCCESS: "success", EXIT_TIMEOUT: "timeout",
                EXIT_CANCELLED: "cancelled", EXIT_CONFIG: "config_error",
            }.get(code, "failed")
            final_payload = {
                "version": 1,
                "state": state,
                "exit_code": code,
                "detail": detail,
                "game_ready": ready,
                "finished_at": time.time(),
            }
            _atomic_write_json(status_path, final_payload)
            _atomic_write_json(result_path, final_payload)
            return AutoLoginResult(code, state, detail, run_dir, ready)
        except AutoLoginValidationError as exc:
            failure = {
                "version": 1, "state": "config_error",
                "exit_code": EXIT_CONFIG, "detail": str(exc),
                "game_ready": False, "finished_at": time.time(),
            }
            _atomic_write_json(status_path, failure)
            _atomic_write_json(result_path, failure)
            return AutoLoginResult(
                EXIT_CONFIG, "config_error", str(exc), run_dir, False
            )
        except Exception as exc:
            detail = f"Could not launch or supervise autologin: {exc}"
            failure = {
                "version": 1, "state": "failed",
                "exit_code": EXIT_FAILED, "detail": detail,
                "game_ready": False, "finished_at": time.time(),
            }
            _atomic_write_json(status_path, failure)
            _atomic_write_json(result_path, failure)
            return AutoLoginResult(
                EXIT_FAILED, "failed", detail, run_dir, False
            )
        finally:
            # Delete ciphertext and cancellation control data; status/result are
            # deliberately retained for diagnostics and contain no credentials.
            for secret_path in (config_path, cancel_path):
                try:
                    secret_path.unlink()
                except FileNotFoundError:
                    pass
            if process is not None and hasattr(process, "close"):
                process.close()


def purge_run(run_dir: Path) -> None:
    """Explicitly remove retained non-secret diagnostics for a completed run."""
    shutil.rmtree(run_dir, ignore_errors=True)
