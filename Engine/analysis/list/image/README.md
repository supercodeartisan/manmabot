# 리니지 클래식 2026 이미지 (NC 공식 사이트 내려적재)

리스트(몬스터·아이템·마법)에 대응되는 **공식 이미지를 전부 내려적재**한 폴더입니다.
NC 공식 CDN(`assets.playnccdn.com`)의 원본 PNG를 그대로 저장했습니다.

- **기준일**: 2026-09-24
- **총 파일**: **1,021개** (약 7.5 MiB)
- **파일명 규칙**: `{이름}_{id}.png` — **이름이 파일과 대응**되도록 했습니다.
  (이름은 한국어 우선, 한국어가 없으면 중국어 번체)

## 폴더 구조

```
이미지/
  몬스터/   343개   NPCIcon   (예: 오크_0.png, 얼음_여왕_723.png)
  아이템/   568개   ItemIcon  (예: 장검_3.png, 빨간_물약_14.png)
  마법/     110개   SpellIcon (예: 힐_0.png, 파이어볼_24.png)
  이미지_목록.csv    명칭(한/번체/간체) ↔ 파일명 ↔ 원본 URL 대응표
  이미지_검증.txt    검증 결과
  README.md
```

## 이미지_목록.csv

| 열 | 설명 |
| --- | --- |
| `category` | monster / item / spell |
| `id` | 공식 id |
| `korean` | 한국어 명칭 |
| `chinese_tw` | 중국어 번체 명칭 |
| `chinese_cn` | 중국어 간체 명칭 |
| `filename` | 저장된 파일명(`{이름}_{id}.png`) |
| `url` | NC 공식 원본 이미지 URL |

## 원본 출처

| 부문 | 원본 URL 패턴 |
| --- | --- |
| 몬스터 | `https://assets.playnccdn.com/static-lineageclassic-gamedata/resources/NPCIcon/{n}.png` |
| 아이템 | `https://assets.playnccdn.com/static-lineageclassic-gamedata/resources/ItemIcon/{n}.png` |
| 마법 | `https://assets.playnccdn.com/static-lineageclassic-gamedata/resources/SpellIcon/{n}.png` |

## 검증 결과 (`이미지_검증.txt`)

| 폴더 | 대상 | 적재 | 누락 | 손상 | 크기 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 몬스터 | 343 | 343 | 0 | 0 | 3,274,089 B |
| 아이템 | 568 | 568 | 0 | 0 | 3,462,991 B |
| 마법 | 110 | 110 | 0 | 0 | 1,151,770 B |
| **합계** | **1,021** | **1,021** | **0** | **0** | **7,888,850 B** |

- 모든 파일이 정상 PNG(시그니처 검증)이며, 대응 리스트의 **누락 0건**입니다.
- 고유 이미지 URL은 893개이고, 54개 URL은 여러 항목이 공유합니다(예: 여러 아이템이 같은 아이콘 사용).
  이 경우에도 **이름별로 각각 파일을 저장**했습니다(중복 허용, 총 1,021파일).

## DB 연계

`DB\lineage_classic_2026.db` 의 `combined.image` 열에 각 항목의 이미지 파일명이 들어 있어
**명칭 ↔ 이미지 파일**을 바로 연결할 수 있습니다.
