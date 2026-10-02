"""검증 1: cheap structural checks first, Terra semantic review only when needed."""
import json
import re
import hashlib
from pathlib import Path
from agent_strategy.runtime.llm_runtime import request_json
from agent_validation_1.semantic_review import review_issues, REVIEW_PERSONA

RUBRIC_PATH=Path(__file__).parent/'res'/'prompts'/'validation_rubric.json'
RUBRIC=json.loads(RUBRIC_PATH.read_text(encoding='utf-8-sig')) if RUBRIC_PATH.exists() else {}
VALIDATION_POLICY_VERSION=RUBRIC.get('version','2026-10-01.3')


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

def _as_list(value):
    """Return a safe list for optional JSON collection fields."""
    if isinstance(value, list): return value
    if value in (None, ''): return []
    return [value]

def _string_set(value):
    return {str(item) for item in _as_list(value) if isinstance(item, (str, int, float))}

def _unique_messages(values):
    seen=set(); result=[]
    for value in values:
        text=str(value).strip()
        if text and text not in seen:
            seen.add(text); result.append(text)
    return result

def _confirmation_items(warnings):
    return [str(w) for w in warnings if any(word in str(w) for word in ('확인 필요','미확정','사용자 확인','입력 필요'))]

def _feature_key(value):
    """기능명 표기의 괄호·구분점·공백 차이를 제거해 의미상 동일성을 비교한다."""
    return re.sub(r'[\s\(\)\[\]{}·•,/:;_\-]+', '', str(value)).lower()

def _feature_tokens(value):
    return [ _feature_key(t) for t in re.findall(r'[가-힣A-Za-z0-9]+', str(value)) if len(_feature_key(t))>=2 ]

