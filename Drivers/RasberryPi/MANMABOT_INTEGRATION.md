# Manmabot ↔ Pico(control) 입력 결합 분석

작성: 2026-10-16  
대상 프로젝트: `e:\ManmabotV1_final_final_final` (이하 Manmabot)  
컨트롤러 트리: `D:\Rasberrypi` (`control` 패키지 + Pico CircuitPython 펌웨어)

관련 문서:
- Manmabot 보관 정본(환경구축·설정·운용):  
  `e:\10_17\ManmabotV1_final_final_final\Docs\input\`  
  (`README.md`, `OVERVIEW.md`, `SETUP.md`, `MANMABOT_CONFIG.md`, `OPS_TROUBLESHOOTING.md`)
- 로컬: [`control/OVERVIEW.md`](control/OVERVIEW.md), [`control/README.md`](control/README.md), [`control/AIM_LATENCY.md`](control/AIM_LATENCY.md)

---

## 1. 요약 판정

| 질문 | 판정 |
|------|------|
| Pico로 Interception **주입(inject)** 대체 가능? | **가능** (실측 PASS) |
| Interception **가로채기/차단(intercept)** 대체? | **불가** (커널 필터 필요) |
| Manmabot 실사용(클릭·핫바·연타)에 충분? | **충분** (프로젝트형 연속 시험 PASS) |
| Manmabot 쪽 어댑터 제작 여부 (현재) | **미작성** — 펌웨어/`control`만 개선·검증 |
| 결합 시 수정 규모 | **입력 계층 집중** (의사결정 로직 거의 불변) |

**실사용 기준 커버리지:** 주입 목적 ≈ 85–95%.  
Interception 전체(주입+필터) 평균이면 ≈ 50%대 — Manmabot는 필터를 거의 안 쓰므로 전자가 맞다.

---

## 2. 양쪽 구조

### 2.1 `D:\Rasberrypi` (Pico 2 HID 컨트롤러)

```
[제어 PC]  ControlClient ──CDC data COM──► [Pico 2]
              │                              boot.py + main.py
              │                              → USB HID keyboard + mouse
              ▼
         대상 OS가 실물 키보드/마우스로 인식
