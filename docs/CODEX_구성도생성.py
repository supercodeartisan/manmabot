"""Codex documentation artifact generator. Reads source; writes only CODEX_ docs.

Run with the bundled python from any directory. No game or input imports.
"""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'

def pair(a, b=None):
    return (a, b if b is not None else a)

PANELS = [
 ('system', '전체 구조', '화면·메모리 → 판단 → 입력 → 피드백',
  '한 틱의 의도는 하나지만 상점 의도에는 여러 키·클릭·대기가 포함됩니다. 세 모드는 같은 Blackboard를 공유합니다.', [
   (pair('게임 창·프레임·일시정지 정상?'), pair('아니오: 입력을 멈추고 대기'), '아니오', '예'),
   (pair('화면 / 플레이어 / 엔티티 갱신'), pair('가방 20초 간격 설정·핫바 주기 갱신'), '자료', '계속'),
   (pair('HP 0 또는 부활 대기?'), pair('사망 2초 확인 → 재시작 / 대기'), '예', '아니오'),
   (pair('레벨 상승 감지?'), pair('Esc 두 번으로 창 닫기'), '예', '아니오'),
   (pair('현재 모드가 후퇴?'), pair('후퇴 구성도: 회복 / 종료 / 안전 이동'), '예', '아니오'),
   (pair('현재 모드가 이동?'), pair('생존·보급 → 목적별 교전 → 이동'), '예', '아니오'),
   (pair('사냥 모드'), pair('일반 사냥 / 활성 던전 분기'), '실행', ''),
  ], '의도 실행 → 실제 클릭·상점 결과 반영 → 다음 프레임부터 다시 판단', 'system'),
 ('farm', '사냥 우선순위', '먼저 성립한 행동이 이번 틱을 사용',
  '일반 사냥 기준입니다. 던전은 초보·일반 사냥터 교대를 생략하고 마지막에 순찰합니다. 조건 불성립이면 아래로 내려갑니다.', [
   (pair('사망 / 레벨 상승 처리 필요?'), pair('부활·대기 또는 창 닫기'), '예', '아니오'),
   (pair('포위 10마리 조건 성립?', '긴급 카드 켜짐 + 포위 4마리 등?'), pair('랜덤 텔레포트 요청 / 추가 힐 예약'), '예', '아니오'),
   (pair('HP / 해독 / MP 물약 행동 가능?'), pair('HP 구성도의 첫 가능한 행동'), '예', '아니오'),
   (pair('별도 마법사 MP 후퇴?'), pair('V1 시작에서 비활성 / 엔진 경로는 존재'), '해당', '다음'),
   (pair('Fix/Return HP·MP 조건?'), pair('일반 귀환 → 후퇴 모드'), '예', '아니오'),
   (pair('비전투 54초 귀환?', '비전투 귀환 켜짐 + 60초?'), pair('일반 귀환 → 후퇴 모드'), '예', '아니오'),
   (pair('텔레포트 후 추가 힐 필요?'), pair('저장값 HP 40%까지', '엔진 기본 HP 50%까지'), '예', '아니오'),
   (pair('사용할 정기 버프 있음?'), pair('방어 → 빛 → 힘 / 슬롯·MP·시간 조건'), '예', '아니오'),
   (pair('갇힘 5칸 범위 / 13초?'), pair('전투 고정·상점은 차단 / 탈출 검토'), '예', '아니오'),
   (pair('레벨 5 미만?'), pair('공통 교전·루팅 먼저 → 훈련장 / 수색'), '예', '아니오'),
   (pair('부활 후 두루마리 예약?'), pair('말하는 섬 마법서 상인'), '예', '아니오'),
   (pair('상점 보급 / 판매 필요?'), pair('진행 중 여행 유지 → 신규 보급 선택'), '예', '아니오'),
   (pair('사냥터 교대 조건 성립?'), pair('구역별 3600초 / 기타 조건', '기본 600초 / 기타 옵션 켜졌을 때'), '예', '아니오'),
   (pair('상점 후 복귀 / 사냥 맵 복귀?'), pair('섬 텔레포터 / 기란 텔레포터'), '예', '아니오'),
   (pair('전투·루팅 행동 있음?'), pair('기존 대상 → 근접 위협 → 아이템'), '예', '아니오'),
   (pair('활성 사냥 구역 밖?'), pair('입구 이동: 도중 전투·루팅 가능'), '예', '아니오'),
  ], '수색: 5~7칸 이동 구간 → 다음 틱 최상위 조건부터 재검사', 'normal'),
 ('hp', 'HP 행동', 'HP가 낮아도 반드시 텔레포트하는 것은 아님',
  '저장값은 레벨 5 이상 요정 기준입니다. 기본값 버튼은 엔진의 기본 순서를 표시합니다. 모든 줄은 켜짐·슬롯·수량·마나 조건도 만족해야 합니다.', [
   (pair('중독 + 해독 자동 + 사용 가능?'), pair('해독제 사용 (저장 슬롯은 꺼짐)', '해독제 사용 (기본 자동 옵션 꺼짐)'), '예', '아니오'),
   (pair('0.5초에 HP 20%p 급락 + 위협?'), pair('아래 목록의 HP 문턱을 이번 검사에서 무시'), '예', '보통 HP'),
   (pair('HP ≤ 30% + 힐 가능?', 'HP ≤ 55% + 힐 가능?'), pair('힐 / MP ≤20% 또는 <5이면 불가'), '예', '아니오'),
   (pair('HP ≤ 30% + 빨간 물약 가능?', 'HP ≤ 30% + 요정 나무 가능?'), pair('빨간 물약: 실제 수량 >0 + 핫바', '나무 귀환 → HP·MP 충전 → 복귀'), '예', '아니오'),
   (pair('HP ≤ 30% + 텔레포트 가능?', 'HP ≤ 55% + 회복 아이템 가능?'), pair('후퇴 → 랜덤 이동 / 낮으면 안전지대로', '첫 사용 가능 회복 아이템 사용'), '예', '아니오'),
   (pair('HP ≤ 30% + 안전지대 가능?', 'HP ≤ 30% + 텔레포트 가능?'), pair('두루마리: 허수아비 수련장 / 없으면 도보', '후퇴 → 랜덤 이동 / 낮으면 안전지대로'), '예', '아니오'),
   (pair('HP ≤ 30% + 요정 나무 가능?', 'HP ≤ 30% + 안전지대 가능?'), pair('나무 귀환 → HP·MP 충전 → 마법서 상인', '두루마리: 허수아비 수련장 / 없으면 도보'), '예', '아니오'),
  ], '기타 활성 회복 아이템 / 안전지대 보완 / MP 물약 검사 → 다음 우선순위', 'hp'),
 ('shop', '보급·복귀', '필요 판정과 실제 구매 성공은 별개',
  '새 인벤토리가 들어올 때 수량 필요를 갱신합니다. 상점 여행 중에는 여러 탈출 경로가 차단됩니다. 구매량은 목표 재고가 아닌 추가 구매 입력값입니다.', [
   (pair('진행 중 상점 / 판매 대기열 있음?'), pair('기존 행동을 유지하고 다음 상점 연결'), '예', '아니오'),
   (pair('판매 켜짐 + 무게 ≥30%?', '판매 켜짐 + 무게 ≥85%?'), pair('섬 잡화 → 기란 무기 → 잡화 → 방어구'), '예', '아니오'),
   (pair('회복제 합계 ≤1개 + 억제 해제?', '회복제 합계 ≤20개 + 억제 해제?'), pair('기란 잡화: 3개 요청 / 재보급 억제 600초', '섬 잡화: 100개 요청 / 재보급 억제 600초'), '예', '아니오'),
   (pair('해독제 구매 켜짐 + 수량 ≤0?', '해독제 구매·귀환 켜짐 + 수량 ≤1?'), pair('저장 구매 꺼짐 / 켜면 기란 잡화 1개', '기본 구매 꺼짐 / 켜면 기란 잡화 1개'), '예', '아니오'),
   (pair('일반 화살 구매 켜짐 + ≤100개?', '일반 화살 구매 켜짐 + ≤300개?'), pair('섬 잡화: 100개 추가 구매 요청', '섬 잡화: 200개 추가 구매 요청'), '예', '아니오'),
   (pair('모든 필요 해소 + 복귀 예약?'), pair('현재 사냥 구역 밖 → 사냥 맵 텔레포터'), '예', '아니오'),
  ], '보급 필요 없음 → 교대 / 전투 / 루팅 / 사냥터 진입', 'shop'),
 ('combat', '전투·루팅', '살아 있는 기존 대상이 루팅보다 먼저',
  '여기에 도달하기 전 HP·귀환·보급 등이 먼저 실행될 수 있습니다. 표시된 거리와 초 단위는 서로 다른 타이머/조건입니다.', [
   (pair('기존 대상 살아 있고 유지 가능?'), pair('공격 유지 / 현재는 동일 대상 15초 포기', '공격 유지 / 기본 동일 대상 시간 포기 꺼짐'), '예', '아니오'),
   (pair('줍기 접근 중 5칸 / 그 외 3칸 위협?'), pair('루팅 취소 → 몬스터 교전'), '예', '아니오'),
   (pair('직전 집기 실패 + 공격할 적 있음?'), pair('몬스터를 우선 교전'), '예', '아니오'),
   (pair('집기 클릭 후 더미 남음 + 2초 미만?'), pair('메모리에서 사라지길 대기'), '예', '아니오'),
   (pair('허용된 바닥 아이템 있음?'), pair('접근 → 집기 / 무게 >70%면 아데나', '접근 → 집기 / 무게 >30%면 아데나'), '예', '아니오'),
   (pair('화면 안 새 공격 후보 있음?'), pair('가장 가까운 후보 / 같으면 작은 ID'), '예', '아니오'),
  ], '행동 없음 → 사냥터 진입 / 수색 / 이동 계속', 'normal'),
 ('retreat', '후퇴·회복', '회복 행동 문턱과 후퇴 종료선은 다름',
  '종료 판단은 예약된 이동보다 먼저입니다. 원인이 return이면 MP 귀환이어도 HP 종료선을 사용하므로 반복 전환 가능성을 별도로 검증해야 합니다.', [
   (pair('나무 여행 중?'), pair('나무 시전 → HP99%·MP90% → 두루마리'), '예', '아니오'),
   (pair('후퇴 원인이 mp인가?'), pair('MP ≥90%: 종료 / 미만: 아래 이동·회복'), '예', '아니오'),
   (pair('원인 mp가 아니고 HP ≥99%?'), pair('도착을 기다리지 않고 후퇴 종료'), '예', '아니오'),
   (pair('도착 + HP 미인식?'), pair('후퇴 종료 (목표 없음도 도착 취급)'), '예', '아니오'),
   (pair('활성 회복 가능: 도착 + HP ≥90%?'), pair('후퇴 종료 → 이전 이동 / 사냥 복귀'), '예', '아니오'),
   (pair('활성 회복 불가: HP ≥50%?'), pair('후퇴 종료 → 이전 이동 / 사냥 복귀'), '예', '아니오'),
   (pair('예약된 두루마리 / 텔레포트 있음?'), pair('예약 수행 / HP 안전지대는 훈련장'), '예', '아니오'),
   (pair('추가 힐·HP 보조·재탈출 가능?'), pair('각 문턱에서 실행 / 일반 HP 문턱 30%', '각 문턱에서 실행 / 기본 힐·물약 55%'), '예', '아니오'),
   (pair('공격 가능 적 없음 + 주울 것 있음?'), pair('후퇴 중에도 루팅 가능'), '예', '아니오'),
  ], '안전지대로 이동 / 긴급 재탈출 조건 / 자연회복 대기 → 다음 틱', 'retreat'),
 ('movement', '이동·막힘', '이동·전투·상점의 막힘 조건을 분리',
  '생존·보급 선행 검사는 생략한 상세도입니다. 화면 안 대상은 8칸보다 멀어도 클릭 가능하므로 전투 우회 조건에서 제외될 수 있습니다.', [
   (pair('상점 여행 중?'), pair('착지·상점 진행 / 막힘 텔레포트 차단'), '예', '아니오'),
   (pair('살아 있는 기존 공격 대상 유지?'), pair('공격 / 범위 밖 대상 5초 고정 시 2칸 우회'), '예', '아니오'),
   (pair('기준점 5칸 범위에서 13초?'), pair('갇힘 탈출: 텔레포트 → 불가 시 두루마리'), '예', '아니오'),
   (pair('이동·수색·루팅 같은 칸 5초?'), pair('주변 3칸 클릭 / 반복·소진 시 탈출 검토'), '예', '아니오'),
   (pair('사냥터 진입 경로를 못 찾음?'), pair('별도 5칸 우회 → 소진 시 탈출 검토'), '예', '아니오'),
   (pair('이동 목적지 도착?'), pair('목적별 도착 처리 → 사냥 / 다음 순찰'), '예', '아니오'),
  ], '일반 커서 확인 후 이동 클릭 → 실제 클릭 칸으로 목표 보정', 'normal'),
]

