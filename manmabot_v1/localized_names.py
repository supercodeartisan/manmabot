"""Map and species display names for English, Korean, and Chinese.

Internal ids stay Korean (vision / profile keys). This module only changes
what the Version 1 UI shows.
"""
from __future__ import annotations

import re
from functools import lru_cache

from manmabot_v1.strings import normalize_language

_SEARCH_LANGS = ("en", "ko", "zh")

_LANG_I = {"en": 0, "ko": 1, "zh": 2}
_FOLD = re.compile(r"\s+")

# pack id → (en, ko, zh)  — non-dungeon maps and optional dungeon overrides
MAP_NAMES: dict[str, tuple[str, str, str]] = {
    "talking_island": ("Talking Island", "말하는 섬", "说话之岛"),
    "mainland": ("Mainland", "본토", "大陆"),
    "thebes_desert_dungeon": (
        "Thebes Desert Dungeon",
        "테베 사막 던전",
        "底比斯沙漠地下城",
    ),
}

# ``{place}_dungeon_F{n}`` / ``{place}_dungeon_F{n}_{room}``
_PLACE_NAMES: dict[str, tuple[str, str, str]] = {
    "talking_island": ("Talking Island", "말하는 섬", "说话之岛"),
    "desert": ("Desert", "사막", "沙漠"),
    "giran": ("Giran", "기란", "奇岩"),
    "gludio": ("Gludio", "글루디오", "古鲁丁"),
    "ant_cave": ("Ant Cave", "개미굴", "蚂蚁洞穴"),
}
_DUNGEON_ID = re.compile(
    r"^(?P<place>.+)_dungeon_F(?P<major>\d+)(?:_(?P<minor>\d+))?$",
    re.IGNORECASE,
)
_ROUTE_POINT = re.compile(
    r"^(?P<kind>area|mid)[_-]?(?P<num>\d+)(?:_(?P<extra>.+))?$",
    re.IGNORECASE,
)

