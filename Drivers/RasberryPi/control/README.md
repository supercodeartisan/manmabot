# control — 라즈베리파이 하드웨어 입력(마우스·키보드) 실시간 주입 모듈

컴퓨터(PC)가 **의도(화면 픽셀좌표 / 누를 키 / 누르는 시간 / 클릭)** 를 보내면,
라즈베리파이가 **하드웨어 준위**로 마우스·키보드를 실제 입력하는 저지연·고결합 모듈.

```
  [ 컴퓨터(PC) ]                         [ 라즈베리파이 ]
   ControlClient  ── 지령 프레임 ─▶  Transport ─▶ ControlServer ─▶ HidBackend ─▶ 실제 입력
   (좌표/키/시간/클릭)                시리얼·TCP·UDP         (수신·스케줄)      (uinput / usb_hid)
```

## 핵심 3요소

1. **저지연**
   - 고정 12 byte 바이너리 헤더 + CRC16, 리틀엔디언 (`protocol.py`)
   - `send()` 즉시 write, 여러 명령은 `send_many()` 로 **한 번의 write** 에 묶음
   - TCP 는 `TCP_NODELAY`, 서버 루프는 **무블로킹**, `누르는 시간(hold)` 은 sleep 대신 **예약 큐**
   - 실측(로컬): 메모리 전송 RTT **avg ≈ 0.05 ms**, TCP localhost **avg ≈ 0.13 ms**

2. **안정성**
   - CRC16(무결성) + 시퀀스 번호 + 파서의 **자동 재동기화**(magic 스캔)
   - `client.ping()` 으로 왕복 지연·생존을 상시 확인 (PING/PONG)

3. **결합성(확장)**
   - `Transport` / `HidBackend` / 명령 핸들러를 **모두 주입·등록식**으로 교체
   - 새 명령 타입은 `server.register(TYPE, handler)` 한 줄로 추가
   - 클라이언트 고수준 API 는 임의 파이프라인(비전/자동화/테스트)에서 그대로 호출

## 파일 구성

| 파일 | 역할 |
|---|---|
| `protocol.py` | 프레임/CRC/메시지 정의 (PC·Pi·Pico 공용) |
| `transport.py` | `Memory` / `Serial` / `TCP` / `UDP` 전송, `TcpListener` |
| `backend.py` | `HidBackend` 인터페이스, `NullBackend`, 절대좌표 추적기 |
| `backends_linux.py` | 라즈베리파이 OS용 **uinput** 백엔드 (+ HID→리눅스 키 매핑) |
| `server.py` | 라즈베리파이 측 수신·디스패치·hold 스케줄러 |
| `pi_server.py` | **라즈베리파이(리눅스) 실행 진입점** (TCP/시리얼) |
| `client.py` | 컴퓨터 측 전송·고수준 API·`ping()` |
| `feedback.py` | **1방안**: 커서 위치 피드백 폐루프 + 대상 에이전트 |
| `guard.py` | **사용자 간섭 시 자동 일시정지/재개** (충돌 방지, 두 시간 설정) |
| `keys.py` | 키 이름/핫키 → HID 코드 |
| `sequence.py` | 시퀀스 스텝 실행 (UI/테스트 공용) |
| `ui.py` | **시퀀스 테스트 UI (한/중/영)** |
| `i18n.py` | 다국어(한/중/영) 문자열 |
| `demo.py` | 하드웨어 없이 전체 경로·지연·안정성·정확도 실측 |
| `pico/boot.py`, `pico/main.py` | **Pico(CircuitPython)** usb_hid 주입 (동일 프로토콜) |
| `pico/abs_hid.py`, `pico/boot_abs.py` | **3방안(b)**: Pico 절대좌표 포인터(커스텀 HID) |

## 메시지 (protocol.py)

| 타입 | 값 | 페이로드 | 의미 |
|---|---|---|---|
| `T_PING`/`T_PONG` | 0x01/0x02 | `Q` / `Q Q` | 지연·생존 확인 |
| `T_MOUSE_ABS` | 0x10 | `H H` | 화면 픽셀좌표로 이동 |
| `T_MOUSE_REL` | 0x11 | `h h` | 상대 이동 |
| `T_MOUSE_BTN` | 0x12 | `B B H` | 버튼, 동작(0up/1down/2press), 유지ms |
| `T_MOUSE_WHEEL` | 0x13 | `b` | 휠 |
| `T_KEY` | 0x20 | `B B B H` | HID키코드, 수정자비트, 동작, 유지ms |
| `T_KEY_TEXT` | 0x21 | utf-8 | 문자열 입력 |
| `T_SET_SCREEN` | 0x30 | `H H` | 화면 크기(절대좌표 변환용) |
| `T_SYNC` | 0x31 | – | 즉시 반영 |

