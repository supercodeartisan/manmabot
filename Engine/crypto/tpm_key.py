"""TPM / NCrypt Platform Crypto Provider probe + RSA OAEP (Windows)."""

from __future__ import annotations

import ctypes
import enum
import sys
from ctypes import wintypes
from dataclasses import dataclass

from .constants import CEK_LEN
from .errors import CryptoError

TPM_KSP_NAME = "Microsoft Platform Crypto Provider"
TPM_CONTAINER = "ManmabotV1.DeviceRSA"

# Selected NCrypt / HRESULT codes (not exhaustive — code+tests are authoritative).
NTE_BAD_KEYSET = 0x80090016
NTE_EXISTS = 0x8009000F
NTE_NOT_SUPPORTED = 0x80090029
NTE_DEVICE_NOT_READY = 0x80090030
NTE_INTERNAL_ERROR = 0x800900DF
NTE_BAD_FLAGS = 0x80090009
SCARD_W_CANCELLED_BY_USER = 0x8010006E
TPM_E_PCP_UNSUPPORTED_TYPE = 0x80290400  # illustrative band
# Access denied style
E_ACCESSDENIED = 0x80070005
NTE_PERM = 0x80090010


class TpmError(CryptoError):
    def __init__(self, message: str, *, hr: int | None = None) -> None:
        super().__init__(message)
        self.hr = hr


class TpmFailureClass(enum.Enum):
    permanent = "permanent"  # Soft fallback allowed on first install
    transient = "transient"  # retry; Soft forbidden
    denied = "denied"  # ACL/permission; Soft forbidden
    unknown = "unknown"  # Soft forbidden


def classify_tpm_failure(hr: int) -> TpmFailureClass:
    """Map HRESULT → permanent|transient|denied|unknown (R-01)."""
    u = hr & 0xFFFFFFFF
    if u in (E_ACCESSDENIED, NTE_PERM):
        return TpmFailureClass.denied
    if u in (NTE_DEVICE_NOT_READY, NTE_INTERNAL_ERROR):
        return TpmFailureClass.transient
    if u in (
        NTE_NOT_SUPPORTED,
        NTE_BAD_KEYSET,  # often "no TPM key / provider empty" for open
        NTE_BAD_FLAGS,
        TPM_E_PCP_UNSUPPORTED_TYPE & 0xFFFFFFFF,
    ):
        # NTE_BAD_KEYSET on OpenKey = key absent (not a Soft-trigger by itself).
        # Provider open failures with NOT_SUPPORTED = permanent.
        return TpmFailureClass.permanent
    # Provider missing / TPM absent commonly surfaces as provider open failure;
    # treat unrecognized open failures as permanent only when documented in tests.
    return TpmFailureClass.unknown


class KeyProbeStatus(enum.Enum):
    present = "present"
    absent = "absent"
    error_transient = "error_transient"
    error_denied = "error_denied"
    error_unknown = "error_unknown"
    unsupported = "unsupported"  # non-Windows / no NCrypt


@dataclass(frozen=True)
class TpmProbeResult:
    status: KeyProbeStatus
    hr: int | None = None
    detail: str = ""


