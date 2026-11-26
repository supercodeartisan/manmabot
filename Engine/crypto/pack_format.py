"""MMB2 (MMBA v2) Writer / Reader — READY Phase 1 Spec §5.

Independent of asset_store / bot logic. Roundtrip via CEK + product/cek ids.
"""

from __future__ import annotations

import hmac
import os
import struct
import zlib
from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping, Protocol, Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .constants import (
    AAD_PREFIX,
    CEK_LEN,
    FORMAT_VERSION,
    GCM_TAG_LEN,
    MAGIC,
    MANIFEST_MAC_LEN,
    MANIFEST_MAC_PREFIX,
    MAX_COMPRESSION_RATIO,
    MAX_ENTRY_COUNT,
    MAX_HEADER_SIZE,
    MAX_MANIFEST_SIZE,
    MAX_PACK_FILE_SIZE,
    MAX_PATH_BYTES,
    MAX_RAW_SIZE,
    MAX_STORED_SIZE,
    MIN_ENTRY_COUNT,
    MMB2_FIXED_PREAMBLE,
    NONCE_LEN,
    PACK_ID_LEN,
    PHASE1_FLAGS,
    PROVISIONAL_MAX_TOTAL_RAW_SIZE,
)
from .errors import PackFormatError, SessionBindingError
from .kdf import derive_manifest_key, derive_pack_aes_key, derived_nonce
from .paths import assert_no_case_collisions, canonicalize_pack_path


# ---------------------------------------------------------------------------
# Binary helpers
# ---------------------------------------------------------------------------


def _u16be(n: int) -> bytes:
    return struct.pack(">H", n)


def _u32be(n: int) -> bytes:
    return struct.pack(">I", n)


def _u64be(n: int) -> bytes:
    return struct.pack(">Q", n)


def _u16le(n: int) -> bytes:
    return struct.pack("<H", n)


def _u32le(n: int) -> bytes:
    return struct.pack("<I", n)


def _u64le(n: int) -> bytes:
    return struct.pack("<Q", n)


def _lp_utf8_be(s: str) -> bytes:
    b = s.encode("utf-8")
    if len(b) > 0xFFFF:
        raise PackFormatError("string too long for u16 length")
    return _u16be(len(b)) + b


def peek_mmb2_public_header(blob: bytes) -> dict:
    """Read product_id / cek_id / pack_id / entry_count without CEK (header only).

    Used by seller Stage 5 to carry-forward an on-disk pack into BUILD.json when
    that side was not rebuilt in the current publish.
    """
    if len(blob) < MMB2_FIXED_PREAMBLE:
        raise PackFormatError("file too small")
    if bytes(blob[0:4]) != MAGIC:
        raise PackFormatError("bad magic")
    (format_version,) = struct.unpack_from("<H", blob, 4)
    header_size, flags, entry_count = struct.unpack_from("<III", blob, 6)
    _require_exact(format_version == FORMAT_VERSION, "unsupported format_version")
    _require_exact(flags == PHASE1_FLAGS, "unknown header flags")
    if header_size < MMB2_FIXED_PREAMBLE or header_size > MAX_HEADER_SIZE:
        raise PackFormatError("header_size out of range")
    if header_size > len(blob):
        raise PackFormatError("header beyond EOF")
    mv = memoryview(blob)
    off = MMB2_FIXED_PREAMBLE
    product_id, off = _read_lp_utf8(mv, off, max_len=MAX_PATH_BYTES)
    cek_id, off = _read_lp_utf8(mv, off, max_len=MAX_PATH_BYTES)
    if off + 2 > header_size:
        raise PackFormatError("truncated pack_id in header")
    (pid_len,) = struct.unpack_from(">H", blob, off)
    off += 2
    _require_exact(pid_len == PACK_ID_LEN, "header pack_id length")
    if off + PACK_ID_LEN != header_size:
        raise PackFormatError("header_size does not match trailing pack_id")
    pack_id = bytes(blob[off : off + PACK_ID_LEN])
    return {
        "product_id": product_id,
        "cek_id": cek_id,
        "pack_id": pack_id,
        "pack_id_hex": pack_id.hex(),
        "entry_count": int(entry_count),
        "header_size": int(header_size),
    }


