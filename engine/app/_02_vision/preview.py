"""Live vision preview drawing shared by the CLI loop and Version1."""
from __future__ import annotations

import cv2
import numpy as np

from app._03_world import ActionType, GameState, ObjectType
from app._03_world.constants import get_classification_thresholds
from app._03_world.memory_sync import format_snapshot_preview_lines

PREVIEW_SCALE = 0.8
# HUD strip stacked under the scaled game view (not overlaid on it).
PREVIEW_INFO_H = 112
PREVIEW_FALLBACK_SIZE = (960, 540)  # width, height of the game pane
_last_preview_info_h = PREVIEW_INFO_H
# Box colours by ObjectType (BGR).
PREVIEW_TYPE_COLOURS = {
    ObjectType.MONSTER: (0, 255, 0),
    ObjectType.ITEM: (0, 165, 255),
    ObjectType.PLAYER: (255, 255, 0),
    ObjectType.NPC: (255, 128, 255),
    ObjectType.OTHER: (160, 160, 160),
}
ACTION_COLOURS = {
    ActionType.SEARCHING: (200, 200, 0),
    ActionType.COMBAT: (0, 255, 0),
    ActionType.ATTACK: (0, 255, 0),
    ActionType.RETREATING: (0, 0, 255),
    ActionType.LOOTING: (255, 128, 0),
    ActionType.PICKUP: (255, 128, 0),
    ActionType.TRAVELING: (0, 200, 200),
    ActionType.IDLE: (128, 128, 128),
    ActionType.USE_HP_POTION: (255, 0, 255),
    ActionType.USE_MP_POTION: (0, 255, 255),
    ActionType.HEAL: (200, 100, 255),
    ActionType.BUFF: (180, 220, 80),
    ActionType.ESCAPE: (255, 0, 0),
    ActionType.TELEPORT: (255, 128, 255),
    ActionType.RETURN_TO_MOTHER_TREE: (80, 200, 80),
    ActionType.HP_TO_MP: (80, 160, 220),
    ActionType.USE_TALKING_SCROLL: (200, 160, 80),
    ActionType.SHOP_BUY_ARROWS: (220, 180, 60),
    ActionType.SHOP_STOP: (200, 160, 40),
    ActionType.DISMISS_LEVEL_UP: (180, 140, 255),
}
# Enter/next-farm A* failure → 5-tile ring ("enter farm, walk around").
DETOUR_COLOUR = (0, 140, 255)  # bright orange (BGR)
DETOUR_REASON = "enter farm, walk around"
_DETOUR_PURPOSES = frozenset({"enter_farm", "next_farm"})


def enter_farm_detour_active(action, blackboard=None) -> bool:
    """True while enter/next-farm walk-around detour is the live travel hop."""
    reason = str(getattr(action, "reason", "") or "")
    if reason == DETOUR_REASON:
        return True
    if blackboard is None:
        return False
    if getattr(blackboard, "travel_purpose", None) not in _DETOUR_PURPOSES:
        return False
    if not getattr(blackboard, "travel_unstick_active", False):
        return False
    scratch = getattr(blackboard, "scratch", None) or {}
    return scratch.get("enter_farm_detour_origin") is not None


def _absolute_tile_to_preview_xy(
    tile: tuple[int, int] | list[int],
    origin,
    fw: int,
    fh: int,
    sx: float,
    sy: float,
) -> tuple[int, int] | None:
    """Map an absolute nav tile to scaled preview pixels via content UV."""
    if origin is None or tile is None or len(tile) < 2:
        return None
    from app._03_world.world_coords import absolute_to_relative, world_to_content

    try:
        rx, ry = absolute_to_relative(int(tile[0]), int(tile[1]), origin)
        content = world_to_content(float(rx), float(ry))
    except Exception:
        return None
    return int(content.x * fw * sx), int(content.y * fh * sy)


