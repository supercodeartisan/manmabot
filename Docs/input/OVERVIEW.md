# 외부 마우스·건반으로 봇 조종 — 개요

작성: 2026-10-18  
대상: ManmabotV1 + `D:\Rasberrypi\control` (Pico CircuitPython HID)

---

## 1. 한 줄 정의

제어 PC(봇 프로세스)가 CDC 시리얼로 지령을 보내고,  
**Raspberry Pi Pico**가 USB HID 키보드·마우스 리포트를 내어  
대상 Windows가 **실물 입력장치**로 인식하게 한다.

```
[Manmabot Engine]
  MouseController / KeyboardController / shop scroll
        │
   InputBackend
        ├── InterceptionBackend   ← 기본 (커널 필터 주입)
        └── PicoHidBackend        ← 선택 (CDC → Pico → USB HID)
                │
         ControlClient (D:\Rasberrypi\control)
                │  SerialTransport 115200, CDC data COM
                ▼
         [Pico] boot.py + main.py + abs_hid.py
                │  KEYBOARD + REL mouse + ABS mouse
                ▼
         Windows HID 스택 → 게임 창
```

의사결정·전투·HP·로그인 **정책 코드는 바꾸지 않는다**.  
바뀌는 것은 **주입(inject) 경로**뿐이다.

---

## 2. Interception과의 역할 분담

| 능력 | Interception | Pico HID |
|------|--------------|----------|
| 마우스/키 주입 | ✅ 커널 | ✅ 물리 USB HID |
| 절대 좌표 조준 | ✅ ~1 ms snap | ✅ ABS ~9 ms avg (실측) |
| 실입력 가로채기/차단 | ✅ | ❌ (커널 필터 필요) |
| 드라이버 설치 | 필수 | 불필요 (HID 표준) |
| Manmabot 농장 사용 | 기본 | `input_backend=pico` |

Manmabot 농장은 필터/차단을 거의 쓰지 않으므로 **주입만** 보면 Pico로 대체 가능하다  
(실측·프로브 PASS — `D:\Rasberrypi\MANMABOT_INTEGRATION.md`).

**아직 Interception을 쓰는 곳**

- 기본 백엔드 (프로필 미설정 시)
- 오토로그인 `Engine/autologin/.../win/interception.py` (농장 Pico와 **별 스택**, 미통일)

---

## 3. 엔진에서의 호출 경로

| 계층 | 파일 | 역할 |
|------|------|------|
| 설정 유입 | `settings/profile.py`, `task_runtime.py`, `schedule.py`, `session/runtime_settings.py` | `input_backend`, `pico_com`, `pico_baud`, `pico_control_root` |
| 액션 적용 | `app/_04_decision/configure.py` → `configure_input_backend(...)` | 세션 시작 시 백엔드 선택 + 화면 해상도 |
| 어댑터 | `app/_05_action/input_backend.py` | `PicoHidBackend` / `InterceptionBackend` |
| 마우스 | `app/_05_action/mouse.py` | `prepare_capture` / `move` / click → `get_backend()` |
| 키보드 | `app/_05_action/keyboard.py` | press/hold/combo → backend |
| 휴머나이즈 | `app/_05_action/humanize.py` | 곡선 스텝; Pico 예산 `MOVE_BUDGET_PICO_S=0.03` |
| 상점 스크롤 | `shop/runtime.py` | wheel → backend |
| 준비 검사 | `session/driver_setup.pico_ready` | VID `0x2E8A`, CDC data(`x.2`) 선호 |

수명주기:

1. `configure_input_backend("pico", pico_com=..., ...)`
2. `prepare_capture()` → COM open, `set_screen`, `ensure_mode`, 포인터 가속 OFF
3. 틱마다 `move_to` / `click` / `key_down`…
4. `release_capture()` → sync, COM close, 가속 복원

---

## 4. Pico 펌웨어가 하는 일

| 파일 (CIRCUITPY / `control/pico/`) | 역할 |
|------------------------------------|------|
| `boot.py` | CDC console+**data**, HID: Keyboard + REL mouse + **ABS mouse** |
| `main.py` | 바이너리 프레임 수신 → HID; ABS 1리포트 우선; PING; `T_RESET` |
| `abs_hid.py` | 절대 마우스 디스크립터 (0..32767 → 화면 매핑) |

프로토콜: 12바이트 헤더 + CRC16 (`control/protocol.py`).  
농장 조준: `ControlClient.move_abs_aim` (ABS 우선, REL 버스트는 폴백).

`boot.py`는 **전원 재연결 / `T_RESET` / UF2** 에서만 다시 돈다.  
`main.py` 저장(autoreload)·DTR만으로는 HID 구성이 바뀌지 않는다.

---

## 5. 지연·정확도 (요약)

| 경로 | 대략 |
|------|------|
| Pico ABS `move_abs_aim` | avg **~9 ms**, err≈0 (1920×1080, 가속 OFF) |
| Pico REL 버스트 폴백 | 거리 비례, 과거 ~84 ms |
| Interception snap | ~0.9 ms |
| 휴머나이즈 곡선 예산 | Interception 20 ms / **Pico 30 ms** |

상세 실측: `D:\Rasberrypi\control\AIM_LATENCY.md`.

---

## 6. 한계 (알고 쓸 것)

1. Pico USB가 **게임 PC에 상시 연결**되어야 한다.
2. Windows에 COM이 **두 개** 뜬다 → 지령은 **CDC data**(보통 인터페이스 `x.2`)만.
3. 실입력 **차단/필터**는 불가 → 그 기능이 필요하면 Interception 유지.
4. 오토로그인은 아직 Interception 스택.
5. 곡선 이동은 **열린루프**; 스텝마다 폐루프 피드백을 넣지 않는다 (지연 폭발).

---

## 7. 관련 문서

- 본 폴더: [`SETUP.md`](SETUP.md), [`MANMABOT_CONFIG.md`](MANMABOT_CONFIG.md), [`OPS_TROUBLESHOOTING.md`](OPS_TROUBLESHOOTING.md)
- 외부: `D:\Rasberrypi\MANMABOT_INTEGRATION.md`, `control\README.md`, `control\OVERVIEW.md`
- 변경 기록: `Docs/decision_change_log.md`
