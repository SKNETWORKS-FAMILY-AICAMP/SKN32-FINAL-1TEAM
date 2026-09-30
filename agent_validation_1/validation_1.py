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


def validate_section(section_spec, content, source_data):
    issues=[]; warnings=list(content.get('issues',[]))
    text=content.get('generatedText','')
    rules=section_spec.get('rules',{})
    if not isinstance(text,str) or not text.strip():issues.append('필수 generatedText 없음')
    text=text if isinstance(text,str) else ''
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    bullets=[line for line in lines if re.match(r'^(?:[◦•●\-]|\d+[.)]|[①-⑩])\s*',line)]
    if rules.get('exactItems') and len(bullets)!=rules['exactItems']:
        issues.append(f'항목은 {rules["exactItems"]}개 불릿으로 작성해야 함 (현재 {len(bullets)}개)')
    item_count=sum(len(t.get('rows',[])) for t in content.get('tables',[])) if section_spec.get('contentType')=='table' else len(bullets)
    if rules.get('minItems') and item_count<rules['minItems']:
        issues.append(f'필수 항목 {rules["minItems"]}개 이상 필요')
    if rules.get('maxLines') and len(lines)>rules['maxLines']:issues.append(f'최대 {rules["maxLines"]}줄 초과')
    if rules.get('maxSentences') and len([s for s in re.split(r'[.!?](?:\s|$)',text) if s.strip()])>rules['maxSentences']:
        issues.append('한 문장 요구조건 위반')
    for field in rules.get('requiredFields',[]):
        if content.get(field) in [None,'',[]]:issues.append('필수 필드 누락: '+field)
    for stage in rules.get('stages',[]):
        if stage not in text:issues.append('개발 단계 누락: '+stage)
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
    limits=source_data.get('strategy_limits',{}) or original.get('strategy_limits',{}) if isinstance(original,dict) else {}
    # 공고 마감일 이후로 계획된 일정과 지원규모 상한 초과를 구조 단계에서 차단한다.
    deadline=limits.get('deadline') if isinstance(limits,dict) else None
    end_month=original.get('period',{}).get('end') if isinstance(original,dict) else None
    if deadline and end_month and str(end_month) > str(deadline):
        issues.append(f'개발 종료월 {end_month}이 공고 접수 마감일 {deadline} 이후임')
    support_limit=limits.get('supportLimit') if isinstance(limits,dict) else None
    if support_limit is not None:
        try:
            total=original.get('budget',{}).get('government_amount',0) if isinstance(original,dict) else 0
            if float(total)>float(support_limit): issues.append(f'정부지원사업비 {total}원이 지원규모 상한 {support_limit}원을 초과함')
        except (TypeError,ValueError): warnings.append('supportLimit 또는 정부지원사업비가 숫자가 아니어서 상한 비교를 건너뜀')
    feature_list=limits.get('featureList') if isinstance(limits,dict) else None
    if feature_list and isinstance(feature_list,list):
        missing=[str(f) for f in feature_list if str(f) not in text]
        if missing: issues.append('전략 확정 featureList 누락: '+', '.join(missing))
    for fact in content.get('facts',[]):
        try:
            if _at(original,fact['path'])!=fact['value']:issues.append('원본 값 불일치: '+fact['path'])
        except (KeyError,IndexError,TypeError,ValueError,AttributeError):issues.append('원본에 없는 fact 경로')
    allowed=set(_refs(source_data))
    invalid=set(content.get('sourceRefs',[]))-allowed
    if invalid:issues.append('제공되지 않은 출처 참조: '+', '.join(sorted(invalid)))
    # Numeric factual drift is checked cheaply for explicit currency figures.
    original_text=json.dumps(original,ensure_ascii=False)
    amounts={int(n.replace(',','')) for n in re.findall(r'(?<![\d.])(\d[\d,]*)\s*원',text)}
    known={int(n) for n in re.findall(r'(?<![\w.])\d+(?![\w.])',original_text)}
    for amount in amounts:
        if amount not in known:issues.append(f'원본에 없는 원 단위 금액: {amount}')
    if issues:
        return {'agent':'검증 1','status':'fail','issues':issues,'warnings':warnings,'semanticCalled':False}
    semantic=request_json('F19',{'section_spec':section_spec,'content':{k:content.get(k) for k in ['generatedText','sourceRefs','facts','nodes'] if k in content},'source_data':source_data})
    issues.extend(semantic['issues'])
    warnings.extend(semantic.get('warnings',[]))
    passed=semantic['passed'] and not issues
    if not passed and not issues:issues.append('의미 검증 미통과: 요구조건 재검토 필요')
    return {'agent':'검증 1','status':'pass' if passed else 'fail','issues':issues,'warnings':warnings,
            'semanticCalled':True,'model':semantic['model'],'responseId':semantic['responseId'],'usage':semantic.get('usage',{})}