def _draw_detour_mark(
    preview: np.ndarray,
    action,
    blackboard,
    *,
    fw: int,
    fh: int,
    sx: float,
    sy: float,
) -> None:
    """Bold orange diamond + label on the detour hop; dots on tried ring tiles."""
    colour = DETOUR_COLOUR
    hop_xy: tuple[int, int] | None = None
    if action.destination is not None:
        hop_xy = (
            int(action.destination.x * fw * sx),
            int(action.destination.y * fh * sy),
        )
    nav_wp = getattr(blackboard, "nav_waypoint", None) if blackboard else None
    nav_pos = getattr(blackboard, "world_origin", None) if blackboard else None
    if hop_xy is None and nav_wp is not None:
        hop_xy = _absolute_tile_to_preview_xy(nav_wp, nav_pos, fw, fh, sx, sy)

    scratch = getattr(blackboard, "scratch", None) if blackboard else None
    tried = list((scratch or {}).get("enter_farm_detour_tried") or [])
    for tile in tried:
        xy = _absolute_tile_to_preview_xy(tile, nav_pos, fw, fh, sx, sy)
        if xy is None:
            continue
        cv2.circle(preview, xy, 4, colour, 1)

    if hop_xy is None:
        return
    dx, dy = hop_xy
    cv2.drawMarker(
        preview,
        (dx, dy),
        colour,
        markerType=cv2.MARKER_DIAMOND,
        markerSize=36,
        thickness=3,
    )
    cv2.circle(preview, (dx, dy), 22, colour, 2)
    cv2.drawMarker(
        preview,
        (dx, dy),
        (255, 255, 255),
        markerType=cv2.MARKER_TILTED_CROSS,
        markerSize=16,
        thickness=2,
    )
    label = "DETOUR"
    if nav_wp is not None and len(nav_wp) >= 2:
        label = f"DETOUR ({nav_wp[0]},{nav_wp[1]})"
    cv2.putText(
        preview,
        label,
        (max(4, dx - 48), max(18, dy - 28)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        colour,
        2,
    )


def _blank_game_pane(size: tuple[int, int] | None = None) -> np.ndarray:
    w, h = size if size else PREVIEW_FALLBACK_SIZE
    return np.zeros((max(h, 1), max(w, 1), 3), dtype=np.uint8)


def _stack_preview_info(
    game: np.ndarray,
    lines: list[tuple[str, tuple[int, int, int], float]],
) -> np.ndarray:
    """Put HUD text in a strip under the game pane."""
    global _last_preview_info_h
    width = int(game.shape[1])
    height = max(28, 12 + len(lines) * 20 + 8)
    _last_preview_info_h = height
    info = np.zeros((height, width, 3), dtype=np.uint8)
    info[:] = (18, 18, 18)
    y = 22
    for text, colour, scale in lines:
        cv2.putText(
            info, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale, colour, 1
        )
        y += 20
    return np.vstack([game, info])


def paused_preview(last: np.ndarray | None, message: str) -> np.ndarray:
    """Keep a valid preview image while capture is paused (minimized / hotkey)."""
    if last is not None and last.size > 0:
        canvas = last.copy()
        game_h = max(1, canvas.shape[0] - _last_preview_info_h)
        canvas[:game_h] = (canvas[:game_h].astype(np.float32) * 0.35).astype(np.uint8)
        cv2.putText(
            canvas, message,
            (16, max(32, game_h // 2)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2,
        )
        return canvas
    game = _blank_game_pane()
    return _stack_preview_info(game, [(message, (0, 200, 255), 0.55)])


def weight_ratio_preview_line(game_state: GameState | None) -> str:
    """Info-strip text for HUD bag fill (``inventory.weight_ratio``)."""
    player = getattr(game_state, "player", None) if game_state is not None else None
    if player is None:
        return "weight_ratio: -"
    ratio = float(player.inventory.weight_ratio)
    return f"weight_ratio: {ratio:.2f}  ({ratio * 100.0:.0f}%)"


def _preview_class_label(obj) -> str:
    """Short class name for the box: detail classification only."""
    if obj.species_name:
        return str(obj.species_name)
    if obj.detail_classification:
        return str(obj.detail_classification)
    if obj.label:
        return str(obj.label)
    return obj.object_type.value


def draw_vision_preview(
    frame,
    action,
    game_state: GameState,
    blackboard=None,
    *,
    scale: float = PREVIEW_SCALE,
) -> np.ndarray:
    """Draw live detections only; box text is detail class name.

    Ghost / occluded tracks (missed frames) are omitted. HUD text sits in a
    strip under the game image so it does not cover detections.
    """
    scale = float(scale) if scale else PREVIEW_SCALE
    if frame is None or getattr(frame, "size", 0) == 0:
        preview = _blank_game_pane()
        fh, fw = preview.shape[:2]
    else:
        preview = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
        fh, fw = frame.shape[:2]
    sx = scale
    sy = scale

    ws = game_state.world_state
    weak_ids = {o.track_id for o in ws.weak_monsters}
    strong_ids = {o.track_id for o in ws.strong_monsters}
    coarse_min, detail_min = get_classification_thresholds()

    for obj in ws.all_objects():
        # Live detections only — skip ghosts (missed frames) and occluded tracks.
        if game_state.missing_frames(obj.track_id) > 0:
            continue
        if obj.occluded:
            continue
        if obj.size is None:
            continue

        # Normalized position/size -> scaled pixel coordinates.
        cx = int(obj.position.x * fw * sx)
        cy = int(obj.position.y * fh * sy)
        w = int(obj.size.width * fw * sx)
        h = int(obj.size.height * fh * sy)
        x1 = cx - w // 2
        y1 = cy - h // 2
        x2 = cx + w // 2
        y2 = cy + h // 2

        is_target = (
            action.target_id is not None
            and action.target_id == obj.track_id
        )

        colour = PREVIEW_TYPE_COLOURS.get(obj.object_type, (200, 200, 200))
        if obj.object_type is ObjectType.MONSTER:
            if obj.track_id in strong_ids:
                colour = (0, 0, 255)
            elif obj.track_id in weak_ids:
                colour = (0, 255, 0)

        thickness = 3 if is_target else 2
        cv2.rectangle(preview, (x1, y1), (x2, y2), colour, thickness)

        if is_target:
            cv2.rectangle(
                preview, (x1 - 2, y1 - 2), (x2 + 2, y2 + 2), (255, 255, 255), 1
            )
        cv2.putText(
            preview,
            _preview_class_label(obj),
            (x1, max(12, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            colour,
            1,
        )

    detour = enter_farm_detour_active(action, blackboard)

    # Click destination marker (content-normalized UV).
    # Detour uses its own mark below so the normal cyan cross is skipped.
    if action.destination is not None and not detour:
        dx = int(action.destination.x * fw * sx)
        dy = int(action.destination.y * fh * sy)
        cv2.drawMarker(
            preview, (dx, dy), (0, 255, 255),
            markerType=cv2.MARKER_CROSS, markerSize=18, thickness=2,
        )
        cv2.circle(preview, (dx, dy), 6, (0, 255, 255), 1)

    if detour:
        _draw_detour_mark(
            preview, action, blackboard, fw=fw, fh=fh, sx=sx, sy=sy
        )

    # Info panel: action + reason + destination + cls thresholds + player.
    nav_wp = getattr(blackboard, "nav_waypoint", None) if blackboard else None
    nav_goal = getattr(blackboard, "nav_goal", None) if blackboard else None
    nav_pos = getattr(blackboard, "world_origin", None) if blackboard else None

    if action.action is ActionType.TRAVELING:
        goal_s = f"({nav_goal[0]},{nav_goal[1]})" if nav_goal else "-"
        hop_s = f"({nav_wp[0]},{nav_wp[1]})" if nav_wp else "-"
        action_line = f"Action: traveling  goal={goal_s}  hop={hop_s}"
        if action.destination is not None:
            dest_line = (
                f"dest: click=({action.destination.x:.3f},"
                f"{action.destination.y:.3f})"
            )
            if nav_pos is not None:
                dest_line += f"  pos=({nav_pos.x},{nav_pos.y})"
        else:
            dest_line = "dest: -"
            if nav_pos is not None:
                dest_line += f"  pos=({nav_pos.x},{nav_pos.y})"
    else:
        action_line = (
            f"Action: {action.action.value} target={action.target_id}"
        )
        dest_parts: list[str] = []
        if action.destination is not None:
            dest_parts.append(
                f"click=({action.destination.x:.3f},{action.destination.y:.3f})"
            )
        if nav_pos is not None:
            dest_parts.append(f"pos=({nav_pos.x},{nav_pos.y})")
        dest_line = "dest: " + (" ".join(dest_parts) if dest_parts else "-")

    cls_line = (
        f"boxes: live detections only  "
        f"cls min coarse>={coarse_min:.2f} detail>={detail_min:.2f}"
    )
    weight_line = weight_ratio_preview_line(game_state)
    mem_colour = (180, 255, 180)
    mem_lines = format_snapshot_preview_lines(
        getattr(game_state, "last_memory_snapshot", None),
        nav=nav_pos,
    )

    action_colour = ACTION_COLOURS.get(action.action, (255, 255, 255))
    lines = [
        (action_line, action_colour, 0.52),
        (f"reason: {action.reason}", (255, 255, 255), 0.42),
        (dest_line, (0, 255, 255), 0.40),
        (cls_line, (200, 200, 200), 0.40),
        (weight_line, (180, 220, 255), 0.40),
    ]
    if detour:
        hop_s = f"({nav_wp[0]},{nav_wp[1]})" if nav_wp else "-"
        tried_n = len(
            list(
                (getattr(blackboard, "scratch", None) or {}).get(
                    "enter_farm_detour_tried"
                )
                or []
            )
        )
        lines.insert(
            1,
            (
                f"DETOUR: enter/next-farm walk-around  hop={hop_s}  tried={tried_n}",
                DETOUR_COLOUR,
                0.50,
            ),
        )
    for text in mem_lines:
        lines.append((text, mem_colour, 0.38))
    return _stack_preview_info(preview, lines)


def encode_preview_jpeg(
    image: np.ndarray | None,
    *,
    quality: int = 70,
    max_width: int = 960,
) -> bytes | None:
    """JPEG-encode a BGR preview for the Version1 UI thread."""
    if image is None or getattr(image, "size", 0) == 0:
        return None
    out = image
    h, w = image.shape[:2]
    if w > max_width > 0:
        scale = max_width / float(w)
        out = cv2.resize(image, (max_width, max(1, int(h * scale))))
    ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return None
    return buf.tobytes()
