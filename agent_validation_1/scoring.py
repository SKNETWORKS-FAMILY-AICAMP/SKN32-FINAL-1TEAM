"""Deterministic section scoring based on validation results and regulation basis."""
import json
import hashlib
from pathlib import Path

ROOT = Path(__file__).parent
RUBRIC_PATH = ROOT / 'res' / 'prompts' / 'evaluation_rubric.json'
RUBRIC = json.loads(RUBRIC_PATH.read_text(encoding='utf-8-sig'))

def _count(value):
    return len(value) if isinstance(value, list) else (1 if value else 0)

def _flatten_text(value):
    if isinstance(value, dict):
        return ' '.join(f'{k} {_flatten_text(v)}' for k,v in value.items())
    if isinstance(value, list):
        return ' '.join(_flatten_text(v) for v in value)
    return str(value or '')

def _month(value):
    import re
    m=re.search(r'(20\d{2})\s*(?:[.\-/년]\s*)?(\d{1,2})\s*월?',str(value))
    return int(m.group(1))*12+int(m.group(2)) if m else None

def score_section(section_spec: dict, content: dict, validation: dict, document_type: str = 'general', source_data: dict | None = None) -> dict:
    """Return score, component scores, deductions, and regulation basis.

    This scorer never invents facts or regulatory thresholds; it only scores
    observable contracts and the validation result supplied by validation_1.
    """
    config = RUBRIC['documentTypes'].get(document_type, RUBRIC['documentTypes']['general'])
    weights = config['weights']
    basis_status = [{'path': path, 'available': (Path(__file__).parents[1] / path).exists()} for path in config.get('basis', [])]
    issues = validation.get('issues', []) if isinstance(validation, dict) else []
    warnings = validation.get('warnings', []) if isinstance(validation, dict) else []
    confirmations = validation.get('needsUserConfirmation', []) if isinstance(validation, dict) else []
    status = validation.get('status', 'not_run') if isinstance(validation, dict) else 'not_run'
    generated = _flatten_text(content) if isinstance(content, dict) else str(content or '')
    limits = (source_data or {}).get('_strategy_limits', {}) if isinstance(source_data, dict) else {}
    components = {key: 100 for key in weights}
    deductions = []
    seen_reasons = set()
    if status == 'fail':
        components['structure'] = max(0, components['structure'] - 40)
        deductions.append({'reason': '검증 1 fail', 'amount': 40, 'source': 'validation_1'})
    for item in issues:
        if str(item) in seen_reasons: continue
        seen_reasons.add(str(item))
        target = 'requirement' if any(word in str(item) for word in ('필수','표','이미지','마감','지원금','기능')) else 'provenance'
        amount = RUBRIC['penalties']['issue']
        components[target] = max(0, components[target] - amount)
        deductions.append({'reason': str(item), 'amount': amount, 'source': 'validation_1'})
    for item in warnings:
        if str(item) in seen_reasons: continue
        seen_reasons.add(str(item))
        target = 'provenance' if any(word in str(item) for word in ('근거','출처','source','fact')) else 'clarity'
        amount = RUBRIC['penalties']['warning']
        components[target] = max(0, components[target] - amount)
        deductions.append({'reason': str(item), 'amount': amount, 'source': 'validation_1'})
    for item in confirmations:
        if str(item) in seen_reasons: continue
        seen_reasons.add(str(item))
        amount = RUBRIC['penalties']['needsUserConfirmation']
        components['clarity'] = max(0, components['clarity'] - amount)
        deductions.append({'reason': str(item), 'amount': amount, 'source': 'needsUserConfirmation'})
    if not generated.strip():
        components['structure'] = 0
        deductions.append({'reason': '생성 본문 없음', 'amount': 100, 'source': 'section_output'})
    if any(not item['available'] for item in basis_status):
        components['clarity'] = max(0, components['clarity'] - 10)
        deductions.append({'reason': '평가 기준 원문 파일 누락', 'amount': 10, 'source': 'evaluation_rubric.basis'})
    limit_text = str(limits.get('deadline', ''))
    deadline_month = _month(limit_text)
    if limit_text and deadline_month is None:
        components['clarity'] = max(0, components['clarity'] - 2)
        deductions.append({'reason': 'deadline 형식을 해석할 수 없음', 'amount': 2, 'source': '_strategy_limits.deadline'})
    periods = [_month(x) for x in __import__('re').findall(r'20\d{2}\s*(?:[.\-/년]\s*)\d{1,2}\s*월?', generated)]
    if deadline_month and periods and max(periods) > deadline_month:
        components['requirement'] = max(0, components['requirement'] - 40)
        deductions.append({'reason': '개발 일정이 deadline 이후일 가능성', 'amount': 40, 'source': '_strategy_limits.deadline'})
    support_limit = limits.get('supportLimit')
    if support_limit:
        import re
        limit_digits = re.sub(r'[^0-9]', '', str(support_limit))
        if not limit_digits:
            components['clarity'] = max(0, components['clarity'] - 2)
            deductions.append({'reason': 'supportLimit 형식을 해석할 수 없음', 'amount': 2, 'source': '_strategy_limits.supportLimit'})
        amounts = [int(x.replace(',', '')) for x in re.findall(r'(?:정부지원사업비|지원금|government_amount)[^0-9]{0,20}([0-9][0-9,]*)', generated)]
        if amounts and limit_digits and max(amounts) > int(limit_digits):
            components['requirement'] = max(0, components['requirement'] - 50)
            deductions.append({'reason': '지원금 상한 초과', 'amount': 50, 'source': '_strategy_limits.supportLimit'})
    components={key: min(100, max(0, float(value))) for key,value in components.items()}
    weighted = round(sum(components[key] * weights[key] for key in weights) / sum(weights.values()), 1)
    weighted = min(100.0, max(0.0, weighted))
    # A structural/confirmed-fact failure must never appear as a passing score.
    if status == 'fail':
        weighted = min(weighted, 59.0)
    return {
        'score': weighted,
        'status': 'fail' if status == 'fail' else ('warning' if warnings or confirmations else 'pass'),
        'components': components,
        'weights': weights,
        'deductions': deductions,
        'basis': config['basis'],
        'regulationFocus': config.get('regulationFocus', []),
        'basisStatus': basis_status,
        'isOfficial': False,
        'basisType': 'internal_contract_and_regulation_review',
        'evaluationHash': hashlib.sha256(json.dumps({'section': section_spec, 'content': content, 'validation': validation}, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest(),
        'scorePolicyVersion': RUBRIC['version']
    }

def aggregate_scores(rows: list[dict]) -> dict:
    """Summarize section evaluations without hiding failed sections."""
    evaluations=[row.get('evaluation',{}) for row in rows if row.get('evaluation')]
    scores=[float(item['score']) for item in evaluations if isinstance(item.get('score'),(int,float))]
    failed=[row.get('sectionId') for row in rows if row.get('validation',{}).get('status')=='fail']
    return {'count':len(scores),'averageScore':round(sum(scores)/len(scores),1) if scores else None,
            'minimumScore':min(scores) if scores else None,'failedSections':failed,
            'status':'fail' if failed else ('warning' if any(item.get('status')=='warning' for item in evaluations) else 'pass')}
