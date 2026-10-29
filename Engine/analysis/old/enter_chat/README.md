# enter_chat — PID 대상 혼합 텍스트 입력 모듈

`enter_chat`은 **PID로 지목한 프로세스**의 현재 포커스된 입력 컨트롤에
한글·중국어(간체/번체)·영문·기호가 섞인 텍스트를 입력하는 모듈입니다.

- 입력할 텍스트
- 대상 PID (또는 HWND)
- 초당 타이핑 속도(`cps`)
- 키 입력 간격에 주는 무작위 오차(`jitter`, ms)
- 마지막에 Enter를 칠지 여부

를 API/CLI로 넘기면, 대상 프로세스에 맞는 키 이벤트를 발생시킵니다.

> 이 모듈은 Lineage Classic처럼 **클립보드 붙여넣기를 막고 키보드 입력만 받는**
> 고무결성(High integrity) 게임 창을 위해 만들어졌습니다. 일반 Win32 앱에도
> 사용할 수 있습니다.

---

## 1. 빠른 사용법 (CLI)

빌드 결과물은 `enter_chat/bin/`에 생성됩니다.

### 일반 앱 (관리자 권한 불필요)

```bat
bin\enter_chat_cli.exe --pid 1234 --text "한글简体ABC!@#" --cps 12 --jitter 25 --enter
```

### 고무결성 대상 (게임 등, 관리자 권한 필요)

`enter_chat_cli_admin.exe`는 manifest에 `requireAdministrator`가 들어 있어
실행 시 UAC 승인을 받습니다.

```bat
bin\enter_chat_cli_admin.exe --pid 19708 --file chat.txt --cps 8 --jitter 30
```

- `--enter`를 주지 않으면 마지막 Enter를 치지 않습니다.
- 게임에서는 **채팅 입력창이 열려 있어야** 합니다.
  필요하면 `--esc --open`으로 현재 입력줄을 닫고 새 입력줄을 열 수 있습니다.

```bat
bin\enter_chat_cli_admin.exe --pid 19708 --file chat.txt --cps 8 --jitter 30 --esc --open
```

### 입력 내용 미리 확인 (실제 입력 없음)

```bat
bin\enter_chat_cli.exe --pid 19708 --file chat.txt --cps 8 --jitter 30 --dry-run --json
```

예시 출력:

```json
{"ok":true,"status":0,"pid":19708,"hwnd":"0x401FA","chars":15,"keys":22,"failed":0,"skipped":0,"enter":false,"elapsed_ms":0,"message":"dry-run: 15 chars, 22 key events"}
```

### 텍스트 지정 방법

| 옵션 | 설명 |
|---|---|
| `--text "..."` | 명령줄 문자열. `wmain`이 UTF-16으로 받으므로 콘솔 코드페이지와 무관합니다. |
| `--file <path>` | UTF-8 / UTF-16LE / UTF-16BE 파일. BOM을 자동 감지합니다. |
| `--stdin` | 표준입력 바이트. UTF-8/UTF-16 BOM 자동 감지. |

한글·중국어가 섞인 긴 문자열은 **UTF-8 파일 + `--file`**을 권장합니다.
(콘솔 리다이렉션·코드페이지 문제를 피할 수 있습니다.)

