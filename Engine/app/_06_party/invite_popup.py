"""Read the in-game party invite popup from the uidialog snapshot.

``uidialog_listen`` lists every open Yes/No confirm under ``confirm`` (chat
confirm panel or popup window) with its text (``\\f`` colour codes already
stripped, UTF-8). Korean client text of a party invite::

    번개공격이 자동 분배 파티에 초대합니다. 승낙하시겠습니까?
    poorboy이(가) 자동 분배 파티에 초대합니다. 승낙하시겠습니까?

A trade request ("…거래를 원합니다. 거래하시겠습니까?(Y/N)") is never an invite.
``ask`` 954 (0x3BA) is the invite callback id; logged, not required.
"""
from __future__ import annotations

import re
from typing import Any, Optional

INVITE_ASK = 954
_CODES = re.compile(r"\f.|[\x00-\x1f]", re.S)
# Name, then the subject particle: 이(가) for latin names, 이 / 가 otherwise.
_INVITER = re.compile(r"^(?P<name>\S+?)(?:이\(가\)|이|가)\s")


def clean_text(msg: Any) -> str:
    return " ".join(_CODES.sub("", str(msg or "")).split())


def is_invite_text(msg: Any) -> bool:
    text = clean_text(msg)
    if "거래" in text:
        return False
    return "파티" in text and "초대합니다" in text and ("승낙" in text or "수락" in text)


def inviter_of(msg: Any) -> str:
    m = _INVITER.match(clean_text(msg))
    return m.group("name") if m else ""


def party_invite(snapshot: Any) -> Optional[dict[str, Any]]:
    """The open party invite confirm in a uidialog snapshot, else None."""
    if not isinstance(snapshot, dict):
        return None
    for row in snapshot.get("confirm") or []:
        if not isinstance(row, dict):
            continue
        msg = clean_text(row.get("msg"))
        if not is_invite_text(msg):
            continue
        try:
            ask = int(row.get("ask") or 0)
        except (TypeError, ValueError):
            ask = 0
        return {
            "inst": str(row.get("inst") or ""),
            "src": str(row.get("src") or ""),
            "ask": ask,
            "msg": msg,
            "inviter": inviter_of(msg),
        }
    return None


def same_name(a: Any, b: Any) -> bool:
    x, y = str(a or "").strip().casefold(), str(b or "").strip().casefold()
    return bool(x) and x == y


__all__ = [
    "INVITE_ASK",
    "clean_text",
    "inviter_of",
    "is_invite_text",
    "party_invite",
    "same_name",
]
