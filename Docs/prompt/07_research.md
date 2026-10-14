## 17. 부록 E — 2차 검증 잔여문제 수정 (커뮤니티·가이드 근거)

> 출처: NC 공식 파워북(MP 회복 틱), 인벤(화살통/아이템 DB), 린클·게임팟·팔복소프트(물약/도감), 커뮤니티(요정 150물약+1000화살=무게50%↑, 거래소 미스릴화살 2아데나). 이 부록이 §16 D14를 대체한다.

### E1. 근거가 되는 게임 사실
- **무게와 재생**: "무게 게이지가 **50% 이하**이며 포만도 17% 이상일 때 MP 자연회복. 정지 15초/이동 32초/전투 64초마다." → 무게 50% 초과 시 회복 중단(유지력↓). ATS 49% 권장과 정합. **sell=0.49, loot_skip=0.40의 직접 근거.**
- **화살 무게**: 화살통(가죽=3200발, 수렵꾼=6400발)이 각각 무게 150/300 감소 → **화살 1발 ≈ 0.047(≈0.05), 무게 0 아님.**
- **휴대 실측**: 커뮤니티 "요정 물약 150개 + 화살 1000개 → 무게 50% 초과".
- **물약 무게**: 빨간8, 비취8, 주홍10, 맑은12, 파란7, 초록(촐기)23, 강화초록14, 엘븐와퍼4, 용기9, 엔트열매5.
- **버프 지속**: 초록 300s, 강화초록 1800s, 엘븐와퍼 480s, 용기 300s, 파란물약 600s tick, 변신 1200s, 에바 1800s.
- **화살 대미지/가격**: 화살 6/5, 은화살 7/6, 미스릴화살 10/9. 거래소 미스릴화살 500,000발=1,000,000아데나 → **약 2아데나/발**. (커뮤니티 은화살 5발/1아데나 수준)

### E2. 잔여문제 수정 (B1~B5)
- **B1 상점/자원 파라미터화**:
  - `shop.potion_qty: 150`(커뮤니티 140~150), `shop.arrow_qty`는 **무게 예산으로 산출**:
    `arrow_qty = floor((max_weight·k_carry − Σ potion_weight·수량) / arrow_unit_weight)`.
    기본값 1000(무게≈50). `arrow_unit_weight: 0.05`.
  - `return_arrow_count = clamp(k·arrow_rate, 100, arrow_qty−1)` (동적).
  - 제약: `return_potion_count < potion_qty`, `return_arrow_count < arrow_qty`.
- **B2 키 통일**: `economy.loot_pickup_tiles` 단일 키(구 `pickup_tiles`, `player_mode.LOOT_PICKUP_TILES` 별칭/이관).
- **B3**: `economy.hp_trend_window_s: 5` (MP 틱 15~64s·물약 딜레이 대비 교전 되먹임에 충분).
- **B4 파일 명시**: `ActionType` → `engine/app/_03_world/enums.py`; `ActionIntent` → `engine/app/_04_decision/types.py`.
- **B5 검증**: `tests/test_input_latency.py`(T12); DoD#10 버프 가동률 = Σ(버프별 가동 초)/Σ(파밍 초) 로그 집계(≥95%).

### E3. 값 교정(§8 대비 변경)
| 키 | 변경 | 근거 |
|---|---|---|
| economy.arrow_unit_cost | 0 → **2** | 미스릴화살 2아데나/발 → 비용 인지 유효 |
| economy.arrow_unit_weight | 신규 **0.05** | 화살통 3200발=150 |
| economy.hp_trend_window_s | 신규 **5** | 틱/딜레이 정합 |
| shop.potion_qty | 신규 **150** | 커뮤니티 |
| shop.arrow_qty | 999 → **1000(무게 예산 산출)** | 무게 50% |
| shop.return_arrow_count | 300 → **dynamic** | 소모율 기반 |
| spells.buff_recast_margin | s=10 → **ratio 0.05 + min 10s** | 버프 300~1800s |

### E4. nit 확정
- `hotbar` 실제 위치는 `decision.hotbar`(D1 우선).
- `pickup` = 지상 클릭(F4 미사용).
- `adena_only` = `loot_adena_weight_ratio` 초과 시 아데나만 루팅.
- A/B는 30분 **또는** 누적 300처치 중 먼저 도달 시점까지.

### E5. 무게 상한 운용(근거 반영)
- 파밍 중 `weight_ratio`를 **0.49 이하** 유지(MP/HP 재생 보존). 0.49 도달 시 판매 트립.
- 화살·물약 구매량은 "무게 예산 − 장비/루팅 여유"로 계산, 고정값 999 사용 금지.
