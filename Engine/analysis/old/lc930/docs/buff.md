# buff_listen — 활성 버프 읽기 (Manmabot)

정본: `E:\Lineage\extra` (`core/lbuff.h` + `buff_930` / `realtime_buff_930`).
봇 DLL: `analysis/lc930/buff/buff_listen.c` → `buff_listen.dll` (동일 엔진).
소비: 매 `capture_tick` 동기 `snapshot_fresh` → `GameState.player.buffs` / `last_buff`.
**시전하지 않는다.**

---

## 1. 알고리즘 (2026-10-06)

`BuffSubsystem = lc_subsGet(VFT_BUFF)` → `unordered_map` 버킷·노드 walk.
**BFS / HudSlot 체인 없음.** 폴링 ≈ 레코드 수 비례(~70 reads / ~1.4ms).

레코드 = `_Ref_count_obj2<BuffInstance>` (`RECORD_VFT_RVA`).

| 필드 | 오프셋 | JSON |
|---|---|---|
| `_Uses` | +0x08 | 0 → 제외 |
| skill | +0x14 | `skill` |
| duration | +0x18 | `duration` / `perpetual` |
| strID | +0x2C | `strId` → KR `name` |
| remain | +0x84 | `remain` |

필터: 고아 제외, strID 중복 1회, `rem<=0`(비상시) 제외. **STABLE 프레임 억제 없음.**

Registry: `BUFF_MAP_OFF` / `BUFF_VEC_OFF` / `BUFF_MASK_OFF` / `BUFF_END_OFF` /
`BUFF_BUCKET_PTR` / `BUFF_NODE_*` (SEC-6).

---

## 2. 봇 연결

| 층 | 역할 |
|---|---|
| `buff_listen.dll` | `lbuff_poll` → JSON |
| `capture_tick` | uidialog와 병렬 동기 fresh |
| `apply_buff_snapshot` | `PlayerState.buffs` |
| `due_buff` | 메모리 remain / 타이머 |

빌드: `analysis/lc930/build_new_readers.bat`.
