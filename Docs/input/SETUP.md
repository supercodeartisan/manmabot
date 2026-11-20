# 환경구축 — Pico CircuitPython + control + Manmabot

목표: 게임 PC에 Pico를 USB로 연결하고, Manmabot가 `input_backend=pico`로  
마우스·키보드를 주입할 수 있는 상태까지 만든다.

권장 보드: **Raspberry Pi Pico 2** (RP2350). Pico / Pico W도 동일 절차(보드 ID만 다름).

---

## 0. 사전 준비물

| 항목 | 비고 |
|------|------|
| Pico (USB 케이블 데이터 전송 가능) | 충전 전용 케이블이면 COM이 안 뜸 |
| Windows 게임 PC (관리자 권한 권장) | Manmabot + CIRCUITPY 복사 |
| `D:\Rasberrypi` 트리 | `control/` + 설치기 |
| Manmabot 번들 Python | `python\python.exe` 또는 시스템 Python 3.10+ |
| Adafruit CircuitPython Bundle | `adafruit_hid` 라이브러리 |

네트워크: CircuitPython UF2 자동 다운로드 시 인터넷 필요  
(`RasberryPi install board\install_circuitpython.py`).

---

## 1. CircuitPython 설치 (보드에 UF2)

### 1.1 부트로더 진입

1. Pico의 **BOOTSEL** 버튼을 누른 채 USB를 PC에 연결한다.  
2. 탐색기에 `RPI-RP2` / `RP2350` 등 **부트로더 드라이브**가 나타난다 (`INFO_UF2.TXT` 확인).

이미 CircuitPython이 떠 있으면:

```bat
python "D:\Rasberrypi\RasberryPi install board\install_circuitpython.py" --port COMx --reboot-to-bootloader
```

(또는 USB 뽑고 BOOTSEL 재진입.)

### 1.2 UF2 기록

```bat
cd /d "D:\Rasberrypi\RasberryPi install board"
python install_circuitpython.py
```

보드를 강제 지정할 때:

```bat
python install_circuitpython.py --board raspberry_pi_pico2
python install_circuitpython.py --board raspberry_pi_pico2_w
```

로컬 UF2가 있으면:

```bat
python install_circuitpython.py --uf2 path\to\adafruit-circuitpython-....uf2
```

성공 시 드라이브가 **`CIRCUITPY`** 로 바뀌고, 시리얼 COM이 생긴다.

---

## 2. 펌웨어·라이브러리 배포 (CIRCUITPY)

### 2.1 `adafruit_hid` 복사

