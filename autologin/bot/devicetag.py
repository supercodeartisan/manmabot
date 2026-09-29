"""Device-tag (NCSDK.sdkdata_deviceTag) backup / restore.

The Purple SDK writes the deviceTag registry value only after a full login into
the game world completes; it stays empty during/right after launcher login. If
the value is lost the game may re-run machine registration (SMS) on the next
login. This module snapshots a good value and can restore it before login.
"""
import json
import logging
import os
import time
import winreg

log = logging.getLogger("devicetag")

DEVICE_TAG_NAME = "NCSDK.sdkdata_deviceTag"
APP_KEY = r"Software\NCSoft\PLATFORM\APPS\047850D2-50FD-4405-AC24-0B1D107A7C5D"
APP_KEY_ALT = r"Software\NCSOFT\PLATFORM\APPS\047850D2-50FD-4405-AC24-0B1D107A7C5D"
BACKUP_FILENAME = "device_token.json"


def read_device_tag() -> str:
    """Return the current deviceTag (first hive that has it), or ''."""
    for sub in (APP_KEY, APP_KEY_ALT):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_READ) as k:
                val, _ = winreg.QueryValueEx(k, DEVICE_TAG_NAME)
                if val:
                    return val
        except OSError:
            continue
    return ""


def write_device_tag(value: str):
    """Write deviceTag into both hives (create keys as needed)."""
    if not value:
        return
    for sub in (APP_KEY, APP_KEY_ALT):
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, sub, 0,
                                    winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, DEVICE_TAG_NAME, 0, winreg.REG_SZ, value)
        except OSError as e:
            log.warning(f"failed to write deviceTag to {sub}: {e}")


def backup_path(base_dir: str | None = None) -> str:
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, BACKUP_FILENAME)


def backup_device_tag(base_dir: str | None = None) -> str:
    """Snapshot the current deviceTag (if non-empty) to a JSON file."""
    tag = read_device_tag()
    if not tag:
        log.info("deviceTag is empty right now; nothing to back up")
        return ""
    p = backup_path(base_dir)
    record = {
        "backed_up_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deviceTag": tag,
        "registry_value": APP_KEY + "\\" + DEVICE_TAG_NAME,
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    log.info(f"deviceTag backed up -> {p}")
    return tag


def restore_device_tag(base_dir: str | None = None) -> str:
    """Restore a previously backed-up deviceTag if the live one is empty."""
    p = backup_path(base_dir)
    if not os.path.exists(p):
        log.info("no deviceTag backup yet")
        return ""
    try:
        with open(p, "r", encoding="utf-8") as f:
            record = json.load(f)
    except Exception as e:
        log.warning(f"failed to read deviceTag backup {p}: {e}")
        return ""
    tag = record.get("deviceTag", "")
    if not tag:
        return ""
    live = read_device_tag()
    if live:
        log.info(f"live deviceTag already set ({len(live)} chars); no restore needed")
        return live
    write_device_tag(tag)
    log.info(f"restored deviceTag from backup ({len(tag)} chars)")
    return tag


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        tag = read_device_tag()
        print(f"current deviceTag: {tag or '(empty)'}")
    elif cmd == "backup":
        backup_device_tag()
    elif cmd == "restore":
        restore_device_tag()
    else:
        print("usage: devicetag.py [status|backup|restore]")