키코드는 **USB HID usage id** 표준 (`0x04='a'`, `0x28=Enter`, `0xE0=LeftCtrl` …).
Pico 는 `Keycode` 값과 동일해 그대로 사용, 리눅스는 내부 표에서 변환.

## 사용 예

### 컴퓨터 측
```python
from control import ControlClient, tcp_connect          # 또는 SerialTransport("COM5")

c = ControlClient(tcp_connect("192.168.0.10", 9999))
c.set_screen(1920, 1080)
c.move_click(300, 200, hold_ms=25)      # 이동 후 좌클릭
c.key(0x04)                             # 'a'
c.hotkey(0xE0, 0x06)                    # Ctrl+C
c.type_text("hello world")
print("RTT(ms):", c.ping(samples=5))    # min/avg/max
```

### 라즈베리파이 측 (리눅스, uinput)
```bash
sudo modprobe uinput
pip install evdev          # 또는 sudo apt install python3-evdev
```
```python
from control import ControlServer, TcpListener
from control.backends_linux import UinputBackend

tr, addr = TcpListener(port=9999).accept()
ControlServer(tr, UinputBackend(screen=(1920, 1080))).run()
```

### Pico(CircuitPython) 측 — 하드웨어 준위 USB HID
1. CircuitPython 번들의 `adafruit_hid/` 폴더를 보드 `lib/` 로 복사
2. `pico/boot.py` → 보드 루트 `boot.py`, `pico/main.py` → 보드 루트 `main.py`
3. 재부팅하면 COM 포트가 **2개** 생김(하나는 REPL, **다른 하나가 지령용 `data`**)
4. 컴퓨터 측:
```python
from control import ControlClient, SerialTransport
c = ControlClient(SerialTransport("COM7", 115200))   # data 포트
c.set_screen(1920, 1080); c.move_click(400, 300)
```

## 지연시간 예산 (실제 하드웨어)

| 구간 | 대략 |
|---|---|
| 코덱 인코딩/디코딩 | ≈ 3 µs / frame |
| 시리얼 115200 (소형 프레임) | < 0.5 ms |
| USB HID 폴링(대상 PC) | ≈ 1 ms (1 kHz) |
| 서버 처리 + 주입 | 수십 µs ~ 수백 µs |
| **합계 (USB 직결)** | **대략 수 ms 이내** |
| 원격(TCP/UDP) | 네트워크 RTT 가 지배 |

> 무선/원거리에서는 `TCP`(NODELAY, 안정) 또는 저지연이 최우선이면 `UDP`(손실 허용)를 선택.
> `hold`(누르는 시간)는 서버가 **비블로킹 예약**으로 처리하므로 다음 지령이 밀리지 않습니다.

## 절대좌표 정확도 '보장' (1방안 / 3방안)

`move_abs` 는 **명령 레벨에서는 절대 픽셀좌표**지만, 표준 마우스는 상대이동이라
가속/외부개입으로 목표에 정확히 못 갈 수 있다(데모: 오픈루프 오차 `(384,240)`).
아래 두 방법이 이를 실제로 '보장'한다.

### 1방안 — 커서 위치 피드백(폐루프)  `feedback.py`
매 이동마다 실제 커서 위치를 읽어 `(목표-실제)` 델타를 다시 보내 수렴시킨다.
데모 결과: **폐루프 성공=True, 위치=(640,400), 반복 6회** (가속 무력화).

```python
from control import ControlClient, tcp_connect, FeedbackController

fc = FeedbackController(ControlClient(tcp_connect("192.168.0.10", 9999)))  # 로컬 커서 자동감지
fc.set_screen(1920, 1080)
ok, pos, n = fc.move_abs(640, 400)     # 실제 커서가 (640,400)±2 에 들어올 때까지 보정
fc.move_click(1200, 700)               # 이동 후 클릭
```
- 자기주입(보드가 제어 PC에 꽂힘): `local_cursor()` 로 바로 폐루프.
- 대상이 다른 PC: 대상에서 **에이전트** 실행 → `RemoteCursor` 로 폐루프.
  ```bash
  # 대상 PC 에서
  python -m control.feedback --agent --port 9001
  ```
  ```python
  from control.feedback import RemoteCursor, FeedbackController
  fc = FeedbackController(client, RemoteCursor("192.168.0.50", 9001))
  ```
