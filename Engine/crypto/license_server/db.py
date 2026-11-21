"""SQLite schema + helpers for the license server."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS licenses (
    license_id      TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL,
    cek_id          TEXT NOT NULL,
    license_key_hash TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL CHECK(status IN ('issued','revoked','suspended')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bindings (
    license_id          TEXT PRIMARY KEY REFERENCES licenses(license_id),
    device_id           TEXT NOT NULL,
    hwid_hash           TEXT,
    spki_der            BLOB NOT NULL,
    activation_id       TEXT NOT NULL,
    binding_generation  INTEGER NOT NULL,
    bound_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activation_requests (
    request_id      TEXT PRIMARY KEY,
    license_id      TEXT NOT NULL REFERENCES licenses(license_id),
    payload_hash    TEXT NOT NULL,
    response_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS binding_resets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id      TEXT NOT NULL REFERENCES licenses(license_id),
    old_device_id   TEXT NOT NULL,
    old_generation  INTEGER NOT NULL,
    new_generation  INTEGER NOT NULL,
    reset_at        TEXT NOT NULL,
    reason          TEXT,
    admin_id        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cek_vault (
    cek_id      TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL,
    ciphertext  BLOB NOT NULL,
    nonce       BLOB NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pack_id_reservations (
    cek_id      TEXT NOT NULL,
    pack_id     BLOB NOT NULL,
    note        TEXT,
    reserved_at TEXT NOT NULL,
    PRIMARY KEY (cek_id, pack_id)
);

CREATE TABLE IF NOT EXISTS signing_keys_meta (
    kid         TEXT PRIMARY KEY,
    role        TEXT NOT NULL CHECK(role IN ('current','previous','retired')),
    created_at  TEXT NOT NULL,
    public_pem  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bindings_device
    ON bindings(device_id);
CREATE INDEX IF NOT EXISTS idx_resets_license_device
    ON binding_resets(license_id, old_device_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite with foreign keys; caller manages transactions."""
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


class LicenseDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = connect(self.path)
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def begin_immediate(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self.conn.execute("COMMIT")

    def rollback(self) -> None:
        self.conn.execute("ROLLBACK")