# Korean catalog name → (en, ko, zh)
# Engine memory matching also loads species_aliases.json, which includes these
# plus Traditional-Chinese game labels such as 杜賓狗 / 地靈 / 妖魔.
SPECIES_NAMES: dict[str, tuple[str, str, str]] = {
    "가스트": ("Ghast", "가스트", "加斯"),
    "거대 개미": ("Giant Ant", "거대 개미", "巨大蚂蚁"),
    "거대 병정 개미": ("Giant Soldier Ant", "거대 병정 개미", "巨大兵蚁"),
    "개과": ("Canines", "개과", "犬类"),
    "고블린": ("Goblin", "고블린", "哥布林"),
    "괴물 눈": ("Monster Eye", "괴물 눈", "怪物之眼"),
    "그렘린": ("Gremlin", "그렘린", "格雷姆林"),
    "난쟁이": ("Dwarf", "난쟁이", "矮人"),
    "난쟁이족 전사": ("Dwarf Warrior", "난쟁이족 전사", "矮人战士"),
    "네루가 오크": ("Neruga Orc", "네루가 오크", "奈鲁加半兽人"),
    "놀": ("Gnoll", "놀", "豺狼人"),
    "눈사람": ("Snowman", "눈사람", "雪人"),
    "늑대": ("Wolf", "늑대", "狼"),
    "늑대인간": ("Werewolf", "늑대인간", "狼人"),
    "다크엘프": ("Dark Elf", "다크엘프", "黑暗精灵"),
    "도베르만": ("Doberman", "도베르만", "杜宾犬"),
    "돌 골렘": ("Stone Golem", "돌 골렘", "石魔像"),
    "두다-마라 오크": ("Duda-Mara Orc", "두다-마라 오크", "都达玛拉半兽人"),
    "드래곤 플라이": ("Dragon Fly", "드래곤 플라이", "飞龙蜻蜓"),
    "라미아": ("Lamia", "라미아", "拉米亚"),
    "라바 골렘": ("Lava Golem", "라바 골렘", "熔岩魔像"),
    "라이칸스로프": ("Lycanthrope", "라이칸스로프", "莱坎斯洛普"),
    "로바오크": ("Rova Orc", "로바오크", "罗巴半兽人"),
    "리자드맨": ("Lizardman", "리자드맨", "蜥蜴人"),
    "버그베어": ("Bugbear", "버그베어", "熊地精"),
    "불타는 궁수": ("Burning Archer", "불타는 궁수", "燃烧弓箭手"),
    "샤벨 타이거": ("Saber Tooth Tiger", "샤벨 타이거", "剑齿虎"),
    "세퍼드": ("Shepherd", "세퍼드", "牧羊犬"),
    "셸로브": ("Shellob", "셸로브", "谢洛布"),
    "스콜피온": ("Scorpion", "스콜피온", "蝎子"),
    "스파토이": ("Spartoi", "스파토이", "斯巴托"),
    "아울베어": ("Owlbear", "아울베어", "猫头鹰熊"),
    "아투바 오크": ("Atuba Orc", "아투바 오크", "阿图巴半兽人"),
    "에티": ("Ettin", "에티", "双头巨人"),
    "오우거": ("Ogre", "오우거", "食人魔"),
    "오크": ("Orc", "오크", "半兽人"),
    "오크 궁수": ("Orc Archer", "오크 궁수", "半兽人弓箭手"),
    "오크 마법사": ("Orc Wizard", "오크 마법사", "半兽人法师"),
    "오크전사": ("Orc Fighter", "오크전사", "半兽人战士"),
    "웅골리언트": ("Ungoliant", "웅골리언트", "安格利安特"),
    "임프": ("Imp", "임프", "小恶魔"),
    "장로": ("Elder", "장로", "长老"),
    "좀비": ("Zombie", "좀비", "僵尸"),
    "좀비 엘모어 마법사": ("Elmore Zombie Wizard", "좀비 엘모어 마법사", "艾尔摩僵尸法师"),
    "좀비 엘모어 병사": ("Elmore Zombie Soldier", "좀비 엘모어 병사", "艾尔摩僵尸士兵"),
    "좀비 엘모어 장군": ("Elmore Zombie General", "좀비 엘모어 장군", "艾尔摩僵尸将军"),
    "코볼트": ("Kobold", "코볼트", "狗头人"),
    "코카트리스": ("Cockatrice", "코카트리스", "鸡蛇兽"),
    "터틀 드래곤": ("Turtle Dragon", "터틀 드래곤", "龟龙"),
    "하피": ("Harpy", "하피", "鹰身女妖"),
    "해골": ("Skeleton", "해골", "骷髅"),
    "해골궁수": ("Skeleton Archer", "해골궁수", "骷髅弓箭手"),
    "허스키": ("Husky", "허스키", "哈士奇"),
    "허수아비": ("Scarecrow", "허수아비", "稻草人"),
    "홉고블린": ("Hobgoblin", "홉고블린", "霍布哥布林"),
    "흑기사": ("Dark Knight", "흑기사", "黑骑士"),
}

_SPECIES_FOLD: dict[str, tuple[str, str, str]] = {
    _FOLD.sub("", key).lower(): names for key, names in SPECIES_NAMES.items()
}

