# Sell tour (shared solo / party shopkeeper personal sell)

## Principle — no shop re-open to “verify”

After a merchant sell **confirm**, the bot must **not** re-open the same shop
window to check leftovers. That legacy loop is removed on purpose.

**Re-check = bag / WEIGHT memory**, not another Sell-tab pass:

1. After sell success → **weight settle** (IDLE + force bag) so LC inventory catches up.
2. Only then adopt next step (early-stop / next merchant / warehouse / trip end).
3. Warehouse (`give_goods`) uses the settled bag: unread bag → do **not** invent
   leftovers by reopening the merchant UI.

This matches the rule: **do not move to another shop state until bag reading
has had its settle window.** (Decide jitter does not force-bag again; it only
pauses adoption.)

## Merchants

Four calibrated sell behaviors (locale + `sell_mode`). Warehouse `give_goods`
is **not** in the shuffle; it may run once after the merchant loop when
`store_after_sell` is on.

| Slot | Typical scroll spot |
|------|---------------------|
| TI general | `ti_general_goods` |
| Giran weapon | `giran_weapon` |
| Giran general | `giran_general_goods` |
| Giran armor | `giran_armor` |

## Order (humanize)

Each sell trip calls `_shuffled_sell_ids()` → `random.sample` of all four ids.
Every trip gets a **new random permutation**. There is no fixed circuit.

Log line: `sell tour randomized A → B → C → D`.

## Early stop by weight

- **Start** sell trip when weight ≥ `SELL_WEIGHT_RATIO` (default **70%**, Fix/Return).
- After each merchant **sell** succeeds:
  1. **Weight settle** `SELL_WEIGHT_SETTLE_S` (~0.75–1.35s): IDLE + forced bag refresh.
  2. **Decide jitter** `SELL_DECIDE_JITTER_S` (~0.18–0.22s ≈ **0.2s**): IDLE only, **no** force-bag — think pause before adopting the next step.
- **Stop** visiting more merchants when weight &lt; `SELL_STOP_BELOW_RATIO` (default **35%**), checked in `advance_sell_trip` only after settle + decide jitter.
- Remaining queue entries are dropped; then warehouse uses the bag/weight from that adopt moment (no mid-jitter force refresh).
- Config key (optional): `shop.sell_stop_below_ratio` via `configure_decision`.

## Warehouse (`give_goods`) — current rule

After the merchant loop ends (all four done **or** early-stop), using the
post-settle bag/weight snapshot (never on an unread bag):

1. `STORE_AFTER_SELL` must be on (schedule equipment / profile).
2. Current behavior is not already `give_goods`.
3. Bag must be **ready** (`bag_ready`); unread → **skip** warehouse.
4. Weight must be ≥ `STORE_AFTER_SELL_MIN_RATIO` (default **40%**); below that → **skip**.
   Early-stop under 35% therefore skips warehouse naturally.
5. `_bag_needs_give_goods(state)` → **go** only if any item still matches
   **sell_except_keep** (outside the keep list); keep-only → **skip**.

Warehouse is **not** in the random four-shop shuffle; it is a single optional tail step on Talking Island (`ti_warehouse`).

## Code

- `app/_04_decision/shop_trip.py` — `_shuffled_sell_ids`, `schedule_sell_weight_settle`, `finish_sell_weight_settle` (settle → decide jitter → advance), `sell_tour_weight_done`, `store_after_sell_weight_ok`, `_bag_needs_give_goods`
- `app/_04_decision/shops.py` — `SELL_STOP_BELOW_RATIO`, `SELL_WEIGHT_SETTLE_S`, `SELL_DECIDE_JITTER_S`, `STORE_AFTER_SELL_MIN_RATIO`
- `app/_04_decision/manager.py` — merchant sell defers advance; store advances immediately
- `session/bot_controller.py` — force bag only while `sell_advance_pending` (not during decide jitter)
