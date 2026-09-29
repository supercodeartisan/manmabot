# Phase 0 — Sell vector order vs UI

Goal: prove ShopSubsystem sell vector index maps 1:1 to the Sell-tab list
(top → bottom), and that scrolling the UI does **not** reorder that vector.
Only then is memory-driven scroll+click safe.

Runtime sell / decision code is **not** changed in this phase.

## Prep

1. LC.exe running; signeddrv loaded (same as inventory_listen / print_state).
2. Rebuild watcher:

```bat
cd engine\analysis\NPC_conv
build_shopwatch.bat
```

3. Start capture (Ctrl+C to stop, or pass seconds):

```bat
shopwatch.exe
```

4. Open a general-goods NPC → click **Sell**. Watcher prints `[SELL]` /
   `[SELL-ORDER]` when the list fills.

## Checklist

Record pass/fail next to each item. Prefer a bag with **more than 7** sellable
rows so scroll tests are meaningful.

### A. Top-of-list order

| # | Check | Pass? |
|---|--------|-------|
| A1 | After Sell tab opens, `[SELL] n=` matches visible+scrolled total (or at least ≥ on-screen count) | |
| A2 | `idx=0` name matches the **top** row on screen | |
| A3 | `idx=1` … `idx=6` match the next six visible rows top→bottom | |
| A4 | `[SELL-ORDER]` one-liner matches handwritten top→bottom names for those rows | |

### B. Scroll does not reorder memory

| # | Check | Pass? |
|---|--------|-------|
| B1 | Scroll the sell list **down** several notches; screen top row changes | |
| B2 | New dump (or unchanged sig): **same** `idx=0` name / same full `[SELL-ORDER]` as before scroll | |
| B3 | Scroll back to top; screen again matches `idx=0..6` | |

If B2 fails (vector follows the viewport), index→`scroll_steps` mapping is
invalid — redesign before Phase 2.

### C. Sell shrinks the vector

| # | Check | Pass? |
|---|--------|-------|
| C1 | Manually sell the **top** item; `n` decreases by 1 | |
| C2 | Former `idx=1` becomes new `idx=0` (list compact, no hole) | |
| C3 | Selling a **middle** visible row removes that id; remaining order stays relative | |

### D. NPC / locale smoke (optional)

| # | Check | Pass? |
|---|--------|-------|
| D1 | Weapon shop Sell list also ordered top→bottom | |
| D2 | Chinese client: resolved names still line up with on-screen order (ids sufficient even if name resolve empty) | |

## Pass criteria

- **A + B + C** all pass on at least one Korean general-goods NPC.
- B2 is mandatory: scroll must be UI-only relative to a stable full vector.

## Capture tip

Redirect for a log file:

```bat
shopwatch.exe 120 > shopwatch_sell_phase0.txt
```

Paste the `[SELL]` / `[SELL-ORDER]` blocks (and note which UI rows you saw)
into the chat or `docs/decision_change_log.md` under CN50 results.

## Next

On pass → Phase 1: `shop_listen` DLL + Python reader (no sell-loop change yet).
On fail → stop; re-evaluate click strategy before any runtime integration.
