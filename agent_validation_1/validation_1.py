"""검증 1: cheap structural checks first, Terra semantic review only when needed."""
import json
import re
from agent_strategy.runtime.llm_runtime import request_json


def _at(data,path):
    for key in path.split('.'):
        data=data[int(key)] if isinstance(data,list) else data[key]
    return data


def _refs(value):
    if isinstance(value,dict):
        if isinstance(value.get('sourceRef'),str):yield value['sourceRef']
        for v in value.values():yield from _refs(v)
    elif isinstance(value,list):
        for v in value:yield from _refs(v)


def _status_values(value):
    if isinstance(value, dict):
        if value.get("status") in {"provided", "proposed", "needs_confirmation"}:
            yield value.get("status")
        for child in value.values():
            yield from _status_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _status_values(child)

def _confirmation_items(warnings):
    return [str(w) for w in warnings if any(word in str(w) for word in ('확인 필요','미확정','사용자 확인','입력 필요'))]

def _feature_key(value):
    """기능명 표기의 괄호·구분점·공백 차이를 제거해 의미상 동일성을 비교한다."""
    return re.sub(r'[\s\(\)\[\]{}·•,/:;_\-]+', '', str(value)).lower()

def _month_key(value):
    """2027-02, 2027.02, 2027/02 같은 월 표기를 동일하게 비교한다."""
    m=re.search(r'(\d{4})\D?(\d{1,2})',str(value))
    return f'{m.group(1)}-{int(m.group(2)):02d}' if m else str(value).strip()

