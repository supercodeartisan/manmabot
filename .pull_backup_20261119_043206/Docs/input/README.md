# 외부 HID 입력 (Raspberry Pi Pico) — 문서 색인

Manmabot 농장 마우스·키보드를 **Interception 커널 주입** 대신  
**USB로 꽂힌 Pico가 내보내는 실물 HID**로 조종하는 경로의 정본 문서다.

| 문서 | 내용 |
|------|------|
| [`OVERVIEW.md`](OVERVIEW.md) | 아키텍처, Interception 대비, 엔진 호출 경로, 한계 |
| [`SETUP.md`](SETUP.md) | CircuitPython·펌웨어·`D:\Rasberrypi`·pyserial 환경구축 |
| [`MANMABOT_CONFIG.md`](MANMABOT_CONFIG.md) | 프로필/스케줄/환경변수로 `input_backend=pico` 켜기 |
| [`OPS_TROUBLESHOOTING.md`](OPS_TROUBLESHOOTING.md) | COM 선택, boot 재적용, 지연·휴머나이즈, 복구 |

## 외부 트리 (펌웨어·프로토콜 구현체)

컨트롤러 소스·펌웨어 정본은 Manmabot 밖:

```
D:\Rasberrypi\
├─ MANMABOT_INTEGRATION.md      # 결합 분석·실측 (상세)
├─ control\                     # PC 클라이언트 + Pico 펌웨어
│  ├─ README.md / OVERVIEW.md / AIM_LATENCY.md
│  └─ pico\  boot.py, main.py, abs_hid.py, …
└─ RasberryPi install board\    # CircuitPython UF2 설치기
```

엔진 쪽 어댑터: `Engine/app/_05_action/input_backend.py` (`PicoHidBackend`).

기본 백엔드는 여전히 **Interception**. Pico는 프로필에서 명시할 때만 사용한다.

변경 이력: `Docs/decision_change_log.md` (farm input backend, Pico move budget 30ms).
