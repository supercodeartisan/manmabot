# Manmabot에서 Pico 입력 켜기

전제: [`SETUP.md`](SETUP.md) 체크리스트 통과.

---

## 1. 설정 키 (정본)

| 키 | 타입 | 기본 | 의미 |
|----|------|------|------|
| `input_backend` | `"interception"` \| `"pico"` | `interception` | 농장 주입 경로 |
| `pico_com` | 문자열 | `""` | CDC **data** COM (빈 값이면 VID 2E8A·`x.2` 자동) |
| `pico_baud` | int | `115200` | 시리얼 보레이트 |
| `pico_control_root` | 경로 | `D:\Rasberrypi` | `import control` 상위 폴더 |

코드 정의:

- `Engine/settings/profile.py` — `Profile` 필드
- `Engine/settings/task_runtime.py` — `other` / 스케줄 반영
- `Engine/settings/schedule.py` — 스케줄 스냅샷
- `Engine/session/runtime_settings.py` — 런타임 `action` 섹션
- `Engine/app/_04_decision/configure.py` — `configure_input_backend(...)`

---

## 2. 프로필 / 스케줄 JSON

스케줄 설정은 보통:

`UserData/schedules/<schedule_id>/settings.json`

또는 시험용:

`UserData/trial/settings.json`

`other` (또는 프로필이 읽는 동등 섹션)에 예:

```json
{
  "other": {
    "input_backend": "pico",
    "pico_com": "COM5",
    "pico_baud": 115200,
    "pico_control_root": "D:\\Rasberrypi"
  }
}
```

`pico_com`을 비우면:

```json
"input_backend": "pico",
"pico_com": ""
```

엔진이 Raspberry Pi VID(`0x2E8A`) 중 hwid에 `x.2`가 있는 포트를 고른다.

Interception으로 되돌리기:

```json
"input_backend": "interception"
```

---

## 3. 환경변수 오버라이드 (디버그)

`configure_input_backend` / `PicoHidBackend`가 읽는다.

| 변수 | 효과 |
|------|------|
| `MANMABOT_INPUT_BACKEND` | `interception` 또는 `pico` (설정 파일보다 우선) |
| `MANMABOT_PICO_COM` | COM 포트 (프로필 `pico_com`이 비었을 때) |
| `MANMABOT_PICO_ROOT` | `control` 패키지 상위 경로 |

PowerShell 예:

```powershell
$env:MANMABOT_INPUT_BACKEND = "pico"
$env:MANMABOT_PICO_COM = "COM5"
$env:MANMABOT_PICO_ROOT = "D:\Rasberrypi"
```

세션을 끈 뒤 봇을 다시 시작한다.

---

## 4. 세션 시작 시 무엇이 일어나는지

1. 런타임이 `action` 설정에 `input_backend` 등을 넣는다.
2. `configure.configure_action` → `configure_input_backend(..., screen=GetSystemMetrics)`.
3. 마우스 `prepare_capture()`:
   - Pico: COM open → `set_screen` → `ensure_mode`(ABS) → `no_pointer_accel()`
   - Interception: 기존 장치 capture
4. 이후 이동/클릭/키/휠은 전부 `get_backend()` 경유.

준비 램프(드라이버 UI 쪽):

```python
from session.driver_setup import driver_readiness, pico_ready
pico_ready("COM5")
driver_readiness(input_backend="pico", pico_com="COM5")
```

`input_backend=pico`이면 Interception 설치 여부가 아니라 **Pico COM 존재**를 본다.

---

## 5. 어떤 입력이 Pico로 가고 / 안 가는지

| 경로 | Pico 적용 |
|------|-----------|
| 농장 `MouseController` 이동·클릭·홀드 | ✅ |
| 농장 `KeyboardController` press/hold/combo | ✅ |
| 상점·토킹 스크롤 (`shop/runtime`) | ✅ |
| 휴머나이즈 곡선 (`humanize_move`) | ✅ (예산 30 ms) |
| 오토로그인 `win.interception` | ❌ 아직 Interception |
| 의사결정·월드·지각 | 무관 (입력 계층만) |

---

## 6. 휴머나이즈 (Pico 전용 예산)

| 상수 | 값 | 파일 |
|------|-----|------|
| `MOVE_BUDGET_S` | 0.02 s | Interception |
| `MOVE_BUDGET_PICO_S` | **0.03 s** | Pico ABS 웨이포인트용 |

`MouseController._move_curved`가 `backend.name == "pico"`일 때 30 ms를 쓴다.  
ABS가 웨이포인트당 수 ms라 20 ms면 곡선이 일찍 스냅된다.

---

## 7. 권장 운용 순서

1. Interception으로 정상 사냥이 되는 스케줄을 확보한다.
2. Pico 스모크(`ping` / `move_abs_aim`) PASS.
3. 동일 스케줄에 `input_backend=pico` + 정확한 `pico_com`만 바꾼다.
4. 짧은 사냥 세션으로 조준·핫바·클릭 연타를 확인한다.
5. 문제 시 `input_backend=interception`으로 즉시 롤백.

비교 로그 도구(로컬): `Engine/logs/_compare_ix_pico.py`, `_compare_move_humanize.py`.

---

## 8. 의존성 재확인

```bat
python\python.exe -m pip show pyserial
dir D:\Rasberrypi\control\client.py
```

portable 빌드를 쓰면 release 트리의 `python\`에도 pyserial이 있어야 한다.