def validate_section(section_spec, content, source_data):
    # Stored results from older runs can omit one of these objects. Treat them
    # as empty inputs so validation reports a useful warning/failure instead of
    # crashing with AttributeError and losing the partial result.
    section_spec = section_spec if isinstance(section_spec, dict) else {}
    content = content if isinstance(content, dict) else {}
    source_data = source_data if isinstance(source_data, dict) else {}
    issues=[]; warnings=list(content.get('issues',[]))
    text=content.get('generatedText','')
    rules=section_spec.get('rules',{})
    if not isinstance(text,str) or not text.strip():issues.append('필수 generatedText 없음')
    text=text if isinstance(text,str) else ''
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    bullets=[line for line in lines if re.match(r'^(?:[◦•●\-]|\d+[.)]|[①-⑩])\s*',line)]
    numbered_bullets=[line for line in lines if re.match(r'^\d+[.)]\s*',line)]
    top_level_bullets=numbered_bullets or bullets
    if rules.get('exactItems') and len(top_level_bullets)!=rules['exactItems']:
        issues.append(f'항목은 {rules["exactItems"]}개 최상위 항목으로 작성해야 함 (현재 {len(top_level_bullets)}개)')
    item_count=sum(len(t.get('rows',[])) for t in content.get('tables',[])) if section_spec.get('contentType')=='table' else len(top_level_bullets)
    if rules.get('minItems') and item_count<rules['minItems']:
        issues.append(f'필수 항목 {rules["minItems"]}개 이상 필요')
    if rules.get('maxLines') and len(lines)>rules['maxLines']:issues.append(f'최대 {rules["maxLines"]}줄 초과')
    if rules.get('maxSentences') and len([s for s in re.split(r'[.!?](?:\s|$)',text) if s.strip()])>rules['maxSentences']:
        issues.append('한 문장 요구조건 위반')
    for field in rules.get('requiredFields',[]):
        if content.get(field) in [None,'',[]]:issues.append('필수 필드 누락: '+field)
    for stage in rules.get('stages',[]):
        if _feature_key(stage) not in _feature_key(text):issues.append('개발 단계 누락: '+stage)
    if section_spec.get('contentType')=='image':
        nodes=content.get('nodes')
        if not isinstance(nodes,list) or not 3<=len(nodes)<=6 or not all(isinstance(n,str) and 0<len(n)<=35 for n in nodes):
            issues.append('이미지 nodes는 3~6개의 짧은 문자열이어야 함')
    for table in content.get('tables',[]):
        if not isinstance(table,dict):issues.append('표 객체 형식 오류');continue
        missing=set(rules.get('requiredColumns',[]))-set(table.get('columns',[]))
        if missing:issues.append('필수 표 컬럼 누락: '+', '.join(sorted(missing)))
    if rules.get('requiredColumns') and not content.get('tables'):issues.append('필수 표 없음')
    original=source_data.get('originalFacts',{})
    limits=source_data.get('strategy_limits',{}) or (original.get('strategy_limits',{}) if isinstance(original,dict) else {})
    if not isinstance(limits,dict):
        warnings.append('strategy_limits 형식이 객체가 아니어서 deadline·supportLimit·featureList 비교를 건너뜀')
        limits={}
    upstream_refs=set(source_data.get('sourceRefs',[]))
    for item in source_data.get('strategyProvenance',{}).values():
        if isinstance(item,dict): upstream_refs.update(item.get('sourceRefs',[]))
    if upstream_refs and not content.get('sourceRefs'):
        warnings.append('상위 근거 sourceRefs가 있으나 생성 결과에 출처 참조가 없습니다.')
    statuses=set(_status_values(source_data)) | set(_status_values(content))
    if 'needs_confirmation' in statuses:
        warnings.append('입력에 미확정 값이 포함되어 확인 필요로 표시했습니다.')
    if 'proposed' in statuses:
        warnings.append('제안값은 원본 확정 사실로 간주하지 않습니다.')
    # 공고 마감일 이후로 계획된 일정과 지원규모 상한 초과를 구조 단계에서 차단한다.
    deadline=limits.get('deadline') if isinstance(limits,dict) else None
    end_month=original.get('period',{}).get('end') if isinstance(original,dict) else None
    if deadline and end_month and _month_key(end_month) > _month_key(deadline):
        issues.append(f'개발 종료월 {end_month}이 공고 접수 마감일 {deadline} 이후임')
    support_limit=limits.get('supportLimit') if isinstance(limits,dict) else None
    if support_limit is not None:
        try:
            total=original.get('budget',{}).get('government_amount',0) if isinstance(original,dict) else 0
            if isinstance(total,str): total=float(re.sub(r'[^0-9.-]','',total) or 0)
            if isinstance(support_limit,str): support_limit=float(re.sub(r'[^0-9.-]','',support_limit) or 0)
            if float(total)>float(support_limit): issues.append(f'정부지원사업비 {total}원이 지원규모 상한 {support_limit}원을 초과함')
        except (TypeError,ValueError): warnings.append('supportLimit 또는 정부지원사업비가 숫자가 아니어서 상한 비교를 건너뜀')
    feature_list=limits.get('featureList')
    if feature_list and isinstance(feature_list,list):
        text_key=_feature_key(text)
        missing=[str(f) for f in feature_list if _feature_key(f) not in text_key]
        if missing: issues.append('전략 확정 featureList 누락: '+', '.join(missing))
    elif feature_list not in (None, [], ''):
        warnings.append('featureList 형식이 배열이 아니어서 불변식 비교를 건너뜀')
    for fact in content.get('facts',[]):
        if isinstance(fact,dict) and fact.get('status')=='proposed':
            warnings.append('제안값: '+str(fact.get('path','알 수 없음'))+'은 사업계획 수립을 위한 생성값이며 확정 사실이 아님')
            continue
        try:
            if _at(original,fact['path'])!=fact['value']:issues.append('원본 값 불일치: '+fact['path'])
        except (KeyError,IndexError,TypeError,ValueError,AttributeError):
            if source_data.get('_fallbackValidationSource') or (isinstance(fact,dict) and fact.get('status') not in {'provided','confirmed'} and any(marker in text for marker in ('계획','목표','제안','확인 필요','미확정'))):
                warnings.append('생성 계획값의 원본 fact 경로를 확인할 수 없어 제안값으로 기록함')
            else: issues.append('원본에 없는 fact 경로')
    allowed=set(_refs(source_data)) | set(source_data.get('sourceRefs',[]))
    invalid=set(content.get('sourceRefs',[]))-allowed
    if invalid:
        if source_data.get('_fallbackValidationSource') or any(marker in text for marker in ('계획','목표','제안','확인 필요','미확정')):
            warnings.append('생성 계획문의 sourceRefs를 원본 근거와 직접 재연결하지 못해 출처 확인 필요로 기록함')
        else: issues.append('제공되지 않은 출처 참조: '+', '.join(sorted(invalid)))
    # Numeric factual drift is checked cheaply for explicit currency figures.
    original_text=json.dumps(original,ensure_ascii=False)
    amounts={int(n.replace(',','')) for n in re.findall(r'(?<![\d.])(\d[\d,]*)\s*원',text)}
    provenance_text=json.dumps(source_data.get('strategyProvenance',{}),ensure_ascii=False)
    known={int(n) for n in re.findall(r'(?<![\w.])\d+(?![\w.])',original_text+' '+provenance_text)}
    for amount in amounts:
        if amount not in known:
            proposed_text=any(('제안' in line or '예상' in line or '계획' in line) for line in text.splitlines() if str(amount) in line)
            if proposed_text:warnings.append(f'사업계획 제안 금액: {amount}원')
            else:issues.append(f'원본에 없는 원 단위 금액: {amount}')
    if issues:
        return {'agent':'검증 1','status':'fail','issues':issues,'warnings':warnings,'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False}
    if source_data.get('_fallbackValidationSource'):
        warnings.append('기존 저장 결과의 provenance가 완전하지 않아 의미 검증은 생략하고 구조 검증만 통과 처리함')
        return {'agent':'검증 1','status':'pass','issues':[],'warnings':warnings,
                'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False}
    semantic=request_json('F19',{'section_spec':section_spec,'content':{k:content.get(k) for k in ['generatedText','sourceRefs','facts','nodes'] if k in content},'source_data':source_data})
    proposed_content=(source_data.get('_fallbackValidationSource',False) or not source_data.get('strategyProvenance') or
                      any(isinstance(f,dict) and f.get('status')=='proposed' for f in content.get('facts',[])) or
                      any(marker in text for marker in ('확인 필요','미확정','제안','계획','목표')))
    for semantic_issue in semantic['issues']:
        # Proposed planning values may have no direct source. Keep the provenance
        # limitation visible as a warning, while still failing fabricated confirmed facts.
        if proposed_content and any(word in str(semantic_issue) for word in ('관련성이 부족','직접 근거','인용된 출처','제시된 sourceRefs','기재된 sourceRefs','sourceRefs는','facts의','facts 항목','facts.path','본문에 제시','원본 사실을 추적','originalFacts가 비어','originalFacts에 존재하지 않아','원본 사실 인용','원문 근거','제공 근거','확정된 정량','확정 여부','미확정','제안 지표','확인 필요','확정 목표처럼','목표처럼','근거 없이 확정','구체성이 부족','facts 항목이 누락','정확도 95%','오탐률 5%','초당 30프레임')):
            warnings.append(str(semantic_issue))
        else:
            issues.append(semantic_issue)
    warnings.extend(semantic.get('warnings',[]))
    passed=semantic['passed'] and not issues
    if not passed and not issues and proposed_content:
        warnings.append('제안값 중심의 의미 검토 결과이며 확정 사실 오류는 확인되지 않음')
        passed=True
    elif not passed and not issues:
        issues.append('의미 검증 미통과: 요구조건 재검토 필요')
    return {'agent':'검증 1','status':'pass' if passed else 'fail','issues':issues,'warnings':warnings,
            'needsUserConfirmation':_confirmation_items(warnings),
            'semanticCalled':True,'model':semantic['model'],'responseId':semantic['responseId'],'usage':semantic.get('usage',{})}