### CLI 옵션 전체

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--pid <n>` | — | 대상 프로세스 ID |
| `--hwnd <hex\|dec>` | — | 대상 창을 직접 지정 (선택) |
| `--cps <n>` | `10` | 초당 문자 수 |
| `--jitter <ms>` | `0` | 문자 간격에 더하는 무작위 오차 `±ms` |
| `--jamo-delay <ms>` | `8` | 한글 한 음절 내 자모 키 사이 간격 |
| `--enter` | 꺼짐 | 마지막에 Enter |
| `--esc` | 꺼짐 | 입력 전에 Esc (현재 입력줄 닫기/취소) |
| `--open` | 꺼짐 | 입력 전에 Enter (새 입력줄 열기) |
| `--no-focus` | 꺼짐 | 대상 창을 foreground로 가져오지 않음 |
| `--no-sendinput` | 꺼짐 | `WM_CHAR` 실패 시 SendInput fallback 비활성화 |
| `--no-start-commit` | 꺼짐 | 시작 시 IME 조합 flush용 Right-arrow 생략 |
| `--dry-run` | 꺼짐 | 실제 입력 없이 문자/키 개수만 계산 |
| `--json` | 꺼짐 | JSON 한 줄 출력 |
| `--help`, `-h` | — | 도움말 |

---

## 2. C API 사용법

### 헤더와 링크

```c
#include "enter_chat.h"
```

- DLL: `bin/enter_chat.dll`
- Import library: `bin/enter_chat.lib`
- 헤더: `include/enter_chat.h`

```bat
cl /Iinclude my_app.c /link bin\enter_chat.lib
```

호출 프로세스가 고무결성 대상에 입력하려면 **관리자 권한**으로 실행해야 합니다.
DLL은 스스로 권한을 올릴 수 없습니다.

### 기본 예제

```c
#include <windows.h>
#include <stdio.h>
#include "enter_chat.h"

int wmain(void)
{
    EcRequest req;
    EcResult  res;

    ZeroMemory(&req, sizeof(req));
    req.text             = L"#안녕하세요 简体team@#";
    req.pid              = 19708;          /* 대상 프로세스 */
    req.chars_per_second = 8.0;            /* 초당 8자 */
    req.jitter_ms        = 30;             /* ±30ms */
    req.press_enter      = FALSE;          /* 마지막 Enter 없음 */

    ZeroMemory(&res, sizeof(res));
    int rc = ec_run(&req, &res);

    wprintf(L"rc=%d status=%ls chars=%d keys=%d failed=%d\n",
            rc, ec_status_string(res.status),
            res.chars, res.keys, res.failed);
    if (res.message[0])
        wprintf(L"message: %ls\n", res.message);
    return rc;
}
```

### UTF-8 문자열로 호출

```c
EcResult res;
int rc = ec_run_utf8("#안녕하세요 简体team@#", 19708,
                     8.0, 30, FALSE, &res);
```

### 요청 구조체 (`EcRequest`)

| 필드 | 형 | 의미 | 기본값 |
|---|---|---|---|
| `text` | `const wchar_t*` | UTF-16, NUL 종료. 필수 | — |
| `pid` | `DWORD` | 대상 프로세스 ID | — |
| `hwnd` | `HWND` | 대상 창 직접 지정. `pid`와 함께 쓰면 PID 일치 검사 | `NULL` |
| `chars_per_second` | `double` | 초당 문자 수. `<=0`이면 10 | `10` |
| `jitter_ms` | `int` | 문자 간격에 더하는 무작위 오차 `±ms` | `0` |
| `jamo_delay_ms` | `int` | 한글 자모 키 사이 간격. `<=0`이면 8 | `8` |
| `press_enter` | `BOOL` | 마지막에 Enter | `FALSE` |
| `flags` | `DWORD` | 아래 플래그 조합 | `0` |
| `focus_timeout_ms` | `DWORD` | foreground 전환 대기. `0`이면 1500 | `1500` |

### 플래그 (`flags`)

| 플래그 | 의미 |
|---|---|
| `EC_FLAG_CLEAR_FIRST` | 입력 전에 Esc (현재 입력줄 닫기/취소) |
| `EC_FLAG_OPEN_CHAT` | 입력 전에 Enter (새 입력줄 열기) |
| `EC_FLAG_NO_FOCUS` | 대상 창을 foreground로 가져오지 않음 |
| `EC_FLAG_SENDINPUT_FALLBACK` | `WM_CHAR` 실패 시 `SendInput`으로 재시도 |
| `EC_FLAG_DRY_RUN` | 실제 입력 없이 계획만 계산 |
| `EC_FLAG_NO_START_COMMIT` | 시작 시 IME 조합 flush용 Right-arrow 생략 |

CLI는 `EC_FLAG_SENDINPUT_FALLBACK`을 기본으로 켭니다.
C API는 명시적으로 켜야 합니다.

### 결과 구조체 (`EcResult`)

| 필드 | 의미 |
|---|---|
| `status` | `EC_OK`(0) 또는 첫 번째 치명 오류 |
| `os_error` | 관련 Win32 오류 코드 |
| `pid`, `hwnd` | 실제 해석된 대상 |
| `chars` | 성공적으로 보낸 코드포인트 수 (dry-run은 계획 수) |
| `keys` | 텍스트 키 이벤트 수 (자모 키 + `WM_CHAR` 단위) |
| `failed` | 보내지 못한 코드포인트 수 |
| `skipped` | 건너뛴 제어문자 수 |
| `enter_pressed` | 마지막 Enter를 보냈는지 |
| `elapsed_ms` | 호출 소요 시간 |
| `message` | 경고/오류 설명 (UTF-16, 512자) |

`keys`는 Shift 보조키와 마지막 Enter를 세지 않습니다.
예: `#안녕하세요 简体team@#` = 15자, 22키.

