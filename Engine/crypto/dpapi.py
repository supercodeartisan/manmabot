"""Windows DPAPI CurrentUser protect/unprotect (ctypes)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from .errors import CryptoError


class DpapiError(CryptoError):
    pass


if sys.platform == "win32":
    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
        buf = (ctypes.c_byte * len(data)).from_buffer_copy(data)
        blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        return blob, buf

    def protect(data: bytes, *, description: str = "ManmabotV1") -> bytes:
        in_blob, _keep = _blob_from_bytes(data)
        out_blob = DATA_BLOB()
        desc = ctypes.c_wchar_p(description)
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            desc,
            None,
            None,
            None,
            0,  # CurrentUser
            ctypes.byref(out_blob),
        )
        if not ok:
            raise DpapiError(f"CryptProtectData failed: {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)

    def unprotect(data: bytes) -> bytes:
        in_blob, _keep = _blob_from_bytes(data)
        out_blob = DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise DpapiError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            _kernel32.LocalFree(out_blob.pbData)

else:

    def protect(data: bytes, *, description: str = "ManmabotV1") -> bytes:
        raise DpapiError("DPAPI only available on Windows")

    def unprotect(data: bytes) -> bytes:
        raise DpapiError("DPAPI only available on Windows")
