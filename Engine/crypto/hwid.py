"""HWID helper (READY Phase 1 Spec §4). MachineGuid required."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass

from .errors import CryptoError


class HwidError(CryptoError):
    pass


@dataclass(frozen=True)
class HwidParts:
    machine_guid: str
    volume_serial: str  # fixed-width hex
    bios_uuid: str | None  # normalized or None if absent
    bios_uuid_present: bool

    def material(self) -> str:
        bios = self.bios_uuid if self.bios_uuid_present and self.bios_uuid else ""
        return f"{self.machine_guid}|{self.volume_serial}|{bios}"

    def sha256_hex(self) -> str:
        return hashlib.sha256(self.material().encode("utf-8")).hexdigest()


def _normalize_bios_uuid(raw: str | None) -> tuple[str | None, bool]:
    if raw is None:
        return None, False
    s = raw.strip()
    if not s or s in ("{", "}") or s.upper() in ("NONE", "NULL", "N/A"):
        return None, False
    # Strip braces / spaces; keep hex+hyphen form if possible.
    s = s.strip("{}").strip()
    s = s.lower()
    if re.fullmatch(r"[0-9a-f]{32}", s):
        s = f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"
    if not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s
    ):
        # Present but malformed — still record as present for binding strictness;
        # store normalized lowercase stripped form.
        return s, True
    return s, True


def _read_machine_guid() -> str:
    if sys.platform != "win32":
        raise HwidError("MachineGuid requires Windows")
    try:
        import winreg
    except ImportError as e:
        raise HwidError("winreg unavailable") from e
    key_path = r"SOFTWARE\Microsoft\Cryptography"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            val, _ = winreg.QueryValueEx(k, "MachineGuid")
    except OSError as e:
        raise HwidError("MachineGuid missing") from e
    if not isinstance(val, str) or not val.strip():
        raise HwidError("MachineGuid empty")
    return val.strip().lower()


def _read_volume_serial() -> str:
    """System drive volume serial as 8-digit lowercase hex (fixed width)."""
    if sys.platform != "win32":
        return "00000000"
    import ctypes

    root = ctypes.create_unicode_buffer("C:\\")
    serial = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        root,
        None,
        0,
        ctypes.byref(serial),
        None,
        None,
        None,
        0,
    )
    if not ok:
        # Still require a fixed-width field; zeros if unreadable would weaken
        # identity — prefer error for system drive failure.
        raise HwidError("volume serial unreadable")
    return f"{serial.value:08x}"


def _read_bios_uuid() -> str | None:
    if sys.platform != "win32":
        return None
    # Prefer UUID from Windows; fall back to WMI if needed.
    try:
        # uuid.getnode is MAC — not BIOS. Use WMI via ctypes/com is heavy;
        # try powershell-less: SMBIOS via GetSystemFirmwareTable is complex.
        # Use a light WMI query through win32com if present; else ctypes+wbem.
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode == 0:
            line = (r.stdout or "").strip().splitlines()
            if line:
                return line[-1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def collect_hwid() -> HwidParts:
    machine = _read_machine_guid()
    vol = _read_volume_serial()
    bios_raw = _read_bios_uuid()
    bios, present = _normalize_bios_uuid(bios_raw)
    return HwidParts(
        machine_guid=machine,
        volume_serial=vol,
        bios_uuid=bios,
        bios_uuid_present=present,
    )


def device_id_from_spki(spki_der: bytes) -> str:
    return hashlib.sha256(spki_der).hexdigest()