### 상태 코드

| 코드 | 이름 | 의미 |
|---|---|---|
| 0 | `EC_OK` | 성공 |
| 1 | `EC_E_ARGUMENT` | 잘못된 인자 / 텍스트 없음 |
| 2 | `EC_E_PID` | PID에 사용할 창이 없음 / PID 불일치 |
| 3 | `EC_E_WINDOW` | 잘못된 HWND |
| 4 | `EC_E_ELEVATION` | 고무결성 대상 — 관리자 권한 필요 |
| 5 | `EC_E_INTERCEPTION` | Interception DLL/드라이버 없음 |
| 6 | `EC_E_IME` | 한국어 레이아웃/IME 준비 실패 |
| 7 | `EC_E_FOCUS` | 대상 foreground 전환 실패 |
| 8 | `EC_E_TEXT` | 일부 문자 전송 실패 |
| 9 | `EC_E_INTERNAL` | 내부 오류 |

`ec_run`의 반환값은 `(int)result->status`입니다.

### 부가 API

```c
const wchar_t* ec_version(void);                 /* L"1.0.0" */
const wchar_t* ec_status_string(EcStatus s);     /* 사람이 읽는 상태 문자열 */
BOOL ec_is_elevated(void);                       /* 현재 프로세스 권한 */
int ec_decompose_hangul(wchar_t ch,
                        char* keys, int max_keys); /* 2벌식 키열 */
```

`ec_decompose_hangul` 예:

```c
char keys[8];
int n = ec_decompose_hangul(L'안', keys, 8);  /* n=3, keys="dks" */
```

대문자는 Shift가 필요한 키입니다.

### 다른 언어/스크립트에서 호출

DLL 대신 CLI를 얇은 API로 사용할 수 있습니다. `--json`은 UTF-8 JSON 한 줄을
출력하므로 Python 등에서 그대로 파싱할 수 있습니다.

```python
import json, subprocess

req = {
    "pid": 19708,
    "text": "#안녕하세요 简体team@#",
    "cps": 8,
    "jitter": 30,
    "enter": False,
}

args = [
    r"E:\entity-naming-realtiming\enter_chat\bin\enter_chat_cli.exe",
    "--pid", str(req["pid"]),
    "--text", req["text"],
    "--cps", str(req["cps"]),
    "--jitter", str(req["jitter"]),
    "--json",
]
if req["enter"]:
    args.append("--enter")

cp = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
print(json.loads(cp.stdout))
```

- 고무결성 대상 자동화에서는 **Python 프로세스 자체를 관리자로 실행**하고
  `enter_chat_cli.exe`를 호출하는 편이 좋습니다.
  `enter_chat_cli_admin.exe`는 호출할 때마다 UAC를 띄우므로 수동 테스트용입니다.
- `--text` 대신 `--file`을 쓰면 콘솔/코드페이지 문제를 완전히 피할 수 있습니다.

---

## 3. 동작 원리 (간단)

### 3.1 문자 분류와 입력 경로

