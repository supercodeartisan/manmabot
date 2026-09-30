from app._04_decision.shops import normalize_hp_potion_npc
from manmabot_v1.localized_names import (
    inventory_name_for_ui,
    item_catalog_display_name,
    item_search_names,
    language_display_name,
    map_display_name,
    monster_region_candidates,
    memory_name_for_ui,
    route_point_display_name,
    shop_npc_display,
    species_display_name_ui,
    species_search_names,
)
from manmabot_v1.probes import localize_probe_detail


def test_overworld_maps_follow_ui_language():
    assert map_display_name("talking_island", "en") == "Talking Island"
    assert map_display_name("talking_island", "ko") == "말하는 섬"
    assert map_display_name("talking_island", "zh") == "说话之岛"
    assert map_display_name("mainland", "ko") == "본토"


def test_dungeon_maps_follow_ui_language():
    assert map_display_name("giran_dungeon_F1", "en") == "Giran Dungeon F1"
    assert map_display_name("giran_dungeon_F1", "ko") == "기란 던전 1층"
    assert map_display_name("giran_dungeon_F1", "zh") == "奇岩地下城1层"
    assert map_display_name("desert_dungeon_F4", "ko") == "사막 던전 4층"
    assert map_display_name("gludio_dungeon_F5", "zh") == "古鲁丁地下城5层"
    assert map_display_name("ant_cave_dungeon_F1_3", "en") == "Ant Cave F1-3"
    assert map_display_name("ant_cave_dungeon_F1_3", "ko") == "개미굴 1층-3"
    assert map_display_name("ant_cave_dungeon_F1_3", "zh") == "蚂蚁洞穴1层-3"
    assert map_display_name("talking_island_dungeon_F1", "ko") == "말하는 섬 던전 1층"


def test_monster_region_candidates_use_catalog_language():
    assert monster_region_candidates("talking_island", "ko") == ("말하는 섬",)
    assert monster_region_candidates("talking_island", "en") == ("말하는 섬",)
    assert monster_region_candidates("talking_island", "zh") == ("说话之岛",)
    assert monster_region_candidates("giran_dungeon_F1", "ko") == ("기란 던전 1층",)
    assert monster_region_candidates("talking_island_dungeon_F2", "ko") == (
        "말하는 섬 던전 2층",
    )
    assert "개미굴 던전 1층-3" in monster_region_candidates("ant_cave_dungeon_F1_3", "ko")
    assert "奇岩地监1楼" in monster_region_candidates("giran_dungeon_F1", "zh")
    assert monster_region_candidates("mainland", "ko") == ("본토",)


def test_area_and_mid_names_follow_ui_language():
    assert route_point_display_name("area_1", "en") == "Area 1"
    assert route_point_display_name("area_3", "ko") == "구역 3"
    assert route_point_display_name("area_2", "zh") == "区域 2"
    assert route_point_display_name("mid_1", "en") == "Mid 1"
    assert route_point_display_name("mid_4", "ko") == "중간점 4"
    assert route_point_display_name("mid_2", "zh") == "中点 2"
    assert route_point_display_name("area_1_copy", "ko") == "구역 1 (복사)"
    assert route_point_display_name("custom_spot", "ko") == "custom_spot"


def test_shop_npc_field_follows_ui_language():
    korean = "기란 마을 / 잡화 상인"
    assert shop_npc_display(korean, "en") == "Giran Village / General Merchant"
    assert shop_npc_display(korean, "ko") == "기란 마을 / 잡화 상인"
    assert shop_npc_display(korean, "zh") == "奇岩村庄 / 杂货商人"
    assert shop_npc_display("Talking Island / General Merchant", "ko") == "말하는 섬 / 잡화 상인"
    assert normalize_hp_potion_npc("奇岩村庄 / 杂货商人") == "mainland"
    assert normalize_hp_potion_npc("说话之岛 / 杂货商人") == "talking"
    assert normalize_hp_potion_npc("Giran Village / General Merchant") == "mainland"


def test_memory_names_follow_ui_language():
    assert memory_name_for_ui("初級治癒術", "ko") == "힐"
    assert memory_name_for_ui("初級治癒術(4/0)", "zh") in {"初级治愈术", "初級治癒術"}
    assert memory_name_for_ui("빨간 물약", "zh") in {"红色药水", "紅色藥水"}
    assert memory_name_for_ui("체력 회복제", "ko") in {"체력 회복제", "빨간 물약"}
    assert memory_name_for_ui("+0 화살 (826)", "ko") == "화살"
    assert memory_name_for_ui("체력 회복제 (2)", "ko") in {"체력 회복제", "빨간 물약"}
    assert memory_name_for_ui("아데나 (1,277)", "ko") == "아데나"
    assert memory_name_for_ui("아데나 (1,277)", "en") == "Adena"
    assert memory_name_for_ui("체력 회복제 (2)", "en") == "Healing Potion"
    assert item_catalog_display_name("화살", "zh") in {"箭", "箭矢"}
    assert language_display_name("ko", "en") == "Korean"
    assert language_display_name("en", "ko") == "영어"
    assert species_display_name_ui("고블린", "en") == "Goblin"
    assert species_display_name_ui("고블린", "zh") == "哥布林"


def test_species_search_names_cover_ui_languages() -> None:
    blob = " ".join(species_search_names("monster_고블린")).lower()
    assert "goblin" in blob
    assert "고블린" in blob
    assert "哥布林" in blob


def test_item_search_names_cover_ui_languages() -> None:
    blob = " ".join(item_search_names("아데나")).lower()
    assert "adena" in blob
    assert "아데나" in blob
    assert "金币" in blob or "金幣" in blob


def test_inventory_name_follows_ui_language() -> None:
    assert inventory_name_for_ui(name="아데나", name_tw="金幣", language="ko") == "아데나"
    assert inventory_name_for_ui(name="아데나", name_tw="金幣", language="en") == "Adena"
    assert inventory_name_for_ui(
        name="아데나", name_tw="金幣", language="zh"
    ) in {"金币", "金幣"}


def test_probe_details_follow_ui_language() -> None:
    assert localize_probe_detail("Game is not in focus", "en") == "Game is not in focus"
    assert localize_probe_detail("Game is not in focus", "ko") == "게임이 포커스가 아닙니다"
    assert localize_probe_detail("Memory connected", "zh") == "内存已连接"
