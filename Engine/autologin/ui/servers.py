"""Load selectable server names from bot/data/servers_*.json by UI language."""
import json
import os
import re
from functools import lru_cache

from .i18n import LANGUAGES

# UI lang code (en, ko, zh_cn, zh_tw) -> servers_<suffix>.json
UI_LANG_TO_SERVER_FILE = {
    "en": "en",
    "ko": "ko",
    "zh_cn": "zh-CN",
    "zh_tw": "zh-TW",
}


def _bot_search_dirs():
    try:
        from launcher.auto_login import bot_dir
        bd = bot_dir()
        return [bd, os.path.join(bd, "data")]
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        src = os.path.dirname(here)
        bot = os.path.join(src, "bot")
        return [bot, os.path.join(bot, "data")]


def _server_json_path(lang_code: str):
    suffix = UI_LANG_TO_SERVER_FILE.get(lang_code)
    if not suffix:
        suffix = UI_LANG_TO_SERVER_FILE.get(LANGUAGES.get("English", "en"), "en")
    fname = "servers_%s.json" % suffix
    for base in _bot_search_dirs():
        path = os.path.join(base, fname)
        if os.path.isfile(path):
            return path
    return None


def _read_server_json(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        raw = re.sub(r",\s*([}\]])", r"\1", raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        for rows in data.values():
            if not isinstance(rows, dict):
                continue
            for cols in rows.values():
                if not isinstance(cols, dict):
                    continue
                if any((cols.get(c) or "").strip() for c in ("left", "right")):
                    return data
        return {}
    except Exception:
        return {}


def _sort_key(value):
    text = str(value)
    return (0, int(text)) if text.isdigit() else (1, text)


def _names_from_table(data: dict) -> list:
    names = []
    seen = set()
    for page in sorted(data.keys(), key=_sort_key):
        rows = data.get(page)
        if not isinstance(rows, dict):
            continue
        for row in sorted(rows.keys(), key=_sort_key):
            cols = rows.get(row)
            if not isinstance(cols, dict):
                continue
            for side in ("left", "right"):
                name = (cols.get(side) or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


@lru_cache(maxsize=8)
def server_names_for_lang(lang_code: str) -> tuple:
    path = _server_json_path(lang_code)
    if not path:
        return ()
    return tuple(_names_from_table(_read_server_json(path)))


def server_names_list(lang_code: str) -> list:
    """Return server names for the UI language (readonly combobox values)."""
    return list(server_names_for_lang(lang_code))