| 문자 | 경로 | 이유 |
|---|---|---|
| 한글 음절/자모 | Interception으로 2벌식 자모 스캔코드 전송 → 설치된 한국어 IME가 조합 | 게임이 `WM_CHAR`의 UTF-16을 시스템 ANSI 코드페이지(CP936)로 변환하면서 한글을 버리기 때문 |
| 중국어·영문·기호 | `PostMessage(WM_CHAR)` (필요 시 `SendInput` fallback) | 일반 텍스트 입력 경로. 게임도 `WM_CHAR`를 소비 |
| Tab / Esc / Enter | Interception 물리 키 | 게임/일반 앱 모두 키 이벤트로 처리 |
| `\n`, `\r` | 건너뜀 | 채팅 한 줄 입력에서 줄바꿈은 위험. 마지막 Enter는 `press_enter`로 제어 |
| 이모지(서로게이트) | UTF-16 단위로 `WM_CHAR` 2회 | 일반 앱은 처리 가능. 게임 클라이언트는 BMP만 지원할 수 있음 |

### 3.2 왜 한글만 Interception인가

Lineage Classic은 GLFW30 창으로 `WM_CHAR`를 받지만, 내부에서 UTF-16 문자를
시스템 ANSI 코드페이지로 변환합니다. 중국어 로케일 Windows에서는 이 값이
**CP936**이고, CP936에는 한글이 없습니다. 그래서:

- `안`, `녕`, `ㅇ`, `ㅏ` → 버려짐
- `简`, `体`, `テ`, `П`, ASCII → 통과

실제 주입 실험에서 `1안2|3ㅇㅏㄴ4|5テ6|7П8|9简0`을 보냈을 때 게임에는
`12|34|5テ6|7П8|9简0`만 남았습니다.

해결책은 사람이 한국어 키보드로 치는 것과 같은 경로입니다.

1. 한글 음절을 2벌식 자모 키로 분해
   (`안` → `dks`, `값` → `rkqt`, `뷁` → `qnpfr`)
2. Interception으로 물리 스캔코드 전송
3. 설치된 한국어 IME가 자모를 음절로 조합
4. 오른쪽 화살표(`E0 4D`)로 조합을 commit (문자 삽입 없이 확정)

### 3.3 PID → 창 → 포커스

1. PID의 visible top-level 창을 열거합니다.
   - foreground 창, 제목 유무, 창 면적을 점수화해 가장 적합한 창 선택
2. `GetGUIThreadInfo`로 실제 포커스된 자식 컨트롤을 찾습니다.
   - `WM_CHAR`는 이 자식 컨트롤로 보냅니다.
3. `AttachThreadInput` + `SetForegroundWindow`로 대상을 foreground로 가져옵니다.
   - Interception 스캔코드는 foreground 창으로 들어가기 때문입니다.
4. `focus_timeout_ms` 안에 전환되지 않으면 `EC_E_FOCUS`로 중단합니다.
   - 엉뚱한 창에 입력하는 것을 막기 위함입니다.

### 3.4 IME 모드

- 가능하면 `ImmGetContext(포커스된 자식 창)`으로 변환 모드를 조회하고,
  영문 모드이면 `IME_CMODE_NATIVE`(한글)로 설정합니다.
- 다른 프로세스라 `ImmGetContext`가 `NULL`이면,
  `ImmGetDefaultIMEWnd` + `WM_IME_CONTROL`(`IMC_GETCONVERSIONMODE` /
  `IMC_SETCONVERSIONMODE`)로 best-effort 전환합니다.
- 둘 다 실패하면 경고를 남기고, 사용자가 한국어 IME를 **`한` 모드**로
  두었을 것을 전제로 동작합니다.
- 호출이 끝나면 가능한 경우 이전 IME 모드/레이아웃을 복원합니다.

### 3.5 고무결성(UIPI)과 권한

- 대상이 현재 프로세스보다 높은 무결성(예: High)이면 `WM_CHAR`가
  `ERROR_ACCESS_DENIED`로 차단됩니다.
