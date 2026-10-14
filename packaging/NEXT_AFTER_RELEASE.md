# version2 — 릴리스 이후 논의 (아직 구현하지 않음)

version2 고객 폴더는 이미 만들어져 있다.

```
D:\completed\ManmabotV1_final_final_final_final_version2\release\portable\ManmabotV1
```

지금 배포 상태는 유지한다.

- 게임 로직은 `.pyd` (Nuitka `--module`, 컴파일이지 암호화가 아님)
- `Engine\data`는 평문 폴더. `data.pack`은 고객 폴더에 없다
- `Engine\analysis_text.pack`만 팩으로 남는다. 오프셋 텍스트는 실행 중에만 풀렸다가 정상 종료 때 지워진다
- 서명은 하지 않았다
- 릴리스 절차는 `packaging\RELEASE_PLAYBOOK.md`

아래는 그 배포를 고객에게 준 뒤에 검토할 일이다. 이 문서를 읽는 세션은 구현 요청이 있기 전에는 코드를 바꾸지 않는다.

로그인, 이동, 전투, HP 로직은 범위를 알리고 동의를 받기 전에는 수정하지 않는다. 라이브 mapId는 MapSubsystem 경로만 사용한다 (`mgr → holder → subs → MapSubsystem(vft) → +MapIdOff`).

---

## 1. 설치 exe 하나

고객이 zip 대신 설치 파일 하나만 실행하게 한다.

목표 순서:

1. 설치 프로그램이 관리자 권한으로 뜬다.
2. 지금 portable 폴더 내용물을 `C:\ManmabotV1`처럼 짧은 경로에 푼다. 경로가 길면 짧은 이름(`MANMAB~3`)과 긴 경로가 어긋난다.
3. 그 자리에서 Interception 설치를 실행한다. 지금 수동 진입은 `Driver_Install_Interception.bat` → `Drivers\install-interception.bat`이다.
4. 드라이버가 켜지려면 재부팅이 필요하다. 사용자가 재부팅을 고르게 하고, 설치 프로그램은 봇을 켜 두지 않는다.
5. 재부팅 후 봇 아이콘만 실행한다.

재부팅으로 없어지는 수동 단계는 Interception 설치뿐이다. 계정 입력, 권한 상승, SmartScreen, 다른 PC의 환경 문제(OpenCV 로딩, 원격 제어, 입력기)는 설치 파일이 지우지 못한다. “재부팅 후 아이콘만 누르면 설치는 끝”까지가 목표이고, “모든 PC에서 사냥까지 버그 없음”은 이 작업의 완료 조건이 아니다.

도구 후보는 Inno Setup이다. 아직 스크립트는 없다.

## 2. Interception을 설치 과정에 넣기

첫 PC에서는 사용자가 bat를 직접 실행해야 한다. 설치 직후, 재부팅 전에는 봇이 SendInput으로 동작한다. Interception은 재부팅 뒤에 켜진다.

자동 범위는 “설치 버튼 한 번에 드라이버 설치까지 끝나고, 재부팅만 확인받는 것”이다. 사용자 동의 없이 PC를 재부팅하지 않는다.

## 3. `Engine\data`를 다시 팩으로

맵 PNG, yaml, 카탈로그 json은 `data.pack`으로 묶고 메모리에서만 읽게 하는 코드가 이미 있다 (`asset_store.py`, `asset_pack.py`). 고객 폴더를 평문으로 둔 이유는 팩이 불가능해서가 아니다. 다른 PC에서 짧은 경로, 공유 폴더 경로, 컴파일된 로더 재귀 때문에 파일을 못 찾았고, 그 상태에서 평문으로 풀라고 했기 때문이다.

로더에는 그 세 가지 수정이 들어가 있다 (`RELEASE_BUGFIX_LOG.md`의 RBF-003, RBF-004, RBF-005). 다시 팩으로 갈 때는 고객 폴더에 `data.pack`만 두고 평문 `Engine\data`를 뺀 뒤, 짧은 경로와 가능하면 공유 경로에서 `skills_names.json`과 맵 `meta.yaml`이 열리는지 확인하고 배포한다. 그 확인 없이 다시 묶지 않는다.

## 4. `Engine\analysis`