# Common hotbar / loot items → (en, ko, zh)
ITEM_NAMES: dict[str, tuple[str, str, str]] = {
    "아데나": ("Adena", "아데나", "金币"),
    "화살": ("Arrow", "화살", "箭"),
    "은화살": ("Silver Arrow", "은화살", "银箭"),
    "체력 회복제": ("Healing Potion", "체력 회복제", "体力恢复剂"),
    "빨간 물약": ("Red Potion", "빨간 물약", "红色药水"),
    "맑은 물약": ("White Potion", "맑은 물약", "白色药水"),
    "주홍 물약": ("Orange Potion", "주홍 물약", "橙色药水"),
    "파란 물약": ("Blue Potion", "파란 물약", "蓝色药水"),
    "초록 물약": ("Haste Potion", "초록 물약", "自我加速药水"),
    "강화 초록 물약": ("Greater Haste Potion", "강화 초록 물약", "强化自我加速药水"),
    "비취 물약": ("Jade Potion", "비취 물약", "翡翠药水"),
    "해독제": ("Antidote", "해독제", "解毒剂"),
    "말하는 두루마리": ("Talking Scroll", "말하는 두루마리", "说话卷轴"),
    "순간이동 주문서": ("Teleport Scroll", "순간이동 주문서", "瞬间移动卷轴"),
    "귀환 주문서": ("Return Scroll", "귀환 주문서", "返回卷轴"),
    "엔트의 열매": ("Ent Fruit", "엔트의 열매", "安特的水果"),
}
ITEM_CATEGORIES: dict[str, tuple[str, str, str]] = {
    "물약": ("Potion", "물약", "药水"),
    "주문서": ("Scroll", "주문서", "卷轴"),
    "기타": ("Other", "기타", "其他"),
    "한손검": ("One-handed Sword", "한손검", "单手剑"),
    "양손검": ("Two-handed Sword", "양손검", "双手剑"),
    "둔기": ("Blunt", "둔기", "钝器"),
    "활": ("Bow", "활", "弓"),
    "창": ("Spear", "창", "矛"),
}
LANGUAGE_LABELS: dict[str, tuple[str, str, str]] = {
    "en": ("English", "영어", "英语"),
    "ko": ("Korean", "한국어", "韩语"),
    "zh": ("Chinese", "중국어", "中文"),
}


def _index_triples(
    table: dict[str, tuple[str, str, str]],
) -> dict[str, tuple[str, str, str]]:
    index: dict[str, tuple[str, str, str]] = {}
    for key, names in table.items():
        index[_FOLD.sub("", key).lower()] = names
        for alias in names:
            folded = _FOLD.sub("", alias).lower()
            if folded:
                index[folded] = names
    return index


_ITEM_FOLD = _index_triples(ITEM_NAMES)
_ITEM_CATEGORY_FOLD = _index_triples(ITEM_CATEGORIES)


def _pick(names: tuple[str, str, str], language: str | None) -> str:
    i = _LANG_I.get(normalize_language(language), 0)
    return names[i]


def dungeon_tag(language: str | None) -> str:
    """Short 'dungeon' label next to a map name."""
    return _pick(("dungeon", "던전", "地下城"), language)


def _title_place(place_id: str) -> str:
    return " ".join(part.capitalize() for part in str(place_id).split("_") if part)


def _floor_label(major: str, minor: str | None, language: str) -> str:
    if language == "ko":
        text = f"{int(major)}층"
        return f"{text}-{int(minor)}" if minor else text
    if language == "zh":
        text = f"{int(major)}层"
        return f"{text}-{int(minor)}" if minor else text
    text = f"F{int(major)}"
    return f"{text}-{int(minor)}" if minor else text


def _dungeon_display_name(map_id: str, language: str | None) -> str:
    """Build 기란 던전 1층 / 奇岩地下城1层 / Giran Dungeon F1 from a pack id."""
    match = _DUNGEON_ID.match(map_id)
    if match is None:
        return ""
    place_id = str(match.group("place") or "").strip().lower()
    major = match.group("major")
    minor = match.group("minor")
    lang = normalize_language(language)
    places = _PLACE_NAMES.get(place_id)
    place = _pick(places, lang) if places is not None else _title_place(place_id)
    floor = _floor_label(major, minor, lang)
    if place_id == "ant_cave":
        return f"{place}{floor}" if lang == "zh" else f"{place} {floor}"
    if lang == "ko":
        return f"{place} 던전 {floor}"
    if lang == "zh":
        return f"{place}地下城{floor}"
    return f"{place} Dungeon {floor}"


def route_point_display_name(name: str, language: str | None) -> str:
    """Show ``area_1`` / ``mid_2`` as Area 1 / 구역 1 / 区域 1. Ids stay raw."""
    raw = str(name or "").strip()
    match = _ROUTE_POINT.match(raw)
    if match is None:
        return raw
    lang = normalize_language(language)
    kind = str(match.group("kind") or "").lower()
    number = str(int(match.group("num")))
    extra = str(match.group("extra") or "").strip()
    if kind == "mid":
        label = _pick(("Mid {n}", "중간점 {n}", "中点 {n}"), lang).format(n=number)
    else:
        label = _pick(("Area {n}", "구역 {n}", "区域 {n}"), lang).format(n=number)
    if not extra:
        return label
    if extra.lower() == "copy":
        extra = _pick(("copy", "복사", "副本"), lang)
    return f"{label} ({extra})"


