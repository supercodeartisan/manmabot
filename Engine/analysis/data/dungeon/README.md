# 10_5/dungeon — 던전 정본자료 (10_3_data = TMO.GG 기준)

실행파일이 아니라 **외부 정본(권위) 자료**를 규격화해 보관한다.
**원천: `10_3_data/`** (TMO.GG 리니지 클래식 맵 데이터: 포탈 618·맵 154·지역 49).

## 파일
| 파일 | 내용 |
|---|---|
| `dungeon.tsv` | **던전 정본 통합자료** (맵+지역+포탈, 기계용) |
| `floors_entrances.txt` | **던전 입구 · 층별 전환지점(계단 양끝 좌표)** (사람이 보기 쉬움) |
| `MANIFEST.txt` | 파일 해시 |

## 통합 스키마 (`dungeon.tsv`, 탭, 11열)
```
kind  map  mapName  x  y  x2  y2  id  type  note  src
```
| kind | 내용 | 좌표 | id/type/note |
|---|---|---|---|
| `map` | 맵 메타 | x,y=minX,minY · x2,y2=maxX,maxY | id=floor · type=is_dungeon · note=complex |
| `region` | 지역 | x,y=left,top · x2,y2=right,bottom | id=regionId · type=isDungeon · note=nameId |
| `portal` | 포탈 | **x,y=source_x,source_y · x2,y2=target_x,target_y** | id=portal_id · type=category · note=to:target_map;name;sf;tf |

- `portal` 의 `type`(category): `world-dungeon entry/exit`, `dungeon floor change`,
  `dungeon zone link (same floor)`, `dungeon passage link`, `dungeon internal teleport`,
  `world or building internal teleport`, `ship transport`, `building/interior`.

## `floors_entrances.txt` (읽기용)
- **[던전 입구]**: 월드↔던전 (source_map_name 좌표 → target_map_name 좌표). 30건.
- **[층별 전환지점]**: 던전 **층 사이 계단/통로의 양끝 좌표**.
  `A`=출발층 좌표, `B`=도착층 좌표. 178건(층변화), 던전(complex)별 묶음.
  ```
  ==== 개미굴 던전 ====
    개미굴 던전 1층  1F  A(32743,32779)  ->  개미굴 던전 2층  2F  B(32726,32744)
  ```
- **[같은층 구역간 링크]** 19건 · **[던전↔지하통로/타던전 연결]** 22건.

## 원칙 / 갱신
- 이 자료는 **정적** → 런타임 드라이버 읽기(signeddrv/MmCopy) 대상 **아님**. 실행파일 없음.
- 런타임에는 `map` 모듈이 읽는 **mapId/셀**을 키로 이 자료에서 좌표를 조회한다.
- 갱신: `10_3_data` 가 바뀌면 `tools/build_dungeon_tsv.py`·`tools/build_floors_entrances.py`
  → `tools/make_dungeon_data.ps1` 재실행.
- 단일출처: registry(SEC-11) `DUNGEON_TSV=10_5/dungeon/dungeon.tsv`.