```

- 프로토콜: 12B 헤더 + CRC16 (`control/protocol.py`)
- 전송: 시리얼 115200 (Pico), TCP/UDP (Pi SBC uinput — Manmabot와는 별 경로)
- 고수준 API: `move_abs` / `move_rel` / `click` / `key_*` / `type_text` / `ping` / `sync`

**펌웨어 정본 (CIRCUITPY + `control/pico/`):**

| 파일 | 역할 |
|------|------|
| `boot.py` | CDC console+data, KEYBOARD + **REL mouse** + **ABS mouse**(report id 4) |
| `main.py` | 지령 → HID; ABS 1리포트 우선; REL 버스트 폴백; PING/PONG; `T_RESET`/`T_GET_MODE` |
| `abs_hid.py` | 절대 마우스 디스크립터 + `AbsolutePointer` (정본) |
| `boot_abs.py` | `boot.py`와 동일(명시적 ABS 부팅 복사본) |

`boot.py`는 **전원 사이클 / `T_RESET` / UF2** 에서만 재실행된다 (main autoreload·DTR로는 HID 재구성 안 됨).

**정밀 절대 조준 전략 (현재 기본 — 절대 HID):**

1. 보드 `mode=ABS` (`T_GET_MODE` / `ensure_mode`)  
2. `T_MOUSE_ABS` → **절대 HID 1리포트** (Windows 시스템 커서)  
3. 호스트 `GetCursorPos` 짧은 폴링으로 도착 확인 (±2px)  
4. ABS 미매핑/미바인딩 시에만 SYNC + REL 버스트 폴백  
5. Windows 포인터 가속 OFF (`control.pointer.no_pointer_accel`)

농장 조준 API: `ControlClient.move_abs_aim` / `FeedbackController.move_abs_fast`.  
상세·실측: [`control/AIM_LATENCY.md`](control/AIM_LATENCY.md).

### 2.2 Manmabot Interception 사용

동일 커널 필터에 **두 사용자 스택**이 있다.

| 스택 | 위치 | 사용처 |
|------|------|--------|
| A. ctypes/`interception.dll` | `Engine/autologin/bot/win/interception.py` | 오토로그인, `InputRouter` |
| B. PyPI `interception` | `MouseController` / `KeyboardController` | 농장·전투·상점 |

수명주기: `prepare_capture` / `release_capture` (독점 `\\.\interceptionXX` 핸들).  
필터/차단(`set_filter`)·하드웨어 관찰은 사실상 미사용 → Pico 대체와 잘 맞음.

---

## 3. 실측 결과 (Pico 2, COM data, 2026-10)

### 3.1 정밀도·기본 기능

| 항목 | 결과 |
|------|------|
| 상대 이동 (가속 OFF) | 1:1에 가깝음 |
| 절대 HID (`mode=ABS`) | 다수 지점 **err=0 px**, arrive **~5–9 ms** |
| `move_abs_aim` (ABS) | avg **~9 ms**, fails=0/7, max_err=0 (2026-10-18) |
| 클릭 / 휠 / Esc·F키·문자 | OK |
| PING/PONG | 펌웨어 처리 후 응답 확인 (~60 ms RTT, idle sleep 후) |

### 3.2 프로젝트형 입력 프로브

조준 ≤2px, 봇 키(`esc,f1–f4,f8,enter,a,space`), 문자열 → **VERDICT PASS**.

### 3.3 연속 클릭·키 충돌 시험

엔진 패턴 모사: 연클릭, 더블 F8, 키→클릭, Esc→클릭, hold 겹침, F4↔클릭 교차 → **VERDICT PASS** (끼임/대량 누락 없음).

### 3.4 지연 (지령 → 커서 도착)

| 구간 | 대략 |
|------|------|
| 시리얼 1프레임 | &lt; 0.5 ms |
| USB HID 폴링 | ~1 ms |
| 제자리 클릭 | **약 1–3 ms** |
| **ABS 조준** (`move_abs_aim`) | **~9 ms** avg (err=0) |
| REL 버스트 조준 (폴백) | 거리 × (~ms / 127 px) + 수 ms → 과거 ~84 ms |
| Interception snap (비교) | ~0.9 ms |
| `hold_ms` | 의도적 누름 시간 (지연이 아님) |

### 3.5 초기에 겪은 함정 (수정됨)

1. CircuitPython 10에서 `Device.report_ids`가 비어 있음 → report-id만으로 abs를 못 찾음 → **마우스 장치 중 마지막**을 abs로 바인딩.  
2. Digitizer Touch Screen은 이 호스트에서 `GetCursorPos`에 안 붙음 → **Generic Desktop Mouse + Abs** 디스크립터로 고정.  
3. `boot.py` 변경은 autoreload/DTR로 안 적용 → **`T_RESET` / 전원 / UF2** 필요.  
4. 긴 상대 버스트를 sleep 없이 연속 전송 → HID 드롭 → yield (REL 폴백 시).  
5. 호스트 `SerialTransport`의 DTR 토글이 CircuitPython 소프트 리셋 → DTR 비활성.  
6. CDC data write timeout / 보드 행 — 1200 baud touch로 RP2350 부트로더 진입 후 CP UF2로 복구 가능.

---

## 4. Manmabot와의 결합 가능성

### 4.1 기능 대응

| Manmabot 필요 | Pico `control` | 비고 |
|---------------|----------------|------|
| 절대 픽셀 이동 | `move_abs_aim` / `move_abs_fast` | ABS HID 우선, 가속 OFF |
| 클릭/홀드/릴리즈 | `button` / `click` | 엔진은 down→sleep→up 권장 |
| 키 press/hold/combo | HID usage + down/up | 문자열→HID 맵 필요 |
| 휠 | `wheel` | 상점 스크롤 |
| 장치 capture | COM open/close | Interception 핸들 독점 대체 |
| 실입력 차단/필터 | ❌ | 현재 코드 미사용 |
| 20 ms 곡선 휴머나이즈 | 가능(open-loop) | 폐루프를 스텝마다 쓰면 안 됨 |

### 4.2 결합하지 않을 때의 한계

- Pico USB가 게임 PC에 상시 연결되어야 함.  
- COM(data) 포트 선택·재연결 UX 필요.  
- 가로채기/차단이 나중에 필요해지면 Interception 또는 별도 드라이버 유지.

### 4.3 어댑터 현황

- **`D:\Rasberrypi\control`**: 단독 컨트롤러로 완성도 높음 (ABS HID ~9ms aim).  
- **Manmabot `Engine/app/_05_action/input_backend.py`**: `InterceptionBackend` + `PicoHidBackend` 연결됨.  
  - 프로필/설정: `input_backend=interception|pico`, `pico_com`, `pico_baud`, `pico_control_root`  
  - 환경변수 오버라이드: `MANMABOT_INPUT_BACKEND`, `MANMABOT_PICO_COM`, `MANMABOT_PICO_ROOT`  
  - 농장 `MouseController` / `KeyboardController` / 상점·토킹 스크롤이 백엔드 경유.  
  - 오토로그인 `win.interception` 스택은 아직 별도(단계 4).

---

## 5. 실현 방안

### 5.1 권장 아키텍처

```
MouseController / KeyboardController / InputRouter
        │
   InputBackend  (공통 인터페이스)
        ├── InterceptionBackend   (현행)
        └── PicoHidBackend        (ControlClient + SerialTransport)
