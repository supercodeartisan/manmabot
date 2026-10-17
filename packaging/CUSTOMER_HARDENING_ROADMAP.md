# Customer hardening roadmap (설계만 — 미구현)

작성: 2026-10-12  
상태: **문서만**. 구현은 별도 지시 시 진행.

이 문서는 배포 UX·리버스 난이도 논의를 모아 둔다.  
이미 적용된 keep-script / `__init__` 슬림화는 `RELEASE_PLAYBOOK.md` §2.6 과 `verify_shims.py` 를 본다.

---

## 0. 목표와 한계

| 목표 | 한계 (솔직히) |
|------|----------------|
| 고객이 bat을 일일이 안 눌러도 설치·실행 | 커널 드라이버는 UAC 필수 |
| 탐색기에서 소스·오프셋·맵을 바로 못 보게 | 실행 중 메모리 덤프 / `.pyd` 리버싱은 막지 못함 |
| UserData는 고객 PC에서 생성 | 계정 DPAPI는 PC 종속 |

**절대 불가 수준 보호는 목표가 아님.** “캐주얼 유출을 어렵게”가 목표.

---

## 1. Interception 설치 / 재부팅 정책

**현재:** 첫 환경에서 사용자가 `Driver_Install_Interception.bat` (또는 UI)로 수동 설치. 설치 후 재시작 권장.

**합의된 정책 (구현 시):**

```
Setup / 첫 실행
  → interception_ready()?
        YES → 설치 스킵, 재부팅 스킵
        NO  → install-interception /install → 재부팅만 예약
```

- “우리 봇 첫 설치” ≠ “Interception 첫 설치”
- 이미 ready면 **재설치·재시작 zero**
- 강제 재설치는 복구/고급 메뉴만

관련 코드(참고): `Engine/session/driver_setup.py` — `interception_ready`, `install_interception_driver`.

---

## 2. 단일 설치 EXE (Setup)

**골격:**

1. Inno Setup / NSIS / WiX 등으로 `release/portable/ManmabotV1` 압축 해제 (예: `C:\ManmabotV1`)
2. 관리자 UAC
3. §1 Interception 분기
4. 필요 시에만 재부팅
5. 바로가기 → `ZF.bat` / `ZF.exe`

**재부팅 후에도 100% 무인·무결점은 약속하지 않음** (게임 클라이언트, SmartScreen, AV, SignedDriver 차단, 계정 입력).

미결정: 설치 경로 기본값, 코드 서명, 재부팅 후 RunOnce 안내 여부.

---

## 3. `Engine/data` · `Engine/analysis` 팩

| 자산 | 지금 고객 zip | 다음 후보 |
|------|----------------|-----------|
| `Engine/data` | 평문 (Stage 5 팩 → unpack으로 복구) | **`data.pack` 유지**, unpack 배포 중단 (런타임 `ensure_packed_assets`) |
| analysis 텍스트 | `analysis_text.pack` | 유지·강화 |
| analysis DLL | 평문 (`LoadLibrary`) | 평문 유지 (팩 불가에 가깝음) |

참고: `SENSITIVE_ASSETS.md`, `session/asset_pack*.py`.

---

## 4. keep-script / `__init__.py` (일부 적용됨)

| 항목 | 상태 |
|------|------|
| `run.py` → `session/run_entry.py` | **적용** |
| `bot2.py` → `bot2_core.py` | **적용** |
| `launcher_manmabot.py` | 이미 얇음 (유지) |
| 두꺼운 `__init__.py` → `_public.py` / `fonts/loader.py` | **적용** (주요 패키지) |
| `verify_shims.py` + 플레이북 §2.6 | **적용** |

추가 후보 (나중에): 남은 두꺼운 `__init__`, `deny_globs`로 analysis/scripts 누수 `.py` 제거.

---

## 5. 남은 `.py` / yaml / json

- 번들 `python/Lib/*.py` — 제거 비현실적
- 제품 로직 `.py` — Stage 2 `.pyd` + deny
- yaml/json — 자산 팩 축 (`data.pack` / `analysis_text.pack`)
- UserData yaml/json — **평문 유지** (고객 편집)

---

## 6. UserData

- 고객 zip에 실계정/로그/이 PC trial **넣지 않음**
- `ensure_userdata()`가 실행 시 폴더 생성
- 빈 시드 폴더만 있어도 됨

---

## 7. 구현 우선순위 (제안)

1. Setup.exe + Interception ready 분기 (§1–2)  
2. 고객 zip에 `data.pack` 유지 / unpack 정책 변경 (§3)  
3. deny_globs로 배포 누수 `.py` 추가 정리 (§5)  
4. (선택) Authenticode 서명  

각각 착수 전에 영향 범위·검증 방법을 짧게 합의한다.
