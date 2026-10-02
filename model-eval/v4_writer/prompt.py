"""작성 Agent T-W1(본문)·T-W2(그래프)·T-W3(표) 시험 프롬프트와 출력 스키마. 모든 후보에 같은 것을 쓴다.

실제 팀 프롬프트가 아니라 이 실험용 기준선이다. 규칙은 기능정의서 v1.9 시트 2의 T-W1·T-W2·T-W3 정의에서 옮겼다.
T-W1 결과의 글 품질은 검증-1 채점자(luna-medium)로 따로 잰다(v1_verifier.prompt 재사용).
"""
from __future__ import annotations

import json
from pathlib import Path

PROMPT_VERSION = 'v4-writer-baseline'
FIXTURES = Path(__file__).resolve().parent.parent / 'fixtures'

W1_SYSTEM = """당신은 정부지원사업 사업계획서 서비스의 작성 Agent다. 지금 할 일은 '사업계획서 본문 작성'이다.
공고 양식의 필수 항목마다 섹션을 하나씩 써서 사업계획서 본문을 만든다.

규칙:
- 양식의 필수 항목 코드마다 섹션을 정확히 하나씩 쓴다(누락·중복·추가 금지). section_code와 title은 양식 그대로 쓴다.
- 문체는 공공 제출 문서 형식을 따른다: 개조식, 단정형 종결(예: "~함", "~임", "~할 계획임"). "~한다", "~합니다"로 끝내지 않는다.
  금지 표현은 쓰지 않는다. 분량 제한이 있으면 섹션마다 그 글자 수 이내로 쓴다.
- 입력에 없는 경력·수치·회사를 지어내지 않는다. 대표자·팀 경력과 수익모델 단가는 회사 정보에 적힌 것만 쓴다.
- 시장 규모 등 수치는 시장 분석 결과에 출처와 함께 주어진 것만 인용하고, 출처를 밝힌다.
- 자금 운용 계획의 금액 합계는 공고의 지원규모 상한을 넘지 않는다.
- feature_list에는 요구사항 분석의 기준 기능 목록을 글자 그대로 옮긴다(추가·삭제·수정 금지). 본문에서 각 기능을 빠짐없이 설명한다.
- 표와 그래프는 다른 Task가 만든다. 본문에 표나 그래프를 직접 그리지 않는다."""

W2_SYSTEM = """당신은 정부지원사업 사업계획서 서비스의 작성 Agent다. 지금 할 일은 '그래프 생성'이다.
사업계획서 본문과 시장 분석 결과를 읽고, 본문의 수치를 시각화하는 그래프 사양(ChartSpec)을 만든다.

규칙:
- series의 value는 본문 또는 시장 분석에 적힌 수치를 단위 환산 없이 숫자 그대로 쓴다. 본문에 없는 수치를 만들지 않는다.
- 그래프마다 type(bar, line, pie 중 하나), title, axis_labels(가로축 이름, 세로축 이름), series, source_ref(근거가 된 섹션 코드)를 채운다.
- 단위가 다른 수치(예: 곳과 %)를 한 그래프에 섞지 않는다.
- 데이터가 부족해 그래프를 만들 수 없으면 charts를 빈 배열로 둔다."""

W3_SYSTEM = """당신은 정부지원사업 사업계획서 서비스의 작성 Agent다. 지금 할 일은 '표 생성'이다.
사업계획서 본문, 회사 정보, 공고를 읽고 필요한 표(TableSpec)를 만든다. 필요한 표는 '자금 운용표'와 '추진 일정표'다.

규칙:
- 각 행의 칸 수는 headers의 칸 수와 같아야 한다.
- 자금 운용표의 금액은 본문에 적힌 것만 쓰고, 합계 행을 넣는다면 항목 금액의 합과 같아야 한다. 합계는 공고의 지원규모 상한을 넘지 않는다.
- 금액 칸은 '45,000,000원'처럼 숫자와 단위를 함께 쓴다.
- 본문에 없는 수치를 만들지 않는다. source_ref에는 근거가 된 섹션 코드를 쓴다."""


def load_cases() -> dict[str, dict]:
    doc = json.loads((FIXTURES / 'writer_cases.json').read_text(encoding='utf-8'))
    return {c['case_id']: c for c in doc['cases']}


def announcement_text(case: dict) -> str:
    rubric = json.loads((FIXTURES / 'rubric.json').read_text(encoding='utf-8'))
    ann = rubric['announcement']
    names = ' / '.join(it['item_name'] for it in rubric['items'])
    a = case['announcement']
    return '\n'.join(['[선택된 공고] %s (%s)' % (ann['title'], ann['agency']), ann['summary'], '평가항목: ' + names,
                      '접수 마감일: ' + a['apply_end'], '지원규모 상한: {:,}원'.format(a['support_amount_max'])])


