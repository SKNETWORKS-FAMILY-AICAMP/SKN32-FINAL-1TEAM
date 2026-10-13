"""계획서(planDoc)의 항목 문장 → 공식 양식(별첨1)의 글 칸 (SB-339).

SB-310 이후 계획서는 담당자 양식의 모든 항목을 항목 번호(예비창업자 2.1.1 ~ 2.7.4, 개인사업자 · 법인 3.1.1 ~ 3.7.4)로 담는다. 그 번호의
뒤 두 자리(`a.b`)가 별첨1 구조와 1:1로 맞는다 — 담당자 `section_mapping.json`의 입력 경로와 항목 제목(예: "산출물 목록(창업아이템명과
팀구성현황은 web에서 수령됨)")이 근거다.

    x.2.2                    산출물(일반현황)
    x.3.1                    아이템 개요(요약)
    x.3.2 · 3.3 · 3.4 · 3.5  요약 문제인식 · 실현가능성 · 성장전략 · 팀구성
    x.4.1                    1. 문제인식 본문
    x.5.1                    2. 실현가능성 본문   (x.5.2 개발계획 표 · x.5.3 · x.5.4 사업비 표의 서술은 아래 *_서술)
    x.6.1                    3. 성장전략 본문     (x.6.2 전체 일정 표의 서술은 성장전략_일정_서술)
    x.7.1 ~ x.7.4            4. 팀 구성 본문(대표자 역량 · 장비 · 채용 · 협력 역량)

x.1.*(2.1.1 ~ 2.1.6)은 x.2 · x.3이 "2.1.2에 작성한 …"으로 가져다 쓰는 초안이라 내려받기에는 쓰지 않는다. 창업아이템명 · 팀구성현황은 웹이 받은
값이라 여기서 다루지 않는다(builder가 웹 값을 쓴다). 표 자체는 웹에 저장된 입력 행으로 그린다(사용자 입력 그대로).

항목 번호 모양이 아닌 계획서(SB-310 이전 실행 건 · 스텁 Agent의 `1-1` ~ `4-1` 태그 4개)는 예전처럼 태그로 본문을 찾는다.
"""
import re
from dataclasses import dataclass

from app.orch.mapping import section_body

_ITEM_CODE_RE = re.compile(r'^\d\.(\d)\.(\d)$')
# F17(generate_table)이 표 항목의 글에 붙이는 서술 머리 줄 — 표를 글자로 옮긴 줄 다음에 온다
_NARRATIVE_HEADING_RE = re.compile(r'^(개발계획|사업비 집행계획) 서술:\s*$')
# F17이 단계를 모르는 원본 행을 서술 뒤에 JSON으로 덧붙이는 줄(단계별 합계에 들어가지 않는 진단용)
_UNASSIGNED_MARKER = '단계 미지정 원본'

TEAM_LABELS = {
    '7.1': '대표자 보유 역량',
    '7.2': '구매 후 보유 예정 장비 · 시설',
    '7.3': '추가 채용 시 보유 예정 역량',
    '7.4': '협력기관 협업 시 보유 예정 기술 · 역량',
}


@dataclass
class PlanTexts:
    """양식 글 칸에 들어갈 계획서 문장. 없는 칸은 None(builder가 웹 값이나 안내 문구로 채운다)."""

    by_item_number: bool = False       # 항목 번호 모양 계획서인가(False면 옛 태그 모양이거나 계획서 없음)
    산출물: str | None = None
    아이템_개요: str | None = None
    요약_문제인식: str | None = None
    요약_실현가능성: str | None = None
    요약_성장전략: str | None = None
    요약_팀구성: str | None = None
    문제인식_본문: str | None = None
    실현가능성_본문: str | None = None
    성장전략_본문: str | None = None
    팀구성_본문: str | None = None
    # 표 항목(개발계획 · 사업비 집행계획 · 전체 일정)의 서술 문장 — 표는 웹 행으로 그리고 서술만 여기서 온다
    실현가능성_일정_서술: str = ''
    사업비_서술: str = ''          # 예비창업자는 1단계 표의 서술(x.5.3), 그 밖은 사업비 표 하나의 서술
    사업비_2단계_서술: str = ''    # 예비창업자 2단계 표의 서술(x.5.4)
    성장전략_일정_서술: str = ''


