"""Detect Purple / Lineage Classic UI language from OCR text.

Screens can switch among Korean, English, Traditional Chinese and
Simplified Chinese independently of launcher_config language.
"""
from __future__ import annotations

LANGS = ("ko", "en", "zh-TW", "zh-CN")

# Windows.Media.Ocr language tags
WINOCR_TAGS = {
    "ko": "ko",
    "en": "en",
    "zh-TW": "zh-Hant",
    "zh-CN": "zh-Hans",
    "zh-HK": "zh-Hant",
    "zh-Hant": "zh-Hant",
    "zh-Hans": "zh-Hans",
}

# Characters that usually appear only in one Chinese script.
_TW_ONLY = set(
    "選擇驗證裝置登錄經關爲後從餘髮體東車門開風雲點無這過還將來時"
    "會對帳務錄證擇裝簡經"
)
_CN_ONLY = set(
    "选择验证装置登录经关为后从余发体东车门开风云点无这过还将时"
    "会对帐务录证择装简经"
)


def detect_ui_lang(text: str) -> str | None:
    """Return ko / en / zh-TW / zh-CN from OCR, or None if unsure.

    Title-bar English (Lineage Classic, LIVE, Login) is ignored when
    Hangul or CJK body text is present so a Chinese splash is not
    classified as English.
    """
    if not text:
        return None
    hangul = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    cjk = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    tw = sum(1 for c in cjk if c in _TW_ONLY)
    cn = sum(1 for c in cjk if c in _CN_ONLY)

    if hangul >= 2:
        return "ko"
    if len(cjk) >= 2:
        if tw > cn:
            return "zh-TW"
        if cn > tw:
            return "zh-CN"
        if any(m in text for m in ("證", "擇", "錄", "裝", "簡", "驗證", "裝置")):
            return "zh-TW"
        if any(m in text for m in ("证", "择", "录", "装", "简", "验证", "装置")):
            return "zh-CN"
        return "zh-TW"
    if latin >= 10:
        return "en"
    return None


def has_hangul(text: str) -> bool:
    return any("\uac00" <= c <= "\ud7a3" for c in text or "")


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in text or "")