def company_text(case: dict) -> str:
    c = case['company']
    return '\n'.join(['[회사 정보]', '대표자 경력: ' + ', '.join(c['representative_career']), '팀 경력: ' + ', '.join(c['team_careers']),
                      '수익모델 단가(원): {:,}'.format(c['revenue_unit_price']), '개발 기간: ' + c['development_period']])


def market_text(case: dict) -> str:
    lines = ['[시장 분석 결과] 시장 정의: %s의 목표 시장' % case['item_spec']['item_name']]
    for f in case['facts']:
        lines.append('- %s: %s (출처: %s)' % (f['label'], f['display'], f['source']))
    lines.append('경쟁 현황: 수기 관리와 기존 대체 방식')
    lines.append('포지셔닝: ' + case['differentiator'])
    return '\n'.join(lines)


def item_text(case: dict) -> str:
    s = case['item_spec']
    return '\n'.join(['[요구사항 분석]', '아이템: %s — %s' % (s['item_name'], s['one_line_summary']), '목표 고객: ' + s['target_customer'],
                      '기준 기능 목록: ' + ' | '.join(s['core_features']), '차별점: ' + case['differentiator']])


def form_text(case: dict) -> str:
    f = case['form']
    lines = ['[양식] 필수 항목(코드: 제목):'] + ['- %s: %s' % (s['code'], s['title']) for s in f['sections']]
    fm = f['format']
    lines.append('서술 형식: %s, 종결 %s, 금지 표현: %s' % (fm['style_type'], fm['ending_rule'], ', '.join(fm['banned_expressions'])))
    lines.append('섹션당 분량 제한: ' + ('%d자 이내' % f['max_chars_per_section'] if f['max_chars_per_section'] else '없음'))
    return '\n'.join(lines)


def doc_text(sections: list[dict]) -> str:
    return '\n'.join('[%s] %s\n%s' % (s['section_code'], s['title'], s['text']) for s in sections)


def build_w1(case: dict) -> list[dict]:
    user = '\n\n'.join([announcement_text(case), form_text(case), item_text(case), market_text(case), company_text(case),
                        '[지시문] 위 양식의 필수 항목마다 섹션을 작성하라.'])
    return [{'role': 'system', 'content': W1_SYSTEM}, {'role': 'user', 'content': user}]


def build_w2(case: dict) -> list[dict]:
    user = '\n\n'.join(['[사업계획서 본문]\n' + doc_text(case['fixed_doc']), market_text(case), '[지시문] 본문의 수치를 시각화하는 그래프를 만들어라.'])
    return [{'role': 'system', 'content': W2_SYSTEM}, {'role': 'user', 'content': user}]


def build_w3(case: dict) -> list[dict]:
    user = '\n\n'.join(['[사업계획서 본문]\n' + doc_text(case['fixed_doc']), company_text(case), announcement_text(case),
                        '[지시문] 자금 운용표와 추진 일정표를 만들어라.'])
    return [{'role': 'system', 'content': W3_SYSTEM}, {'role': 'user', 'content': user}]


def w1_schema() -> dict:
    return {'name': 'plan_doc', 'strict': True, 'schema': {
        'type': 'object', 'additionalProperties': False, 'required': ['sections', 'feature_list'],
        'properties': {
            'sections': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False, 'required': ['section_code', 'title', 'text'],
                'properties': {'section_code': {'type': 'string'}, 'title': {'type': 'string'}, 'text': {'type': 'string'}}}},
            'feature_list': {'type': 'array', 'items': {'type': 'string'}}}}}


def w2_schema() -> dict:
    point = {'type': 'object', 'additionalProperties': False, 'required': ['label', 'value'],
             'properties': {'label': {'type': 'string'}, 'value': {'type': 'number'}}}
    chart = {'type': 'object', 'additionalProperties': False,
             'required': ['chart_id', 'type', 'title', 'axis_labels', 'series', 'source_ref'],
             'properties': {'chart_id': {'type': 'string'}, 'type': {'type': 'string', 'enum': ['bar', 'line', 'pie']},
                            'title': {'type': 'string'}, 'axis_labels': {'type': 'array', 'items': {'type': 'string'}},
                            'series': {'type': 'array', 'items': point}, 'source_ref': {'type': 'string'}}}
    return {'name': 'charts', 'strict': True, 'schema': {
        'type': 'object', 'additionalProperties': False, 'required': ['charts'], 'properties': {'charts': {'type': 'array', 'items': chart}}}}


def w3_schema() -> dict:
    table = {'type': 'object', 'additionalProperties': False, 'required': ['table_id', 'title', 'headers', 'rows', 'source_ref'],
             'properties': {'table_id': {'type': 'string'}, 'title': {'type': 'string'},
                            'headers': {'type': 'array', 'items': {'type': 'string'}},
                            'rows': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'string'}}},
                            'source_ref': {'type': 'string'}}}
    return {'name': 'tables', 'strict': True, 'schema': {
        'type': 'object', 'additionalProperties': False, 'required': ['tables'], 'properties': {'tables': {'type': 'array', 'items': table}}}}
