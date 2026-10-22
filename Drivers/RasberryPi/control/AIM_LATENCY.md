# 조준 지연 원인과 대책 (2026-10-18 실측)

## 원인 (결정적)

| # | 원인 | 증거 |
|---|------|------|
| 1 | **폐루프 P제어가 느림** — `FeedbackController.move_abs(factor=0.5, settle=12ms)` | 같은 목표 **~160–180 ms**, iters 12–14 |
| 2 | **열린루프 대기 과소** — 호스트가 `chunks×1ms`만 기다림 | CircuitPython `sleep(0.001)` 실효 **~8 ms/청크** → 커서 도착 전 측정해 FAIL로 오인 |
| 3 | **펌웨어 버스트 yield** — REL `_burst_rel`이 거리∝시간 | 대각선 이동 시 보드 측만 수십 ms |
| 4 | **커스텀 절대 HID 미바인딩** — CircuitPython 10에서 `report_ids`가 비어 있음 | `find_in_devices`가 abs를 못 찾아 REL만 사용 |

## 대책 (적용됨)

### A. 진짜 절대 HID (정본)

1. [`boot.py`](pico/boot.py): `KEYBOARD + REL mouse + ABS mouse` (`abs_hid.make_device`)
2. [`abs_hid.py`](pico/abs_hid.py): Generic Desktop Mouse, Logical/Physical 0..32767, Report ID 4
3. 장치 탐색: `report_id==4` 또는 **마우스 장치 중 마지막**(builtin REL이 첫 번째)
4. `main.py` `move_abs`: `abs_ptr`가 있으면 **HID 1리포트**만 전송

`boot.py`는 **전원 사이클 / `T_RESET`(0x32) / UF2 재플래시** 때만 재실행된다.  
`main.py` 저장(autoreload)·DTR 소프트 리로드만으로는 HID 구성이 바뀌지 않는다.

### B. 호스트 (`client.move_abs_aim`)

1. 모드 캐시 (`ensure_mode` / `T_GET_MODE`)
2. **ABS**: SYNC 없이 ABS 1회 + 짧은 폴링(~15ms), 보정 REL 기본 OFF
3. **REL 폴백**: SYNC + 버스트 + 폴링 + 최대 1회 REL 보정
4. 세션 중 `no_pointer_accel()`

### C. 실측 (COM5, 1920×1080, 가속 OFF, ABS 모드)

```
move_abs_aim  7점
  avg 9.01 ms   min 8.86   max 9.33
  err=0   fails=0/7   corr=0
GATE_PASS (avg<=10 max<=15 fails=0 err<=2)

ABS_RAW (SYNC 없음) arrive ≈ 5–9 ms, err=0
Interception snap (비교) ≈ 0.9 ms
```

상대 버스트 시절: avg **~84 ms**.  
절대 HID 전환 후: avg **~9 ms** (약 **9×** 개선, Interception 대비 약 **10×**).

USB HID 폴링 + `GetCursorPos` 확인 때문에 Interception 커널 주입(~1ms)과는 같은 급이 되기 어렵다. 실용 게이트는 **avg≤10ms · max≤15ms · err≤2 · fails=0**.

## Manmabot 결합

- `PicoHidBackend.move` → `ControlClient.move_abs_aim` / `FeedbackController.move_abs_fast`
- 부팅 정본: CIRCUITPY `boot.py` + `abs_hid.py` + `main.py`
- 전체 HID 재열거: `client.reset_board()` (`T_RESET`)
- 1200 baud touch는 RP2350 부트로더 진입 → UF2 필요 (응급 복구용)

## 재현 스크립트

- `_abs_reflash_test.py` — 배포 + `T_RESET` + ABS_RAW/AIM
- `_aim_fast_verify.py` — 게이트 검증
- `_aim_rootcause.py` — ABS/REL 분리
