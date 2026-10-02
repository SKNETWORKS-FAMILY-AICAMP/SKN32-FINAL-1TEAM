"""검증-1 채점 프롬프트와 출력 스키마. 모든 후보 모델에 같은 것을 쓴다(모델만 바꾸는 실험)."""
from __future__ import annotations

PROMPT_VERSION = 'v1-baseline'

SYSTEM = """당신은 정부지원사업 사업계획서 심사위원이다. 주어진 평가항목별 기준에 따라 계획서를 채점한다.

규칙:
- 항목마다 0 이상 max_score 이하의 점수를 준다. 소수점 가능.
- 계획서에 실제로 적힌 내용만 근거로 삼는다. 없는 내용을 추측해서 채우지 않는다.
- 해당 항목을 다룬 부분이 없으면 0점에 가깝게 준다.
- 시장 규모 등 수치에 출처가 없거나 근거 없이 부풀린 수치는 감점한다.
- 공고 취지와 무관한 내용은 점수를 주지 않는다.
- evidence_locator: 점수의 근거가 된 계획서 문장 일부를 그대로 인용한다. 근거가 없으면 "없음".
- comment: 점수 이유를 한두 문장으로 쓴다.
- 총점은 계산하지 않는다. 항목 점수만 낸다."""


def build_messages(rubric: dict, plan_text: str) -> list[dict]:
    ann = rubric['announcement']
    lines = ['[공고] %s (%s)\n%s' % (ann['title'], ann['agency'], ann['summary']), '', '[평가항목]']
    for it in rubric['items']:
        lines.append('- %s %s (max_score %s): %s' % (it['item_code'], it['item_name'], it['max_score'], it['description']))
        lines.append('    기준: ' + ' / '.join(it['criteria']))
    lines += ['', '[사업계획서]', plan_text]
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': '\n'.join(lines)}]


def output_schema(rubric: dict) -> dict:
    codes = [it['item_code'] for it in rubric['items']]
    return {
        'name': 'doc_score', 'strict': True,
        'schema': {
            'type': 'object', 'additionalProperties': False, 'required': ['items'],
            'properties': {'items': {
                'type': 'array',
                'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['item_code', 'score', 'evidence_locator', 'comment'],
                    'properties': {
                        'item_code': {'type': 'string', 'enum': codes},
                        'score': {'type': 'number'},
                        'evidence_locator': {'type': 'string'},
                        'comment': {'type': 'string'},
                    }}}}}}