def table_narrative(text: str) -> str:
    """표 항목의 글에서 서술만 꺼낸다 — 표를 글자로 옮긴 줄('구분 | 추진내용 | …')과 단계 미지정 원본 JSON은 뺀다.

    F17 글 모양: 표 머리줄 + 행들 → 빈 줄 → '개발계획 서술:'(또는 '사업비 집행계획 서술:') → 번호 문장들 → (있으면) '단계 미지정 원본 …'.
    서술 머리 줄이 없으면 표를 본문으로 대체한 글(그대로 둔다)이거나 표 글자뿐인 글(서술이 없으니 빈 글)이다."""
    lines = (text or '').splitlines()
    for i, line in enumerate(lines):
        if _NARRATIVE_HEADING_RE.match(line.strip()):
            narrative = []
            for rest in lines[i + 1:]:
                if rest.strip().startswith(_UNASSIGNED_MARKER):
                    break
                narrative.append(rest)
            return '\n'.join(narrative).strip()
    non_empty = [line for line in lines if line.strip()]
    if non_empty and all(' | ' in line for line in non_empty):
        return ''
    return (text or '').strip()


def _by_item_number(plan_doc) -> dict[str, str]:
    """항목 번호 뒤 두 자리('2.4' 같은 a.b가 아니라 x.a.b의 'a.b') → 그 항목의 문장."""
    texts: dict[str, str] = {}
    for section in plan_doc.sections:
        match = _ITEM_CODE_RE.match(section.section_code or '')
        if match:
            texts[f'{match.group(1)}.{match.group(2)}'] = section_body(section)
    return texts


def plan_texts(plan_doc, table_fallbacks=()) -> PlanTexts:
    """계획서(없으면 None) → 양식 글 칸. 항목 번호 모양이 아니면 옛 태그(1-1 ~ 3-1)로 읽는다.

    table_fallbacks: 표를 본문 서술로 바꾼 항목들(오케스트레이터 `Outputs.table_fallbacks`, 항목 번호 `section_code`). 웹은 표를 늘 사용자가
    입력한 행으로 그려서, 바꾼 항목의 서술('· 열: 값; …' 줄)은 그 표와 같은 내용이 되풀이될 뿐이라 문서에 쓰지 않는다."""
    if plan_doc is None:
        return PlanTexts()
    by_number = _by_item_number(plan_doc)
    if not by_number:
        legacy = {s.section_code: section_body(s) for s in plan_doc.sections}
        return PlanTexts(
            요약_문제인식=legacy.get('1-1') or None, 요약_실현가능성=legacy.get('2-1') or None, 요약_성장전략=legacy.get('3-1') or None,
            문제인식_본문=legacy.get('1-1') or None, 실현가능성_본문=legacy.get('2-1') or None, 성장전략_본문=legacy.get('3-1') or None)

    for fallback in table_fallbacks:  # 옛 계획서인지는 위에서 바꾸기 전 항목으로 이미 가렸다
        match = _ITEM_CODE_RE.match(getattr(fallback, 'section_code', '') or '')
        if match:
            by_number.pop(f'{match.group(1)}.{match.group(2)}', None)

    def get(number: str) -> str | None:
        return by_number.get(number) or None

    team = [f'[{label}]\n{by_number[number]}' for number, label in TEAM_LABELS.items() if by_number.get(number)]
    budget = table_narrative(by_number.get('5.3', ''))
    second = table_narrative(by_number.get('5.4', ''))  # 예비창업자만 2단계 사업비 항목(x.5.4)이 있다
    return PlanTexts(
        by_item_number=True, 산출물=get('2.2'), 아이템_개요=get('3.1'),
        요약_문제인식=get('3.2'), 요약_실현가능성=get('3.3'), 요약_성장전략=get('3.4'), 요약_팀구성=get('3.5'),
        문제인식_본문=get('4.1'), 실현가능성_본문=get('5.1'), 성장전략_본문=get('6.1'),
        팀구성_본문='\n'.join(team) or None,
        실현가능성_일정_서술=table_narrative(by_number.get('5.2', '')), 사업비_서술=budget, 사업비_2단계_서술=second,
        성장전략_일정_서술=table_narrative(by_number.get('6.2', '')))
