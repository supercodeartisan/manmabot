# 라즈베리파이 기반 마우스·건반 입력 시뮬레이션 — 구현 개요 및 평가

> Manmabot 프로젝트와의 결합 가능성·실현 방안·실측 요약:  
> 상위 문서 [`../MANMABOT_INTEGRATION.md`](../MANMABOT_INTEGRATION.md)

## 1. 무엇을 만들었나 (한 줄 요약)
**컴퓨터(제어 PC)가 보낸 지령을, 라즈베리파이(Pi SBC 또는 Pico)가 받아 "실제 USB HID
하드웨어"로 대상 컴퓨터에 마우스·키보드 입력을 주입**하는, 저지연·고결합 모듈 `control`.

```
[제어 PC]  UI/스크립트 ──(시리얼/TCP/UDP, 바이너리 프레임)──►  [라즈베리파이]
  ControlClient/Sequence                                    ControlServer ─► HidBackend
                                                              (Pico usb_hid / Pi uinput)
                                                                    │
                                                          실제 마우스·키보드 입력(HID)
                                                                    ▼
                                                              [대상 화면/앱]
```

## 2. 아키텍처 (3계층, 모두 교체 가능)
| 계층 | 인터페이스 | 구현 |
|---|---|---|
| 전송 Transport | `send/recv/close` | Memory, Serial, TCP, UDP |
| 백엔드 HidBackend | `move/button/wheel/key/text` | Null(테스트), Uinput(Linux/Pi), Pico usb_hid |
| 프로토콜 Codec | `encode/Frameparser` | 12B 헤더 + CRC16 |

## 3. 구성 파일
```
control/
├─ protocol.py        프레임/CRC/메시지 정의 (전 계층 공용)
├─ transport.py       Memory/Serial/TCP/UDP + list_serial_ports
├─ backend.py         HidBackend 인터페이스 + Null + AbsoluteTracker
├─ backends_linux.py  라즈베리파이 SBC용 uinput (상대/절대 EV_ABS)
├─ pi_server.py       라즈베리파이(리눅스) 실행 진입점 (TCP/시리얼)
├─ server.py          수신→디스패치→hold 예약(무블로킹)
├─ client.py          컴퓨터 측 전송 + 고수준 API + ping()
├─ feedback.py        1방안: 커서 위치 피드백 폐루프 + TargetAgent/RemoteCursor
├─ guard.py           사용자 간섭 감지 → 자동 일시정지/재개 + 키/버튼 자동 해제
├─ pointer.py         Windows 포인터 '가속' on/off (정확도)
├─ keys.py            키 이름/핫키 → HID usage
├─ sequence.py        시퀀스 스텝 실행 (UI/테스트 공용)
├─ ui.py              테스트 UI (한/중/영)
├─ i18n.py            다국어 문자열
├─ demo.py / test_input.py / samples/
└─ pico/  boot.py, main.py, abs_hid.py(절대 펜), boot_abs.py
```

## 4. 프로토콜 (저지연 바이너리)
- 고정 12 byte 헤더(magic/ver/type/seq/len/CRC16) + payload, 리틀엔디언
- 메시지: PING/PONG, MOUSE_ABS, MOUSE_REL, MOUSE_BTN, MOUSE_WHEEL,
  KEY, KEY_TEXT, TYPE(cps), SET_SCREEN, SYNC
- 안정성: CRC16 + 시퀀스 + magic 재동기화 / 결합성: 타입 추가 용이

## 5. 기능
### 마우스
- 상대 이동(±127 분할), **절대 이동**(폐루프 또는 절대 포인터), 클릭(좌/우/중), 더블클릭,
  **끌기(드래그)**, 휠, 버튼 down/up
### 건반
- 단일 키, **핫키(수정자+키)**, 문자열 입력(**건별 타이핑 속도 cps**)
### 정확도
- **폐루프 피드백**(실제 커서 위치 읽어 오차 보정) + **포인터 가속 OFF** → ±2px, 반복 일정
- 대안: 절대 HID 포인터(디지타이저/펜)
### 안전 / 충돌
- **사용자 마우스 간섭 감지 → 일시정지 → 멈춘 뒤 재개** (두 시간 사용자 설정)
- 정지 순간 눌린 키/버튼 자동 해제, hold 예약(블로킹 없음)
### 결합성
- Transport / HidBackend / 명령 핸들러 모두 주입·등록식, 클라이언트 API는 임의 파이프라인에서 호출