def map_display_name(map_id: str, language: str | None, fallback: str = "") -> str:
    """Localized pack title. Falls back to ``fallback`` or the raw id."""
    mid = str(map_id or "").strip()
    names = MAP_NAMES.get(mid)
    if names is not None:
        return _pick(names, language)
    generated = _dungeon_display_name(mid, language)
    if generated:
        return generated
    text = str(fallback or "").strip()
    return text or mid


def species_catalog_name(species: str) -> str:
    """Korean name used in training tables and monster image files."""
    text = str(species or "").strip()
    lowered = text.lower()
    if lowered.startswith("monster_"):
        text = text[len("monster_") :]
    parts = text.split("_")
    if len(parts) > 1 and parts[-1].isdigit():
        text = "_".join(parts[:-1])
    return text


# Talking-scroll row labels → (en, ko, zh)
SCROLL_LABELS: dict[str, tuple[str, str, str]] = {
    "말하는 섬": ("Talking Island", "말하는 섬", "说话之岛"),
    "기란 마을": ("Giran Village", "기란 마을", "奇岩村庄"),
    "잡화 상인": ("General Merchant", "잡화 상인", "杂货商人"),
    "창고지기": ("Warehouse Keeper", "창고지기", "仓库管理员"),
    "여관": ("Inn", "여관", "旅馆"),
    "텔레포터": ("Teleporter", "텔레포터", "传送师"),
    "마법서 상인": ("Spellbook Merchant", "마법서 상인", "魔法书商人"),
    "펫 관리인": ("Pet Manager", "펫 관리인", "宠物管理人"),
    "말하는 섬 선착장": ("Talking Island Dock", "말하는 섬 선착장", "说话之岛码头"),
    "허수아비 수련장": ("Scarecrow Training Ground", "허수아비 수련장", "稻草人修炼场"),
    "무기 상인": ("Weapon Merchant", "무기 상인", "武器商人"),
    "방어구 상인": ("Armor Merchant", "방어구 상인", "防具商人"),
}

_SHOP_NPC_MAINLAND = (
    "giran_general_goods",
    "giran",
    "기란",
    "mainland",
    "본토",
    "奇岩",
)
_SHOP_NPC_TALKING = (
    "ti_general_goods",
    "talking",
    "말하는",
    "说话",
)


def scroll_label_display(label: str, language: str | None) -> str:
    """Localized talking-scroll row name for the current UI language."""
    text = str(label or "").strip()
    names = SCROLL_LABELS.get(text)
    if names is None:
        return text
    return _pick(names, language)


def resolve_shop_npc_id(value: str) -> str:
    """Map a stored NPC label/id to talking-island or Giran general goods."""
    text = str(value or "").strip()
    if not text:
        return ""
    folded = text.lower()
    if any(token in text or token in folded for token in _SHOP_NPC_MAINLAND):
        return "giran_general_goods"
    if any(token in text or token in folded for token in _SHOP_NPC_TALKING):
        return "ti_general_goods"
    return ""


def shop_npc_display(value: str, language: str | None) -> str:
    """HP-potion buy NPC as shown in the Item tab."""
    spot_id = resolve_shop_npc_id(value)
    if spot_id == "giran_general_goods":
        return (
            f"{scroll_label_display('기란 마을', language)} / "
            f"{scroll_label_display('잡화 상인', language)}"
        )
    if spot_id == "ti_general_goods":
        return (
            f"{scroll_label_display('말하는 섬', language)} / "
            f"{scroll_label_display('잡화 상인', language)}"
        )
    return str(value or "").strip()


