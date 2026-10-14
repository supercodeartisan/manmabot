"""Rebuild the bundled static fonts from the upstream variable fonts."""
from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


ROOT = Path(__file__).resolve().parent
FAMILIES = {
    "NotoSansKR": "Manmabot Noto KR",
    "NotoSansSC": "Manmabot Noto SC",
    "Inter": "Manmabot Inter",
}


def build() -> None:
    for stem, family in FAMILIES.items():
        for style, weight in (("Regular", 400), ("Medium", 500), ("Bold", 700)):
            target = ROOT / f"Manmabot-{stem}-{style}.ttf"
            if target.is_file() and stem != "Inter":
                font = TTFont(target)
            else:
                source = TTFont(ROOT / f"{stem}.ttf")
                axes = {"wght": weight}
                if stem == "Inter":
                    axes["opsz"] = 14
                font = instantiateVariableFont(source, axes, inplace=False)
            display_family = f"{family} Medium" if style == "Medium" else family
            subfamily = "Regular" if style == "Medium" else style
            names = font["name"]
            values = {
                1: display_family,
                2: subfamily,
                4: f"{display_family} {subfamily}",
                6: f"{display_family.replace(' ', '')}-{subfamily}",
                16: display_family,
                17: subfamily,
            }
            for name_id, value in values.items():
                names.setName(value, name_id, 3, 1, 0x409)
                names.setName(value, name_id, 1, 0, 0)
            font["OS/2"].usWeightClass = weight
            font["head"].macStyle = 1 if style == "Bold" else 0
            temporary = target.with_suffix(".tmp.ttf")
            font.save(temporary)
            font.close()
            temporary.replace(target)


if __name__ == "__main__":
    build()
