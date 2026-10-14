"""Obfuscated asset pack (stdlib-only) for Engine/data.

Layered hardening for customer builds — not perfect secrecy. A skilled
attacker who runs the app can still recover assets from memory or the
runtime cache. Goal: stop casual folder browsing / zip ripping of map
PNGs and related data.

Format (version 1):
  magic (4) = b'MMBA'
  version u16 = 1
  flags u16 = 0
  salt 16 bytes
  entry_count u32
  for each entry:
    path_len u16
    path utf-8
    raw_size u64
    stored_size u64
    crc32 u32
  payload: concatenated zlib(raw) blobs, then whole payload XOR keystream
  trailer: hmac-sha256 over (header + xored payload)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import struct
import zlib
from pathlib import Path
from typing import Iterable

MAGIC = b"MMBA"
VERSION = 1
_HEADER = struct.Struct("<4sHH16sI")  # magic, ver, flags, salt, count


def _obfuscated_passphrase() -> bytes:
    # Split so a trivial strings scan is less useful. Not strong crypto.
    a = bytes([0x4D, 0x61, 0x6E, 0x6D, 0x61])  # Manma
    b = bytes([0x62, 0x6F, 0x74, 0x56, 0x31])  # botV1
    c = hashlib.sha256(b"map-pack-layer-2026").digest()[:10]
    return a + b + c


def _derive_key(salt: bytes) -> bytes:
    return hashlib.scrypt(
        _obfuscated_passphrase(),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )


def _keystream(key: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hashlib.sha256(key + counter.to_bytes(8, "little")).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, key: bytes) -> bytes:
    stream = _keystream(key, len(data))
    return bytes(a ^ b for a, b in zip(data, stream))


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if "__pycache__" in path.parts:
            continue
        yield path


def build_pack(source_dir: Path, pack_path: Path) -> dict:
    """Create ``pack_path`` from all files under ``source_dir``."""
    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(f"asset source missing: {source_dir}")

    salt = os.urandom(16)
    key = _derive_key(salt)

    table = bytearray()
    payload = bytearray()
    meta: list[tuple[str, int, int, int]] = []
    for path in iter_files(source_dir):
        rel = path.relative_to(source_dir).as_posix()
        raw = path.read_bytes()
        stored = zlib.compress(raw, level=9)
        crc = _crc32(raw)
        rel_b = rel.encode("utf-8")
        table.extend(struct.pack("<H", len(rel_b)))
        table.extend(rel_b)
        table.extend(struct.pack("<QQI", len(raw), len(stored), crc))
        payload.extend(stored)
        meta.append((rel, len(raw), len(stored), crc))

    header = bytearray(_HEADER.pack(MAGIC, VERSION, 0, salt, len(meta)))
    header.extend(table)
    xored = _xor(bytes(payload), key)
    digest = hmac.new(key, bytes(header) + xored, hashlib.sha256).digest()

    pack_path.parent.mkdir(parents=True, exist_ok=True)
    with pack_path.open("wb") as fh:
        fh.write(header)
        fh.write(xored)
        fh.write(digest)

    total_raw = sum(m[1] for m in meta)
    return {
        "files": len(meta),
        "raw_bytes": total_raw,
        "pack_bytes": pack_path.stat().st_size,
        "pack_path": str(pack_path),
    }


def load_pack_bytes(pack_path: Path) -> dict[str, bytes]:
    """Decrypt/verify pack into memory. Keys are posix relative paths."""
    blob = pack_path.resolve().read_bytes()
    files, _count = _decode_pack(blob)
    return files


def extract_pack(pack_path: Path, dest_dir: Path) -> dict:
    """Decrypt/verify pack into ``dest_dir`` (files overwritten)."""
    pack_path = pack_path.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    files = load_pack_bytes(pack_path)
    for rel, raw in files.items():
        out = dest_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
    return {"files": len(files), "dest": str(dest_dir)}


def _decode_pack(blob: bytes) -> tuple[dict[str, bytes], int]:
    if len(blob) < _HEADER.size + 32:
        raise ValueError("asset pack too small")
    magic, version, _flags, salt, count = _HEADER.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError("bad asset pack magic")
    if version != VERSION:
        raise ValueError(f"unsupported asset pack version: {version}")
    key = _derive_key(salt)
    offset = _HEADER.size
    entries: list[tuple[str, int, int, int]] = []
    for _ in range(count):
        path_len = struct.unpack_from("<H", blob, offset)[0]
        offset += 2
        rel = blob[offset : offset + path_len].decode("utf-8")
        offset += path_len
        raw_size, stored_size, crc = struct.unpack_from("<QQI", blob, offset)
        offset += 8 + 8 + 4
        entries.append((rel, raw_size, stored_size, crc))

    payload_xored = blob[offset : len(blob) - 32]
    digest = blob[len(blob) - 32 :]
    header = blob[:offset]
    expect = hmac.new(key, header + payload_xored, hashlib.sha256).digest()
    if not hmac.compare_digest(expect, digest):
        raise ValueError("asset pack HMAC mismatch (corrupt or wrong key)")

    payload = _xor(payload_xored, key)
    cursor = 0
    files: dict[str, bytes] = {}
    for rel, raw_size, stored_size, crc in entries:
        stored = payload[cursor : cursor + stored_size]
        cursor += stored_size
        raw = zlib.decompress(stored)
        if len(raw) != raw_size or _crc32(raw) != crc:
            raise ValueError(f"asset CRC mismatch: {rel}")
        files[rel] = raw
    return files, count