def language_display_name(code: str | None, language: str | None) -> str:
    """Language name shown in the operator UI language."""
    key = normalize_language(code)
    names = LANGUAGE_LABELS.get(key)
    if names is None:
        return str(code or "").strip()
    return _pick(names, language)


def species_display_name_ui(species: str, language: str | None) -> str:
    """Localized monster name for the Species tab and editor."""
    base = species_catalog_name(species)
    names = SPECIES_NAMES.get(base) or _SPECIES_FOLD.get(_FOLD.sub("", base).lower())
    if names is not None:
        return _pick(names, language)
    try:
        from app._03_world.game_catalog import monster_by_key

        row = monster_by_key(species) or monster_by_key(base)
        if row is not None:
            catalog = SPECIES_NAMES.get(row.name_ko) or _SPECIES_FOLD.get(
                _FOLD.sub("", row.name_ko).lower()
            )
            if catalog is not None:
                return _pick(catalog, language)
            return row.display_name(language)
    except Exception:
        pass
    return base or str(species or "")


def item_category_display_name(name: str, language: str | None) -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    names = ITEM_CATEGORIES.get(raw) or _ITEM_CATEGORY_FOLD.get(_FOLD.sub("", raw).lower())
    if names is not None:
        return _pick(names, language)
    return raw


def item_catalog_display_name(name: str, language: str | None) -> str:
    """Localized ground-item name from the official JSON lists."""
    folded = _fold_memory_label(name)
    names = ITEM_NAMES.get(folded) or _ITEM_FOLD.get(_FOLD.sub("", folded).lower())
    if names is not None:
        return _pick(names, language)
    try:
        from app._03_world.game_catalog import item_by_key

        row = item_by_key(folded) or item_by_key(name)
        if row is not None:
            extra = ITEM_NAMES.get(row.name_ko) or _ITEM_FOLD.get(
                _FOLD.sub("", row.name_ko).lower()
            )
            if extra is not None:
                return _pick(extra, language)
            return row.display_name(language)
    except Exception:
        pass
    return folded or str(name or "").strip()


def _unique_search_names(*groups: object) -> tuple[str, ...]:
    seen: list[str] = []
    for group in groups:
        values = group if isinstance(group, (tuple, list)) else (group,)
        for raw in values:
            text = str(raw or "").strip()
            if text and text not in seen:
                seen.append(text)
    return tuple(seen)


@lru_cache(maxsize=1)
def _species_alias_labels() -> dict[str, tuple[str, ...]]:
    """Catalog key → every alias a player might type (en / ko / zh / game)."""
    try:
        from app._03_world.memory_entities import load_species_aliases
    except Exception:
        return {}
    try:
        aliases = load_species_aliases()
    except Exception:
        return {}
    grouped: dict[str, list[str]] = {}
    for label, key in aliases.items():
        catalog = str(key or "").strip()
        if not catalog:
            continue
        grouped.setdefault(catalog, []).append(str(label))
    return {key: tuple(values) for key, values in grouped.items()}


def species_search_names(species: str, *, row: object | None = None) -> tuple[str, ...]:
    """Names that should match a monster search, in every UI language.

    Includes the catalog key, Korean / English / Chinese labels, official
    list names, and species aliases. The table still *shows* the current
    UI language; this list is only for the search box.
    """
    base = species_catalog_name(species)
    triple = SPECIES_NAMES.get(base) or _SPECIES_FOLD.get(_FOLD.sub("", base).lower())
    catalog_row = row
    if catalog_row is None:
        try:
            from app._03_world.game_catalog import monster_by_key

            catalog_row = monster_by_key(species) or monster_by_key(base)
        except Exception:
            catalog_row = None
    extra: list[object] = [species, base]
    extra.extend(species_display_name_ui(species, lang) for lang in _SEARCH_LANGS)
    if triple is not None:
        extra.extend(triple)
    if catalog_row is not None:
        extra.append(getattr(catalog_row, "key", ""))
        extra.extend(getattr(catalog_row, "search_names", lambda: ())())
        extra.extend(getattr(catalog_row, "regions_ko", ()) or ())
        extra.extend(getattr(catalog_row, "regions_zh", ()) or ())
        extra.extend(getattr(catalog_row, "regions_zh_cn", ()) or ())
        for lang in _SEARCH_LANGS:
            display = getattr(catalog_row, "display_name", None)
            if callable(display):
                extra.append(display(lang))
        extra.extend(_species_alias_labels().get(str(getattr(catalog_row, "key", "")), ()))
    extra.extend(_species_alias_labels().get(str(species or "").strip(), ()))
    extra.extend(_species_alias_labels().get(f"monster_{base}", ()))
    return _unique_search_names(*extra)