텍스트(offsets json, txt, yaml, md)는 `analysis_text.pack`에 넣을 수 있다. 메모리 DLL은 `fopen`으로 디스크 경로를 열어야 하므로, 실행 중에만 그 텍스트를 썼다가 정상 종료 때 지운다. 프로세스를 죽이면 파일이 남을 수 있다.

DLL과 EXE는 메모리 팩에 넣을 수 없다. Windows `LoadLibrary`와 프로세스 실행은 실제 파일 경로가 필요하다. 고객 실행에 필요 없는 조사 파일(캡처 PNG, 실험용 EXE, ps1, bat, jsonl)은 팩이 아니라 배포 목록에서 뺀다. 런타임 DLL만 평문으로 남긴다.

## 5. 남아 있는 `.py`

반드시 스크립트로 남는 파일:

- `run.py`
- `launcher_manmabot.py`
- `Engine\autologin\bot\bot2.py` (로그인이 이 파일을 파이썬으로 직접 실행함)

`__init__.py`와 `Engine\session\__main__.py`는 패키지 인식용으로 남는다. Nuitka `--module`은 `__init__.py`를 컴파일하지 못한다. 이 파일에는 로직과 오프셋을 넣지 않는다.

컴파일 목록에 없어서 소스가 그대로인 파일은 실행에 필요하면 컴파일 목록에 넣고, 필요 없으면 배포에서 뺀다. version2 고객 폴더에서 보였던 예:

- `Engine\win32_prototypes.py`
- `Engine\analysis\combat_attack\` 아래 `.py`
- `Engine\scripts\classify_model\` 아래 `.py`
- `Engine\data\world\_build_map_transitions_draft.py`

`bot2.py`를 `.pyd`로 없애려면 로그인이 파일 실행 대신 모듈 import로 바뀌어야 한다. 그것은 로그인 동작 변경이라 동의 후에만 한다. `run.py`는 입구로 남기고, 로직은 `.pyd`로 옮기면 남은 스크립트는 짧은 시작 코드가 된다.

yaml과 json은 코드가 아니다. 맵과 카탈로그는 `data.pack`, 오프셋 텍스트는 `analysis_text.pack`으로 넣을 수 있다. 고객이 저장하는 스케줄 json은 `UserData`에 둔다.

## 6. UserData

고객 zip에 `UserData`를 넣을 필요가 없다. 시작 시 `ensure_userdata()`가 프로필, 로그, 스케줄, trial 폴더를 만든다. 빌드 PC의 `accounts.json`, 로그, 스케줄은 넣지 않는다. 계정은 그 Windows 사용자 DPAPI라서 다른 PC로 복사해도 풀리지 않는다.

## 7. 바뀐 파일만 다시 컴파일

파일마다 `.pyd` 하나이므로, 이전 `release\portable\ManmabotV1`을 지우지 않으면 고친 `.py`만 다시 컴파일할 수 있다. Stage 1은 그 폴더를 통째로 지우므로, 부분 컴파일과 함께 쓰면 안 된다.

순서는 이전 portable 유지, 바뀐 `.py`만 같은 경로에 덮어쓰기, 그 파일만 Nuitka, 데이터만 바뀌었으면 컴파일 생략, 마지막에 Stage 4로 체크섬 전체 갱신. git diff로 파일 목록을 골라 주는 기능은 아직 없다. `--stage 2 --packages session`은 그 패키지 전체이다.

전체를 다시 하는 경우: 첫 릴리스, `python` 구성 변경, 컴파일/제외 목록 변경, portable 폴더가 없을 때.

`.gitignore` 때문에 `*.png`, `*.dll`, `*.exe`, `*.bat`, `*.pyd`, `python\`, `UserData\`, `release\` 변경은 `git diff`에 나오지 않는다.

## 8. 아직 하지 않는 것

- Authenticode 서명
- 서버 라이선스
- “절대 역분석 불가”. `.pyd`는 컴파일된 기계어이고, 팩 열쇠는 프로그램 안에 있다. 목표는 폴더를 열었을 때 소스, 오프셋, 맵 json이 바로 보이지 않게 하는 것까지다.

## 9. 고객이 불만을 갖지 않게 하려면

패킹을 늘리기 전에, 이미 배포한 portable이 그 PC에서 시작, 로그인, 맵 로드까지 되는지 본다. 설치 exe와 `data.pack` 재적용은 그 확인 다음이다.
