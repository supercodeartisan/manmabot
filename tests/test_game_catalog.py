"""Official Korean / Chinese monster and item lists."""
from __future__ import annotations

from app._03_world.game_catalog import (
    hp_restore_item,
    is_dungeon_region,
    is_mainland_region,
    item_by_key,
    list_hp_restore_items,
    list_item_rows,
    list_monster_rows,
    mainland_filter_label,
    monster_by_key,
    monster_region_labels,
    resolve_item_key,
    resolve_monster_key,
)
from app._03_world.memory_entities import resolve_catalog_key
from app._03_world.zh_convert import _T2S_CHARS, to_simplified


def test_monster_catalog_merges_korean_and_chinese():
    orc = monster_by_key("monster_오크")
    assert orc is not None
    assert orc.name_ko == "오크"
    assert orc.name_zh == "妖魔"
    assert orc.level == 2
    assert "말하는 섬" in orc.regions_ko
    assert orc.display_name("ko") == "오크"
    assert orc.display_name("zh") == "妖魔"
    assert "说话之岛" in orc.display_regions("zh")


def test_monster_lookup_accepts_korean_chinese_and_converted_forms():
    assert resolve_monster_key("고블린") == "monster_고블린"
    assert resolve_monster_key("monster_고블린") == "monster_고블린"
    assert resolve_monster_key("monster_고블린_2") == "monster_고블린"
    assert resolve_monster_key("哥布林") == "monster_고블린"
    assert resolve_monster_key("도베르만") == "monster_도베르만"
    assert resolve_monster_key("杜賓狗") == "monster_도베르만"
    assert resolve_monster_key("杜宾狗") == "monster_도베르만"
    assert resolve_monster_key("地靈") == "monster_코볼트"
    assert resolve_monster_key("葛林") == "monster_그렘린"
    assert resolve_monster_key(to_simplified("地靈")) == "monster_코볼트"
    assert resolve_catalog_key("哥布林") == "monster_고블린"
    assert resolve_catalog_key("杜宾狗") == "monster_도베르만"
    assert resolve_monster_key("없는몬스터") is None


def test_item_catalog_localizes_name_and_category():
    adena = item_by_key("아데나")
    assert adena is not None
    assert adena.display_name("ko") == "아데나"
    assert adena.display_name("zh") == "金币"
    assert adena.display_category("ko") == "기타"
    assert adena.display_category("zh") in {"其他", "其它"}
    potion = item_by_key("빨간 물약")
    assert potion is not None
    assert resolve_item_key("빨간 물약") == "빨간 물약"
    assert resolve_item_key("紅色藥水") == "빨간 물약"
    assert resolve_item_key("红色药水") == "빨간 물약"
    assert resolve_item_key("아데나") == "아데나"
    assert resolve_item_key("金幣") == "아데나"
    assert resolve_item_key("金币") == "아데나"
    assert resolve_item_key("없는아이템") is None


def test_zh_convert_tables_stay_aligned():
    trad, simp = _T2S_CHARS
    assert len(trad) == len(simp)


def test_catalog_images_match_name_and_id():
    orc = monster_by_key("monster_오크")
    assert orc is not None
    assert 0 in orc.ids
    orc_image = orc.image_path()
    assert orc_image is not None
    assert orc_image.name.startswith("오크_")
    assert orc_image.suffix.lower() == ".png"

    queen = monster_by_key("monster_얼음 여왕")
    assert queen is not None
    queen_image = queen.image_path()
    assert queen_image is not None
    assert queen_image.name.startswith("얼음_여왕_")
    queen_id = int(queen_image.stem.rsplit("_", 1)[1])
    assert queen_id in queen.ids

    adena = item_by_key("아데나")
    assert adena is not None
    adena_image = adena.image_path()
    assert adena_image is not None
    assert adena_image.name.startswith("아데나_")

    potion = item_by_key("빨간 물약")
    assert potion is not None
    potion_image = potion.image_path()
    assert potion_image is not None
    assert potion_image.name.startswith("빨간_물약_")