- 모듈은 창 프로브와 토큰 무결성 레벨을 함께 확인합니다.
- 텍스트에 `WM_CHAR`가 필요한 문자(한글 외)가 있고 권한이 부족하면,
  **입력을 시작하기 전에** `EC_E_ELEVATION`으로 중단합니다.
- 한글만 있는 텍스트는 Interception 경로만 쓰므로 권한 없이도 될 수 있지만,
  게임 대상은 관리자 실행을 권장합니다.

---

## 4. 타이핑 속도와 jitter 모델

```
문자 간격(ms) = 1000 / chars_per_second
실제 대기(ms) = 문자 간격 + random(-jitter_ms, +jitter_ms)
                (0 미만이면 0)
```

- `cps`는 **초당 문자 수**입니다.
- `jitter_ms`는 문자 사이 대기에 주는 **균등 무작위 오차**입니다.
- 한글 한 음절 내부의 자모 키 사이에는 `jamo_delay_ms`(기본 8ms)를 사용합니다.
  - IME가 각 자모를 소비할 시간을 주기 위함입니다.
  - 이 값은 `cps`와 무관합니다.
- 키를 누르고 있는 시간은 3ms 고정입니다.
- 정밀한 `Sleep`을 위해 호출 동안 `timeBeginPeriod(1)`을 사용합니다.

예: 15자, `cps=8`, `jitter=30` → 문자 간 기본 125ms + ±30ms.
여기에 한글 자모 지연이 더해져 대략 2초 안팎이 됩니다.

---

## 5. 파일 해설

```
enter_chat/
├─ include/
│  └─ enter_chat.h          공개 API: EcRequest/EcResult/상태/플래그/함수
├─ src/
│  ├─ ec_internal.h         내부 공용 구조체(EcContext)와 함수 선언
│  ├─ enter_chat.c          오케스트레이터: 검증→대상→권한→포커스→IME→텍스트→Enter
│  ├─ ec_target.c           PID→창 열거, 포커스 해석, foreground, UIPI/무결성
│  ├─ ec_keyboard.c         Interception 로딩, 스캔코드 주입, VK/ASCII 매핑
│  ├─ ec_hangul.c           한글 분해(2벌식), IME 모드/레이아웃 준비·복원, commit
│  └─ ec_text.c             UTF-8 변환, WM_CHAR/SendInput, sleep, RNG, jitter
├─ cli/
│  └─ enter_chat_cli.c      CLI 파서, 파일/stdin 텍스트 로딩, JSON 출력
├─ tests/
│  └─ test_hangul.c         한글 분해 단위 테스트 (입력 없음)
├─ examples/
│  ├─ call_enter_chat.c     C API 호출 예제
│  └─ build_example.bat     예제 빌드 스크립트
├─ build.bat                MSVC x64 빌드 (DLL + CLI 2종 + 테스트)
├─ registry.json            모듈 등록부 메타데이터
├─ README.md                이 문서
└─ bin/                     빌드 산출물
   ├─ enter_chat.dll
   ├─ enter_chat.lib
   ├─ enter_chat_cli.exe        asInvoker
   ├─ enter_chat_cli_admin.exe  requireAdministrator
   ├─ test_hangul.exe
   ├─ example_call.exe          (examples 빌드 시)
   └─ interception.dll          (있으면 복사)
```

### 각 소스의 역할

- **`include/enter_chat.h`**
  DLL 사용자와의 유일한 계약입니다. 구조체 크기/필드/플래그/상태 코드를
  바꾸면 ABI가 바뀌므로 버전을 올려야 합니다.

- **`src/enter_chat.c`**
  한 번의 호출 전체를 조율합니다.
  텍스트를 코드포인트 단위로 순회하고, 한글 run이 끝날 때 IME commit을 보냅니다.
  호출은 `CRITICAL_SECTION`으로 직렬화됩니다(동시 호출 금지).

- **`src/ec_target.c`**
  `EnumWindows`로 PID의 창을 찾고, 점수(foreground/제목/면적)로 주 창을 고릅니다.
  `GetGUIThreadInfo`로 포커스 자식 창을 찾고, `AttachThreadInput`으로
  foreground 전환 성공률을 높입니다.

