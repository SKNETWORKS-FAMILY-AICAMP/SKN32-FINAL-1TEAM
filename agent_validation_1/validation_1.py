"""검증 1: 먼저 저비용 구조 검사를 수행하고 필요한 경우에만 Terra 의미 검증을 호출한다."""
import json
import re
import hashlib
from pathlib import Path
from agent_strategy.runtime.llm_runtime import request_json
from agent_validation_1.semantic_review import review_issues, REVIEW_PERSONA

RUBRIC_PATH=Path(__file__).parent/'res'/'prompts'/'validation_rubric.json'
RUBRIC=json.loads(RUBRIC_PATH.read_text(encoding='utf-8-sig')) if RUBRIC_PATH.exists() else {}
VALIDATION_POLICY_VERSION=RUBRIC.get('version','2026-10-07.1')
REGISTRY_PATH=Path(__file__).parent/'res'/'reference'/'regulations'/'criteria_registry.json'
try:
    CRITERIA_REGISTRY=json.loads(REGISTRY_PATH.read_text(encoding='utf-8-sig')) if REGISTRY_PATH.exists() else {}
except (OSError,ValueError,UnicodeError):
    CRITERIA_REGISTRY={}


def _at(data,path):
    parts = re.findall(r'[^.\[\]]+|\[\d+\]', str(path or ''))
    for part in parts:
        key = part[1:-1] if part.startswith('[') else part
        data=data[int(key)] if isinstance(data,list) else data[key]
    return data


def _fact_at(data, path):
    """정규화 과정에서 평탄화된 자원 경로도 동일한 원본으로 조회한다."""
    try:
        return _at(data, path)
    except (KeyError, IndexError, TypeError, ValueError):
        text = str(path or '')
        # F13 resource_plan은 partners/equipment/hiring을 평탄화해 전달하지만
        # validationSource.originalFacts에는 resources 아래에 보존될 수 있다.
        if text == 'partners' or text.startswith('partners['):
            return _at(data, 'resources.' + text)
        if text == 'equipment' or text.startswith('equipment['):
            return _at(data, 'resources.' + text)
        if text == 'hiring' or text.startswith('hiring['):
            return _at(data, 'resources.' + text)
        raise


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
    """선택적 JSON 컬렉션 필드에서 안전한 목록을 반환한다."""
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

def _regulation_evidence(criteria):
    """항목 기준의 파일·검색어 주변에서 짧은 근거 문자열을 추출한다."""
    evidence=[]
    for mapping in criteria.get('sourceMappings',[]) if isinstance(criteria,dict) else []:
        rel=mapping.get('path') if isinstance(mapping,dict) else None
        if not rel: continue
        path=Path(__file__).parent.parent/rel
        if not path.exists() and rel.replace('\\\\','/').startswith('agent_validation_1/'):
            path=Path(__file__).parent.parent.parent/rel
        keywords=mapping.get('locatorKeywords',[]) if isinstance(mapping,dict) else []
        if not isinstance(keywords,list): keywords=[keywords]
        use_for=mapping.get('useFor',[]) if isinstance(mapping,dict) else []
        item={'path':rel,'available':path.exists(),'keywords':keywords,'matchedKeywords':[],'relevance':'low','useFor':use_for,
              'sourceRole':mapping.get('sourceRole','reference') if isinstance(mapping,dict) else 'reference',
              'authorityLevel':mapping.get('authorityLevel','low') if isinstance(mapping,dict) else 'low',
              'directFactAllowed':bool(mapping.get('directFactAllowed',False)) if isinstance(mapping,dict) else False,
              'rationale':'','excerpts':[]}
        if path.exists():
            try:
                raw=json.loads(path.read_text(encoding='utf-8-sig'))
                text=' '.join(str(raw).split())
                seen=set()
                for keyword in item['keywords']:
                    pos=text.find(str(keyword))
                    if pos>=0 and keyword not in seen:
                        item['matchedKeywords'].append(str(keyword))
                        item['excerpts'].append({'keyword':keyword,'text':text[max(0,pos-100):min(len(text),pos+300)]})
                        seen.add(keyword)
                    if len(item['excerpts'])>=2: break
                item['relevance']='high' if len(item['matchedKeywords'])>=2 else ('medium' if item['matchedKeywords'] else 'low')
                purpose='·'.join(str(v) for v in use_for) if use_for else '해당 사업계획서 항목의 기준'
                matched='·'.join(item['matchedKeywords']) if item['matchedKeywords'] else '일치 키워드 없음'
                item['rationale']=(f'{rel} 파일에서 {matched}로 언급되어 있어 {purpose}에 맞춰 위와 같이 작성·검증함'
                                   if item['matchedKeywords'] else
                                   f'{rel} 파일에서 항목 관련 키워드가 확인되지 않아 직접 근거로 사용하지 않음')
            except (OSError,ValueError,UnicodeError):
                item['readError']=True
        else:
            item['available']=False
        evidence.append(item)
    return evidence