def text_at(x, y, value, cls='node-text'):
    a, b = value
    return f'<text class="{cls}" x="{x}" y="{y}" data-saved="{escape(a, quote=True)}" data-default="{escape(b, quote=True)}">{escape(a)}</text>'

def diagram(pid, title, rows, end, kind):
    h = 235 + len(rows)*116
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 {h}" role="img" aria-labelledby="{pid}-svg-title">',
         f'<title id="{pid}-svg-title">{escape(title)} — 판단은 아래 방향, 해당 분기는 오른쪽</title>',
         f'<defs><marker id="arrow-{pid}" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0 L9 4.5 L0 9z" fill="#63738a"/></marker></defs>']
    def line(d):
        return f'<path d="{d}" class="edge" marker-end="url(#arrow-{pid})"/>'
    s += ['<text x="300" y="25" class="hint" text-anchor="middle">위에서부터 검사 · 조건 불성립이면 아래로</text>',
          '<text x="840" y="25" class="hint" text-anchor="middle">해당 행동 · 실행 후 다음 틱</text>']
    for i, (condition, action, yes, no) in enumerate(rows):
        y = 50 + i*116
        s.append(f'<path class="condition" d="M65 {y+34} L90 {y} H510 L535 {y+34} L510 {y+68} H90 Z"/>')
        s.append(text_at(300, y+40, condition))
        s.append(f'<rect class="action" x="610" y="{y}" width="460" height="68" rx="6"/>')
        s.append(text_at(840, y+40, action))
        s.append(line(f'M535 {y+34} H605'))
        s.append(f'<text x="570" y="{y+23}" class="branch">{yes}</text>')
        if i+1 < len(rows):
            s.append(line(f'M300 {y+68} V{y+111}'))
            s.append(f'<text x="330" y="{y+96}" class="branch">{no}</text>')
        else:
            s.append(line(f'M300 {y+68} V{h-158}'))
        if kind == 'hp' and i == 1:
            s.append(line(f'M1070 {y+34} H1115 V{y+90} H540 L528 {y+125}'))
        elif kind == 'system' and i == 1:
            s.append(line(f'M1070 {y+34} H1115 V{y+90} H540 L528 {y+125}'))
        elif kind == 'retreat' and i == 1:
            s.append(f'<path d="M1070 {y+34} H1125" class="edge"/>')
            s.append(f'<text x="1095" y="{y+18}" class="branch">90%↑</text>')
            recovery_y = 50 + 6*116 + 34
            s.append(line(f'M840 {y+68} V{y+91} H1090 V{recovery_y} H1075'))
            s.append(f'<text x="980" y="{y+85}" class="branch">MP 90% 미만: HP 종료선 건너뜀</text>')
        else:
            s.append(f'<path d="M1070 {y+34} H1125" class="edge"/>')
    s.append(f'<rect class="action" x="65" y="{h-155}" width="1005" height="62" rx="6"/>')
    s.append(text_at(565, h-118, pair(end)))
    s.append(line(f'M565 {h-93} V{h-69}'))
    s.append(f'<path d="M1125 84 V{h-38} H1080" class="edge" marker-end="url(#arrow-{pid})"/>')
    s.append(f'<rect class="end" x="65" y="{h-65}" width="1005" height="55" rx="26"/>')
    s.append(text_at(565, h-31, pair('선택한 행동 실행 / 호출자 반환 → 피드백 반영 → 다음 틱 재검사')))
    s.append('</svg>')
    return ''.join(s)

