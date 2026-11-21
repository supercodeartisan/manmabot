# Track identity: guid over heap `ent` (mainline)

**Scope:** main / farm–loot–combat entity identity.  
**Not in scope:** shop humanize branch (`modified_humanize_shop`), buy/sell UI, warehouse.

**Date:** 2026-11-19  
**Consent:** user — fix sticky identity that used heap `ent` instead of game `guid`.  
**Change log:** `docs/decision_change_log.md` § *TrackIds prefer guid over heap ent*.

---

## 1. Problem (what broke farm loot)

Farming showed FREE / MINE adena correctly in `loot decide` (`allowed=1`), then often failed to **walk onto** the pile long enough to F4.

Observed pattern (e.g. `bot-20261119-181222.log`):

1. `begin_loot` / `walk onto item` for a `金幣` with valid `own` / `contrib`.
2. Shortly after: `loot track hold` (IDLE — no ground re-click) and/or sticky release.
3. Character never reaches Chebyshev ≤ `LOOT_PICKUP_TILES`, so F4 never runs.
4. Ownership reading was **not** the failure mode (already validated; decide lines were `allowed=1`).

Root cause was **not** “print_state stopped listing items.” Long-term monitor tests already showed items stay in the JSON roster. The bot’s **sticky key** was wrong.

---

## 2. Old model

| Layer | Identity |
| --- | --- |
| print_state JSON | `ent` (heap pointer), `guid` (game id at entity+0x18) |
| Python `TrackIds` | keyed only on **`ent`** → int `track_id` |
| Blackboard sticky | `current_item_id` / `current_target_id` = that `track_id` |
| “Gone?” | `memory_target_gone` ⇔ fresh print_state ∧ `missing_frames(track_id) ≥ 1` |

`entities_to_handoff` did:

```text
live.add(ent)
track_id = tracks.resolve(ent)
# memory_guid stored only as sidecar metadata
```

`TrackIds.prune(live)` dropped any `ent` not in the current sweep. One omitted tick (or a new heap address for the same object) meant:

- old `track_id` → `missing_frames++`
- new `ent` → **new** `track_id`
- sticky still held the old id → treated as missing → **`loot track hold`** / release

Documented earlier as a symptom workaround (2026-11-09 loot blink hold by guid+kind+cell), not a fix of the key itself:

> *A ground pile that drops out of one memory sweep and returns with a new track id…*

Combat already had a parallel comment: sticky species+cell rebind “survives TrackIds / heap-pointer churn.”

---

## 3. Why `ent` was used historically

1. Decision / World APIs were built around int `track_id` (vision / YOLO era).
2. print_state was wired in with “same handoff shape so Decision/World stay unchanged.”
3. Heap `ent` is always present on a live row; `guid` can be missing or `0x0` on some rows.
4. Game `guid` was added later as `memory_guid` for contested filters, loot claim logs, and blink **rebind** — not as the primary `TrackIds` key.

So this was **pipeline compatibility**, not “guid is worse than ent for identity.”

---

## 4. Fix (mainline)

**File:** `Engine/app/_03_world/merge/memory_entities.py`

- `TrackIds.resolve` / `prune` still map string → int, but the string key is chosen by `_track_key`:
  - usable guid → `guid:{guid}`
  - else → `ent:{ent}`
- Unusable guid: empty, `-`, `0x0` / `0X0`.
- `entities_to_handoff` adds that key to `live` and resolves it for `track_id`.
- `memory_guid` on the row is unchanged (still from raw `guid`).

**Unchanged on purpose:**

- Decision sticky fields still use int `track_id` (`current_item_id`, etc.).
- `loot track hold` / guid+kind+cell rebind remains as **backup** for guid-less rows and true despawns.
- Ownership policy (`FREE` or `contrib > 50`) unchanged.
- Shop / UI aim / sell tour unchanged.

**Comments updated:** `blackboard.py`, `combat.py` (churn language → guid-less / ent fallback).

**Tests:** `Engine/app/_03_world/merge/tests/test_track_ids_guid.py`

- same guid + different ent → same `track_id`
- `guid=0x0` → ent fallback → different ents get different ids

---

## 5. Cause chain (before → after)

```text
print_state entities[]  (ent + guid)     [usually fine]
        |
        v
entities_to_handoff + TrackIds
  BEFORE: key=ent     → remaps track_id on ent churn
  AFTER:  key=guid|ent → stable track_id when guid present
        |
        v
apply_perception_objects / missing_frames(track_id)
        |
        v
memory_target_gone → loot track hold / sticky combat rebind
```

| Bucket | Meaning after fix |
| --- | --- |
| print_state omit | Real miss still increments missing_frames (unchanged). |
| ent remap, guid stable | **Same track_id** — no false hold from key churn. |
| no guid | Still ent-keyed; hold/rebind backup still needed. |

---

## 6. Impact surface

| Area | Effect |
| --- | --- |
| Ground loot sticky | Primary benefit: walk-onto survives guid-stable remaps. |
| Combat sticky | Monsters with guid keep track_id across ent churn; species+cell rebind still for guid-less. |
| Party / contested | Still match on `memory_guid`; complementary, not replaced. |
| YOLO / vision tracks | Untouched (separate path). |
| Shop branch | **None** — do not mix with `modified_humanize_shop` docs. |

---

## 7. How to verify live

1. Farm with adena drops; note `loot decide` `guid=…`.
2. On a former failure window, confirm fewer `loot track hold` while the same guid remains in `last_print_state.entities`.
3. Discriminator if hold still appears: sticky `memory_guid` present in JSON under a **new** `ent` but **same** `track_id` → identity fix working; hold is a true miss or another preemption (combat sticky / attacks_me).
4. Unit: `pytest Engine/app/_03_world/merge/tests/test_track_ids_guid.py`.

---

## 8. Related docs

- `docs/decision_change_log.md` — short consent entry (this change).
- `Docs/decision_change_log.md` — 2026-11-09 loot blink hold (workaround; still valid as backup).
- `Docs/architecture/MEMORY_READ_CANON.md` — how print_state is read (unchanged by this Python keying fix).
- Shop: `Engine/shop/*`, humanize shop change-log entries — **separate branch work**.
