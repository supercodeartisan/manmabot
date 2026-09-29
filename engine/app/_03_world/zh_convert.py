"""Traditional ↔ Simplified Chinese for catalog display and name matching."""
from __future__ import annotations

# Common TW/HK ↔ CN pairs used by Lineage monster / item / region names.
_T2S_PHRASES: tuple[tuple[str, str], ...] = (
    ("說話之島", "说话之岛"),
    ("金幣", "金币"),
    ("紅色藥水", "红色药水"),
    ("藍色藥水", "蓝色药水"),
    ("伊娃王國", "伊娃王国"),
    ("古魯丁", "古鲁丁"),
    ("亞丁大陸", "亚丁大陆"),
    ("眠龍洞穴", "眠龙洞穴"),
    ("單手劍", "单手剑"),
    ("雙手劍", "双手剑"),
    ("說話的卷軸", "说话的卷轴"),
    ("說話卷軸", "说话卷轴"),
    ("初級治癒術", "初级治愈术"),
    ("中級治癒術", "中级治愈术"),
    ("高級治癒術", "高级治愈术"),
    ("全部治癒術", "全部治愈术"),
    ("體力回復術", "体力回复术"),
    ("體力回復劑", "体力回复剂"),
    ("世界樹的呼喚", "世界树的呼唤"),
)

_T2S_CHARS = (
    "說話島幣國樓監銀騎地區魯亞歐劍環獸頭單雙鈍擊語詞戰鬥鬥東問題體機氣風雲電腦視聽關"
    "龍螞後從這還對開間時會現發經動過點種樣麼門車紅藍長釘燈殼飛沙漠肯特森林冰女王海葵"
    "厚裡面嫩靈敏作為距離禦攻擊生命魔力重量傳送卷軸倉庫旅館雜貨裝備武器防具盾牌靴手套"
    "巨大兵蟻半獸人弓箭法師戰士石魔像熔岩骷髏僵雞霍布哈士奇惡狗頭拉米亞蜥蜴萊坎斯洛普"
    "怪物之眼奈魯加食人魔飛蜻蜓羅巴劍齒謝洛牧羊蠍斯巴托貓頭鷹阿圖巴雙頭安格利安特鷹身"
    "女妖龜黑稻草層獄與於賓靈"
    "術級癒藥樹喚強餅乾護聖劑"
    ,
    "说话岛币国楼监银骑地区鲁亚欧剑环兽头单双钝击语词战斗斗东问题体机气风云电脑视听关"
    "龙蚂后从这还对开间时会现发经动过点种样么门车红蓝长钉灯壳飞沙漠肯特森林冰女王海葵"
    "厚里面嫩灵敏作为距离御攻击生命魔力重量传送卷轴仓库旅馆杂货装备武器防具盾牌靴手套"
    "巨大兵蚁半兽人弓箭法师战士石魔像熔岩骷髅僵鸡霍布哈士奇恶狗头拉米亚蜥蜴莱坎斯洛普"
    "怪物之眼奈鲁加食人魔飞蜻蜓罗巴剑齿谢洛牧羊蝎斯巴托猫头鹰阿图巴双头安格利安特鹰身"
    "女妖龟黑稻草层狱与于宾灵"
    "术级愈药树唤强饼干护圣剂"
    ,
)


def _char_table(src: str, dst: str) -> dict[str, str]:
    n = min(len(src), len(dst))
    return {src[i]: dst[i] for i in range(n) if src[i] != dst[i]}


_T2S_MAP = _char_table(*_T2S_CHARS)
_S2T_MAP = {dst: src for src, dst in _T2S_MAP.items()}
for _tw, _cn in _T2S_PHRASES:
    _T2S_MAP[_tw] = _cn
    _S2T_MAP[_cn] = _tw


def to_simplified(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    for tw, cn in _T2S_PHRASES:
        if tw in value:
            value = value.replace(tw, cn)
    return "".join(_T2S_MAP.get(ch, ch) for ch in value)


def to_traditional(text: str) -> str:
    value = str(text or "")
    if not value:
        return ""
    for tw, cn in _T2S_PHRASES:
        if cn in value:
            value = value.replace(cn, tw)
    return "".join(_S2T_MAP.get(ch, ch) for ch in value)


def chinese_aliases(text: str) -> tuple[str, ...]:
    """Original plus simplified and traditional forms, de-duplicated."""
    raw = str(text or "").strip()
    if not raw:
        return ()
    seen: list[str] = []
    for item in (raw, to_simplified(raw), to_traditional(raw)):
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)