def _read_lp_utf8(buf: memoryview, off: int, *, max_len: int = MAX_PATH_BYTES) -> tuple[str, int]:
    if off + 2 > len(buf):
        raise PackFormatError("truncated length prefix")
    (n,) = struct.unpack_from(">H", buf, off)
    off += 2
    if n > max_len:
        raise PackFormatError("length-prefixed string exceeds limit")
    if off + n > len(buf):
        raise PackFormatError("truncated length-prefixed string")
    try:
        s = bytes(buf[off : off + n]).decode("utf-8")
    except UnicodeDecodeError as e:
        raise PackFormatError("invalid utf-8") from e
    return s, off + n


def _require_exact(cond: bool, msg: str) -> None:
    if not cond:
        raise PackFormatError(msg)


# ---------------------------------------------------------------------------
# Session binding (minimal; full AuthorizedSession comes later)
# ---------------------------------------------------------------------------


class PackSession(Protocol):
    authorized_product_id: str
    authorized_cek_id: str
    decrypted_cek_32: bytes


@dataclass(frozen=True)
class SimplePackSession:
    """Test / early-integration session stub. Not a verified ticket."""

    authorized_product_id: str
    authorized_cek_id: str
    decrypted_cek_32: bytes

    def __post_init__(self) -> None:
        if len(self.decrypted_cek_32) != CEK_LEN:
            raise ValueError("CEK must be 32 bytes")


# ---------------------------------------------------------------------------
# Entry model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackEntryMeta:
    entry_id: int
    path: str
    raw_size: int
    stored_size: int
    ciphertext_size: int
    data_rel_offset: int
    nonce: bytes
    tag: bytes
    flags: int


@dataclass
class _BuiltEntry:
    meta: PackEntryMeta
    ciphertext: bytes


# ---------------------------------------------------------------------------
# AAD / compress / encrypt
# ---------------------------------------------------------------------------


def build_entry_aad(
    *,
    product_id: str,
    cek_id: str,
    pack_id: bytes,
    format_version: int,
    entry_id: int,
    path: str,
    raw_size: int,
    stored_size: int,
    ciphertext_size: int,
    flags: int,
) -> bytes:
    return (
        AAD_PREFIX
        + _lp_utf8_be(product_id)
        + _lp_utf8_be(cek_id)
        + _u16be(PACK_ID_LEN)
        + pack_id
        + _u16be(format_version)
        + _u64be(entry_id)
        + _lp_utf8_be(path)
        + _u64be(raw_size)
        + _u64be(stored_size)
        + _u64be(ciphertext_size)
        + _u32be(flags)
    )


def _zlib_wrap(raw: bytes) -> bytes:
    if not raw:
        return b""
    co = zlib.compressobj(level=9, wbits=15)  # zlib-wrapped DEFLATE
    out = co.compress(raw) + co.flush()
    # Highly compressible assets (maps/tables) can exceed the zip-bomb ratio
    # check on round-trip verify. Fall back to zlib store (level 0).
    if len(out) * MAX_COMPRESSION_RATIO < len(raw):
        co0 = zlib.compressobj(level=0, wbits=15)
        out = co0.compress(raw) + co0.flush()
    return out


def _zlib_unwrap(stored: bytes, expected_raw: int) -> bytes:
    if expected_raw == 0:
        if stored:
            raise PackFormatError("empty raw requires empty stored")
        return b""
    if not stored:
        raise PackFormatError("non-empty raw requires non-empty stored")
    # Single stream, require EOF, reject trailing.
    decomp = zlib.decompressobj(wbits=15)
    try:
        raw = decomp.decompress(stored, max_length=expected_raw + 1)
    except zlib.error as e:
        raise PackFormatError(f"zlib decompress failed: {e}") from e
    if len(raw) != expected_raw:
        raise PackFormatError("zlib output size != raw_size")
    if decomp.unconsumed_tail:
        raise PackFormatError("zlib trailing unconsumed data")
    # Must have reached stream end; unused_data means concatenate/trailing.
    if decomp.unused_data:
        raise PackFormatError("zlib trailing bytes after stream")
    # Ensure flush completes (EOF).
    try:
        more = decomp.flush()
    except zlib.error as e:
        raise PackFormatError(f"zlib flush failed: {e}") from e
    if more:
        raise PackFormatError("zlib flush produced extra bytes")
    if not decomp.eof:
        raise PackFormatError("zlib stream incomplete (no EOF)")
    return raw