[Adafruit CircuitPython Library Bundle](https://circuitpython.org/libraries)에서  
보드 CP 버전에 맞는 zip을 받아 `lib/adafruit_hid/` 폴더를 CIRCUITPY에 복사한다.

```
CIRCUITPY/
└─ lib/
   └─ adafruit_hid/     ← 없으면 키/마우스 전부 실패
```

### 2.2 control 펌웨어 정본 복사

`D:\Rasberrypi\control\pico\` → CIRCUITPY 루트:

| 원본 | CIRCUITPY |
|------|-----------|
| `boot.py` | `boot.py` |
| `main.py` | `main.py` |
| `abs_hid.py` | `abs_hid.py` |

주의:

- 루트에 `code.py`가 있으면 CircuitPython이 그걸 먼저 실행한다 → **삭제하거나 이름 변경**.
- `boot.py` 변경 후 반드시 **하드 리셋**(USB 재연결, 또는 호스트에서 `T_RESET` / UF2).

배포 후 권장 구조:

```
CIRCUITPY/
├─ boot.py
├─ main.py
├─ abs_hid.py
└─ lib/
   └─ adafruit_hid/
```

### 2.3 HID 재열거 확인

재부팅 후 장치 관리자 / `python -m serial.tools.list_ports -v` 에서:

- Vendor **2E8A** (Raspberry Pi)
- COM이 **두 개**: console(REPL) + **data** (지령용, hwid에 `x.2` 인 쪽을 우선)

data COM이 하나뿐이면 `boot.py`가 적용되지 않은 것이다 → USB 재연결 또는 UF2 재기록.

---

## 3. 제어 PC 쪽 `D:\Rasberrypi` (클라이언트)

Manmabot `PicoHidBackend`는 런타임에 `sys.path`에 다음을 넣는다:

- 프로필 `pico_control_root` (기본 `D:\Rasberrypi`)
- 또는 환경변수 `MANMABOT_PICO_ROOT`

필수 패키지(호스트):

```
D:\Rasberrypi\
└─ control\
   ├─ __init__.py
   ├─ client.py, protocol.py, transport.py, pointer.py, keys.py, …
   └─ pico\   (보드용 소스; 호스트 import에는 불필요)
```

경로가 다르면 프로필/`MANMABOT_PICO_ROOT`를 그 경로로 맞춘다.  
**`control` 패키지 상위 폴더**를 가리켜야 한다 (`import control`이 되게).

스모크 (보드 연결 후, data COM 예: COM5):

```bat
cd /d D:\Rasberrypi
python -c "from control import ControlClient, SerialTransport; c=ControlClient(SerialTransport('COM5',115200)); c.set_screen(1920,1080); print(c.ping(samples=3)); c.move_abs_aim(960,540); c.close()"
```

시퀀스 UI:

```bat
cd /d D:\Rasberrypi
python -m control.ui
```

연결: **시리얼 → data COM**.

---

## 4. Manmabot Python 의존성

번들 인터프리터에 pyserial이 있어야 한다.

```bat
cd /d e:\10_17\ManmabotV1_final_final_final
python\python.exe -m pip install pyserial==3.5
```

`Engine/requirements.txt`에 `pyserial==3.5`가 명시되어 있다.  
portable 배포본을 쓰면 **그 트리의 `python\`에도** 동일하게 설치한다.

확인:

```bat
python\python.exe -c "import serial; print(serial.__version__)"
python\python.exe -c "from serial.tools.list_ports import comports; print([(p.device, hex(p.vid or 0), p.hwid) for p in comports()])"
```

---

## 5. (선택) 라즈베리파이 SBC + uinput

USB Pico 경로와 **별개**. Linux Pi가 TCP/시리얼로 받아 `uinput`으로 주입하는 모드다.  
Manmabot `PicoHidBackend`는 현재 **시리얼 + Pico HID**만 연결한다.

SBC 쪽은 `D:\Rasberrypi\control\README.md`의 `pi_server` 절을 따른다:

```bash
sudo modprobe uinput
pip install evdev
python -m control.pi_server --tcp 9999 --screen 1920x1080
```

농장 봇 기본 경로로는 **쓰지 않는다**.

---

## 6. 구축 완료 체크리스트

- [ ] CIRCUITPY에 `boot.py` / `main.py` / `abs_hid.py` / `lib/adafruit_hid`
- [ ] USB 재연결 후 COM **2개**, data COM 식별됨 (VID 2E8A, 가능하면 `x.2`)
- [ ] `D:\Rasberrypi\control`에서 `ControlClient` ping / `move_abs_aim` 성공
- [ ] Manmabot `python`에 `pyserial` 설치됨
- [ ] (다음) [`MANMABOT_CONFIG.md`](MANMABOT_CONFIG.md)로 `input_backend=pico` 설정

---

## 7. 설치기·검증 스크립트 위치

| 용도 | 경로 |
|------|------|
| CP UF2 설치 | `D:\Rasberrypi\RasberryPi install board\install_circuitpython.py` |
| 조준 게이트 | `D:\Rasberrypi\control\_aim_fast_verify.py` |
| ABS 재플래시 시험 | `D:\Rasberrypi\control\_abs_reflash_test.py` |
| 지연 원인 | `D:\Rasberrypi\control\AIM_LATENCY.md` |