def test_hp_restore_catalog_lists_consumable_potions():
    keys = [row.key for row in list_hp_restore_items()]
    assert keys[:4] == ["빨간 물약", "주홍 물약", "맑은 물약", "엔트의 열매"]
    red = hp_restore_item("hp_potion")
    assert red is not None
    assert red.key == "빨간 물약"
    assert 14 in red.ids
    assert 80 in red.ids
    assert "체력 회복제" in red.aliases()
    orange = hp_restore_item("item:주홍 물약")
    assert orange is not None
    assert 15 in orange.ids
    assert hp_restore_item("엔트의 열매") is not None
    assert all("요정" not in row.name_ko for row in list_hp_restore_items())


def test_mainland_region_excludes_talking_island_and_dungeons():
    assert mainland_filter_label("ko") == "본토"
    assert mainland_filter_label("en") == "본토"
    assert mainland_filter_label("zh") == "大陆"
    assert not is_mainland_region("말하는 섬")
    assert not is_mainland_region("말하는 섬 던전 1층")
    assert not is_mainland_region("글루디오 던전 7층")
    assert not is_mainland_region("결속의 던전: 어둠")
    assert not is_mainland_region("说话之岛")
    assert not is_mainland_region("说话之岛地监1楼")
    assert not is_mainland_region("沙漠地监1楼")
    assert is_mainland_region("글루디오")
    assert is_mainland_region("요정 숲")
    assert is_mainland_region("오만의 탑 10층")
    assert is_mainland_region("얼음 수정 동굴 3층")
    assert is_mainland_region("아덴 대륙")

    labels = monster_region_labels("ko")
    assert "본토" not in labels
    assert "말하는 섬" in labels
    excluded = [name for name in labels if not is_mainland_region(name)]
    assert excluded
    assert all(name == "말하는 섬" or "던전" in name for name in excluded)
    kept = [name for name in labels if is_mainland_region(name)]
    assert "글루디오" in kept
    assert all("던전" not in name and not name.startswith("말하는 섬") for name in kept)

    zh_labels = monster_region_labels("zh")
    assert "说话之岛" in zh_labels
    assert "大陆" not in zh_labels
    assert all(
        not is_mainland_region(name)
        for name in zh_labels
        if name.startswith("说话之岛") or "地监" in name or "地下城" in name
    )

    kurtz = monster_by_key("monster_커츠")
    assert kurtz is not None
    assert kurtz.regions_ko == ("말하는 섬",)
    assert not any(is_mainland_region(name) for name in kurtz.regions_ko)
    orc = monster_by_key("monster_오크")
    assert orc is not None
    assert any(is_mainland_region(name) for name in orc.regions_ko)
    assert any(not is_mainland_region(name) for name in orc.regions_ko)


def test_region_labels_list_towns_before_dungeons():
    labels = list(monster_region_labels("ko"))
    split = next(index for index, name in enumerate(labels) if is_dungeon_region(name))
    towns, dungeons = labels[:split], labels[split:]
    assert towns and dungeons
    assert towns == sorted(towns)
    assert dungeons == sorted(dungeons)
    assert all(not is_dungeon_region(name) for name in towns)
    assert all(is_dungeon_region(name) for name in dungeons)
    assert labels.index("글루디오") < labels.index("글루디오 던전 1층")
    assert labels.index("말하는 섬") < labels.index("말하는 섬 던전 1층")
    assert "오만의 탑 10층" in towns

    zh_labels = list(monster_region_labels("zh"))
    zh_split = next(index for index, name in enumerate(zh_labels) if is_dungeon_region(name))
    assert all(not is_dungeon_region(name) for name in zh_labels[:zh_split])
    assert all(is_dungeon_region(name) for name in zh_labels[zh_split:])
    assert zh_labels.index("古鲁丁") < zh_labels.index("古鲁丁地监1楼")


def test_catalogs_are_non_empty():
    monsters = list_monster_rows()
    items = list_item_rows()
    assert len(monsters) > 50
    assert len(items) > 50
    assert all(row.name_ko for row in monsters)
    assert all(row.name_ko for row in items)
