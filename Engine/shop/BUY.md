# Buy path (current + unimplemented)

## Merchants — not a tour

Buy does **not** walk a circuit of several merchants (unlike sell’s four-shop shuffle).

`choose_shopping_behavior` picks **one** calibrated behavior id from need kind:

| Need | Resolver | Typical NPC (locale / `HP_POTION_NPC`) |
|------|----------|----------------------------------------|
| HP potion | `resolve_shopping_behavior_id("hp")` | TI general **or** Giran general (setting) |
| Depoison | `"depoison"` | Giran general (fixed by id) |
| Normal arrows | `"normal_arrows"` | TI general |
| Silver arrows | `"silver_arrows"` | Giran (mainland) ids |

There is **no** `_shuffled_buy_ids`, no buy queue of multiple stalls, and no random merchant order for restock. Party supply uses `party_pin_shop_behavior` (still one id).

So: buy is “go to the **mapped** NPC for this item,” not “rotate merchants.”

## Row selection — fixed index today (**unimplemented** memory match)

Live buy UI (`execute_calibrated_buy`) still uses YAML **`item_index`** only:

- `scroll_steps_for_item()` / `visible_row_for_item()` → fixed scroll + row UV
- `shop_listen` buy list is used only for **price** (`_buy_list_price`), not to choose the row

### Proposed (not implemented)

Documented 2026-11-19; **do not treat as done** until coded and consented:

1. After Buy tab opens, read `shop_listen` **buy** rows (`parse_buy_entries`).
2. Match target item by name/id (behavior kind / catalog aliases / optional YAML names).
3. Use live `idx` for scroll + visible row (same 7-row window rule as sell).
4. If memory unread or no match → fall back to current `item_index` (Practice).

Out of scope until that lands: sell tour, warehouse gates, NPC/UI aim, HP/login.

## Related

- Sell tour: `SELL_TOUR.md`
- In-window clicks: `UI_AIM.md`
- NPC open: `NPC_AIM.md`