if sys.platform == "win32":
    _ncrypt = ctypes.windll.ncrypt
    SECURITY_STATUS = wintypes.LONG
    NCRYPT_PROV_HANDLE = ctypes.c_void_p
    NCRYPT_KEY_HANDLE = ctypes.c_void_p

    NCRYPT_SILENT_FLAG = 0x00000040
    NCRYPT_OVERWRITE_KEY_FLAG = 0x00000080
    NCRYPT_MACHINE_KEY_FLAG = 0x00000020
    NCRYPT_PAD_OAEP_FLAG = 0x00000004

    class BCRYPT_OAEP_PADDING_INFO(ctypes.Structure):
        _fields_ = [
            ("pszAlgId", wintypes.LPCWSTR),
            ("pbLabel", ctypes.c_void_p),
            ("cbLabel", wintypes.ULONG),
        ]

    def _open_provider() -> tuple[NCRYPT_PROV_HANDLE | None, int]:
        h = NCRYPT_PROV_HANDLE()
        status = _ncrypt.NCryptOpenStorageProvider(
            ctypes.byref(h),
            TPM_KSP_NAME,
            0,
        )
        if status != 0:
            return None, status & 0xFFFFFFFF
        return h, 0

    def _close_provider(h: NCRYPT_PROV_HANDLE) -> None:
        if h:
            _ncrypt.NCryptFreeObject(h)

    def _close_key(h: NCRYPT_KEY_HANDLE) -> None:
        if h:
            _ncrypt.NCryptFreeObject(h)

    def probe_tpm_key() -> TpmProbeResult:
        hprov, hr = _open_provider()
        if hprov is None:
            klass = classify_tpm_failure(hr)
            if klass is TpmFailureClass.transient:
                return TpmProbeResult(KeyProbeStatus.error_transient, hr=hr, detail="provider")
            if klass is TpmFailureClass.denied:
                return TpmProbeResult(KeyProbeStatus.error_denied, hr=hr, detail="provider")
            if klass is TpmFailureClass.permanent:
                return TpmProbeResult(KeyProbeStatus.absent, hr=hr, detail="provider_permanent")
            return TpmProbeResult(KeyProbeStatus.error_unknown, hr=hr, detail="provider")

        try:
            hkey = NCRYPT_KEY_HANDLE()
            status = _ncrypt.NCryptOpenKey(
                hprov,
                ctypes.byref(hkey),
                TPM_CONTAINER,
                0,
                NCRYPT_SILENT_FLAG,
            )
            status_u = status & 0xFFFFFFFF
            if status == 0:
                _close_key(hkey)
                return TpmProbeResult(KeyProbeStatus.present, hr=0)
            if status_u == NTE_BAD_KEYSET:
                return TpmProbeResult(KeyProbeStatus.absent, hr=status_u)
            klass = classify_tpm_failure(status_u)
            if klass is TpmFailureClass.transient:
                return TpmProbeResult(KeyProbeStatus.error_transient, hr=status_u)
            if klass is TpmFailureClass.denied:
                return TpmProbeResult(KeyProbeStatus.error_denied, hr=status_u)
            return TpmProbeResult(KeyProbeStatus.error_unknown, hr=status_u)
        finally:
            _close_provider(hprov)

    def export_tpm_spki() -> bytes:
        """Export public SPKI DER from TPM container (public blob → SPKI)."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        import struct

        hprov, hr = _open_provider()
        if hprov is None:
            raise TpmError("TPM provider open failed", hr=hr)
        hkey = NCRYPT_KEY_HANDLE()
        try:
            status = _ncrypt.NCryptOpenKey(
                hprov, ctypes.byref(hkey), TPM_CONTAINER, 0, NCRYPT_SILENT_FLAG
            )
            if status != 0:
                raise TpmError("TPM key open failed", hr=status & 0xFFFFFFFF)

            # BCRYPT_RSAPUBLIC_BLOB via NCryptExportKey
            BCRYPT_RSAPUBLIC_BLOB = "RSAPUBLICBLOB"
            pcb = wintypes.DWORD(0)
            status = _ncrypt.NCryptExportKey(
                hkey,
                None,
                BCRYPT_RSAPUBLIC_BLOB,
                None,
                None,
                0,
                ctypes.byref(pcb),
                0,
            )
            if status != 0:
                raise TpmError("TPM export size failed", hr=status & 0xFFFFFFFF)
            buf = (ctypes.c_ubyte * pcb.value)()
            status = _ncrypt.NCryptExportKey(
                hkey,
                None,
                BCRYPT_RSAPUBLIC_BLOB,
                None,
                buf,
                pcb.value,
                ctypes.byref(pcb),
                0,
            )
            if status != 0:
                raise TpmError("TPM export failed", hr=status & 0xFFFFFFFF)
            data = bytes(buf[: pcb.value])
            # BCRYPT_RSAKEY_BLOB: Magic(4) BitLength(4) cbPublicExp(4) cbModulus(4) cbPrime1(4) cbPrime2(4)
            if len(data) < 24:
                raise TpmError("RSA public blob too short")
            magic, bitlen, cb_exp, cb_mod, _p1, _p2 = struct.unpack_from("<IIIIII", data, 0)
            if magic != 0x31415352:  # RSA1
                raise TpmError(f"unexpected RSA blob magic {magic:#x}")
            off = 24
            exp = int.from_bytes(data[off : off + cb_exp], "big")
            off += cb_exp
            mod = int.from_bytes(data[off : off + cb_mod], "big")
            pub = RSAPublicNumbers(exp, mod).public_key()
            return pub.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        finally:
            _close_key(hkey)
            _close_provider(hprov)

    def create_tpm_key() -> bytes:
        """Create persistent non-exportable RSA-2048; return SPKI DER."""
        hprov, hr = _open_provider()
        if hprov is None:
            raise TpmError("TPM provider open failed", hr=hr)
        hkey = NCRYPT_KEY_HANDLE()
        try:
            status = _ncrypt.NCryptCreatePersistedKey(
                hprov,
                ctypes.byref(hkey),
                "RSA",
                TPM_CONTAINER,
                0,
                0,
            )
            if status != 0:
                raise TpmError("NCryptCreatePersistedKey failed", hr=status & 0xFFFFFFFF)

            length = wintypes.DWORD(2048)
            status = _ncrypt.NCryptSetProperty(
                hkey,
                "Length",
                ctypes.byref(length),
                ctypes.sizeof(length),
                0,
            )
            if status != 0:
                raise TpmError("set Length failed", hr=status & 0xFFFFFFFF)

            status = _ncrypt.NCryptFinalizeKey(hkey, NCRYPT_SILENT_FLAG)
            if status != 0:
                raise TpmError("NCryptFinalizeKey failed", hr=status & 0xFFFFFFFF)
        finally:
            # Re-open for export after finalize — finalize may leave handle usable.
            pass

        _close_key(hkey)
        _close_provider(hprov)
        return export_tpm_spki()

    def decrypt_cek_tpm(ciphertext: bytes) -> bytes:
        hprov, hr = _open_provider()
        if hprov is None:
            raise TpmError("TPM provider open failed", hr=hr)
        hkey = NCRYPT_KEY_HANDLE()
        try:
            status = _ncrypt.NCryptOpenKey(
                hprov, ctypes.byref(hkey), TPM_CONTAINER, 0, NCRYPT_SILENT_FLAG
            )
            if status != 0:
                raise TpmError("TPM key open failed", hr=status & 0xFFFFFFFF)

            pad = BCRYPT_OAEP_PADDING_INFO()
            pad.pszAlgId = "SHA256"
            pad.pbLabel = None
            pad.cbLabel = 0

            pcb = wintypes.DWORD(0)
            status = _ncrypt.NCryptDecrypt(
                hkey,
                ctypes.c_char_p(ciphertext),
                len(ciphertext),
                ctypes.byref(pad),
                None,
                0,
                ctypes.byref(pcb),
                NCRYPT_PAD_OAEP_FLAG,
            )
            if status != 0:
                raise TpmError("NCryptDecrypt size failed", hr=status & 0xFFFFFFFF)
            buf = (ctypes.c_ubyte * pcb.value)()
            status = _ncrypt.NCryptDecrypt(
                hkey,
                (ctypes.c_ubyte * len(ciphertext)).from_buffer_copy(ciphertext),
                len(ciphertext),
                ctypes.byref(pad),
                buf,
                pcb.value,
                ctypes.byref(pcb),
                NCRYPT_PAD_OAEP_FLAG,
            )
            if status != 0:
                raise TpmError("NCryptDecrypt failed", hr=status & 0xFFFFFFFF)
            pt = bytes(buf[: pcb.value])
            if len(pt) != CEK_LEN:
                raise TpmError("CEK plaintext must be 32 bytes")
            return pt
        finally:
            _close_key(hkey)
            _close_provider(hprov)

else:

    def probe_tpm_key() -> TpmProbeResult:
        return TpmProbeResult(KeyProbeStatus.unsupported, detail="non-windows")

    def export_tpm_spki() -> bytes:
        raise TpmError("TPM unavailable on this platform")

    def create_tpm_key() -> bytes:
        raise TpmError("TPM unavailable on this platform")

    def decrypt_cek_tpm(ciphertext: bytes) -> bytes:
        raise TpmError("TPM unavailable on this platform")
