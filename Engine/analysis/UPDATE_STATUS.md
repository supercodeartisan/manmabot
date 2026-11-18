# UPDATE STATUS — 11-18analysis (2026-11-17)

> **갱신 완료.** analysis_1 구조 유지 + `11_18`(v38 / LC.exe **26.11.17.2002**) 결합.

| 항목 | 값 |
|---|---|
| 트리 | `11-18analysis` |
| 기준 클라이언트 | LC.exe **26.11.17.2002** (base `0x7FF605750000`, `MODULE_SIZE=0x3D2E000`) |
| registry | **v38** · hash `FC74E3F779D75270` |
| MGR | `0x172A840` |
| PLAYER_X/Y | `0x172A6F0` / `0x172A6F4` |
| 규모 | 1270 files / 29.76 MB |
| EXE 동기화 | 37 |
| party.dll | `48BFA40C33FD8DE3` |
| partyhud.dll | `D34DE7B1FD06683C` |

의도적 예외: **`PARTY_JOIN_ACTOR=1`** (11_18 원본 0) — analysis 동작 보존.

## 검증

```
python _build\check_configs.py
```

UNVERIFIED(유지): ExperiencePct64, 구조 오프셋(NODE_*/ENT_*/ITEM_* field 등),
`skill_offsets.HSD_VFT`, `inventory_offsets.json` orphan — `CONFIG_PROVENANCE.md`.