def _check_size_limits(raw_size: int, stored_size: int) -> None:
    if raw_size < 0 or stored_size < 0:
        raise PackFormatError("negative size")
    if raw_size > MAX_RAW_SIZE:
        raise PackFormatError("raw_size exceeds limit")
    if stored_size > MAX_STORED_SIZE:
        raise PackFormatError("stored_size exceeds limit")
    if raw_size == 0 and stored_size != 0:
        raise PackFormatError("empty raw with non-empty stored")
    if raw_size > 0 and stored_size == 0:
        raise PackFormatError("non-empty raw with empty stored")
    if raw_size > 0 and stored_size * MAX_COMPRESSION_RATIO < raw_size:
        # compression ratio stored:raw — reject if raw/stored > 200
        raise PackFormatError("compression ratio exceeds limit")


# ---------------------------------------------------------------------------
# Encode table / manifest body
# ---------------------------------------------------------------------------


def _encode_table_entry(m: PackEntryMeta) -> bytes:
    return (
        _u64le(m.entry_id)
        + _lp_utf8_be(m.path)
        + _u64le(m.raw_size)
        + _u64le(m.stored_size)
        + _u64le(m.ciphertext_size)
        + _u64le(m.data_rel_offset)
        + m.nonce
        + m.tag
        + _u32le(m.flags)
    )


def _encode_manifest_entry(m: PackEntryMeta) -> bytes:
    return (
        _u64be(m.entry_id)
        + _lp_utf8_be(m.path)
        + _u64be(m.raw_size)
        + _u64be(m.stored_size)
        + _u64be(m.ciphertext_size)
        + _u64be(m.data_rel_offset)
        + m.nonce
        + m.tag
        + _u32be(m.flags)
    )


def _encode_manifest_body(
    *,
    format_version: int,
    header_size: int,
    header_flags: int,
    entry_count: int,
    table_offset: int,
    table_size: int,
    manifest_offset: int,
    manifest_size: int,
    data_offset: int,
    product_id: str,
    cek_id: str,
    pack_id: bytes,
    entries: Sequence[PackEntryMeta],
) -> bytes:
    body = bytearray()
    body += _u16be(format_version)
    body += _u32be(header_size)
    body += _u32be(header_flags)
    body += _u32be(entry_count)
    body += _u64be(table_offset)
    body += _u64be(table_size)
    body += _u64be(manifest_offset)
    body += _u64be(manifest_size)
    body += _u64be(data_offset)
    body += _lp_utf8_be(product_id)
    body += _lp_utf8_be(cek_id)
    body += _u16be(PACK_ID_LEN) + pack_id
    for m in entries:
        body += _encode_manifest_entry(m)
    return bytes(body)


