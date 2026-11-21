"""body_pose find anchors follow analysis overlay (pack-only path)."""
from __future__ import annotations

from pathlib import Path

import app._05_action.body_pose as body_pose


def test_load_find_reads_overlay_entity_offsets(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "entity_offsets.txt").write_text(
        "\n".join(
            [
                "MGR=0x172A840",
                "ACTOR_VFT=0x120DCD8",
                "CLASSES=1210B90:MyPlayer,1210A80:Monster",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "session.analysis_overlay.analysis_registry_file",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    body_pose._FIND.update(
        {"MGR": 0x16EB6F0, "ACTOR_VFT": 0x11DE3E8, "MY_PLAYER": 0x11E1388}
    )
    body_pose._find_ready = False
    body_pose._load_find(force=True)
    assert body_pose._find_ready is True
    assert body_pose._FIND["MGR"] == 0x172A840
    assert body_pose._FIND["ACTOR_VFT"] == 0x120DCD8
    assert body_pose._FIND["MY_PLAYER"] == 0x1210B90


def test_load_find_miss_stays_unready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "session.analysis_overlay.analysis_registry_file",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    body_pose._find_ready = False
    body_pose._load_find(force=True)
    assert body_pose._find_ready is False


def test_source_registry_prefers_overlay(tmp_path: Path, monkeypatch) -> None:
    from app._01_perception import registry_apply as ra

    registry = tmp_path / "registry"
    registry.mkdir()
    overlay_reg = registry / "LC930_REGISTRY.txt"
    overlay_reg.write_text("MGR=0x172A840\n", encoding="utf-8")
    monkeypatch.setattr(
        "session.analysis_overlay.analysis_registry_file",
        lambda *parts: tmp_path.joinpath(*parts),
    )
    assert ra.source_registry() == overlay_reg
