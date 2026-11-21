# 운용·장애 대응 (Pico HID)

---

## 1. COM 포트 고르기

Windows에 Pico CircuitPython이 뜨면 보통 **COM 두 개**:

| 종류 | 용도 | 힌트 |
|------|------|------|
| CDC console | REPL / 디버그 출력 | 인터페이스 `x.0` 쪽 |
| CDC **data** | Manmabot·`ControlClient` 지령 | 인터페이스 **`x.2`** (정본) |

확인:

```bat
python\python.exe -c "from serial.tools.list_ports import comports
for p in comports():
    if p.vid==0x2E8A:
        print(p.device, p.hwid)"
```

`pico_com`에는 **data**만 넣는다. REPL COM에 붙이면 지령이 먹히지 않거나 보드가 이상 동작한다.

자동 선택 순서 (`PicoHidBackend._find_port`):

1. 프로필/인자 `pico_com`
2. `MANMABOT_PICO_COM`
3. VID 2E8A + hwid에 `x.2`
4. VID 2E8A 아무 포트

COM 번호는 USB 포트·재열거마다 바뀔 수 있다 → 바뀌면 설정 갱신 또는 자동 탐지에 맡긴다.

---

## 2. `boot.py`가 안 먹는 경우

증상:

- COM이 하나뿐
- `ensure_mode` / ABS 조준이 안 되고 REL처럼 느림
- `move_abs_aim`이 수십 ms·오차 큼

원인: CircuitPython에서 `boot.py`는 **소프트 리로드로 재실행되지 않음**.

해결 (하나):

1. USB 케이블 뽑았다가 다시 꽂기 (전원 사이클)
2. 호스트 `ControlClient.reset_board()` → 프로토콜 `T_RESET` (0x32)
3. UF2로 CircuitPython 재기록 후 펌웨어 재복사

`main.py`만 CIRCUITPY에 저장하는 것은 HID 장치 목록을 바꾸지 않는다.

---

## 3. 흔한 오류와 조치

| 증상 / 로그 | 조치 |
|-------------|------|
| `pyserial required` / `ModuleNotFoundError: serial` | 번들 `python\python.exe -m pip install pyserial==3.5` |
| `Pico CDC data port not found` | USB·BOOTSEL 해제·케이블·VID 2E8A 확인; data COM 지정 |
| `import control` 실패 | `pico_control_root` / `MANMABOT_PICO_ROOT`가 `D:\Rasberrypi`처럼 **control 상위**인지 |
| 키·마우스 무반응 | CIRCUITPY `lib/adafruit_hid` 누락; `code.py` 잔존 여부 |
| 커서는 움직이는데 게임만 무시 | 창 포커스; 절대 HID가 아닌 다른 장치로 매핑된 경우 → boot/ABS 재적용 |
| 조준이 ~80 ms대 | ABS 미바인딩 → REL 폴백. boot 하드 리셋 + AIM_LATENCY 절 참고 |
| 곡선이 직선처럼 스냅 | 예산 부족이었음 → Pico는 30 ms (`MOVE_BUDGET_PICO_S`). 그래도 짧으면 스텝 수 확인 |
| CIRCUITPY 쓰기 금지 | 읽기 전용 마운트 → 재마운트/재연결 후 복사 |
| 보드가 죽음 / COM 증발 | 1200 baud touch는 RP2350 **부트로더** 진입 → UF2로 CP 복구 |

---

## 4. 포인터 가속

`PicoHidBackend.open`이 세션 동안 `control.pointer.no_pointer_accel()`을 켠다.  
`release_capture`에서 복원한다.

세션 밖에서 수동 시험할 때도 가속을 끄면 ABS/REL 비교가 재현된다.

---

## 5. 키 입력 규칙 (엔진)

Interception과 동일하게 **호스트가** `key_down → sleep → key_up` 한다.  
Pico 펌웨어 `hold_ms` 예약만으로 농장 연타를 돌리지 않는다 (끼임·누락 위험).

지원 키 이름: `input_backend._KEYCODES` + (있으면) `control.keys` 확장.  
핫바 `f1`–`f12`, `esc`, `a`–`z`, 숫자, 방향키 등.

---

## 6. 마우스 API 차이 (구현 메모)

| 동작 | PicoHidBackend |
|------|----------------|
| `move_to` | `move_abs` (resync=False, 곡선 중간점용) |
| `click(x,y)` | `move_abs_aim` 후 button down/up |
| `scroll` | `wheel(±1)` 반복 |
| capture | COM open/close (Interception 핸들 아님) |

---

## 7. 응급 복구 순서

1. 봇 Stop → `input_backend`를 `interception`으로 롤백 가능하면 롤백.
2. USB 재연결 → COM 재확인.
3. CIRCUITPY 파일 4종(`boot`/`main`/`abs_hid`/`lib`) 재확인.
4. `install_circuitpython.py`로 UF2 재설치 후 펌웨어 재배포.
5. `control._aim_fast_verify` / ping으로 보드만 분리 검증한 뒤 다시 `pico` 설정.

---

## 8. 성능 기대치 (회귀 기준)

정상 ABS 모드 (가속 OFF, 풀HD 근처):

- `move_abs_aim`: avg ≤ 10 ms, max ≤ 15 ms, 픽셀 오차 ≤ 2, fail 0
- Interception snap보다 느린 것은 정상 (USB HID + 커서 확인)

상세: `D:\Rasberrypi\control\AIM_LATENCY.md`.

---

## 9. 문서·로그 위치

| 종류 | 경로 |
|------|------|
| 본 문서군 | `Docs/input/` |
| 결합·실측 | `D:\Rasberrypi\MANMABOT_INTEGRATION.md` |
| 엔진 어댑터 | `Engine/app/_05_action/input_backend.py` |
| 변경 동의 로그 | `Docs/decision_change_log.md` |
| 세션 로그 | `Engine/logs/bot-*.log` |