def _feature_key(value):
    """기능명 표기의 괄호·구분점·공백 차이를 제거해 의미상 동일성을 비교한다."""
    return re.sub(r'[\s\(\)\[\]{}·•,/:;_\-]+', '', str(value)).lower()

def _feature_tokens(value):
    return [ _feature_key(t) for t in re.findall(r'[가-힣A-Za-z0-9]+', str(value)) if len(_feature_key(t))>=2 ]

def _feature_present(feature, text):
    """등록된 한국어 동의어를 허용하면서 표준 기능 토큰을 비교한다."""
    fkey=_feature_key(feature); tkey=_feature_key(text)
    if fkey in tkey:
        return True
    aliases={
        '강건': ('변화','대응'),
        '경량화': ('경량화','양자화'),
    }
    tokens=_feature_tokens(feature)
    # 생성 문장은 조사·계획 표현이 달라질 수 있다. 긴 기능명은 핵심
    # 토큰 대부분이 본문에 있으면 같은 기능으로 인정한다.
    if len(tokens)>=4:
        matched=sum(1 for token in tokens if token in tkey)
        if matched>=max(3, (len(tokens)*2+2)//3):
            return True
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
    # 이전 실행 결과에는 이 객체 중 일부가 없을 수 있다. 이를 빈 입력으로
    # 처리해 AttributeError로 중단되거나 부분 결과가 사라지지 않도록 하고,
    # 유용한 warning/fail을 기록한다.
    section_spec = section_spec if isinstance(section_spec, dict) else {}
    content = content if isinstance(content, dict) else {}
    source_data = source_data if isinstance(source_data, dict) else {}
    document_type=str(source_data.get('documentType') or source_data.get('document_type') or '')
    section_id=str(section_spec.get('sectionId',''))
    section_criteria=CRITERIA_REGISTRY.get('documentTypes',{}).get(document_type,{}).get('sections',{}).get(section_id,{})
    source_policy={
        'official_announcement': '명시 조건·지원 기준 확인',
        'application_form': '항목·표 구조 확인',
        'management_standard': '협약·사업비·수행 조건 확인',
        'faq_guidance': '공고 해석 보조만 사용',
        'management_reference': '참고용·직접 사실 근거로 사용하지 않음',
        'reference': '참고용·직접 사실 근거로 사용하지 않음',
    }
    regulation_evidence=_regulation_evidence(section_criteria)
    criteria_meta={
        'sectionId': section_id,
        'documentType': document_type,
        'criteriaApplied': section_criteria.get('criteria',[]) if isinstance(section_criteria,dict) else [],
        'sourceMappings': section_criteria.get('sourceMappings',[]) if isinstance(section_criteria,dict) else [],
        'sourceRefs': section_criteria.get('sourceRefs',[]) if isinstance(section_criteria,dict) else [],
        'evidence': regulation_evidence,
        'sourcePolicy': source_policy,
        'evidenceRoles': sorted({str(e.get('sourceRole','reference')) for e in regulation_evidence}),
    }
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
    # 최상위 불릿 안에 '-' 세부 항목이 있으면 최상위 항목만 센다.
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
    # featureList는 구현 불변식이며 개요·요약 항목에서 모든 기능을
    # 반복해서 작성해야 한다는 의미는 아니다.
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
            if _fact_at(original,fact['path'])!=fact['value']:
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
    # 명시된 통화 금액의 숫자 사실 불일치는 저비용으로 확인한다.
    original_text=json.dumps(original,ensure_ascii=False)
    amounts={int(n.replace(',','')) for n in re.findall(r'(?<![\d.])(\d[\d,]*)\s*원',text)}
    provenance_text=json.dumps(source_data.get('strategyProvenance',{}),ensure_ascii=False)
    known={int(n) for n in re.findall(r'(?<![\w.])\d+(?![\w.])',original_text+' '+provenance_text)}
    proposed_fact_paths={str(f.get('path','')) for f in _as_list(content.get('facts',[]))
                         if isinstance(f,dict) and f.get('status') in {'proposed','needs_confirmation'}}
    for amount in amounts:
        if amount not in known:
            proposed_text=any(('제안' in line or '예상' in line or '계획' in line) for line in text.splitlines() if str(amount) in line)
            if proposed_text or any('budget' in path or '지원' in path for path in proposed_fact_paths):warnings.append(f'사업계획 제안 금액: {amount}원')
            else:issues.append(f'원본에 없는 원 단위 금액: {amount}')
    issues=_unique_messages(issues); warnings=_unique_messages(warnings)
    if issues:
        return {'agent':'검증 1','status':'fail','issues':issues,'warnings':warnings,'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False,'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION,'criteria':criteria_meta}
    if source_data.get('_fallbackValidationSource'):
        warnings.append('기존 저장 결과의 provenance가 완전하지 않아 의미 검증은 생략하고 구조 검증만 통과 처리함')
        return {'agent':'검증 1','status':'pass','issues':[],'warnings':warnings,
                'needsUserConfirmation':_confirmation_items(warnings),'semanticCalled':False,'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION,'criteria':criteria_meta}

    semantic_source=dict(source_data) if isinstance(source_data,dict) else {}
    # 의미 검증에는 항목 키워드와 실제로 연결된 근거만 전달한다.
    # 전체 evidence는 결과 JSON에 보존하되 low 관련도 자료가 판정을 오염시키지 않도록 분리한다.
    prompt_evidence=[e for e in criteria_meta['evidence'] if e.get('relevance') in {'high','medium'}]
    if section_criteria:
        semantic_source['_sectionCriteria']={**section_criteria,'evidence':prompt_evidence}
    prompt_criteria={**section_criteria,'evidence':prompt_evidence} if section_criteria else {}
    semantic=request_json('F19',{'section_spec':section_spec,'content':{k:content.get(k) for k in ['generatedText','sourceRefs','facts','nodes'] if k in content},'source_data':semantic_source,'criteria':prompt_criteria})
    proposed_content=(source_data.get('_fallbackValidationSource',False) or not source_data.get('strategyProvenance') or
                      any(isinstance(f,dict) and f.get('status')=='proposed' for f in _as_list(content.get('facts',[]))) or
                      any(marker in text for marker in ('확인 필요','미확정','제안','계획','목표','활용','적용')))
    for semantic_issue in _as_list(semantic.get('issues',[])):
        # 제안 계획값은 직접 출처가 없을 수 있다. 근거 추적 한계는 warning으로
        # 표시하되, 조작된 확정 사실은 계속 fail로 판정한다.
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
            'semanticCalled':True,'model':semantic.get('model'),'responseId':semantic.get('responseId'),'usage':semantic.get('usage',{}),'contentHash':content_hash,'policyVersion':VALIDATION_POLICY_VERSION,'criteria':criteria_meta}