- `move_abs(x, y, tolerance=2, max_iter=12, max_step=0)` — `max_step` 로 큰 이동을
  잘게 나누면 수렴이 빨라진다.

### 3방안 — 절대 입력장치(가속 자체를 제거)
**(a) 라즈베리파이(Linux): uinput `EV_ABS`**
```python
from control.backends_linux import UinputBackend
be = UinputBackend(screen=(1920, 1080), absolute=True)   # 절대 포인터 생성
be.set_screen(1920, 1080)   # begin() 전에 호출해야 absinfo 범위에 반영
be.begin()
```
**(b) Pico(CircuitPython): 커스텀 HID 디지타이저/펜**  `pico/abs_hid.py`
표준 `usb_hid` MOUSE 는 상대전용이라, 절대좌표 Report Descriptor 를 직접 만든다.
```
보드 루트:  boot.py(=boot_abs.py), main.py, abs_hid.py, lib/adafruit_hid/
```
- 절대 포인터가 감지되면 `main.py` 의 `move_abs` 가 자동으로 절대 보고를 사용.
- 좌표는 16비트(0..32767)로 스케일되어 OS 가 화면에 가속 없이 매핑.
- 스크롤/우클릭 등 상대기능을 위해 표준 마우스도 함께 켠다(RP2040 은 엔드포인트 주의).

정리:
| 방법 | 가속 영향 | 대상측 요구 | 비고 |
|---|---|---|---|
| 상대(기본) | 받음 | 없음 | 오차 누적 가능 |
| 1방안 피드백 | 없음(보정) | 없음(자기주입)/에이전트(원격) | 상대장치 그대로, 매 지령 보정 |
| 3방안(a) uinput EV_ABS | 없음 | 없음 | 리눅스 라즈베리파이 |
| 3방안(b) Pico 커스텀 HID | 없음 | 없음 | CircuitPython `usb_hid.Device` |

## 사용자 간섭 시 자동 일시정지/재개 (충돌 방지)  `guard.py`

자동 입력이 사용자의 실제 마우스와 충돌하지 않도록, 간섭이 감지되면 멈추고
사용자가 멈춘 뒤 일정 시간 후 재개한다. **두 시간은 사용자가 설정**한다.

| 설정 | 의미 |
|---|---|
| `pause_hold`  | 사용자 개입 후 최소 이만큼 멈춘다 (초) |
| `resume_idle` | 마우스가 멈춘 뒤 이만큼 지나면 재개한다 (초) |

```python
from control import ControlClient, tcp_connect, guard_client, local_cursor

client = ControlClient(tcp_connect("192.168.0.10", 9999))
gc, guard = guard_client(
    client,
    cursor=local_cursor(),   # 자기주입이면 로컬, 원격이면 RemoteCursor(...)
    pause_hold=1.0,          # 사용자 개입 후 1초간 정지
    resume_idle=3.0,         # 마우스가 멈춘 뒤 3초 후 재개
    feedback=True,           # 1방안(폐루프)과 결합
)
gc.start()

gc.move_click(300, 200)      # 정지 중이면 '재개될 때까지 대기' 후 전송
gc.type_text("hello")
gc.stop()
```

동작
- 감시 스레드가 실제 커서 위치를 읽어, **우리가 명령한 예상 위치를 벗어난 '변화'** 를
  사용자 개입으로 판단 → 일시정지
- 정지 순간 **눌려 있던 버튼/키를 자동 해제**(키 눌림 사고 방지)
- 재개 조건: `pause_hold` 경과 **그리고** `resume_idle` 동안 커서가 멈춰 있을 것
- 정지 중 `gc.move_abs(...)` 등은 (`timeout=None` 이면) 재개까지 대기, `timeout` 초과 시 `False`
- 커서를 움직이지 않는 클릭/키보드까지 잡으려면 `InputGuard(..., activity_probe=함수)` 훅 사용

검증(시뮬레이션):
```
[중재기] 정상전송=True,True  정지중차단=True  재개후전송=True (정지 1회/재개 1회)
```

## 배포 (설치) — "그냥 복사만 하면 되나?"