```

최소 API: `open`/`close`/`ready`, `move_abs`, `button_down`/`up`/`click`, `wheel`, `key_down`/`up`, `neutralize`/`sync`.

설정 예:

```text
input_backend = interception | pico
pico_com      = COM5          # CDC data (보통 인터페이스 x.2)
pico_baud     = 115200
```

### 5.2 단계

| 단계 | 내용 | 판정 |
|------|------|------|
| 0 | Pico 스모크 (`move_abs`/`key`/연타) — **완료** | PASS |
| 1 | `PicoHidBackend` + 설정 스위치 (농장만) — **코드 완료** | 사냥 1세션 실기 |
| 2 | `prepare_capture`/`release_capture` → COM 수명주기 | Start/Stop 안정 |
| 3 | 키 이름 → HID 맵 (`esc`,`f1`…`f12`, …) | 핫바/스킬 |
| 4 | 오토로그인 `win.interception` / `InputRouter` 동일 백엔드 | 로그인 파이프 |
| 5 | `driver_setup`/UI: COM ready (Interception 설치 선택화) | UX |
| 6 | (선택) Interception 제거 | 회귀 |

### 5.3 수정량 감 (Manmabot)

| 범위 | 규모 |
|------|------|
| 최소 (농장만) | 핵심 4–6파일, ~200–400줄 |
| 농장+오토로그인 | +8–12파일, 합 ~500–900줄 |
| 제품화(UI·i18n·테스트) | 합약 **15–25파일**, 공수 대략 1–1.5주 |

**거의 안 건드림:** `_04_decision`, 월드, 지각.  
**꼭 건드림:** `mouse.py`, `keyboard.py`, capture 수명, `shop/runtime.py` 스크롤, (로그인 시) autologin 입력 스택, driver UI.

의사결정·가드 플래그 변경은 Manmabot 워크스페이스 규칙상 **사전 동의** 후.

### 5.4 엔진 포팅 시 규칙

1. 키는 Interception과 같이 **호스트 블로킹** `down → sleep → up` (Pico `hold_ms` 예약만으로 연타하지 말 것 — 가능은 하나 끼임 위험).  
2. 절대 이동은 `resync=True` + 세션 중 포인터 가속 OFF.  
3. 휴머나이즈 곡선에 폐루프 피드백을 넣지 말 것.  
4. CDC **data COM**만 사용 (REPL COM 아님).  
5. `boot.py` 변경 후 반드시 **하드리셋**(USB 재연결).

---

## 6. 디렉터리 맵 (`D:\Rasberrypi`)

```
D:\Rasberrypi\
├─ control_ui.bat
├─ MANMABOT_INTEGRATION.md     ← 본 문서
├─ control\
│  ├─ README.md / OVERVIEW.md
│  ├─ client.py / protocol.py / transport.py
│  ├─ feedback.py / pointer.py / keys.py / guard.py
│  ├─ pico\   boot.py, main.py, abs_hid.py, boot_abs.py
│  └─ … (ui, demo, samples)
└─ RasberryPi install board\
   └─ install_circuitpython.py / .bat
```

검증 산출물(로컬, 참고용):  
`control/_abs_fw_verify.txt`, `_project_input_probe.txt`, `_burst_collision_probe.txt` 등.

---

## 7. 다음 액션

1. ~~공통 `InputBackend` + `PicoHidBackend`~~ 완료.  
2. 농장 실기 A/B (`input_backend=pico`).  
3. 오토로그인 스택 통일 + 드라이버 UI(COM ready).  
4. (선택) Interception 제거.

---

## 8. 한 줄 결론

Pico `control` 스택은 Manmabot의 **Interception 주입 경로를 대체할 수 있는 수준으로 검증**되었다.  
결합의 남은 일은 펌웨어가 아니라 **엔진 입력 어댑터·COM 수명주기·이중 스택 통일**이다.