def item_search_names(name: str, *, row: object | None = None) -> tuple[str, ...]:
    """Names that should match an item search, in every UI language."""
    folded = _fold_memory_label(name)
    triple = ITEM_NAMES.get(folded) or _ITEM_FOLD.get(_FOLD.sub("", folded).lower())
    catalog_row = row
    if catalog_row is None:
        try:
            from app._03_world.game_catalog import item_by_key

            catalog_row = item_by_key(folded) or item_by_key(name)
        except Exception:
            catalog_row = None
    extra: list[object] = [name, folded]
    extra.extend(item_catalog_display_name(name, lang) for lang in _SEARCH_LANGS)
    if triple is not None:
        extra.extend(triple)
    if catalog_row is not None:
        extra.append(getattr(catalog_row, "key", ""))
        extra.extend(getattr(catalog_row, "search_names", lambda: ())())
        extra.append(getattr(catalog_row, "category_ko", ""))
        extra.append(getattr(catalog_row, "category_zh", ""))
        extra.append(getattr(catalog_row, "category_zh_cn", ""))
        extra.extend(
            item_category_display_name(str(getattr(catalog_row, "category_ko", "")), lang)
            for lang in _SEARCH_LANGS
        )
        for lang in _SEARCH_LANGS:
            display = getattr(catalog_row, "display_name", None)
            if callable(display):
                extra.append(display(lang))
    return _unique_search_names(*extra)


def _fold_memory_label(name: str) -> str:
    from manmabot_v1.hotbar.inspect import fold_hotbar_name

    return fold_hotbar_name(name)


def skill_catalog_display_name(name: str, language: str | None) -> str | None:
    """Localized skill label, or None when the name is not a known skill."""
    text = _fold_memory_label(name)
    if not text:
        return None
    try:
        from manmabot_v1.skill_catalog import load_skill_catalog
    except Exception:
        return None
    try:
        catalog = load_skill_catalog()
    except Exception:
        return None
    folded = "".join(text.split()).lower()
    lang = normalize_language(language)
    for skill in catalog.skills:
        aliases = (skill.ko, skill.zh_tw, skill.zh_cn)
        if text in aliases:
            return skill.label(lang)
        if any("".join(alias.split()).lower() == folded for alias in aliases if alias):
            return skill.label(lang)
    return None


def memory_name_for_ui(name: str, language: str | None) -> str:
    """Show a live hotbar/memory name in the operator UI language."""
    raw = str(name or "").strip()
    if not raw:
        return raw
    folded = _fold_memory_label(raw)
    skill = skill_catalog_display_name(folded, language)
    if skill:
        return skill
    item = item_catalog_display_name(folded, language)
    if item:
        return item
    return folded or raw


def inventory_name_for_ui(
    *,
    name: str = "",
    name_tw: str = "",
    name_cn: str = "",
    name_en: str = "",
    language: str | None = None,
) -> str:
    """One inventory label in the current UI language.

    Memory usually stores Korean in ``name`` and Traditional Chinese in
    ``name_tw``. Prefer the matching live field, then catalog-translate.
    """
    lang = normalize_language(language)
    kr = str(name or "").strip()
    tw = str(name_tw or "").strip()
    cn = str(name_cn or "").strip()
    en = str(name_en or "").strip()
    if lang == "en":
        raw = en or kr or tw or cn
    elif lang == "zh":
        raw = cn or tw or kr or en
    else:
        raw = kr or tw or cn or en
    if not raw or raw == "—":
        return "—"
    shown = memory_name_for_ui(raw, lang)
    return shown or raw
