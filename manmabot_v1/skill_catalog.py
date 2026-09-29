"""Class magic from skills_names.json, icons in data/total, and hotbar roles."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from manmabot_v1.hotbar.inspect import load_role_map, resolve_role

_DATA = Path(__file__).resolve().parent / "data"
_SKILLS_PATH = _DATA / "skills_names.json"
_ICON_DIR = _DATA / "total"

# Schedule UI class id → catalog class id.
_UI_CLASS = {
    "elf": "elf",
    "mage": "wizard",
    "knight": "knight",
    "royal": "prince",
}
_CATEGORY_EN = {
    "offensive_buff": "Offensive buffs",
    "defensive_buff": "Defensive buffs",
    "vision_detection": "Vision / detection",
    "healing_recovery": "Healing",
    "mp_management": "MP",
    "offensive_magic": "Offensive magic",
    "support_utility": "Utility",
}

# Schedule UI category id → catalog category id.
_UI_CATEGORY = {
    "attack_buff": "offensive_buff",
    "defense_buff": "defensive_buff",
    "vision": "vision_detection",
    "recovery": "healing_recovery",
    "mp": "mp_management",
    "attack_magic": "offensive_magic",
    "utility": "support_utility",
}


@dataclass(frozen=True)
class ClassSkill:
    ui_class: str
    category: str
    skill_id: int
    ko: str
    zh_tw: str
    zh_cn: str
    role: str
    icon: Path | None

    def label(self, language: str) -> str:
        lang = str(language or "").strip().lower()
        if lang.startswith("zh"):
            return self.zh_cn or self.zh_tw or self.ko
        if lang.startswith("en"):
            return self.ko
        return self.ko or self.zh_tw or self.zh_cn

    @property
    def setting_key(self) -> str:
        return f"{self.ui_class}_{self.skill_id}"


def _norm(name: str) -> str:
    return name.replace(":", "").replace("：", "").replace(" ", "").strip()


def _icon_index() -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not _ICON_DIR.is_dir():
        return index
    for path in _ICON_DIR.glob("*.png"):
        index[_norm(path.stem)] = path
        index.setdefault(path.stem, path)
    return index


def _roles() -> dict:
    try:
        return load_role_map()
    except Exception:
        return {}


class SkillCatalog:
    def __init__(self, skills: tuple[ClassSkill, ...], category_names: dict[str, dict[str, str]]) -> None:
        self.skills = skills
        self._category_names = category_names

    def category_label(self, ui_category: str, language: str) -> str:
        catalog_id = _UI_CATEGORY.get(ui_category, ui_category)
        names = self._category_names.get(catalog_id, {})
        if language == "zh":
            return names.get("zh_cn") or names.get("zh_tw") or names.get("ko") or ui_category
        if language == "ko":
            return names.get("ko") or ui_category
        return _CATEGORY_EN.get(catalog_id, names.get("ko") or ui_category)

    def for_filter(self, ui_class: str, ui_category: str) -> list[ClassSkill]:
        return [
            skill for skill in self.skills
            if skill.ui_class == ui_class and skill.category == ui_category
        ]


def load_skill_catalog() -> SkillCatalog:
    payload = json.loads(_SKILLS_PATH.read_text(encoding="utf-8"))
    icons = _icon_index()
    roles = _roles()
    category_names = {
        str(item.get("id")): {
            "ko": str(item.get("ko") or ""),
            "zh_tw": str(item.get("zh_tw") or ""),
            "zh_cn": str(item.get("zh_cn") or ""),
        }
        for item in payload.get("categories", [])
    }
    ui_by_catalog = {catalog: ui for ui, catalog in _UI_CLASS.items()}
    category_by_catalog = {catalog: ui for ui, catalog in _UI_CATEGORY.items()}
    skills: list[ClassSkill] = []
    for catalog_class, block in payload.get("classes", {}).items():
        ui_class = ui_by_catalog.get(str(catalog_class))
        if not ui_class:
            continue
        grouped = block.get("skills_by_category") or {}
        for catalog_category, rows in grouped.items():
            ui_category = category_by_catalog.get(str(catalog_category))
            if not ui_category:
                continue
            for row in rows:
                ko = str(row.get("ko") or "").strip()
                zh_tw = str(row.get("zh_tw") or "").strip()
                zh_cn = str(row.get("zh_cn") or "").strip()
                icon = icons.get(ko) or icons.get(_norm(ko))
                role = ""
                if roles:
                    role = resolve_role("", ko, zh_tw or zh_cn, roles)
                    if not role:
                        by_kr = roles.get("__kr__") or {}
                        folded = _norm(ko)
                        role = next(
                            (value for name, value in by_kr.items() if _norm(name) == folded),
                            "",
                        )
                skills.append(
                    ClassSkill(
                        ui_class=ui_class,
                        category=ui_category,
                        skill_id=int(row.get("id")),
                        ko=ko,
                        zh_tw=zh_tw,
                        zh_cn=zh_cn,
                        role=role,
                        icon=icon,
                    )
                )
    return SkillCatalog(tuple(skills), category_names)
