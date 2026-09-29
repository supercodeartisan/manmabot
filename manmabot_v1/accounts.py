"""Windows DPAPI-backed account persistence.

Passwords exist as plaintext only in memory while editing or launching.  The
JSON store contains a base64-encoded DPAPI blob and is safe to keep alongside
the other operator data under ``userdata``.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from manmabot_v1.paths import ACCOUNTS_PATH, assert_userdata_write, ensure_userdata

_CRYPTPROTECT_UI_FORBIDDEN = 0x01
_STORE_VERSION = 1
_EMAIL_OK = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_REGIONS = frozenset(("Taiwan", "Korea", "Japan", "Hong Kong", "China"))
_CLICK_MODES = frozenset(("dynamic", "fixed", "hybrid"))
_LOCALES = frozenset(("ko", "zh-TW", "zh-CN", "ja"))
_CHARACTER_TYPES = frozenset(("royal", "knight", "elf", "mage"))
_REGION_LOCALE = {
    "Taiwan": "zh-TW",
    "Korea": "ko",
    "Japan": "ja",
    "Hong Kong": "zh-TW",
    "China": "zh-CN",
}
_LOCALE_REGION = {
    "ko": "Korea",
    "zh-CN": "China",
    "zh-TW": "Taiwan",
    "ja": "Japan",
}
# Locale codes offered as "server language" in the account UI.
SERVER_LANGUAGE_CODES = ("ko", "zh-CN", "zh-TW", "ja")


def locale_for_region(region: str) -> str:
    """Map a Purple region name to the matching game locale code."""
    return _REGION_LOCALE.get(str(region or "").strip(), "ko")


def region_for_locale(locale: str) -> str:
    """Map a server-language locale code to the matching Purple region."""
    return _LOCALE_REGION.get(str(locale or "").strip(), "Korea")


def normalize_server_language(locale: str, region: str = "") -> str:
    """Normalize stored locale/region into one server-language code."""
    cleaned = str(locale or "").strip()
    if cleaned in _LOCALES:
        return cleaned
    return locale_for_region(region)


class AccountStoreError(RuntimeError):
    """An account operation failed without exposing credential material."""


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise AccountStoreError("Secure account storage requires Windows.")


def _dpapi_protect(secret: str) -> str:
    _require_windows()
    raw = bytearray(str(secret).encode("utf-8"))
    source = (ctypes.c_ubyte * len(raw)).from_buffer(raw)
    in_blob = _DataBlob(len(raw), ctypes.cast(source, ctypes.c_void_p))
    out_blob = _DataBlob()
    try:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise AccountStoreError("Windows could not protect the password.")
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return base64.b64encode(protected).decode("ascii")
    except AccountStoreError:
        raise
    except Exception as exc:
        raise AccountStoreError("Windows could not protect the password.") from exc
    finally:
        if raw:
            ctypes.memset(ctypes.addressof(source), 0, len(raw))
        if out_blob.pbData:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(out_blob.pbData)


def _dpapi_unprotect(encoded: str) -> str:
    _require_windows()
    try:
        protected = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise AccountStoreError("The saved password is invalid.") from exc
    source = ctypes.create_string_buffer(protected)
    in_blob = _DataBlob(len(protected), ctypes.cast(source, ctypes.c_void_p))
    out_blob = _DataBlob()
    try:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise AccountStoreError(
                "Windows could not unlock the saved password for this user."
            )
        plaintext = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AccountStoreError("The saved password is invalid.") from exc
    except AccountStoreError:
        raise
    except Exception as exc:
        raise AccountStoreError(
            "Windows could not unlock the saved password for this user."
        ) from exc
    finally:
        if out_blob.pbData:
            ctypes.memset(out_blob.pbData, 0, out_blob.cbData)
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(out_blob.pbData)


def validate_account_fields(
    username: str,
    password: str,
    region: str,
    server: str,
    character_number: int | str = 1,
    click_mode: str = "dynamic",
    display_name: str = "",
    locale: str = "",
    purple_launcher_path: str = "",
    game_path: str = "",
    character_type: str = "royal",
) -> tuple[str, str, str, str, int, str, str, str, str, str, str]:
    username = str(username or "").strip()
    password = str(password or "")
    region = str(region or "").strip()
    server = str(server or "").strip()
    click_mode = str(click_mode or "dynamic").strip().lower()
    display_name = " ".join(str(display_name or "").strip().split())
    locale = str(locale or _REGION_LOCALE.get(region, "ko")).strip()
    purple_launcher_path = os.path.expandvars(
        str(purple_launcher_path or "").strip()
    )
    game_path = os.path.expandvars(str(game_path or "").strip())
    character_type = str(character_type or "royal").strip().lower()
    if not _EMAIL_OK.fullmatch(username):
        raise ValueError("invalid_username")
    if len(password) < 4:
        raise ValueError("invalid_password")
    if not display_name or len(display_name) > 40:
        raise ValueError("invalid_display_name")
    if locale not in _LOCALES:
        raise ValueError("invalid_server_language")
    # Server language is the source of truth; region is derived for Purple.
    region = _LOCALE_REGION.get(locale, region)
    if region not in _REGIONS:
        raise ValueError("invalid_region")
    if not server or len(server) > 80:
        raise ValueError("invalid_server")
    if len(purple_launcher_path) > 500:
        raise ValueError("invalid_purple_path")
    if len(game_path) > 500:
        raise ValueError("invalid_game_path")
    try:
        character_number = int(character_number)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_character") from exc
    if not 1 <= character_number <= 3:
        raise ValueError("invalid_character")
    if click_mode not in _CLICK_MODES:
        raise ValueError("invalid_click_mode")
    if character_type not in _CHARACTER_TYPES:
        raise ValueError("invalid_character_type")
    return (
        username,
        password,
        region,
        server,
        character_number,
        click_mode,
        display_name,
        locale,
        purple_launcher_path,
        game_path,
        character_type,
    )


@dataclass(repr=False)
class Account:
    account_id: str
    username: str
    password: str = field(repr=False)
    region: str = "Korea"
    server: str = ""
    character_number: int = 1
    click_mode: str = "dynamic"
    display_name: str = ""
    locale: str = ""
    purple_launcher_path: str = ""
    game_path: str = ""
    character_type: str = "royal"

    def __post_init__(self) -> None:
        try:
            self.account_id = str(uuid.UUID(str(self.account_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("invalid_account_id") from exc
        (
            self.username,
            self.password,
            self.region,
            self.server,
            self.character_number,
            self.click_mode,
            self.display_name,
            self.locale,
            self.purple_launcher_path,
            self.game_path,
            self.character_type,
        ) = validate_account_fields(
            self.username,
            self.password,
            self.region,
            self.server,
            self.character_number,
            self.click_mode,
            self.display_name or self.username.split("@", 1)[0],
            self.locale,
            self.purple_launcher_path,
            self.game_path,
            self.character_type,
        )

    @classmethod
    def create(
        cls,
        username: str,
        password: str,
        region: str,
        server: str,
        character_number: int | str = 1,
        click_mode: str = "dynamic",
        display_name: str = "",
        locale: str = "",
        purple_launcher_path: str = "",
        game_path: str = "",
        character_type: str = "royal",
    ) -> "Account":
        return cls(
            account_id=str(uuid.uuid4()),
            username=username,
            password=password,
            region=region,
            server=server,
            character_number=character_number,
            click_mode=click_mode,
            display_name=display_name,
            locale=locale,
            purple_launcher_path=purple_launcher_path,
            game_path=game_path,
            character_type=character_type,
        )

    def __repr__(self) -> str:
        return (
            f"Account(account_id={self.account_id!r}, username={self.username!r}, "
            "password=<redacted>, "
            f"region={self.region!r}, server={self.server!r}, "
            f"character_number={self.character_number!r}, "
            f"click_mode={self.click_mode!r}, display_name={self.display_name!r}, "
            f"locale={self.locale!r}, "
            f"character_type={self.character_type!r}, "
            f"purple_launcher_path={self.purple_launcher_path!r}, "
            f"game_path={self.game_path!r})"
        )

    def to_launcher_account(self) -> dict[str, Any]:
        """Return the existing autologin launcher account contract."""
        return {
            "id": self.username,
            "pw": self.password,
            "region": self.region,
            "server": self.server,
            "character_number": self.character_number,
            "click_mode": self.click_mode,
            "display_name": self.display_name,
            "locale": self.locale,
            "character_type": self.character_type,
            "purple_path": self.purple_launcher_path,
            "game_path": self.game_path,
        }

    def _to_stored_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "username": self.username,
            "password_dpapi": _dpapi_protect(self.password),
            "region": self.region,
            "server": self.server,
            "character_number": self.character_number,
            "click_mode": self.click_mode,
            "display_name": self.display_name,
            "locale": self.locale,
            "character_type": self.character_type,
            "purple_launcher_path": self.purple_launcher_path,
            "game_path": self.game_path,
        }

    @classmethod
    def _from_stored_dict(cls, data: dict[str, Any]) -> "Account":
        if "password" in data or "pw" in data:
            raise AccountStoreError("The account store contains an unsafe record.")
        try:
            return cls(
                account_id=data["account_id"],
                username=data["username"],
                password=_dpapi_unprotect(data["password_dpapi"]),
                region=data.get("region", "Korea"),
                server=data.get("server", ""),
                character_number=data.get("character_number", 1),
                click_mode=data.get("click_mode", "dynamic"),
                display_name=data.get("display_name", ""),
                locale=data.get("locale", ""),
                purple_launcher_path=data.get("purple_launcher_path", ""),
                game_path=data.get("game_path", ""),
                character_type=data.get("character_type", "royal"),
            )
        except AccountStoreError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AccountStoreError("The account store contains an invalid record.") from exc


class AccountStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = assert_userdata_write(path or ACCOUNTS_PATH)

    def load(self) -> list[Account]:
        ensure_userdata()
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AccountStoreError("The account store could not be read.") from exc
        if not isinstance(payload, dict) or payload.get("version") != _STORE_VERSION:
            raise AccountStoreError("The account store format is not supported.")
        records = payload.get("accounts")
        if not isinstance(records, list):
            raise AccountStoreError("The account store contains invalid data.")
        accounts = [Account._from_stored_dict(item) for item in records if isinstance(item, dict)]
        if len(accounts) != len(records):
            raise AccountStoreError("The account store contains an invalid record.")
        ids = [account.account_id for account in accounts]
        usernames = [account.username.casefold() for account in accounts]
        if len(ids) != len(set(ids)) or len(usernames) != len(set(usernames)):
            raise AccountStoreError("The account store contains duplicate records.")
        return accounts

    def save(self, accounts: list[Account]) -> None:
        ensure_userdata()
        account_ids = [account.account_id for account in accounts]
        usernames = [account.username.casefold() for account in accounts]
        if len(account_ids) != len(set(account_ids)) or len(usernames) != len(set(usernames)):
            raise ValueError("duplicate_account")
        payload = {
            "version": _STORE_VERSION,
            "accounts": [account._to_stored_dict() for account in accounts],
        }
        _atomic_write_json(self.path, payload)

    def add(self, account: Account) -> None:
        accounts = self.load()
        accounts.append(account)
        self.save(accounts)

    def update(self, account: Account) -> None:
        accounts = self.load()
        for index, current in enumerate(accounts):
            if current.account_id == account.account_id:
                accounts[index] = account
                self.save(accounts)
                return
        raise KeyError("account_not_found")

    def delete(self, account_id: str) -> None:
        accounts = self.load()
        kept = [account for account in accounts if account.account_id != account_id]
        if len(kept) == len(accounts):
            raise KeyError("account_not_found")
        self.save(kept)

    def get(self, account_id: str | None) -> Account | None:
        if not account_id:
            return None
        return next(
            (account for account in self.load() if account.account_id == account_id),
            None,
        )

    def backup_and_reset_inaccessible(self) -> Path | None:
        """Back up an unreadable DPAPI store, then create an empty one."""
        backup: Path | None = None
        if self.path.is_file():
            backup = assert_userdata_write(
                self.path.with_name(
                    f"{self.path.stem}.locked-{uuid.uuid4().hex[:8]}{self.path.suffix}"
                )
            )
            try:
                shutil.copy2(self.path, backup)
            except OSError as exc:
                raise AccountStoreError(
                    "The inaccessible account store could not be backed up."
                ) from exc
        try:
            self.save([])
        except Exception:
            if backup is not None:
                try:
                    shutil.copy2(backup, self.path)
                except OSError:
                    pass
            raise
        return backup


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = assert_userdata_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = assert_userdata_write(path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp"))
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise AccountStoreError("The account store could not be saved.") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
