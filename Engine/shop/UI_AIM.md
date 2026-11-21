# Shop in-window UI aim (buy / sell / confirm)

## Scope

Live buy and sell window clicks via `_click_uv` / `_scroll_list` / `_type_qty`
in `shop/runtime.py`. Shared by merchant sell, warehouse store, and calibrated buy.

Does **not** change combat `MOVE_BUDGET_S` (0.02s) or NPC-open `npc_aim`
(DIALOG cursor path).

## Live (`executor.humanize`)

Module: `shop/ui_aim.py` (NPC open shares curves via `npc_aim` → `shop_move_to`)

1. **Approach** — `move_with_budget(..., shop_curves=True)` with a **random style combo**
   each move (`arc` / `s_curve` / `lead_in` / `late_bend` / `shallow` / `via` × easing).
2. **Fine adjust** — short varied curves near the UV; **no** cursor verify on window UVs.
3. **Land error** — final point is UV ± **1px** (screen width &lt; 1600) or **2px** (≥1600).
4. **Click hold** — button down **0.10–0.15s** in place (`hold_in_place`).
5. **Scroll think** — before any wheel flick, pause **0.5–2.0s** (`SHOP_UI_SCROLL_THINK_S`).
6. **Typing** — **0.2–0.3s** after the row click, then keys at **5–6 characters/second**.
7. **Stage waits** — tab/button/post-tab sleeps use `shop_stage_sleep` (±**10–15%** jitter).
8. **Pre-confirm fidget** — after rows/qty, before confirm: cursor drifts down-right, then
   **2–4** accidental wheel-downs with **0.3–0.5s** gaps (`_pre_confirm_fidget`).

Buy/Sell tab, row, confirm, recover arrow UI, and NPC DIALOG hold all use this family.
Combat `MOVE_BUDGET_S` / plain `bezier_points` stay unchanged.

## Practice / `humanize=False`

Snap `move_and_click` and fixed scroll sleeps (legacy).