- **`src/ec_keyboard.c`**
  `interception.dll`을 동적으로 로드합니다(호스트 exe 옆 → PATH 순).
  Interception stroke는 64바이트 버퍼로 구성해 DLL 버전 간 구조체 크기 차이를
  피합니다. `ec_send_vk`는 Interception → `PostMessage` → `SendInput` 순으로
  fallback합니다.

- **`src/ec_hangul.c`**
  유니코드 한글 음절을 L/V/T로 분해하고, 겹모음/겹받침을 구성 자모로 풉니다.
  2벌식 QWERTY 매핑(대문자=Shift)을 적용합니다.
  또한 한국어 레이아웃(0412) 전환, IME 모드 조회/설정, Right-arrow commit,
  종료 시 복원을 담당합니다.

- **`src/ec_text.c`**
  UTF-8→UTF-16 변환, `WM_CHAR`/`SendInput(KEYEVENTF_UNICODE)`, `Sleep`,
  xorshift 기반 로컬 RNG, `±jitter` 계산, 결과 메시지 append를 담당합니다.

- **`cli/enter_chat_cli.c`**
  `wmain`으로 UTF-16 명령줄을 받습니다. `--file`/`--stdin`은 BOM을 보고
  UTF-8/UTF-16LE/UTF-16BE를 해석합니다. 결과를 사람용 또는 JSON으로 출력합니다.

- **`tests/test_hangul.c`**
  키보드/IME 없이 분해 규칙만 검증합니다.
  `안녕하세요 → dkssudgktpdy`, `값 → rkqt`, `과 → rhk`, `의 → dml`,
  `ㅃㅆㅒㅖ → QTOP` 등.

- **`build.bat`**
  MSVC 2022 BuildTools x64로 DLL, CLI 2종, 테스트를 빌드하고
  `..\unitext\interception.dll`이 있으면 `bin`으로 복사합니다.

---

## 6. 빌드와 테스트

```bat
cd E:\entity-naming-realtiming\enter_chat
build.bat
```

성공 시 마지막에 `BUILD_OK`와 `TEST_OK`가 출력됩니다.

### 단위 테스트

```bat
bin\test_hangul.exe
```

### 입력 경로 테스트 (일반 앱)

`testpad.exe`는 붙여넣기를 막는 EDIT 컨트롤입니다.

```bat
start ..\unitext\testpad.exe 60
bin\enter_chat_cli.exe --pid <testpad_pid> --text "한글简体ABC!@#" --cps 20 --jitter 5 --enter
type ..\unitext\testpad_out.txt
```

검증 결과: `한글简体ABC!@#`가 정확히 입력되고 마지막 Enter도 동작했습니다.
(10자, 14키, 약 688ms)

### 게임 대상 확인

```bat
:: 채팅 입력창이 열려 있는 상태에서, Enter 없이 입력
bin\enter_chat_cli_admin.exe --pid 19708 --file ..\unitext\live_text.txt --cps 8 --jitter 30
```

`--esc --open`을 쓰면 현재 입력줄을 닫고 새 입력줄을 연 뒤 입력합니다.
게임에서는 **`--enter`를 주면 메시지가 전송**되므로 주의하세요.

---

## 7. 전제와 제약

### 전제

- **Interception 드라이버**가 설치되어 있어야 합니다.
- `interception.dll`이 실행 파일(`enter_chat_cli*.exe` 또는 DLL을 쓰는 호스트)과
  같은 디렉터리나 `PATH`에 있어야 합니다.
- 한글 입력에는 **한국어 키보드 레이아웃(0412)** 과 한국어 IME가 필요합니다.
- 고무결성 대상에는 **관리자 권한**으로 실행해야 합니다.
  (`enter_chat_cli_admin.exe` 사용)
- x64 빌드입니다. 대상/호스트 아키텍처와 맞춰야 합니다.

### 제약

- 호출은 **동기(blocking)** 이며 내부적으로 직렬화됩니다.
  여러 스레드에서 동시에 호출하지 마세요.
