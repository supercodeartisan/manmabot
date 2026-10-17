# Manmabot V1 — Release bugfix log

패키징/고객 빌드에 영향을 주는 버그를 고칠 때마다 **이 파일에 기록**합니다.  
다른 노트북에서 업데이트 소스를 빌드할 때 **수동 패치가 필요 없도록** 하는 것이 목적입니다.

규칙:

1. 수정은 가능하면 **개발 소스**에 넣는다 (`Engine/`, `UI/`, `packaging/`).  
2. `release/` 만 손으로 고치지 않는다. 다음 빌드(Stage 1→2→3→5→4)가 자동으로 포함해야 한다.  
3. 재발을 `verify_*.py` 로 잡을 수 있으면 검증을 추가한다.  
4. 이 로그에 ID / 증상 / 원인 / 수정 위치 / 검증 방법을 적는다.

---

## RBF-001 — Memory monitor disconnected after Stage 2 (2026-10-06)

### 증상

고객 portable 실행 → Start:

- `WinNotify is already running`
- `Reading player memory in this process (offsets.json)`
- 약 20초 후 `Memory wait timed out: Memory monitor disconnected`
- (괄호 없는) `Memory monitor disconnected`

### 원인

Stage 2가 `Engine/app/_01_perception/realtime_monitor_reader.py` 를 `.pyd`로 컴파일하고 `.py`를 삭제함.

그런데 `Engine/session/player_monitor.py` 가 **파일 경로로만** 로드했음:

```text
manmabot_root()/app/_01_perception/realtime_monitor_reader.py
```

`.py`가 없으면 `FileNotFoundError` → `open_monitor_from_config(..., quiet=True)` 가 삼킴 → 모니터 `None` → probe가 disconnected.

같은 패턴: `Engine/session/pipe_client.py` → `memory_client.py` 경로 로드.

### 수정 (소스에 포함됨 — 재빌드만 하면 됨)

| 파일 | 내용 |
|------|------|
| `Engine/session/player_monitor.py` | 먼저 `from app._01_perception import realtime_monitor_reader` 시도, 실패 시 `.py` 경로 폴백 |
| `Engine/session/pipe_client.py` | 먼저 `memory_client` 패키지 import, 실패 시 `.py` 경로 폴백 |
| `packaging/verify_stage2.py` | `session.player_monitor.reader_module()` 로드 검증 추가 |

### 이후 릴리스에서 할 일

**수동 작업 없음.** 업데이트 소스에 위 파일이 포함된 상태로:

```bat
python\python.exe packaging\build_release.py --stage 1 --skip-python --no-checksums
python\python.exe packaging\build_release.py --stage 2 --no-checksums
python\python.exe packaging\verify_stage2.py
```

`verify_stage2` 가 player monitor reader 로드에 실패하면 Stage 2를 통과시키지 말 것.

### 재발 방지 규칙

Stage 2 이후에도 동작해야 하는 코드는:

- `some_module.py` 경로로 `spec_from_file_location` 하지 말 것  
- 일반 import (`from app... import ...`) 를 쓸 것 (`.pyd`와 `.py` 모두 동작)

예외: `keep_scripts.txt` 에 명시된 스크립트 엔트리 (`run.py`, `bot2.py` 등).

---

## RBF-002 — Map editor blank + FlowLayout expandingDirections (2026-10-06)

### 증상

사냥터/맵 편집 창:

- 캔버스: `맵 이미지가 없습니다.`
- 하단 status: `Error calling Python override of QLayout::expandingDirections(): EnumType.__call__() missing 1 required positional argument: 'value'`

### 원인

`UI/ui_qt/widgets/flow_layout.py` 가 `return Qt.Orientations()` (인자 없음)를 반환.  
PySide6 + Python 3.14에서는 flag enum 생성에 `value`가 필요해서 오버라이드가 실패함.

맵 에디터가 `QTimer.singleShot`으로 `load_map`을 호출하는 동안 레이아웃이 돌면 예외가 `_load_pending_map`에 잡혀 status에 영문 에러가 찍히고, 이미지 적용/`canvas.update`가 끊길 수 있음.  
(`Engine/data.pack` 자체와는 무관 — 팩 해제는 정상.)

### 수정 (소스에 포함됨 — 재빌드만 하면 됨)

