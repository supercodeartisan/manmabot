# 바뀐 파일만 다시 릴리스

첫 고객 폴더는 `RELEASE_PLAYBOOK.md`의 Stage 1 → 2 → 3 → 5 → unpack → smoke → 4 이다.  
그 폴더(`release\portable\ManmabotV1`)가 생긴 뒤에는 이 문서만 쓴다. Stage 1은 그 폴더를 지우지 않고 멈춘다.

이미지 암호화는 하지 않는다. 고객 폴더의 `Engine\data`는 평문이다.

개발 트리의 로그인, 이동, 전투, HP 동작은 이 도구가 바꾸지 않는다. 하는 일은 이미 바뀐 소스를 고객 폴더에 반영하는 것이다.

## 명령

고객 폴더 루트에서:

```bat
python\python.exe packaging\incremental_release.py --dry-run
python\python.exe packaging\incremental_release.py
```

`--dry-run`은 무엇을 갱신할지 보여주고 폴더를 쓰지 않는다.  
인자 없이 실행하면 바뀐 파일만 반영하고, 마지막에 체크섬을 다시 계산한다.  
고객용 zip은 만들지 않는다. `release\portable\ManmabotV1`을 직접 압축한다.

`.py`가 바뀌어 컴파일이 필요하면 정식 CPython 3.14와 MSVC `cl`이 필요하다. `cl`이 PATH에 없으면 스크립트가 Visual Studio 2022 Build Tools의 `vcvars64.bat`로 한 번 다시 실행한다.

## 무엇을 비교하는가

`git diff`는 쓰지 않는다. 배포 대상 파일을 모두 해시한다.

| 종류 | 바뀌었을 때 |
|------|-------------|
| `.py` 모듈 | 그 파일만 Nuitka `.pyd`로 다시 컴파일 |
| `__init__.py`, `run.py`, `bot2.py` | `.py` 그대로 복사 |
| 맵 PNG, yaml, DLL, EXE, bat | 그 파일만 복사 |
| `Engine\analysis` 텍스트 | `analysis_text.pack`만 다시 만들고, 평문 텍스트는 고객 폴더에 두지 않음 |
| 묶인 `python\` | 크기나 수정 시각이 다르면 런타임만 다시 복사 |

`.gitignore` 때문에 diff에 안 나오는 png, dll, exe, bat도 이 검사에 들어간다. 해시가 같으면 건너뛰고, 다르면 릴리스 폴더를 갱신한다. 계획 출력에 `git-ignored`로 표시한다. 목록 전체는 `release\version-info\incremental-plan.txt`에 남는다.

기준 해시는 `release\version-info\INPUTS.json`이다. 아직 없으면 고객 폴더에 있는 파일 내용, 분석 팩, `.pyd` 시각과 소스를 직접 비교한다. 반영이 끝나면 Stage 4가 그 스냅샷을 다시 쓴다. 변경이 없고 스냅샷만 없으면 스냅샷만 기록한다.

체크섬은 실제로 파일을 넣은 뒤에만 다시 계산한다. 봇을 그 전에 실행하면 로그가 해시와 어긋난다.

고객 폴더의 `UserData`에 이 PC의 계정, 로그, 스케줄이 있으면 체크섬 전에 지운다. 개발 트리의 `UserData`는 그대로다. `defaults`만 남긴다.

## 전체를 다시 만드는 경우

- 고객 폴더가 없다.
- 폴더가 깨졌다.
- 컴파일 목록이나 제외 목록을 바꿨는데, 증분 반영만으로는 맞출 수 없다.

```bat
python\python.exe packaging\build_release.py --stage 1 --skip-python --no-checksums --force-full
```

그 다음은 플레이북의 Stage 2부터다. `--force-full`은 고객 폴더를 지운다.
