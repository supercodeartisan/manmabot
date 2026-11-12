"""Rows for the party monitor's received-buff table.

The mage reads ``member_orders.party_buffs``. This only formats that list.
"""
from __future__ import annotations

import time
from typing import Any


def party_buff_lines(
    rows: Any,
    now: float | None = None,
) -> list[tuple[str, str, str]]:
    """``(name, buffs, age)`` for each received member row."""
    clock = time.time() if now is None else float(now)
    lines: list[tuple[str, str, str]] = []
    if not isinstance(rows, list):
        return lines
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("from") or "").strip() or "—"
        parts: list[str] = []
        buffs = row.get("buffs")
        if isinstance(buffs, list):
            for buff in buffs:
                if not isinstance(buff, dict):
                    continue
                label = str(buff.get("name") or "").strip()
                skill = buff.get("skill")
                if not label:
                    label = "" if skill in (None, "") else str(skill)
                bit = label
                if skill not in (None, "", 0, "0") and label != str(skill):
                    bit = f"{label} {skill}".strip()
                duration = buff.get("duration")
                if duration not in (None, ""):
                    bit = f"{bit} {duration}s".strip()
                if bit:
                    parts.append(bit)
        if bool(row.get("poisoned")):
            parts.append("poison")
        text = ", ".join(parts) if parts else "—"
        age = "—"
        try:
            noted = float(row.get("noted_at") or 0.0)
        except (TypeError, ValueError):
            noted = 0.0
        if noted > 0.0:
            age = f"{max(0, int(clock - noted))}s"
        lines.append((name, text, age))
    return lines