- 대상의 **채팅 입력창이 열려 있고 포커스**되어 있어야 합니다.
  필요하면 `EC_FLAG_OPEN_CHAT`/`--open`을 사용하세요.
- `--esc`/`EC_FLAG_CLEAR_FIRST`는 현재 입력줄을 닫거나 취소합니다.
  게임 상태에 따라 부작용이 있을 수 있으니 처음에는 수동으로 입력창을 연 뒤
  테스트하는 것을 권장합니다.
- `\n`, `\r`는 건너뜁니다. `\t`는 Tab 키로 보냅니다.
- 게임 클라이언트는 이모지(비BMP)를 지원하지 않을 수 있습니다.
- IME 모드 자동 전환은 **best-effort**입니다. `ImmGetContext`와
  `ImmGetDefaultIMEWnd`가 모두 실패하는 대상에서는 사용자가 IME를
  `한` 모드로 두어야 합니다.
- 대상이 고무결성이고 텍스트에 한글 외 문자(`WM_CHAR` 필요)가 있으면
  관리자 권한이 없을 때 입력을 시작하지 않고 `EC_E_ELEVATION`을 반환합니다.
- 마지막 Enter는 게임에서 **메시지 전송**입니다. `--enter`를 명시할 때만
  전송됩니다.

---

## 8. 검증 이력

- `test_hangul.exe`: `TEST_OK`
  - `안녕하세요 → dkssudgktpdy`
  - `가 → rk`, `각 → rkr`, `갂 → rkR`, `값 → rkqt`
  - `과 → rhk`, `의 → dml`, `한 → gks`, `글 → rmf`
  - `ㅇㅏㄴ → dks`, `ㅘ → hk`, `ㅄ → qt`, `ㄳ → rt`
  - `ㅃㅆㅒㅖ → QTOP`
- `testpad.exe` 실입력: `한글简体ABC!@#` + Enter → 정확히 일치
  - `chars=10`, `keys=14`, `failed=0`, `elapsed≈688ms`
- 게임 PID 19708 dry-run: `hwnd=0x401FA`, `chars=15`, `keys=22`,
  `failed=0`
- 게임 실입력 경로는 기존 `unitext --method korean`으로
  `#안녕하세요 简体team@#`가 정확히 들어가는 것을 확인한 경로와 동일합니다.
  (`enter_chat` 모듈 자체의 게임 실입력은 위 명령으로 최종 확인 가능)
- `--esc --open` 리셋 경로는 구현되어 있으나, 게임에서는 입력창 상태에 따라
  동작이 달라질 수 있으므로 처음에는 수동으로 입력창을 연 뒤 `--esc --open`
  없이 확인하는 것을 권장합니다.

---

## 9. 문제 해결

| 증상 | 확인 |
|---|---|
| `EC_E_INTERCEPTION` | Interception 드라이버 설치, `interception.dll` 위치 확인 |
| `EC_E_ELEVATION` | `enter_chat_cli_admin.exe`로 실행 (UAC 승인) |
| `EC_E_FOCUS` | 대상 창이 최소화/백그라운드인지 확인, `focus_timeout_ms` 증가 |
| `EC_E_IME` | 한국어 키보드 레이아웃 0412 설치 여부 확인 |
| 한글이 영문 자모로 입력됨 (`gksrmf`) | IME가 영문 모드. `한` 모드로 전환 후 재시도 |
| 중국어/기호만 들어감 | 한글 경로가 아니라 `WM_CHAR` 경로로 간 경우. 로그의 `EC_E_*` 확인 |
| 게임에 아무것도 안 들어감 | 채팅 입력창이 열려 있는지, 대상 PID가 맞는지 확인 |
| Enter가 메시지를 보냄 | `--enter`/`press_enter`를 제거 |

---

## 10. 라이선스/주의

이 모듈은 Interception 드라이버를 사용합니다. 드라이버 설치와 사용 권한은
사용 환경의 정책을 따릅니다. 게임 자동화에 사용할 경우 해당 게임의 이용약관을
확인하세요.