## 6. 지연시간 (실측)
| 구간 | 값 |
|---|---|
| 코덱 인코딩/디코딩 | ~2.9 / 3.0 µs per frame |
| 메모리 전송 RTT | avg 0.047 ms |
| TCP localhost RTT | avg 0.09 ms |
| USB HID 폴링(대상 PC) | ~1 ms |
| 지령→실행(로컬 USB) | 대략 수 ms 이내 |

## 7. 검증 결과 (실제 하드웨어 Pico 2)
- 마우스 이동/클릭/드래그/휠 ✅
- 건반 텍스트/키/핫키 ✅ (사용자 화면에서 `PICO-00~11` 실제 입력 확인)
- 정확도: `move_abs` 목표 ±2px, 재실행 시 반복 0회(정확) ✅
- 안정성: CRC 오류 프레임 자동 복구 ✅

## 8. 배포
- **Pico(CircuitPython)**: `boot.py`+`main.py`+`lib/adafruit_hid/`, 필요시 `abs_hid.py`.
  USB는 지령용 CDC(data) + HID(키보드/마우스). 하드리셋 시 boot.py 적용.
- **라즈베리파이 SBC(Linux)**: `sudo modprobe uinput`, `pip install evdev`,
  `python -m control.pi_server --tcp 9999` (또는 --serial).
- **제어 PC**: `python -m control.ui`


# Interception 드라이버 대비 기능 커버리지 (객관 평가)

## 9. Interception 드라이버의 핵심 기능
Windows 커널 **필터 드라이버**로, 입력 스택의 **드라이버 계층**에서:
1. **실제 입력 가로채기/관찰** (모든 키보드/마우스 이벤트를 OS 처리 전에 봄)
2. **실제 입력 차단/필터링** (특정 키/버튼을 막거나 변조)
3. **드라이버급 주입** (SendInput이 막히는 곳에서도 실제 하드웨어처럼 입력)
4. 저지연, 키보드+마우스, (모드에 따라) 장치별 구분

우리는 3번(주입)을 **물리 USB HID**로 수행합니다(드라이버보다 아래, 즉 더 "실물"에 가까움).
1·2번(관찰·차단)은 커널 드라이버가 필요해 **현재 구조로는 불가**.

## 10. 커버리지 표
| Interception 기능 | 우리 구현 | 커버리지 |
|---|---|---|
| 키보드 주입(키/수정자/핫키/텍스트) | ✅ | 100% |
| 마우스 주입(이동/버튼/클릭/끌기/휠) | ✅ | 100% |
| 절대·정밀 위치(±2px, 반복 일정) | ✅ | 100% |
| SendInput 차단 환경에서의 주입(실제 HID) | ✅ | 95% |
| 저지연 | ✅ | 100% |
| 키보드+마우스 동시 | ✅ | 100% |
| **실제 입력 관찰(키 입력 가로채기)** | ❌ (커서 이동만 간접 감지) | ~15% |
| **실제 입력 차단/변조** | ❌ | 0% |
| 장치별 입력 구분/관리 | ❌ | 0% |
| 보안 데스크톱/세션0 주입 | 부분 | ~50% |

## 11. 종합 평가
Interception을 "주입(inject) 50% + 가로채기/차단(intercept) 50%"로 보면:

- **주입 기능 커버리지: 약 95~100%** (물리 HID라 오히려 더 신뢰됨)
- **가로채기/차단 기능 커버리지: 약 0~15%** (커널 드라이버 없이는 원리적으로 불가)
- **단순 평균: 약 50~55%**
- **실사용(입력 주입 목적) 기준: 약 85~95%**

### 요약
- 목적이 **"입력 주입/자동화"** 라면 **약 90%** 수준(사실상 충분, Interception의 주입부와 동등 이상).
- **"실제 입력 감시/차단"** 까지 필요하면 **약 50%** 수준이며, 이 부분은:
  - 호스트 측 후킹(Raw Input / 저수준 훅)으로 **관찰**은 가능(차단은 제한적), 또는
  - 실제 Windows 커널 드라이버(Interception/WDK)를 별도로 개발해야 함.

## 12. 개선하면 커버리지를 올릴 수 있는 항목
| 추가 기능 | 방법 | 상승 |
|---|---|---|
| 실제 키/마우스 입력 **관찰** | 대상 PC에 소형 에이전트(Raw Input) | 가로채기 커버리지 +15~25% |
| 입력 **차단/변조** | 커널 드라이버(WDK) 필요 | +30% |
| 시퀀스 종료 시 **전체 해제(RESET)** | Pico/서버에 구현 | 안정성 ↑ |
| 지령 채널 **PING/PONG + 자동 재연결** | 프로토콜 확장 | 신뢰성 ↑ |