def _parse_manifest_body(body: bytes) -> tuple[dict, list[PackEntryMeta]]:
    mv = memoryview(body)
    off = 0
    if off + 2 + 4 + 4 + 4 + 5 * 8 > len(mv):
        raise PackFormatError("manifest body too short")
    (format_version,) = struct.unpack_from(">H", mv, off)
    off += 2
    header_size, header_flags, entry_count = struct.unpack_from(">III", mv, off)
    off += 12
    table_offset, table_size, manifest_offset, manifest_size, data_offset = struct.unpack_from(
        ">5Q", mv, off
    )
    off += 40
    product_id, off = _read_lp_utf8(mv, off, max_len=MAX_PATH_BYTES)
    cek_id, off = _read_lp_utf8(mv, off, max_len=MAX_PATH_BYTES)
    if off + 2 > len(mv):
        raise PackFormatError("truncated pack_id length")
    (pid_len,) = struct.unpack_from(">H", mv, off)
    off += 2
    _require_exact(pid_len == PACK_ID_LEN, "pack_id length must be 16")
    if off + PACK_ID_LEN > len(mv):
        raise PackFormatError("truncated pack_id")
    pack_id = bytes(mv[off : off + PACK_ID_LEN])
    off += PACK_ID_LEN

    entries: list[PackEntryMeta] = []
    for i in range(entry_count):
        if off + 8 > len(mv):
            raise PackFormatError("truncated entry_id")
        (entry_id,) = struct.unpack_from(">Q", mv, off)
        off += 8
        path, off = _read_lp_utf8(mv, off)
        if off + 8 * 4 + NONCE_LEN + GCM_TAG_LEN + 4 > len(mv):
            raise PackFormatError("truncated entry fields")
        raw_size, stored_size, ciphertext_size, data_rel_offset = struct.unpack_from(">4Q", mv, off)
        off += 32
        nonce = bytes(mv[off : off + NONCE_LEN])
        off += NONCE_LEN
        tag = bytes(mv[off : off + GCM_TAG_LEN])
        off += GCM_TAG_LEN
        (flags,) = struct.unpack_from(">I", mv, off)
        off += 4
        entries.append(
            PackEntryMeta(
                entry_id=entry_id,
                path=path,
                raw_size=raw_size,
                stored_size=stored_size,
                ciphertext_size=ciphertext_size,
                data_rel_offset=data_rel_offset,
                nonce=nonce,
                tag=tag,
                flags=flags,
            )
        )
        _ = i  # silence unused in some linters

    _require_exact(off == len(mv), "manifest body has trailing bytes")
    header = {
        "format_version": format_version,
        "header_size": header_size,
        "header_flags": header_flags,
        "entry_count": entry_count,
        "table_offset": table_offset,
        "table_size": table_size,
        "manifest_offset": manifest_offset,
        "manifest_size": manifest_size,
        "data_offset": data_offset,
        "product_id": product_id,
        "cek_id": cek_id,
        "pack_id": pack_id,
    }
    return header, entries


def _parse_table(buf: memoryview, entry_count: int) -> tuple[list[PackEntryMeta], int]:
    off = 0
    entries: list[PackEntryMeta] = []
    for _ in range(entry_count):
        if off + 8 > len(buf):
            raise PackFormatError("truncated table entry_id")
        (entry_id,) = struct.unpack_from("<Q", buf, off)
        off += 8
        path, off = _read_lp_utf8(buf, off)
        if off + 32 + NONCE_LEN + GCM_TAG_LEN + 4 > len(buf):
            raise PackFormatError("truncated table entry")
        raw_size, stored_size, ciphertext_size, data_rel_offset = struct.unpack_from("<4Q", buf, off)
        off += 32
        nonce = bytes(buf[off : off + NONCE_LEN])
        off += NONCE_LEN
        tag = bytes(buf[off : off + GCM_TAG_LEN])
        off += GCM_TAG_LEN
        (flags,) = struct.unpack_from("<I", buf, off)
        off += 4
        entries.append(
            PackEntryMeta(
                entry_id=entry_id,
                path=path,
                raw_size=raw_size,
                stored_size=stored_size,
                ciphertext_size=ciphertext_size,
                data_rel_offset=data_rel_offset,
                nonce=nonce,
                tag=tag,
                flags=flags,
            )
        )
    return entries, off