### Pico (CircuitPython) — 거의 복사만으로 됩니다
`F:`(CIRCUITPY) 드라이브에 아래처럼 넣으면 재부팅 후 바로 동작한다.
```
CIRCUITPY/
├─ boot.py          ← control/pico/boot.py        (usb_cdc data + usb_hid)
├─ main.py          ← control/pico/main.py        (수신기)  ※ code.py 가 있으면 삭제/이름변경
├─ abs_hid.py       ← control/pico/abs_hid.py     (절대좌표 쓸 때)
├─ boot_abs.py      ← control/pico/boot_abs.py    (절대버전 boot; 쓰려면 boot.py 로 이름변경)
└─ lib/
   └─ adafruit_hid/  ← Adafruit CircuitPython Bundle 의 adafruit_hid 폴더
```
- **주의**: `lib/adafruit_hid/` 를 **빠뜨리면 키/마우스가 동작하지 않는다**. (번들에서 복사)
- CircuitPython 은 `code.py` 를 먼저 실행한다 → 수신기를 `main.py` 로 두려면 `code.py` 를 없앤다.
- `boot.py` 는 **하드 리셋(전원 재연결/UF2 재기록)** 후에만 적용된다. 적용되면 COM 포트가 **2개**
  (콘솔 + data) 생긴다. 컴퓨터 측은 **data 포트**에 접속한다.

### 라즈베리파이 SBC (리눅스) — 복사만으로는 안 됩니다
파일 복사에 더해 준비가 필요하다.
```bash
# 1) 코드 복사 (control/ 폴더 통째로)
scp -r control pi@<pi>:/home/pi/

# 2) 의존성 / 커널 모듈
sudo modprobe uinput
pip install evdev            # 또는 sudo apt install python3-evdev

# 3) 권한 (/dev/uinput): root 로 실행하거나 udev 규칙 추가

# 4) 실행 (진입 스크립트 제공)
python -m control.pi_server --tcp 9999 --screen 1920x1080
python -m control.pi_server --serial /dev/ttyACM0
python -m control.pi_server --tcp 9999 --absolute      # 절대 포인터
python -m control.pi_server --tcp 9999 --null          # 수신만 확인
```

### 컴퓨터 측
```bash
python -m control.ui            # 시퀀스 테스트 UI (가상/TCP/시리얼)
```
- Pico 를 USB 로 직결했다면 연결 방식 **시리얼**에서 **data 포트**(두 번째 COM)를 선택.

## 시퀀스 테스트 UI (한국어 / 中文 / English)  `python -m control.ui`

입력 '시각'과 마우스/건반 사건을 표로 정의하고 [▶ 실행]을 누르면, 그 시각에 맞춰
통신이 발생하며 클릭/이동/끌기/키/핫키/텍스트 입력을 수행한다. 언어는 우측 상단에서
바로 전환된다.

사건(스텝) 종류와 파라미터

| 종류 | 파라미터 |
|---|---|
| 이동 Move | x, y |
| 클릭 Click | x, y, 버튼(좌/우/가운데), 누름(ms) |
| 더블클릭 Double-click | x, y, 버튼 |
| 끌기 Drag | x,y → x2,y2, 기간(ms) |
| 휠 Wheel | dy |
| 키 Key | key (enter, f5, left …) |
| 핫키 Hotkey | ctrl+shift+s 등 |
| 텍스트 Text | 문자열 + **속도 cps (건별 타이핑 속도)** |
| 대기 Wait | 기간(ms) |

기능
- 표에서 추가/삭제/정렬, **[현재 마우스 위치]** 로 좌표 캡처
- 연결: TCP / 시리얼 / **가상(하드웨어 없이 테스트)**
- 옵션: 폐루프 절대좌표, 사용자 간섭 시 정지(+정지/재개 초)
- [저장]/[불러오기] (JSON), 실행 로그 패널

가상 모드: 보드 없이 UI/시퀀스를 즉시 시험할 수 있고, 수신된 지령이 로그에 `[recv] …` 로 찍힌다.

검증(헤드리스 — 실제 실행 로직):
```
[시퀀스] 수신 동작 25개 (일부: screen, move_abs, move_abs, button, button, …)
```

## 확장 예 (결합)
```python
# 1) 새 명령 타입 추가
from control import protocol as P
server.register(0x50, lambda seq, payload: my_module.handle(payload))

# 2) 새 전송 결합 (예: 블루투스/웹소켓) — Transport 만 구현
class MyTransport(Transport):
    def send(self, data): ...
    def recv(self, timeout=None): ...
    def close(self): ...
ControlServer(MyTransport(), UinputBackend()).run()

# 3) 새 백엔드 (예: 커스텀 드라이버)
class MyBackend(HidBackend):
    def move_rel(self, dx, dy): ...
    def button(self, mask, action, hold_ms=0): ...
    def key(self, keycode, modifier=0, action=2, hold_ms=0): ...
    def key_text(self, s): ...
```

## 실행/검증
```bash
python -m control.demo        # 코덱·메모리·TCP 지연 실측 + API 동작 확인
```