def main():
    nav = ''.join(f'<button role="tab" aria-selected="{str(i==0).lower()}" aria-controls="{pid}" id="tab-{pid}" data-panel="{pid}">{i+1:02d} {escape(label)}</button>' for i,(pid,label,*_) in enumerate(PANELS))
    panels = ''
    for i,(pid,label,title,note,rows,end,kind) in enumerate(PANELS):
        extra = ''
        if pid == 'shop':
            extra = '<aside class="note">상점 내부: 근처면 정지→실행 · 멀면 두루마리→착지 대기 · 두루마리 불가/같은 맵이면 도보. 물약 아데나 계산은 52/개. 확인 클릭 완료를 성공으로 보고하며 수량 증가 검증은 별도입니다.</aside>'
        if pid == 'retreat':
            extra = '<aside class="note">원인이 mp이면 MP가 90% 미만인 동안 HP 종료 조건을 건너뛰고 예약 이동·회복 단계로 갑니다. 나무 전용 흐름과 사망 처리는 별도입니다. return 원인은 HP 종료 조건을 사용합니다.</aside>'
        panels += f'<section class="panel" id="{pid}" role="tabpanel" aria-labelledby="tab-{pid}" {"hidden" if i else ""}><h2>{escape(title)}</h2><p class="intro">{escape(note)}</p>{extra}<div class="diagram">{diagram(pid,title,rows,end,kind)}</div></section>'
    html = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>[CODEX] 전투로직 구성도</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:#17263a;font-family:'Malgun Gothic',system-ui,sans-serif;font-size:15px;line-height:1.65}header{padding:28px 36px 20px;background:#fff;border-bottom:1px solid #d7dfe9}h1{font-size:26px;margin:4px 0 8px}h2{font-size:22px;margin:0 0 10px}.eyebrow{font-size:12px;letter-spacing:1px;font-weight:700;color:#236a78}header p{margin:4px 0;max-width:1100px}.muted{color:#5b6b7e;font-size:13px}a{color:#176577}button,select,input{font:inherit}button{cursor:pointer}.controls{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding:16px 36px;background:#eaf0f5;border-bottom:1px solid #d7dfe9}.controls select,.controls button{padding:7px 12px;border:1px solid #abbacc;border-radius:4px;background:white;color:#17263a}.shell{display:grid;grid-template-columns:195px minmax(0,1fr);max-width:1580px;margin:auto}nav{padding:26px 12px;position:sticky;top:0;height:fit-content}nav button{display:block;width:100%;text-align:left;padding:12px 14px;border:0;border-left:3px solid transparent;background:transparent;color:#485b70;font-weight:600}nav button[aria-selected=true]{border-left-color:#217486;background:#e2eff1;color:#154e5a}main{min-width:0;padding:24px}.panel{background:#fff;padding:24px;border:1px solid #d7dfe9}.panel[hidden]{display:none}.intro{max-width:1040px;color:#4a5e74;margin:0 0 16px}.note{padding:12px 16px;border-left:3px solid #b77c22;background:#fff8e9;color:#59421e;font-size:14px;margin-bottom:20px}.diagram{overflow:auto}.diagram svg{display:block;width:100%;min-width:1000px;height:auto;font-family:'Malgun Gothic',sans-serif}.condition{fill:#f4f7fb;stroke:#9cabbc;stroke-width:1.4}.action{fill:#eaf4f5;stroke:#85acb5;stroke-width:1.4}.end{fill:#233e54;stroke:#233e54}.end+text{fill:white}.edge{stroke:#63738a;stroke-width:1.5;fill:none}.node-text{font-size:17px;text-anchor:middle;fill:#1c3045}.branch{font-size:13px;text-anchor:middle;fill:#55667a}.hint{font-size:14px;fill:#607188}footer{padding:16px 36px 32px;color:#61738a;font-size:13px}.legend{display:flex;gap:20px;flex-wrap:wrap;font-size:13px;margin-top:14px}.badge{display:inline-block;padding:2px 8px;background:#edf1f5;border-radius:3px}.status{font-weight:600;color:#175467}@media(max-width:800px){header{padding:20px}.controls{padding:14px 20px;gap:10px}.shell{display:block}nav{position:static;display:flex;overflow:auto;padding:10px}nav button{width:auto;white-space:nowrap}main{padding:10px}.panel{padding:16px}h1{font-size:23px}}@media print{body{background:white}nav,.controls{display:none}.shell{display:block}main{padding:0}.panel,.panel[hidden]{display:block!important;break-before:page;border:0;padding:10px}.diagram{overflow:visible}.diagram svg{min-width:0!important;width:100%!important;max-height:250mm}.intro,.note{font-size:10px}header{padding:12px}footer{padding:12px}}
    </style></head><body><header><div class="eyebrow">CODEX 작성 · 코드 분석 산출물 · 2026-09-28</div><h1>전투·귀환·보급 알고리듬 구성도</h1><p>조건을 위에서부터 읽고, 해당하면 오른쪽 행동으로 이동합니다. 오른쪽 바깥 선은 이번 판단의 종료/호출자 반환을 뜻하며 다음 틱에 최상위 조건부터 다시 검사합니다.</p><p class="muted">저장값은 userdata/profile.json의 분석 시점 값입니다. 실제 실행은 선택 프로필·스케줄·계정 locale·실시간 핫바에 따라 달라집니다.</p><div class="legend"><span class="badge">육각형: 검사/단계</span><span class="badge">청록 상자: 선택 행동</span><span class="badge">아래 어두운 상자: 다음 처리</span><a href="CODEX_전투로직설명서.md">한국어 설명서</a><a href="CODEX_분석근거.md">코드 근거·검증 결과</a></div></header><div class="controls"><label>수치 기준 <select id="preset"><option value="saved">저장된 프로필</option><option value="default">엔진 기본값</option></select></label><span class="status" id="status" aria-live="polite">요정 · HP 30% · 화살 100개 이하 → 100개 · 판매 30%</span><label>확대 <input id="zoom" type="range" min="80" max="160" value="100" step="10" aria-label="구성도 확대 비율"><output id="zoom-value">100%</output></label><button id="print">전체 인쇄 / PDF 저장</button></div><div class="shell"><nav role="tablist" aria-label="로직 구성도 선택">NAV</nav><main>PANELS</main></div><footer>실게임 동작 검증 전의 소스 분석입니다. 기존 관련 테스트: 168 통과 / 2 실패. 실패 내용은 분석근거 및 설명서 15절을 참조하세요. 외부 라이브러리·인터넷 연결 없이 열 수 있습니다.</footer><script>
    const tabs=[...document.querySelectorAll('[role=tab]')];
    function activate(tab){tabs.forEach(t=>t.setAttribute('aria-selected',String(t===tab)));document.querySelectorAll('.panel').forEach(p=>p.hidden=p.id!==tab.dataset.panel);}
    tabs.forEach((tab,i)=>{tab.addEventListener('click',()=>activate(tab));tab.addEventListener('keydown',e=>{if(e.key==='ArrowDown'||e.key==='ArrowRight'){e.preventDefault();const t=tabs[(i+1)%tabs.length];activate(t);t.focus();}if(e.key==='ArrowUp'||e.key==='ArrowLeft'){e.preventDefault();const t=tabs[(i+tabs.length-1)%tabs.length];activate(t);t.focus();}});});
    document.getElementById('preset').addEventListener('change',e=>{const k=e.target.value;document.querySelectorAll('[data-saved]').forEach(t=>t.textContent=t.dataset[k]);document.getElementById('status').textContent=k==='saved'?'요정 · HP 30% · 화살 100개 이하 → 100개 · 판매 30%':'기본 HP 힐 55% · 화살 300개 이하 → 200개 · 판매 85% · 옵션별 적용';});
    document.getElementById('zoom').addEventListener('input',e=>{document.querySelectorAll('.diagram svg').forEach(s=>s.style.width=e.target.value+'%');document.getElementById('zoom-value').textContent=e.target.value+'%';});
    document.getElementById('print').addEventListener('click',()=>window.print());
    </script></body></html>'''.replace('NAV',nav).replace('PANELS',panels)
    (OUT/'CODEX_전투로직구성도.html').write_text(html, encoding='utf-8')
    print('Created HTML: 7 diagrams; offline SVG; 2 presets')

if __name__ == '__main__':
    main()