| 파일 | 내용 |
|------|------|
| `UI/ui_qt/widgets/flow_layout.py` | `return Qt.Orientations(0)` |

### 이후 릴리스에서 할 일

**수동 작업 없음.** Stage 1→2에 UI가 다시 컴파일되면 포함됨.

### 재발 방지 규칙

PySide6 flag/enum은 빈 괄호 `Enum()` 대신 `Enum(0)` / 명시 멤버를 쓴다.

---

## RBF-003 — Portable exe RecursionError at startup (2026-10-07)

### 증상

`bot_manmabotV1.exe` 시작 직후 `RecursionError: Stack overflow`.
스택: `run.py` `ensure_packed_assets` → `paths.manmabot_root` → `Path.is_dir` → `asset_store._os_isdir` → `_under` → `os.path.abspath` → `os.path.isdir` 반복.

### 원인

Python 3.14에서 `os.path.abspath`가 `os.path.isdir`를 호출한다. Stage 5 메모리 마운트가 `os.path.isdir`를 가로채므로 `_under`가 자기 자신을 다시 호출한다.

### 수정

`Engine/session/asset_store.py`: 경로 정규화는 `os.path.abspath`를 쓰지 않고 문자열 `normpath`만 사용. 훅 재진입은 `_BUSY`로 원본 `isdir`에 넘긴다.

이미 빌드된 포터블은 `asset_store.cp314-win_amd64.pyd`를 지우고 수정된 `asset_store.py`를 `Engine/session/`에 두면 된다. 다음 Stage 2는 수정된 소스를 다시 컴파일한다.

---

## RBF-004 — Start crashes: map meta not found on a short path (2026-10-07)

### 증상

다른 PC에서 시작을 누르면 봇이 멈춤.

`FileNotFoundError: Map pack meta not found: D:\MANMAB~3\Engine\data\maps\gludio_dungeon_F1\meta.yaml`

### 원인

맵은 `data.pack` 안에 있다. 설정 로더가 모듈 경로를 `os.path.abspath`로 붙여 `maps_dir`가 8.3 짧은 경로(`MANMAB~3`)가 된다. 메모리 마운트 루트는 긴 경로라서 같은 파일이 없는 것으로 보인다.

### 수정

`Engine/session/asset_store.py`가 `~`가 들어간 경로를 긴 경로로 펼친 뒤 팩과 비교한다.

---

## NOTE — Stage 5 sensitive asset packs (2026-10-06)

기능 추가(버그 아님). 맵 PNG·analysis 텍스트를 고객 폴더에서 평문으로 두지 않는다.

| 항목 | 내용 |
|------|------|
| 정책 | `packaging/SENSITIVE_ASSETS.md` |
| 빌드 | `packaging/pack_assets.py` / `build_release.py --stage 5` |
| 런타임 | `asset_store.py` RAM 마운트 + `asset_pack.py` 오프셋은 종료 시 삭제. `run.py` ensure |
| 검증 | `packaging/verify_stage5.py` |

재빌드만 하면 Stage 5가 팩을 만든다. 고객 zip은 그 다음 `unpack_customer_data.py`로 `Engine/data`를 복구하고 `data.pack`을 지운다. `analysis_text.pack`은 남긴다. 절차는 `RELEASE_PLAYBOOK.md`.

---

## RBF-005 — compiled asset store recurses; share paths miss the pack (2026-10-11)

### 증상

Stage 2가 `asset_store`를 `.pyd`로 만들면 시작 시 `os.path.isdir`이 다시 들어가 스택이 넘친다. 같은 소스를 `.py`로 두면 나지 않는다. 공유 폴더(`\\server\share`)나 매핑된 드라이브로 실행하면 `skills_names.json`을 디스크에서 찾다 실패한다. `~`가 없는 경로는 긴 경로로 펼치지 않았기 때문이다.

### 원인

