"""MMB2 Phase-1 constants (READY Phase 1 Spec §5)."""

from __future__ import annotations

MAGIC = b"MMB2"
FORMAT_VERSION = 1
MMB2_FIXED_PREAMBLE = 58  # 4+2+4+4+4+5*8

PACK_ID_LEN = 16
NONCE_LEN = 12
GCM_TAG_LEN = 16
MANIFEST_MAC_LEN = 32
CEK_LEN = 32

INFO_AES = "mmb2-aes-v1|"
INFO_MANIFEST = "mmb2-manifest-v1|"
MANIFEST_MAC_PREFIX = b"MMB2-MANIFEST-v1\0"
AAD_PREFIX = b"MMB2-AAD-v1\0"

# Limits (R-03)
MAX_PACK_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_HEADER_SIZE = 64 * 1024  # 64 KiB
MAX_MANIFEST_SIZE = 64 * 1024 * 1024  # 64 MiB
MIN_ENTRY_COUNT = 1
MAX_ENTRY_COUNT = 100_000
MAX_PATH_BYTES = 1024
# Per-entry caps: raised after Stage-5 inventory (legacy nav.png ~78 MiB PNG).
MAX_STORED_SIZE = 256 * 1024 * 1024  # 256 MiB per entry (matches raw; PNGs barely shrink)
MAX_RAW_SIZE = 256 * 1024 * 1024  # 256 MiB per entry
MAX_COMPRESSION_RATIO = 200  # stored:raw <= 200:1 when raw>0

# Override via Mmb2Limits / write_pack(max_total_raw_size=...).
PROVISIONAL_MAX_TOTAL_RAW_SIZE = 4 * 1024 * 1024 * 1024  # 4 GiB

PHASE1_FLAGS = 0
