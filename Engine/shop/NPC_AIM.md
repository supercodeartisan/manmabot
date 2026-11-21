# Shop NPC aim (human approach)

## Scope

Live shop / warehouse / teleporter **NPC open** only (`open_shop_npc`).

Does **not** change:

- Combat / travel mouse budget (`MOVE_BUDGET_S = 0.02s`)
- In-window buy/sell UV clicks (`_click_uv`) — see `UI_AIM.md`
- Sell tour order (`_shuffled_sell_ids`)
- Party pin / block / post-shop return

## Why a separate path

Hunt aim must stay fast. Shop open looked mechanical because the same
0.02s Bezier and `snap=True` + fixed 0.25s ring were used at the stall.

## Live path (`executor.humanize`)

Module: `shop/npc_aim.py`

1. **Approach** — `MouseController.move_with_budget` with
   `SHOP_APPROACH_BUDGET_S` (~0.9–1.55s), more steps, wider curve fraction.
2. **Fine confirm** — several micro-moves in a shrinking pixel radius;
   after DIALOG appears, 1–3 extra micro-moves, then `dialog_click`.
3. **Fallback** — other tile UVs / shuffled ring with **jittered** gaps
   (`SHOP_PROBE_STEP_S`), not a fixed 0.25s metronome.

Timings live in `app/_05_action/humanize.py` (`SHOP_APPROACH_*`,
`SHOP_FINE_*`, `SHOP_PROBE_*`). Combat constants are untouched.

## Practice / tests (`humanize=False`)

`open_shop_npc` keeps the legacy snap + fixed-step
`dialog_click_destinations` / `dialog_click_ring` path so Practice stays
fast and deterministic.

## Side-effect notes

- `SHOP_RUN` blocks longer while opening the NPC (seconds, not ms).
- `dialog_click` still requires a DIALOG cursor before the button down.
- Pose pulse during ActionExecutor blocking is unchanged.