Nuitka가 `os.path.isdir = hook` 이후에도 저장해 둔 원본 대신 바뀐 `os.path.isdir`을 호출한다. 공유 경로와 `\\?\` 경로는 문자열이 달라 팩 키와 맞지 않는다.

### 수정 (소스에 포함됨)

`_BUSY`는 리스트 칸으로 둔다. `os.path.isfile` / `isdir` / `exists` 훅은 기본 인자로 훅 설치 전의 함수를 붙잡는다. 존재하는 부모에 `GetFinalPathNameByHandleW`를 써서 8.3, `\\?\`, 매핑 드라이브를 같은 경로로 맞춘다.

### 이후 릴리스에서 할 일

소스를 복사한 뒤 Stage 2를 다시 돌린다. 포터블의 `asset_store.py`만 갈아끼우면 `.pyd`가 우선이라 수정이 적용되지 않는다.

### 재발 방지 규칙

컴파일되는 훅은 원본 함수를 기본 인자로 고정한다. 팩 경로 비교 전에 존재하는 부모의 최종 경로를 구한다.

---

## RBF-006 — Mainland region boundaries missing from the portable folder (2026-10-17)

### 증상

개발 트리에서는 사냥터 편집 창에 본토 지역 색이 보이는데, `release/portable/ManmabotV1` 에서는 지역 경계가 없다.

### 원인

`map4_boundaries.tsv` 는 제품 루트에만 있고 `root_files.txt` 에 없었다. 편집 캔버스는 `Engine/data/maps/<id>/nav.png` 를 쓴다. `images/real_maps` 는 없어도 된다.

### 수정 (소스에 포함됨)

| 파일 | 내용 |
|------|------|
| `packaging/manifests/root_files.txt` | `map4_boundaries.tsv` 를 고객 루트로 복사 |

### 이후 릴리스에서 할 일

**수동 작업 없음.** Stage 1 또는 `incremental_release.py` 가 경계 파일을 넣는다. `images/real_maps` 는 넣지 않는다.

### 재발 방지 규칙

편집기가 `<제품 루트>/map4_boundaries.tsv` 를 읽는다. 구역을 그리는 그림은 각 맵의 `nav.png` 이다.

---

## RBF-007 — Talking-scroll row click misses on another PC (2026-10-17)

### 증상

고객 PC에서 말하는 두루마리 목록은 열리고 휠도 동작하며 커서는 줄 위에 있다. 줄 클릭 뒤에도 캐릭터는 같은 좌표에 남는다. `v1.log`에 `talking scroll click screen=(67,204)` 가 찍힌 뒤 `scroll land timeout` 이 반복된다.

### 원인

그 PC에는 ChangZhi Virtual Mouse가 실제 마우스와 함께 잡혀 있었다. 사냥 클릭은 하드웨어 ID가 있는 마우스 중 마지막 장치로 나간다. 그 장치가 가짜 마우스여서 커서는 움직이고 버튼은 게임이 받지 않았다. Virtual Mouse를 끄면 사냥용 버튼 패킷으로 줄이 선택된다.

### 수정 (소스에 포함됨)

| 파일 | 내용 |
|------|------|
| `Engine/app/_05_action/controller.py` | 두루마리 줄이 다시 `move_and_click` |
| `Engine/app/_05_action/mouse.py` | 줄 전용 `win.interception.click` 제거 |

고객 폴더에는 아래 두 파일을 같이 넣는다. Virtual Mouse는 장치 관리자에서 끈 상태를 유지한다.

`Engine/app/_05_action/mouse.cp314-win_amd64.pyd`
`Engine/app/_05_action/controller.cp314-win_amd64.pyd`

### 이후 릴리스에서 할 일

`incremental_release.py` 가 `mouse.py` 와 `controller.py` 를 다시 컴파일한다. 이미 보낸 고객 폴더에는 아래 두 파일을 같이 교체한다.

`Engine/app/_05_action/mouse.cp314-win_amd64.pyd`
`Engine/app/_05_action/controller.cp314-win_amd64.pyd`

`.py` 원본은 고객 폴더에 넣지 않는다. `.pyd`가 우선이라 원본만 넣으면 수정이 적용되지 않는다.

### 재발 방지 규칙

두루마리 줄은 다른 게임 클릭과 같이 `MouseController.move_and_click` 을 쓴다. 마우스가 여러 개면 사냥 클릭은 마지막 장치로 나가므로, ChangZhi Virtual Mouse 같은 가짜 마우스를 끈다.

---

## (다음 항목)

형식:

```markdown
## RBF-00N — 짧은 제목 (YYYY-MM-DD)

### 증상
### 원인
### 수정 (소스에 포함됨)
### 이후 릴리스에서 할 일
### 재발 방지 규칙
```