def _feature_present(feature, text):
    """Match canonical feature tokens while allowing documented Korean synonyms."""
    fkey=_feature_key(feature); tkey=_feature_key(text)
    if fkey in tkey:
        return True
    aliases={
        '강건': ('변화','대응'),
        '경량화': ('경량화','양자화'),
    }
    tokens=_feature_tokens(feature)
    for token in tokens:
        if token in tkey:
            continue
        alternatives=aliases.get(token)
        if not alternatives or not all(_feature_key(a) in tkey for a in alternatives):
            return False
    return bool(tokens)

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
    content_hash=hashlib.sha256(json.dumps(content,ensure_ascii=False,sort_keys=True,default=str).encode('utf-8')).hexdigest()
    issues=[]; warnings=[str(item) for item in _as_list(content.get('issues',[]))]
    text=content.get('generatedText','')
    rules=section_spec.get('rules',{})
    if not isinstance(rules,dict):
        rules={}
    if not isinstance(text,str) or not text.strip():issues.append('필수 generatedText 없음')
    text=text if isinstance(text,str) else ''
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    bullets=[line for line in lines if re.match(r'^(?:[◦•●\-]|\d+[.)]|[①-⑩])\s*',line)]
    numbered_bullets=[line for line in lines if re.match(r'^\d+[.)]\s*',line)]
    visual_top_level=[line for line in lines if re.match(r'^[◦•●]\s*',line)]
    # When a top-level bullet has nested '-' details, count only the top level.
    top_level_bullets=numbered_bullets or visual_top_level or bullets
    if rules.get('exactItems') and len(top_level_bullets)!=rules['exactItems']:
        issues.append(f'항목은 {rules["exactItems"]}개 최상위 항목으로 작성해야 함 (현재 {len(top_level_bullets)}개)')
    tables=_as_list(content.get('tables',[]))
    item_count=sum(len(_as_list(t.get('rows',[]))) for t in tables if isinstance(t,dict)) if section_spec.get('contentType')=='table' else len(top_level_bullets)
    if rules.get('minItems') and item_count<rules['minItems']:
        issues.append(f'필수 항목 {rules["minItems"]}개 이상 필요')
    if rules.get('maxLines') and len(lines)>rules['maxLines']:issues.append(f'최대 {rules["maxLines"]}줄 초과')
    if rules.get('maxSentences') and len([s for s in re.split(r'[.!?](?:\s|$)',text) if s.strip()])>rules['maxSentences']:
        issues.append('한 문장 요구조건 위반')
    for field in _as_list(rules.get('requiredFields',[])):
        if content.get(field) in [None,'',[]]:issues.append('필수 필드 누락: '+field)
    for stage in _as_list(rules.get('stages',[])):
        if _feature_key(stage) not in _feature_key(text):issues.append('개발 단계 누락: '+stage)
    if section_spec.get('contentType')=='image':
        nodes=content.get('nodes')
        if not isinstance(nodes,list) or not 3<=len(nodes)<=6 or not all(isinstance(n,str) and 0<len(n)<=35 for n in nodes):
            issues.append('이미지 nodes는 3~6개의 짧은 문자열이어야 함')
        specs=content.get('imageSpecs')
        if isinstance(specs,list):
            types={item.get('flowType') for item in specs if isinstance(item,dict)}
            if not {'USER_FLOW','SERVICE_ARCHITECTURE'}.issubset(types):
                issues.append('USERFLOW 및 SERVICE_ARCHITECTURE 이미지 명세가 모두 필요함')
            for item in specs:
                item_nodes=item.get('nodes') if isinstance(item,dict) else None
                if not isinstance(item_nodes,list) or not 3<=len(item_nodes)<=6:
                    issues.append('이미지 명세별 nodes는 3~6개여야 함')
    for table in tables:
        if not isinstance(table,dict):issues.append('표 객체 형식 오류');continue
        missing=_string_set(rules.get('requiredColumns',[]))-_string_set(table.get('columns',[]))
        if missing:issues.append('필수 표 컬럼 누락: '+', '.join(sorted(missing)))
    if _string_set(rules.get('requiredColumns',[])) and not tables:issues.append('필수 표 없음')
    original=source_data.get('originalFacts',{})
    if not isinstance(original,dict):
        original={}
    limits=source_data.get('strategy_limits',{}) or (original.get('strategy_limits',{}) if isinstance(original,dict) else {})
    if not isinstance(limits,dict):
        warnings.append('strategy_limits 형식이 객체가 아니어서 deadline·supportLimit·featureList 비교를 건너뜀')
        limits={}
    upstream_refs=_string_set(source_data.get('sourceRefs',[]))
    provenance=source_data.get('strategyProvenance',{})
    provenance_items=provenance.values() if isinstance(provenance,dict) else _as_list(provenance)
    for item in provenance_items:
        if isinstance(item,dict): upstream_refs.update(_string_set(item.get('sourceRefs',[])))
    if upstream_refs and not content.get('sourceRefs'):
        warnings.append('상위 근거 sourceRefs가 있으나 생성 결과에 출처 참조가 없습니다.')
    statuses=set(_status_values(source_data)) | set(_status_values(content))
    if 'needs_confirmation' in statuses:
        warnings.append('입력에 미확정 값이 포함되어 확인 필요로 표시했습니다.')
    if 'proposed' in statuses:
        warnings.append('제안값은 원본 확정 사실로 간주하지 않습니다.')
    # 공고 마감일 이후로 계획된 일정과 지원규모 상한 초과를 구조 단계에서 차단한다.
    deadline=limits.get('deadline') if isinstance(limits,dict) else None
    period=original.get('period',{})
    end_month=period.get('end') if isinstance(period,dict) else None
    if deadline and end_month and _month_key(end_month) > _month_key(deadline):
        issues.append(f'개발 종료월 {end_month}이 공고 접수 마감일 {deadline} 이후임')
    support_limit=limits.get('supportLimit') if isinstance(limits,dict) else None
    if support_limit is not None:
        try:
            budget=original.get('budget',{})
            total=budget.get('government_amount',0) if isinstance(budget,dict) else 0
            if isinstance(total,str): total=float(re.sub(r'[^0-9.-]','',total) or 0)
            if isinstance(support_limit,str): support_limit=float(re.sub(r'[^0-9.-]','',support_limit) or 0)
            if float(total)>float(support_limit): issues.append(f'정부지원사업비 {total}원이 지원규모 상한 {support_limit}원을 초과함')
        except (TypeError,ValueError): warnings.append('supportLimit 또는 정부지원사업비가 숫자가 아니어서 상한 비교를 건너뜀')
    feature_list=limits.get('featureList')
    # KPI/시험지표 항목은 기능 목록을 반복하는 영역이 아니므로
    # featureList 불변식 비교를 적용하지 않는다.
    section_title=str(section_spec.get('title',''))
    # featureList is an implementation invariant, not a requirement to repeat
    # every feature in introductory/summary sections.
    feature_check_allowed=any(token in section_title for token in ('핵심기술','개발 기능','개발방법','개발계획','양산','기능 목록')) and not any(token in section_title for token in ('성능지표','검증에 필요한 성능'))
    if feature_check_allowed and feature_list and isinstance(feature_list,list):
        text_key=_feature_key(text)
        missing=[]
        for feature in feature_list:
            key=_feature_key(feature)
            tokens=_feature_tokens(feature)
            if not _feature_present(feature,text):
                missing.append(str(feature))
        if missing: issues.append('전략 확정 featureList 누락: '+', '.join(missing))
    elif feature_check_allowed and feature_list not in (None, [], ''):
        warnings.append('featureList 형식이 배열이 아니어서 불변식 비교를 건너뜀')
    for fact in _as_list(content.get('facts',[])):
        if isinstance(fact,dict) and fact.get('status')=='proposed':
            warnings.append('제안값: '+str(fact.get('path','알 수 없음'))+'은 사업계획 수립을 위한 생성값이며 확정 사실이 아님')
            continue
        try:
            if _at(original,fact['path'])!=fact['value']:
                planning_context=any(marker in text for marker in ('계획','목표','제안','확인 필요','미확정','활용','적용','개발'))
                if isinstance(fact,dict) and fact.get('status') not in {'provided','confirmed'} and planning_context:
                    warnings.append('원본과 다른 생성 계획값: '+str(fact.get('path','알 수 없음'))+'은 제안값으로 확인 필요')
                else:
                    issues.append('원본 값 불일치: '+fact['path'])
        except (KeyError,IndexError,TypeError,ValueError,AttributeError):
            malformed_generated_path=isinstance(fact,dict) and str(fact.get('path','')).startswith(('item.originalFacts.','source_data.originalFacts.'))
            if malformed_generated_path or source_data.get('_fallbackValidationSource') or (isinstance(fact,dict) and fact.get('status') not in {'provided','confirmed'} and any(marker in text for marker in ('계획','목표','제안','확인 필요','미확정','활용','적용','개발'))):
                warnings.append('생성 계획값의 원본 fact 경로를 확인할 수 없어 제안값으로 기록함')
            else: issues.append('원본에 없는 fact 경로')
    allowed={str(ref) for ref in _refs(source_data)} | _string_set(source_data.get('sourceRefs',[]))
    invalid=_string_set(content.get('sourceRefs',[]))-allowed
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
    issues=_unique_messages(issues); warnings=_unique_messages(warnings)
    if issues:
        return {'agent':'검증 1','status':'fail','issues':issues,'warnings':warnings,'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False,'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION}
    if source_data.get('_fallbackValidationSource'):
        warnings.append('기존 저장 결과의 provenance가 완전하지 않아 의미 검증은 생략하고 구조 검증만 통과 처리함')
        return {'agent':'검증 1','status':'pass','issues':[],'warnings':warnings,
                'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False,'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION}
    semantic=request_json('F19',{'section_spec':section_spec,'content':{k:content.get(k) for k in ['generatedText','sourceRefs','facts','nodes'] if k in content},'source_data':source_data})
    proposed_content=(source_data.get('_fallbackValidationSource',False) or not source_data.get('strategyProvenance') or
                      any(isinstance(f,dict) and f.get('status')=='proposed' for f in _as_list(content.get('facts',[]))) or
                      any(marker in text for marker in ('확인 필요','미확정','제안','계획','목표','활용','적용')))
    for semantic_issue in _as_list(semantic.get('issues',[])):
        # Proposed planning values may have no direct source. Keep the provenance
        # limitation visible as a warning, while still failing fabricated confirmed facts.
        issue_text=str(semantic_issue)
        reviewed_hard, reviewed_warning = review_issues([issue_text])
        if reviewed_warning and issue_text.strip() != '표현 수정 필요':
            warnings.append('판정 재검토: '+issue_text)
            continue
        proposal_issue=any(word in issue_text for word in ('관련성이 부족','직접 근거','인용된 출처','인용 출처 중','직접 관련성이 낮음','직접 뒷받침하지 못함','수치 근거','근거를 연결','sourceRefs','facts','본문에 제시','원본 사실','원본에 없고','originalFacts','원문 근거','제공 근거','확정된 정량','확정 여부','확정 사실이 아님','미확정','제안 지표','확인 필요','확정 목표','목표처럼','근거 없이 확정','확정하여 기재','구현하고','확정 수행','제안사항','확정 추진내용','status:"proposed"','기술언어','기능은 원본','제안값임을 명시','구체성이 부족','정확도 95%','오탐률 5%','초당 30프레임','상세계획','기간 정합성','확정 추진계획','단계 일정','사업기간','개발함','완료 실적','측정식','FPS 산정','프레임 수를 경과시간','정의가 필요','선정 필요','검토 필요','구체화 필요','확정해야','명확하지 않음','산정 방식','확정적 문제점','서술하기 어려움','제안 상태','전략 기능 목록','기능 목록','원문 토큰','불변식'))
        hard_issue=any(word in issue_text for word in ('원본과 불일치','확정 fact 오류','마감일 이후','지원규모 상한','필수 표','필수 항목','이미지 nodes'))
        if proposed_content and proposal_issue and not hard_issue:
            warnings.append(str(semantic_issue))
        else:
            issues.append(semantic_issue)
    warnings.extend(str(item) for item in _as_list(semantic.get('warnings',[])))
    issues=_unique_messages(issues); warnings=_unique_messages(warnings)
    passed=bool(semantic.get('passed')) and not issues
    if not passed and not issues and proposed_content:
        warnings.append('제안값 중심의 의미 검토 결과이며 확정 사실 오류는 확인되지 않음')
        passed=True
    elif not passed and not issues:
        issues.append('의미 검증 미통과: 요구조건 재검토 필요')
    return {'agent':'검증 1','status':'pass' if passed else 'fail','issues':issues,'warnings':warnings,
            'needsUserConfirmation':_confirmation_items(warnings),
            'semanticCalled':True,'model':semantic.get('model'),'responseId':semantic.get('responseId'),'usage':semantic.get('usage',{}),'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION}