def _entries_semantically_equal(a: Sequence[PackEntryMeta], b: Sequence[PackEntryMeta]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if (
            x.entry_id != y.entry_id
            or x.path != y.path
            or x.raw_size != y.raw_size
            or x.stored_size != y.stored_size
            or x.ciphertext_size != y.ciphertext_size
            or x.data_rel_offset != y.data_rel_offset
            or x.nonce != y.nonce
            or x.tag != y.tag
            or x.flags != y.flags
        ):
            return False
    return True


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_pack(
    entries: Mapping[str, bytes],
    *,
    cek: bytes,
    product_id: str,
    cek_id: str,
    pack_id: bytes | None = None,
    max_total_raw_size: int = PROVISIONAL_MAX_TOTAL_RAW_SIZE,
) -> bytes:
    """Build an MMB2 blob. ``entries`` maps canonical-or-raw paths → raw bytes."""
    if len(cek) != CEK_LEN:
        raise PackFormatError("CEK must be 32 bytes")
    if not product_id or not cek_id:
        raise PackFormatError("product_id and cek_id required")
    # Canonical ASCII UUID-ish: keep as given; enforce printable ASCII.
    for label, val in (("product_id", product_id), ("cek_id", cek_id)):
        if not val.isascii() or any(c.isspace() for c in val):
            raise PackFormatError(f"{label} must be ASCII without whitespace")

    if pack_id is None:
        pack_id = os.urandom(PACK_ID_LEN)
    elif len(pack_id) != PACK_ID_LEN:
        raise PackFormatError("pack_id must be 16 bytes")

    if not entries:
        raise PackFormatError("empty pack rejected (entry_count >= 1)")

    # Sort by path for stable builder order → entry_index ASC by sorted path.
    # Spec: entry_id == entry_index; builder assigns 0..n-1 after path sort.
    canon_items: list[tuple[str, bytes]] = []
    for path, raw in entries.items():
        cpath = canonicalize_pack_path(path)
        if not isinstance(raw, (bytes, bytearray)):
            raise PackFormatError("entry data must be bytes")
        canon_items.append((cpath, bytes(raw)))
    canon_items.sort(key=lambda t: t[0])
    assert_no_case_collisions([p for p, _ in canon_items])

    entry_count = len(canon_items)
    if entry_count < MIN_ENTRY_COUNT or entry_count > MAX_ENTRY_COUNT:
        raise PackFormatError("entry_count out of range")

    total_raw = sum(len(r) for _, r in canon_items)
    if total_raw > max_total_raw_size:
        raise PackFormatError("total raw exceeds max_total_raw_size")

    pack_aes_key = derive_pack_aes_key(cek, pack_id, cek_id)
    aesgcm = AESGCM(pack_aes_key)

    built: list[_BuiltEntry] = []
    rel = 0
    for idx, (path, raw) in enumerate(canon_items):
        raw_size = len(raw)
        stored = _zlib_wrap(raw)
        stored_size = len(stored)
        _check_size_limits(raw_size, stored_size)
        ciphertext_size = stored_size  # GCM CT length == plaintext length
        nonce = derived_nonce(idx)
        aad = build_entry_aad(
            product_id=product_id,
            cek_id=cek_id,
            pack_id=pack_id,
            format_version=FORMAT_VERSION,
            entry_id=idx,
            path=path,
            raw_size=raw_size,
            stored_size=stored_size,
            ciphertext_size=ciphertext_size,
            flags=PHASE1_FLAGS,
        )
        # AESGCM.encrypt returns ciphertext || tag
        sealed = aesgcm.encrypt(nonce, stored, aad)
        ct, tag = sealed[:-GCM_TAG_LEN], sealed[-GCM_TAG_LEN:]
        _require_exact(len(ct) == ciphertext_size, "ciphertext length mismatch")
        meta = PackEntryMeta(
            entry_id=idx,
            path=path,
            raw_size=raw_size,
            stored_size=stored_size,
            ciphertext_size=ciphertext_size,
            data_rel_offset=rel,
            nonce=nonce,
            tag=tag,
            flags=PHASE1_FLAGS,
        )
        built.append(_BuiltEntry(meta=meta, ciphertext=ct))
        # Zero-size entries share the same offset with the next (not overlap).
        rel += ciphertext_size

    metas = [b.meta for b in built]
    table_blob = b"".join(_encode_table_entry(m) for m in metas)
    table_size = len(table_blob)

    # Header variable strings (u16be lengths).
    pid_bytes = product_id.encode("utf-8")
    cid_bytes = cek_id.encode("utf-8")
    var_strings = _u16be(len(pid_bytes)) + pid_bytes + _u16be(len(cid_bytes)) + cid_bytes
    var_strings += _u16be(PACK_ID_LEN) + pack_id
    header_size = MMB2_FIXED_PREAMBLE + len(var_strings)
    if header_size > MAX_HEADER_SIZE:
        raise PackFormatError("header_size exceeds limit")

    table_offset = header_size
    # Manifest size = body + 32; body depends on manifest_size itself → solve.
    # manifest_offset = table_offset + table_size
    # data_offset = manifest_offset + manifest_size
    # body length without the size fields that include manifest_size is fixed
    # once we know all other values; manifest_size appears IN the body.
    # We compute body with a placeholder then set the real size.
    manifest_offset = table_offset + table_size

    def _body_for(manifest_size: int, data_offset: int) -> bytes:
        return _encode_manifest_body(
            format_version=FORMAT_VERSION,
            header_size=header_size,
            header_flags=PHASE1_FLAGS,
            entry_count=entry_count,
            table_offset=table_offset,
            table_size=table_size,
            manifest_offset=manifest_offset,
            manifest_size=manifest_size,
            data_offset=data_offset,
            product_id=product_id,
            cek_id=cek_id,
            pack_id=pack_id,
            entries=metas,
        )

    # Body length is independent of the numeric value of manifest_size /
    # data_offset (fixed-width fields), so one pass is enough.
    probe = _body_for(0, 0)
    manifest_size = len(probe) + MANIFEST_MAC_LEN
    if manifest_size > MAX_MANIFEST_SIZE:
        raise PackFormatError("manifest_size exceeds limit")
    data_offset = manifest_offset + manifest_size
    manifest_body = _body_for(manifest_size, data_offset)
    _require_exact(len(manifest_body) + MANIFEST_MAC_LEN == manifest_size, "manifest_size inconsistency")

    manifest_key = derive_manifest_key(cek, pack_id, cek_id)
    mac = hmac.new(manifest_key, MANIFEST_MAC_PREFIX + manifest_body, sha256).digest()
    _require_exact(len(mac) == MANIFEST_MAC_LEN, "mac length")

    # Fixed preamble (LE integers).
    preamble = (
        MAGIC
        + _u16le(FORMAT_VERSION)
        + _u32le(header_size)
        + _u32le(PHASE1_FLAGS)
        + _u32le(entry_count)
        + _u64le(table_offset)
        + _u64le(table_size)
        + _u64le(manifest_offset)
        + _u64le(manifest_size)
        + _u64le(data_offset)
    )
    _require_exact(len(preamble) == MMB2_FIXED_PREAMBLE, "preamble size")
    header = preamble + var_strings
    _require_exact(len(header) == header_size, "header_size mismatch")
    _require_exact(header_size == table_offset, "table_offset != header_size")

    data_blob = b"".join(b.ciphertext for b in built)
    out = header + table_blob + manifest_body + mac + data_blob
    if len(out) > MAX_PACK_FILE_SIZE:
        raise PackFormatError("pack file exceeds size limit")
    _require_exact(len(out) == data_offset + len(data_blob), "layout EOF mismatch")
    return out


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackInfo:
    product_id: str
    cek_id: str
    pack_id: bytes
    entry_count: int
    paths: tuple[str, ...]


class Mmb2Reader:
    """Authenticated MMB2 reader bound to a PackSession."""

    def __init__(
        self,
        blob: bytes,
        session: PackSession,
        *,
        max_total_raw_size: int = PROVISIONAL_MAX_TOTAL_RAW_SIZE,
    ) -> None:
        self._max_total_raw = max_total_raw_size
        self._session = session
        self._blob = memoryview(blob)
        self._entries: list[PackEntryMeta] = []
        self._by_path: dict[str, PackEntryMeta] = {}
        self._data_offset = 0
        self._product_id = ""
        self._cek_id = ""
        self._pack_id = b""
        self._pack_aes_key = b""
        self._parse_and_authenticate()

    @property
    def info(self) -> PackInfo:
        return PackInfo(
            product_id=self._product_id,
            cek_id=self._cek_id,
            pack_id=self._pack_id,
            entry_count=len(self._entries),
            paths=tuple(e.path for e in self._entries),
        )

    def list_paths(self) -> list[str]:
        return [e.path for e in self._entries]

    def read_entry(self, path: str) -> bytes:
        cpath = canonicalize_pack_path(path)
        meta = self._by_path.get(cpath)
        if meta is None:
            # try as already-canonical miss
            raise PackFormatError(f"path not in pack: {cpath!r}")
        return self._decrypt_entry(meta)

    def read_all(self) -> dict[str, bytes]:
        return {e.path: self._decrypt_entry(e) for e in self._entries}

    # --- parse pipeline (§5.6) ---

    def _parse_and_authenticate(self) -> None:
        blob = self._blob
        file_size = len(blob)
        if file_size < MMB2_FIXED_PREAMBLE:
            raise PackFormatError("file too small")
        if file_size > MAX_PACK_FILE_SIZE:
            raise PackFormatError("file exceeds max pack size")

        # 1. Fixed header
        if bytes(blob[0:4]) != MAGIC:
            raise PackFormatError("bad magic")
        (format_version,) = struct.unpack_from("<H", blob, 4)
        header_size, flags, entry_count = struct.unpack_from("<III", blob, 6)
        table_offset, table_size, manifest_offset, manifest_size, data_offset = struct.unpack_from(
            "<5Q", blob, 18
        )
        _require_exact(format_version == FORMAT_VERSION, "unsupported format_version")
        _require_exact(flags == PHASE1_FLAGS, "unknown header flags")
        if entry_count < MIN_ENTRY_COUNT or entry_count > MAX_ENTRY_COUNT:
            raise PackFormatError("entry_count out of range")
        if header_size < MMB2_FIXED_PREAMBLE or header_size > MAX_HEADER_SIZE:
            raise PackFormatError("header_size out of range")

        # 2. Pre-auth boundary checks (do not trust yet)
        _require_exact(table_offset == header_size, "table_offset != header_size")
        _require_exact(manifest_offset == table_offset + table_size, "manifest_offset mismatch")
        _require_exact(data_offset == manifest_offset + manifest_size, "data_offset mismatch")
        _require_exact(manifest_size >= MANIFEST_MAC_LEN, "manifest_size too small")
        _require_exact(manifest_size <= MAX_MANIFEST_SIZE, "manifest_size exceeds limit")
        _require_exact(table_size <= MAX_MANIFEST_SIZE, "table_size exceeds limit")
        if data_offset > file_size:
            raise PackFormatError("data_offset beyond EOF")
        if manifest_offset + manifest_size > file_size:
            raise PackFormatError("manifest beyond EOF")
        if table_offset + table_size > file_size:
            raise PackFormatError("table beyond EOF")

        # Header variable strings
        off = MMB2_FIXED_PREAMBLE
        product_id, off = _read_lp_utf8(blob, off, max_len=MAX_PATH_BYTES)
        cek_id, off = _read_lp_utf8(blob, off, max_len=MAX_PATH_BYTES)
        if off + 2 > header_size:
            raise PackFormatError("truncated pack_id in header")
        (pid_len,) = struct.unpack_from(">H", blob, off)
        off += 2
        _require_exact(pid_len == PACK_ID_LEN, "header pack_id length")
        if off + PACK_ID_LEN != header_size:
            raise PackFormatError("header_size does not match trailing pack_id")
        pack_id = bytes(blob[off : off + PACK_ID_LEN])

        # Session binding (F-03) — before decrypting assets; after we know ids
        if product_id != self._session.authorized_product_id:
            raise SessionBindingError("product_id mismatch")
        if cek_id != self._session.authorized_cek_id:
            raise SessionBindingError("cek_id mismatch")
        cek = bytes(self._session.decrypted_cek_32)
        if len(cek) != CEK_LEN:
            raise PackFormatError("session CEK length")

        # 3. Manifest HMAC
        manifest_blob = bytes(blob[manifest_offset : manifest_offset + manifest_size])
        body = manifest_blob[:-MANIFEST_MAC_LEN]
        mac = manifest_blob[-MANIFEST_MAC_LEN:]
        manifest_key = derive_manifest_key(cek, pack_id, cek_id)
        expect = hmac.new(manifest_key, MANIFEST_MAC_PREFIX + body, sha256).digest()
        if not hmac.compare_digest(expect, mac):
            raise PackFormatError("manifest MAC mismatch")

        # 4. Header ≡ Manifest (all authenticated fields)
        m_header, m_entries = _parse_manifest_body(body)
        _require_exact(m_header["format_version"] == format_version, "manifest format_version")
        _require_exact(m_header["header_size"] == header_size, "manifest header_size")
        _require_exact(m_header["header_flags"] == flags, "manifest header_flags")
        _require_exact(m_header["entry_count"] == entry_count, "manifest entry_count")
        _require_exact(m_header["table_offset"] == table_offset, "manifest table_offset")
        _require_exact(m_header["table_size"] == table_size, "manifest table_size")
        _require_exact(m_header["manifest_offset"] == manifest_offset, "manifest manifest_offset")
        _require_exact(m_header["manifest_size"] == manifest_size, "manifest manifest_size")
        _require_exact(m_header["data_offset"] == data_offset, "manifest data_offset")
        _require_exact(m_header["product_id"] == product_id, "manifest product_id")
        _require_exact(m_header["cek_id"] == cek_id, "manifest cek_id")
        _require_exact(m_header["pack_id"] == pack_id, "manifest pack_id")
        _require_exact(
            len(body) + MANIFEST_MAC_LEN == manifest_size,
            "parsed_manifest_body+32 != manifest_size",
        )

        # 5. Table ≡ Manifest
        table_mv = blob[table_offset : table_offset + table_size]
        t_entries, parsed_table_len = _parse_table(table_mv, entry_count)
        _require_exact(parsed_table_len == table_size, "parsed_table_bytes != table_size")
        if not _entries_semantically_equal(t_entries, m_entries):
            raise PackFormatError("table ≢ manifest")

        # Validate each entry meta + layout
        total_raw = 0
        expected_rel = 0
        paths: list[str] = []
        for i, e in enumerate(m_entries):
            _require_exact(e.entry_id == i, "entry_id != entry_index")
            expect_nonce = derived_nonce(i)
            _require_exact(e.nonce == expect_nonce, "nonce != derived_nonce")
            _require_exact(e.flags == PHASE1_FLAGS, "unknown entry flags")
            _require_exact(e.ciphertext_size == e.stored_size, "ciphertext_size != stored_size")
            _check_size_limits(e.raw_size, e.stored_size)
            cpath = canonicalize_pack_path(e.path)
            _require_exact(cpath == e.path, "path not canonical in pack")
            paths.append(cpath)
            # Layout: zero-size may share offset; non-zero must be contiguous.
            if e.ciphertext_size == 0:
                _require_exact(e.data_rel_offset == expected_rel, "zero-size offset mismatch")
            else:
                _require_exact(e.data_rel_offset == expected_rel, "data_rel_offset gap/overlap")
            expected_rel += e.ciphertext_size
            total_raw += e.raw_size
            end = data_offset + e.data_rel_offset + e.ciphertext_size
            if end > file_size:
                raise PackFormatError("entry data beyond EOF")

        assert_no_case_collisions(paths)
        _require_exact(data_offset + expected_rel == file_size, "trailing/gap after data")
        if total_raw > self._max_total_raw:
            raise PackFormatError("cumulative raw exceeds max_total_raw_size")

        self._product_id = product_id
        self._cek_id = cek_id
        self._pack_id = pack_id
        self._data_offset = data_offset
        self._entries = list(m_entries)
        self._by_path = {e.path: e for e in m_entries}
        self._pack_aes_key = derive_pack_aes_key(cek, pack_id, cek_id)

    def _decrypt_entry(self, meta: PackEntryMeta) -> bytes:
        # R-07: decrypt into temp only; return after tag OK.
        start = self._data_offset + meta.data_rel_offset
        end = start + meta.ciphertext_size
        ct = bytes(self._blob[start:end])
        aad = build_entry_aad(
            product_id=self._product_id,
            cek_id=self._cek_id,
            pack_id=self._pack_id,
            format_version=FORMAT_VERSION,
            entry_id=meta.entry_id,
            path=meta.path,
            raw_size=meta.raw_size,
            stored_size=meta.stored_size,
            ciphertext_size=meta.ciphertext_size,
            flags=meta.flags,
        )
        aesgcm = AESGCM(self._pack_aes_key)
        try:
            stored = aesgcm.decrypt(meta.nonce, ct + meta.tag, aad)
        except Exception as e:
            raise PackFormatError("AES-GCM decrypt/tag failed") from e
        _require_exact(len(stored) == meta.stored_size, "stored size after decrypt")
        return _zlib_unwrap(stored, meta.raw_size)


def read_pack(
    blob: bytes,
    session: PackSession,
    *,
    max_total_raw_size: int = PROVISIONAL_MAX_TOTAL_RAW_SIZE,
) -> dict[str, bytes]:
    """Convenience: authenticate + decrypt all entries."""
    return Mmb2Reader(blob, session, max_total_raw_size=max_total_raw_size).read_all()
