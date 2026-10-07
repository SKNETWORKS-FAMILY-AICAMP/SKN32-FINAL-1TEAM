"""전략을 한 번 확정하고 항목별 입력을 제한해 검증 1과 회귀 재작성을 연결한다."""
import copy
import json
import os
import re
import time
import uuid
from pathlib import Path
from datetime import datetime,timezone
from agent_strategy.functions import gpt_functions as gpt, python_functions as py
from agent_validation_1.scoring import score_section, aggregate_scores
from agent_strategy.runtime.llm_runtime import CONTRACT,compact
from agent_strategy.runtime.research_context import retrieve

def _strip_section_heading(text, spec):
    """F16 본문에 반복 삽입된 항목 번호·제목 줄만 제거한다."""
    if not isinstance(text, str):
        return text
    sid=str(spec.get('sectionId','')).strip()
    title=str(spec.get('title','')).strip()
    kept=[]
    for line in text.splitlines():
        compact=re.sub(r'^[#\s]+','',line.strip())
        numbered=bool(sid and re.match(r'^'+re.escape(sid)+r'(?:\s*[.)·:\-]\s*|\s+)', compact))
        titled=bool(title and (compact == title or compact.endswith(title)))
        if numbered or titled:
            continue
        kept.append(line)
    return '\n'.join(kept).strip()

def _normalize_section_output(output, spec, source, kind):
    """F16 결과에 상위 출처를 보존하고 원본보다 강한 표현을 줄인다."""
    if not isinstance(output, dict):
        return output
    refs=source.get('sourceRefs',[]) if isinstance(source,dict) else []
    if refs and not output.get('sourceRefs'):
        output['sourceRefs']=sorted(set(refs))
    if isinstance(output.get('generatedText'),str):
        text=output['generatedText']
        original=source.get('originalFacts',{}) if isinstance(source,dict) else {}
        item=original.get('item',{}) if isinstance(original,dict) else {}
        description=item.get('item_input',{}).get('description','') if isinstance(item,dict) else ''
        # 원본이 POS 데이터를 '기반'으로 산출한다고만 말할 때 학습·완료로 확대하지 않는다.
        if kind=='early_startup' and spec.get('sectionId')=='3.3.1' and '기반' in str(description) and '학습해' in text:
            output['generatedText']=text.replace('POS 판매 데이터를 학습해','POS 판매 데이터를 기반으로')
    return output

def _normalize_image_output(output, flow_type='USER_FLOW'):
    """F18 nodes 계약이 깨져도 이미지 생성이 중단되지 않도록 기본 흐름을 만든다."""
    if not isinstance(output,dict):
        output={}
    if output.get('flowType') != flow_type:
        output['flowType']=flow_type
    nodes=output.get('nodes')
    if not isinstance(nodes,list) or not 3 <= len(nodes) <= 6 or not all(isinstance(n,str) and 0 < len(n) <= 35 for n in nodes):
        output['nodes']=['사용자 입력','AI 분석·처리','결과 확인'] if flow_type=='USER_FLOW' else ['입력 데이터','분석 모듈','결과·저장']
        output.setdefault('flowType',flow_type)
        output.setdefault('warnings',[]).append('F18 nodes 형식 오류로 기본 이미지 흐름을 사용함')
    return output


def refresh_user_industry_research(project):
    """현재 사용자 산업 키워드에 대한 KIET 조사 데이터를 선택적으로 갱신한다."""
    if os.getenv('SBRAIN_AUTO_RESEARCH','0').lower() not in {'1','true','yes'}:
        return {'status':'skipped','reason':'SBRAIN_AUTO_RESEARCH disabled'}
    keyword=(project.get('tech_field') or project.get('description') or '').strip()
    if not keyword:
        return {'status':'skipped','reason':'industry keyword missing'}
    try:
        from agent_strategy.res.crawling.industry_research.market_crawler import add_keyword
        result=add_keyword(keyword[:120])
        return {'status':'refreshed','keyword':keyword[:120],'resultCount':result.get('resultCount',0)}
    except Exception as exc:
        return {'status':'failed','keyword':keyword[:120],'error':str(exc)}


def select_path(data,path):
    for key in path.split('.'):
        if not isinstance(data,dict):return None
        data=data.get(key)
    return compact(data)


def _annotate_status(fid, output, input_data):
    """F16 본문 작성과 F19 검증에 전달할 전략 사실의 상태를 표시한다.

    상태값은 확정값(provided), 제안값(proposed), 확인 필요값(needs_confirmation)으로
    구분해 저장한다.
    """
    if not isinstance(output, dict):
        return output
    source_json=json.dumps(input_data, ensure_ascii=False)
    def mark(row, key=None):
        if not isinstance(row, dict): return
        if row.get("status") in {"provided", "proposed", "needs_confirmation"}: return
        value=row.get(key) if key else None
        row["status"] = "provided" if value not in (None, "", [], "확인 필요", "미정") and str(value) in source_json else ("needs_confirmation" if value in (None, "", [], "확인 필요", "미정") else "proposed")
    if fid == "F02":
        features=output.get("coreFeatures", [])
        if isinstance(features, list):
            output["coreFeatureStatus"]=[{"feature": (row.get("name") if isinstance(row, dict) else row), "status": ("provided" if str(row) in source_json else "proposed")} for row in features]
    elif fid == "F06":
        for row in output.get("kpi", []):
            if isinstance(row, dict):
                value=row.get("target")
                row["status"] = "provided" if value not in (None, "", "확인 필요", "미정") and str(value) in source_json else ("needs_confirmation" if value in (None, "", "확인 필요", "미정") else "proposed")
        for row in output.get("core_technologies", []):
            if isinstance(row, dict): mark(row, "name")
    elif fid == "F08":
        for row in output.get("phases", []):
            if isinstance(row, dict):
                period=row.get("period") or row.get("기간")
                row["status"] = "provided" if period and str(period) in source_json else ("needs_confirmation" if not period else "proposed")
    elif fid == "F09":
        for row in output.get("stages", []):
            if isinstance(row, dict):
                period=row.get("period") or row.get("기간")
                row["status"] = "provided" if period and str(period) in source_json else ("needs_confirmation" if not period else "proposed")
    return output


def _provenance(value):
    if not isinstance(value, dict):
        return {"sourceRefs": [], "evidence": [], "originalFacts": {}}
    return {"sourceRefs": value.get("sourceRefs", []), "evidence": value.get("evidence", []), "originalFacts": value.get("originalFacts", value.get("facts", []))}

def _writing_criteria(document_type, section_id):
    """F16 작성 전에 항목별 공고·양식 기준을 전달한다."""
    root=Path(__file__).resolve().parents[2]
    path=root/'agent_validation_1'/'res'/'reference'/'regulations'/'criteria_registry.json'
    try:
        registry=json.loads(path.read_text(encoding='utf-8-sig'))
        section=registry.get('documentTypes',{}).get(document_type,{}).get('sections',{}).get(section_id,{})
        if not section:return {}
        evidence=[]
        for mapping in section.get('sourceMappings',[]):
            rel=mapping.get('path',''); fp=root/rel
            item={'path':rel,'matchedKeywords':[],'excerpts':[],'relevance':'low',
                  'sourceRole':mapping.get('sourceRole','reference'),'authorityLevel':mapping.get('authorityLevel','low'),
                  'directFactAllowed':bool(mapping.get('directFactAllowed',False))}
            try:
                text=' '.join(json.dumps(json.loads(fp.read_text(encoding='utf-8-sig')),ensure_ascii=False).split())
                for keyword in mapping.get('locatorKeywords',[]):
                    pos=text.find(str(keyword))
                    if pos>=0:
                        item['matchedKeywords'].append(str(keyword)); item['excerpts'].append(text[max(0,pos-80):pos+320])
                    if len(item['excerpts'])>=2: break
                item['relevance']='high' if len(item['matchedKeywords'])>=2 else ('medium' if item['matchedKeywords'] else 'low')
                matched='·'.join(item['matchedKeywords']) if item['matchedKeywords'] else '일치 키워드 없음'
                purpose='·'.join(str(v) for v in mapping.get('useFor',[])) or section.get('purpose','해당 사업계획서 항목')
                item['rationale']=(f'{rel} 파일에서 {matched}로 언급되어 있어 {purpose}에 맞춰 작성함'
                                   if item['matchedKeywords'] else
                                   f'{rel} 파일에서 항목 관련 키워드가 확인되지 않아 직접 근거로 사용하지 않음')
            except (OSError,ValueError,TypeError):
                item['readError']=True
            evidence.append(item)
        relevant=[e for e in evidence if e.get('relevance') in {'high','medium'}]
        excluded=[e for e in evidence if e.get('relevance')=='low']
        return {'criteria':section.get('criteria',[]),'purpose':section.get('purpose',''),
                'sourceRefs':section.get('sourceRefs',[]),'sourceMappings':section.get('sourceMappings',[]),
                'relevanceKeywords':section.get('relevanceKeywords',[]),'sourceEvidence':relevant,
                'excludedEvidence':excluded}
    except (OSError,ValueError,TypeError):
        return {}

def section_source(spec,canonical,original,research):
    selected={key:select_path(canonical,key) for key in spec['sourceKeys']}
    roots={k.split('.')[0] for k in spec['sourceKeys']}
    facts={}
    if roots & {'item_spec','development_goal','development_method','development_plan','production_plan','feasibility_plan','growth_strategy','market_analysis'}:
        facts.update(item=original['item'],period=original['period'])
    if roots & {'team_capability','resource_plan'}:facts.update(team=original['team'],resources=original['resources'])
    if roots & {'budget','feasibility_plan'}:facts['budget']=original['budget']
    if roots & {'schedule','development_plan','feasibility_plan'}:facts['schedule']=original['schedule']
    domains=set()
    if roots & {'market_analysis','growth_strategy'}:domains.add('market')
    if roots & {'development_method','architecture'}:domains.add('development')
    refs=[]
    def gather(value):
        if isinstance(value,dict):
            refs.extend(v for v in value.get('sourceRefs',[]) if isinstance(v,str))
            for v in value.values():gather(v)
        elif isinstance(value,list):
            for v in value:gather(v)
    gather(selected)
    evidence=[s for s in research if s['sourceRef'] in refs]
    if not evidence:evidence=[s for s in research if s['domain'] in domains][:4]
    strategy_provenance={root: _provenance(canonical.get(root, {})) for root in roots if root in canonical}
    for provenance in strategy_provenance.values():
        refs.extend(ref for ref in provenance.get('sourceRefs', []) if isinstance(ref, str))
    # Keep provenance from every upstream strategy output available to F16 and F19.
    return {**selected,'originalFacts':facts,'strategy_limits':original.get('strategy_limits',{}),'evidence':evidence,
            'documentType':spec.get('_documentType') or original.get('_documentType'),
            'strategyProvenance':strategy_provenance,'sourceRefs':sorted(set(refs))}


def _won(value):
    """back 표의 금액(예: '12,000,000원')을 정수로 변환한다."""
    if isinstance(value,(int,float)) and not isinstance(value,bool): return value
    digits=''.join(ch for ch in str(value or '') if ch.isdigit())
    return int(digits) if digits else 0


def _month(value):
    import re
    match=re.search(r'(20\d{2})[-./]?(\d{1,2})',str(value or ''))
    return f'{match.group(1)}-{int(match.group(2)):02d}' if match else None


def _period_months(rows):
    """'2026.05~2026.07' 같은 추진기간에서 모든 월을 읽어 (가장 이른 월, 가장 늦은 월)을 반환한다."""
    import re
    months=[f'{y}-{int(m):02d}' for row in rows for y,m in re.findall(r'(20\d{2})[-./]?(\d{1,2})',str(row.get('추진기간') or ''))]
    return (min(months),max(months)) if months else (None,None)


def _pre_startup_budget_phases(budget,items):
    """예비창업 예산을 1·2단계로 나눠 budget.phase_1/phase_2를 채운다.

    calculate_budget()은 모든 유형에서 phase_1/phase_2를 None으로 돌려주므로, 2.5.3/2.5.4가
    근거로 읽는 단계별 예산이 비어 검증이 1단계 표에 2단계 항목이 없다고 오판한다.
    """
    budget=dict(budget or {})
    for key,label in (('phase_1','1단계'),('phase_2','2단계')):
        rows=[row for row in items if row.get('phase')==label]
        budget[key]={'items':rows,'total':sum(row.get('total_amount',0) for row in rows),
                     'government_amount':sum(row.get('government_amount',0) for row in rows)}
    budget['items']=items; budget['phase']='1·2단계 구분(항목별 phase, phase_1/phase_2 참고)'
    return budget


def normalize_back_input(raw,kind):
    """back의 tableData/sectionText 계약을 파이프라인 입력으로 받는다."""
    if not isinstance(raw,dict): return raw
    if isinstance(raw.get('2_지금_입력받는값'),dict): return raw
    table=raw.get('tableData') or {}; text=raw.get('sectionText') or {}
    limits=raw.get('_strategy_limits') or raw.get('strategyLimits') or table.get('_strategy_limits') or {}
    if kind=='general':
        overview=table.get('기술개발_개요_및_필요성',{}); goal=table.get('기술개발_목표',{}); method=table.get('기술개발_방법',{}); commercial=table.get('사업화_계획',{})
        item=overview.get('개발대상_개요',''); output=goal.get('최종목표','')
        stages=method.get('단계별_개발계획',[]); budgets=commercial.get('사업비_집행계획',[]); schedules=stages
        start=_month(stages[0].get('기간')) if stages else None; end=_month(stages[-1].get('기간')) if stages else None
        plan={'main_industry':'일반 기술개발','dev_start_month':start,'dev_end_month':end,'ceo_capability':None,'ceo_careers':[],'strategy_limits':limits, 'no_partners':not bool(commercial.get('협력기관')), 'partners':commercial.get('협력기관',[])}
        project={'description':item,'output_summary':output,'tech_field':'일반 기술개발','target_customer':'확인 필요'}
        budget_rows=budgets
        members=[]
    elif kind=='pre_startup':
        status=table.get('generalStatus',{}); summary=table.get('itemSummary',{}); agreement=[{**row,'_schedule_scope':'agreement'} for row in (table.get('implementationSchedule') or [])]; roadmap=[{**row,'_schedule_scope':'roadmap'} for row in (table.get('fullScaleSchedule') or [])]; schedules=agreement+roadmap
        # 개발 기간은 협약기간 일정만으로 계산한다. fullScaleSchedule은 협약 이후 로드맵이라
        # _strategy_limits.deadline(협약 종료 기한) 비교에 넣지 않고, 표·일정 데이터에만 쓴다.
        dev_start,dev_end=_period_months(agreement)
        if limits.get('deadline'):
            limits={**limits,'deadlineScope':'협약 종료 기한. 협약기간 일정(implementationSchedule)에만 적용하며, 협약 이후 전체 사업단계 일정(fullScaleSchedule)은 이 기한을 넘어도 위반이 아님'}
        # teamPlan은 한글 키(직위·담당업무·보유역량)라 전략 함수가 읽는 role/experience로 옮긴다.
        team_rows=table.get('teamPlan') or []
        members=[{**row,'role':' - '.join(v for v in (row.get('직위'),row.get('담당업무')) if v),'experience':row.get('보유역량')} for row in team_rows]
        ceo=next((row for row in team_rows if '대표' in str(row.get('직위',''))),{})
        project={'description':summary.get('아이템개요') or summary.get('명칭'),'output_summary':status.get('산출물'),'tech_field':status.get('전문기술분야'),'target_customer':'확인 필요'}
        plan={'main_industry':status.get('지원분야'),'dev_start_month':dev_start,'dev_end_month':dev_end,'ceo_capability':ceo.get('보유역량'),'ceo_careers':[],'strategy_limits':limits,'no_partners':not bool(table.get('partnerPlan')),'partners':table.get('partnerPlan',[])}
        budget_rows=[{**row,'_phase':'1단계'} for row in table.get('budgetPlanStep1') or []]+[{**row,'_phase':'2단계'} for row in table.get('budgetPlanStep2') or []]
    elif kind=='early_startup':
        status=table.get('일반현황',{}); summary=table.get('창업아이템개요',{}); agreement=[{**row,'_schedule_scope':'agreement'} for row in (table.get('실현가능성_일정') or [])]; roadmap=[{**row,'_schedule_scope':'roadmap'} for row in (table.get('성장전략_일정') or [])]; schedules=agreement+roadmap
        project={'description':summary.get('아이템_개요') or status.get('창업아이템명'),'output_summary':status.get('산출물'),'tech_field':status.get('전문기술분야'),'target_customer':'확인 필요'}
        plan={'main_industry':status.get('지원분야'),'dev_start_month':_month(agreement[0].get('추진기간')) if agreement else None,'dev_end_month':_month(agreement[-1].get('추진기간')) if agreement else None,'ceo_capability':None,'ceo_careers':[],'strategy_limits':limits,'no_partners':not bool(table.get('협력기관')),'partners':table.get('협력기관',[])}
        budget_rows=table.get('사업비_집행계획',[]); members=table.get('팀구성현황',[])
    else: return raw
    schedules=[{**row,
                 'category':row.get('category') or row.get('구분') or row.get('단계') or row.get('추진내용','확인 필요'),
                 'task':row.get('task') or row.get('추진내용') or row.get('category') or row.get('단계','확인 필요'),
                 'period':row.get('period') or row.get('추진기간') or row.get('기간','미정'),
                 'details':row.get('details') or row.get('세부내용','')}
                for row in schedules]
    parsed_budget=[]
    for row in budget_rows:
        total=_won(row.get('총사업비')); government=_won(row.get('정부지원사업비')); cash=_won(row.get('자기부담_현금',row.get('자기부담금'))); in_kind=_won(row.get('자기부담_현물'))
        if total and government+cash+in_kind != total: total=government+cash+in_kind
        # '_phase'는 예비창업 분기에서만 붙이므로 다른 유형의 항목 모양은 그대로다.
        if total: parsed_budget.append({'category':row.get('비목','확인 필요'),'execution_plan':row.get('집행계획',''),'total_amount':total,'government_amount':government,'self_cash_amount':cash,'self_in_kind_amount':in_kind,**({'phase':row['_phase']} if row.get('_phase') else {})})
    return {'2_지금_입력받는값':{'POST_projects_body':project,'project_plan_inputs':plan,'project_budget_items':parsed_budget,'project_schedule_items':schedules,'team_members':members,'_back_source':raw}}


def table_arguments(raw,kind,spec,canonical):
    original=raw.get('2_지금_입력받는값',{}).get('_back_source',raw)
    tables=original.get('tableData',{})
    suffix='.'.join(spec['sectionId'].split('.')[1:])
    rows=[]; rules={'sectionId':spec['sectionId'],'additions':[], 'note':'원본 우선. 미입력 수량·단가·단계는 임의 생성하지 않음'}
    if kind!='general':
        key=({'5.2':'실현가능성_일정','6.2':'성장전략_일정','5.3':'사업비_집행계획'} if kind=='early_startup' else {'5.2':'implementationSchedule','6.2':'fullScaleSchedule','5.3':'budgetPlanStep1','5.4':'budgetPlanStep2'})[suffix]
        rows=copy.deepcopy(tables.get(key,[]))
        if kind=='early_startup' and suffix=='6.2':
            # Early-startup full schedule includes feasibility and scale-up.
            rows=copy.deepcopy(tables.get('실현가능성_일정',[]))+copy.deepcopy(tables.get('성장전략_일정',[]))
        if kind=='pre_startup' and suffix=='6.2':
            # 예비창업 '사업추진 일정(전체 사업단계)'은 협약기간 일정부터 이후 로드맵까지 모두 담는다.
            rows=copy.deepcopy(tables.get('implementationSchedule',[]))+rows
        if suffix in ('5.3','5.4'):
            if kind=='early_startup' and suffix=='5.3':
                # Initial-startup form has one business-expense plan; do not
                # apply the pre-startup two-phase budget split.
                for row in rows:row.setdefault('산출근거',row.get('집행계획','확인 필요'))
            elif kind=='early_startup':
                phase='1단계' if suffix=='5.3' else '2단계'
                unassigned=[r for r in rows if not r.get('단계')]
                rows=[r for r in rows if r.get('단계')==phase]
                rules.update(unassignedOriginalRows=unassigned,note='단계 미지정 원본은 별도 보존. 각 단계에 중복 배정하지 않음')
            for row in rows:row.setdefault('산출근거',row.get('집행계획','확인 필요'))
        # F17은 원본 표를 우선하지만, 저장된 back 입력에 표가 없거나
        # 경로가 다른 경우 정규화된 전략 결과를 보조 입력으로 사용한다.
        # 빈 표를 성공 결과로 저장하지 않도록 한다.
        if not rows and kind=='early_startup' and suffix=='5.2':
            rows=[{'구분':r.get('category','확인 필요'),'추진내용':r.get('task','확인 필요'),'추진기간':r.get('period','미정'),'세부내용':r.get('details','확인 필요')} for r in (canonical.get('schedule',[]) or []) if isinstance(r,dict)]
        if not rows and kind=='early_startup' and suffix=='5.3':
            rows=[{'비목':r.get('category',r.get('비목','확인 필요')),'산출근거':r.get('집행계획',r.get('산출근거','확인 필요')),'정부지원사업비':r.get('government_amount',r.get('정부지원사업비','확인 필요'))} for r in ((canonical.get('budget') or {}).get('items',[]) or []) if isinstance(r,dict)]
        if suffix in ('5.2','6.2'):
            rules['narrativeRequired']=True
            rules['narrativeType']='schedule'
        if suffix in ('5.3','5.4'):
            rules['narrativeRequired']=True
            rules['narrativeType']='budget'
    else:
        values=select_path(canonical,spec['sourceKeys'][0]) or []
        if suffix=='2.3':
            rows=[{'지표':r.get('name','확인 필요'),'단위':r.get('unit','확인 필요'),'목표값':r.get('target','확인 필요'),'측정환경':r.get('measurementEnvironment','확인 필요')} for r in values if isinstance(r,dict)]
        else:
            rows=[{'핵심기술':r if isinstance(r,str) else r.get('technology',r.get('name','확인 필요')),'개발기능':r.get('function','확인 필요') if isinstance(r,dict) else '확인 필요'} for r in values]
    return dict(columns=spec['rules']['requiredColumns'],rows=rows,rules=rules)

def _table_fallback_text(output, spec):
    """표 재작성 후에도 실패하면 저장할 본문 대체 문구를 만든다."""
    tables=output.get('tables',[]) if isinstance(output,dict) else []
    table=tables[0] if tables and isinstance(tables[0],dict) else {}
    columns=table.get('columns') or spec.get('rules',{}).get('requiredColumns',[])
    rows=table.get('rows') or []
    if rows:
        lines=['; '.join(f'{col}: {row.get(col,"확인 필요")}' for col in columns) for row in rows if isinstance(row,dict)]
        return '표 구조 검증에 실패하여 본문 설명으로 대체함.\n'+'\n'.join(f'· {line}' for line in lines)
    return '표 구조 검증에 실패하여 본문 설명으로 대체함. 원본 행과 필수 항목을 확인한 뒤 다시 작성해야 함.'

def _attach_provenance(fid, value, kwargs):
    """F02~F15의 모든 표준 결과에 상위 근거와 사실을 보존한다."""
    if not isinstance(value, dict) or fid not in {f"F{i:02}" for i in range(1, 16)}:
        return value
    refs=[]; evidence=[]
    def walk(node):
        if isinstance(node, dict):
            ref=node.get("sourceRef")
            if isinstance(ref, str): refs.append(ref)
            if isinstance(node.get("sources"), list):
                evidence.extend(x for x in node["sources"] if isinstance(x, dict) and isinstance(x.get("sourceRef"), str))
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(kwargs)
    if not value.get("sourceRefs"):
        value["sourceRefs"] = sorted(set(refs))
    if not value.get("evidence"):
        value["evidence"] = evidence
    # Keep the exact input contract available to F16/F19 without replacing generated fields.
    if not value.get("originalFacts"):
        value["originalFacts"] = kwargs.get("originalFacts") or {k: v for k, v in kwargs.items() if k not in {"research_data", "market_data", "competitor_data", "constraints"}}
    return value

def _reconcile_validation(spec, output, validation):
    """LLM 진단과 충돌할 때 검증된 저장 구조를 우선한다."""
    if not isinstance(validation, dict):
        return validation
    issues=[str(x) for x in validation.get('issues',[]) if x]
    tables=output.get('tables') if isinstance(output,dict) else None
    rules=spec.get('rules',{}) if isinstance(spec,dict) else {}
    required=set(rules.get('requiredColumns',[]) or [])
    valid_table=bool(tables) and all(required.issubset(set(t.get('columns',[]) or [])) for t in tables if isinstance(t,dict))
    # 일부 문서 계약은 contentType을 section으로 유지하면서 F17 표를
    # 포함한다. requiredColumns/F17 기준으로 실제 저장 표를 판정한다.
    if (spec.get('contentType')=='table' or spec.get('functionId')=='F17' or required) and valid_table:
        issues=[i for i in issues if not ('필수 표' in i or 'tables의 columns/rows 구조' in i or 'tables.columns' in i or 'tables.rows' in i or '표 형식 텍스트만' in i or 'content.tables' in i)]
    if spec.get('contentType')=='image' and isinstance(output.get('imageSpecs'),list):
        types={x.get('flowType') for x in output['imageSpecs'] if isinstance(x,dict)}
        if {'USER_FLOW','SERVICE_ARCHITECTURE'}.issubset(types):
            issues=[i for i in issues if 'SERVICE_ARCHITECTURE' not in i and '이미지 명세' not in i]
    # A schedule/budget table must preserve rows, but does not need to repeat
    # every feature name from the strategy featureList.
    if spec.get('functionId')=='F17':
        issues=[i for i in issues if 'featureList 누락' not in i]
    validation['issues']=issues
    if validation.get('status')=='fail' and not issues:
        validation['status']='warning' if validation.get('warnings') else 'pass'
    return validation

def _remove_roadmap_deadline_warnings(validation, source, kind):
    """초기창업의 협약 이후 성장 로드맵을 협약기간 위반으로 중복 경고하지 않는다."""
    if kind != 'early_startup' or not isinstance(validation, dict):
        return validation
    facts = source.get('originalFacts', {}) if isinstance(source, dict) else {}
    rows = facts.get('schedule', []) if isinstance(facts, dict) else []
    roadmap = [r for r in rows if isinstance(r, dict) and r.get('_schedule_scope') == 'roadmap']
    agreement = [r for r in rows if isinstance(r, dict) and r.get('_schedule_scope') != 'roadmap']
    if roadmap and agreement:
        validation['warnings'] = [w for w in validation.get('warnings', [])
                                  if not ('협약기간' in str(w) and ('일정' in str(w) or '종료' in str(w)))]
    return validation

def _check_agreement_table_overrun(validation, spec, output, source, kind):
    """협약기간용 개발계획 표가 원본 협약 일정의 종료월을 넘는지 검사한다."""
    if kind != 'early_startup' or spec.get('sectionId') != '3.5.2' or not isinstance(validation, dict):
        return validation
    facts = source.get('originalFacts', {}) if isinstance(source, dict) else {}
    rows = facts.get('schedule', []) if isinstance(facts, dict) else []
    agreement = [r for r in rows if isinstance(r, dict) and r.get('_schedule_scope') != 'roadmap']
    tables = output.get('tables', []) if isinstance(output, dict) else []
    if not agreement or not tables:
        return validation
    def months(value):
        return [f'{y}-{int(m):02d}' for y,m in re.findall(r'(20\d{2})[-./~년\s]*(\d{1,2})', str(value or ''))]
    source_end=max((m for r in agreement for m in months(r.get('period') or r.get('추진기간') or r.get('기간'))), default=None)
    generated_end=max((m for t in tables if isinstance(t,dict) for r in (t.get('rows') or []) if isinstance(r,dict) for m in months(r.get('추진기간') or r.get('period') or r.get('기간'))), default=None)
    if source_end and generated_end and generated_end > source_end:
        validation.setdefault('issues', []).append(f'개발계획 표 종료월 {generated_end}이 원본 협약 일정 종료월 {source_end} 이후임')
        validation['status']='fail'
        validation['warnings']=[w for w in validation.get('warnings',[]) if '기간 정합성' not in str(w)]
    return validation

def run_pipeline(raw,kind,progress=None,render_image=None,max_rewrites=1,execution_scope='full'):
    started_at=datetime.now(timezone.utc).isoformat()
    started_clock=time.perf_counter()
    if kind not in CONTRACT['documents']:raise ValueError('문서 유형 오류')
    if execution_scope not in {'full','strategy_writing'}:raise ValueError('실행 범위 오류')
    if not isinstance(raw,dict):raise ValueError('입력 JSON은 객체여야 합니다.')
    raw=normalize_back_input(raw,kind)
    inp=raw.get('2_지금_입력받는값',raw)
    project=inp.get('POST_projects_body')
    if not isinstance(project,dict) or not project.get('description'):raise ValueError('POST_projects_body.description이 필요합니다.')
    plan=inp.get('project_plan_inputs') or {}
    budgets=inp.get('project_budget_items') or []; schedules=inp.get('project_schedule_items') or []
    for row in budgets:
        values=[row.get(k,0) for k in ['total_amount','government_amount','self_cash_amount','self_in_kind_amount']]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or v<0 for v in values) or values[0]!=sum(values[1:]):
            raise ValueError('예산 총액·정부지원·자기부담 합계를 확인하세요.')
    duration=0
    if plan.get('dev_start_month') and plan.get('dev_end_month'):
        start=datetime.strptime(plan['dev_start_month'],'%Y-%m');end=datetime.strptime(plan['dev_end_month'],'%Y-%m')
        duration=(end.year-start.year)*12+end.month-start.month+1
        if duration<1:raise ValueError('개발 종료월이 시작월보다 빠릅니다.')
    trace=[]
    # Keep completed section rows available even when a later model call
    # fails. The server uses these snapshots to persist a partial result.
    sections=[]; images=[]; decisions=[]; selected_chars=0; full_chars=0
    def call(fid,fn,**kwargs):
        if progress:progress(f'{fid} {fn.__name__} 실행 중',len(trace))
        started=time.monotonic()
        try: value=fn(**kwargs)
        except Exception as exc:
            exc.partial_trace=trace
            exc.partial_results=copy.deepcopy(sections)
            exc.partial_images=copy.deepcopy(images)
            raise
        value=_attach_provenance(fid, value, kwargs)
        trace.append({'functionId':fid,'functionName':fn.__name__,'module':fn.__module__,
                      'durationMs':round((time.monotonic()-started)*1000),'inputChars':len(json.dumps(kwargs,ensure_ascii=False,separators=(',',':'))),
                      'inputKeys':list(kwargs),'output':value,'model':value.get('model'),'usage':value.get('usage',{}),'status':value.get('status','returned')})
        return value
    query=project['description']+' '+project.get('tech_field','')
    industry_refresh=refresh_user_industry_research(project)
    web=call('F01',py.collect_web_data,query=query,source_type='attached_crawling',target_fields=['market','development','design'])
    market_evidence=retrieve(query,domains=('market',),limit=4,char_budget=5500)
    competitor_evidence=retrieve(query+' 경쟁사 경쟁 비교',domains=('market',),limit=4,char_budget=4500)
    dev_evidence=retrieve(query,domains=('development',),limit=3,char_budget=3000)
    evidence={s['sourceRef']:s for context in [web,market_evidence,competitor_evidence,dev_evidence] for s in context['sources']}
    item_input={k:project.get(k) for k in ['description','output_summary','tech_field','target_customer']}
    c={'web_data':{'sources':web['sources'],'issues':web['issues']}}
    c['item_spec']=_annotate_status('F02',compact(call('F02',gpt.analyze_item,item_input=item_input,research_data=dev_evidence)),{'item_input':item_input,'research_data':dev_evidence})
    c['market_analysis']=compact(call('F03',gpt.analyze_market,item=c['item_spec'],market_data=market_evidence,analysis_type='need_and_trend'))
    competitors=compact(call('F04',gpt.analyze_competitors,item=c['item_spec'],market_data=c['market_analysis'],competitor_data=competitor_evidence))
    team_input={'representative':{'capabilities':plan.get('ceo_capability'),'careers':plan.get('ceo_careers',[])},
                'members':[{k:r.get(k) for k in ['role','experience']} for r in inp.get('team_members',[])]}
    requirements=c['item_spec'].get('coreFeatures') or [project.get('tech_field','')]
    c['team_capability']=compact(call('F05',gpt.analyze_team_capability,team_data=team_input,item_requirements=requirements))
    c['development_goal']=_annotate_status('F06',compact(call('F06',gpt.define_development_goal,item_spec=c['item_spec'],duration=duration,target_field=project.get('tech_field',''))),{'item_spec':c['item_spec'],'duration':duration,'target_field':project.get('tech_field','')})
    c['development_method']=compact(call('F07',gpt.define_development_method,core_technologies=c['development_goal'].get('core_technologies',requirements),constraints={'duration':duration,'research':dev_evidence}))
    c['architecture']=c['development_method'].get('architecture',{})
    c['development_plan']=_annotate_status('F08',compact(call('F08',gpt.create_development_plan,goals=c['development_goal'],duration=duration,phases=schedules)),{'goals':c['development_goal'],'duration':duration,'phases':schedules})
    c['production_plan']=_annotate_status('F09',compact(call('F09',gpt.create_production_plan,product=c['item_spec'],development_plan=c['development_plan'],phases=schedules)),{'product':c['item_spec'],'development_plan':c['development_plan'],'phases':schedules})
    c['marketing_strategy']=compact(call('F10',gpt.create_marketing_strategy,item=c['item_spec'],market=c['market_analysis'],target_customer=project.get('target_customer','미입력'),stage='초기시장'))
    bm=compact(call('F11',gpt.create_business_model,item=c['item_spec'],market=c['market_analysis'],customer=project.get('target_customer','미입력'),strategy=c['marketing_strategy']))
    c['growth_strategy']=compact(call('F12',gpt.create_growth_strategy,market=c['market_analysis'],competitors=competitors,bm=bm,investment={},social_value={}))
    resource_input={k:plan.get(k) for k in ['no_hires','hires','no_equipment','equipment','no_partners','partners','self_in_kind_resources']}
    c['resource_plan']=compact(call('F13',gpt.create_resource_plan,item=c['item_spec'],required_capabilities=requirements,team={'analysis':c['team_capability'],'originalFacts':resource_input},resource_type=['장비','채용','협력기관']))
    c['budget']=compact(call('F14',py.calculate_budget,items=budgets,quantity=[1]*len(budgets),unit_price=[r['total_amount'] for r in budgets],phase='미구분',rules={'self_funding_allowed':plan.get('self_funding_allowed')}))
    if kind=='pre_startup':c['budget']=_pre_startup_budget_phases(c['budget'],budgets)
    c['schedule']=compact(call('F15',py.create_schedule,tasks=[r['category'] for r in schedules],duration=duration,milestones=schedules))
    c['feasibility_plan']={'goal':c['development_goal'],'development':c['development_plan'],'budget':c['budget']}
    original={'item':item_input,'period':{'start':plan.get('dev_start_month'),'end':plan.get('dev_end_month'),'durationMonths':duration},'strategy_limits':plan.get('strategy_limits',{}),'team':team_input,'resources':resource_input,
              'budget':{k:c['budget'][k] for k in ['items','total','government_amount','self_cash_amount','self_in_kind_amount','phase']},'schedule':schedules,'strategyOutputs':{k:_provenance(v) for k,v in c.items() if not k.startswith('_')}}
    for base_spec in CONTRACT['documents'][kind]:
        spec=copy.deepcopy(base_spec)
        sid=spec['sectionId']
        spec['_documentType']=kind
        if not spec['enabled']:
            sections.append({**spec,'generatedText':'표 생성 제외 (사용자 지정)','tables':[],'images':[],'validation':{'status':'skipped','agent':'검증 1','issues':[]},'status':'skipped'})
            continue
        source=section_source(spec,c,original,list(evidence.values()))
        if kind=='general' and duration>=12 and sid in ['1.2.1','1.3.1']:
            spec['rules']['stages']=['1차','2차']
        full_chars+=len(json.dumps(c,ensure_ascii=False)); selected_chars+=len(json.dumps(source,ensure_ascii=False))
        attempts=[]
        # 재작성은 UI의 통합 회귀 재작성 컨트롤러가 담당한다. 전체 실행은
        # 항목을 한 번만 생성하고 검증 결과를 반환하며, 실패 항목의 추가
        # 호출은 /api/retry-latest를 통해서만 수행한다.
        attempt_limit=2 if spec['functionId']=='F17' else 1
        for attempt in range(attempt_limit):
            if spec['functionId']=='F17':
                image_outputs=[]
                output=call('F17',py.generate_table,**table_arguments(raw,kind,spec,c))
            elif spec['functionId']=='F18':
                output=call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':attempts[-1]['validation']['issues'] if attempts else []},flow_type='USER_FLOW')
                image_outputs=[output,call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':attempts[-1]['validation']['issues'] if attempts else []},flow_type='SERVICE_ARCHITECTURE')]
            else:
                output=call('F16',gpt.generate_section,section_spec=spec,source_data=source,writing_rules={'documentType':kind,'sectionCriteria':_writing_criteria(kind,sid),'tableGenerationEnabled':False,
                            'validationFeedback':attempts[-1]['validation']['issues'] if attempts else [],'previousText':attempts[-1]['generatedText'] if attempts else None,'preserveProvenance':True,'statusPolicy':['provided','proposed','needs_confirmation']})
                image_outputs=[output]
            # Validate the same body that will be stored; repeated section
            # headings must not consume maxLines or exact-item limits.
            if spec['functionId']=='F16':
                output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
            output=_normalize_section_output(output,spec,source,kind)
            if spec['functionId']=='F18':
                output=_normalize_image_output(output,'USER_FLOW')
                image_outputs[0]=output
                if len(image_outputs)>1:
                    image_outputs[1]=_normalize_image_output(image_outputs[1],'SERVICE_ARCHITECTURE')
                output['imageSpecs']=copy.deepcopy(image_outputs)
                output['imageTypes']=['USER_FLOW','SERVICE_ARCHITECTURE']
                # F19 must see both requested image specifications, while the
                # legacy top-level nodes/flowType remain the USERFLOW contract.
                output['imageSpecs']=copy.deepcopy(image_outputs)
                output['imageTypes']=['USER_FLOW','SERVICE_ARCHITECTURE']
            validation=(call('F19',py.validate_section,section_spec=spec,content=output,source_data=source)
                        if execution_scope=='full' else {'status':'not_run','agent':'검증 1','issues':[]})
            validation=_reconcile_validation(spec,output,validation)
            validation=_remove_roadmap_deadline_warnings(validation,source,kind)
            validation=_check_agreement_table_overrun(validation,spec,output,source,kind)
            if (kind=='early_startup' and spec['functionId']=='F17' and sid == '3.5.3'
                    and output.get('tables') and output['tables'][0].get('rows')==[]
                    and output['tables'][0].get('rules',{}).get('unassignedOriginalRows')):
                # An unassigned source budget is intentionally not allocated to
                # either phase. Treat this as confirmation-needed, not a hard
                # table failure, while preserving the original rows.
                validation['issues']=[i for i in validation.get('issues',[]) if '필수 표' not in str(i) and '예산' not in str(i)]
                validation.setdefault('warnings',[]).append('단계 미지정 원본 사업비가 보존되어 단계 확정이 필요함')
                validation['status']='warning' if not validation.get('issues') else validation.get('status','fail')
            attempts.append({'attempt':attempt+1,'generatedText':output['generatedText'],'validation':validation,'responseId':output.get('responseId')})
            if execution_scope!='full' or validation['status'] in {'pass','warning'}:break
        if spec['functionId']=='F17' and validation.get('status')=='fail':
            reason=' · '.join(str(x) for x in validation.get('issues',[]) if x) or '표 필수 구조 검증 실패'
            output['generatedText']=_table_fallback_text(output,spec)
            output['tables']=[]
            output['tableFallbackUsed']=True
            output['fallbackReason']=reason
        rendered=[]
        if spec['functionId']=='F18' and render_image:
            rendered=[render_image(item) for item in image_outputs];images.extend(rendered)
        output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
        sections.append({**spec,'generatedText':output['generatedText'],'tables':output.get('tables',[]),'images':rendered,'functionOutput':output,'validationSource':source,'validation':validation,'evaluation':score_section(spec,output,validation,kind,source),'attempts':attempts,'sourceKeys':list(spec['sourceKeys'])})
        decisions.append({'sectionId':sid,'status':validation['status'],'attemptCount':len(attempts)})
    # Build the summary from the final stored rows. Retry/validation passes can
    # replace an earlier failed attempt; the top-level summary must never keep
    # that stale intermediate status.
    decisions=[{'sectionId':row.get('sectionId'),'status':row.get('validation',{}).get('status','not_run'),
                'attemptCount':len(row.get('attempts',[]))} for row in sections]
    failed=execution_scope=='full' and any(s.get('validation',{}).get('status')=='fail' for s in sections)
    document=None if execution_scope!='full' or failed else call('F20',py.assemble_document,sections=sections,tables=[t for row in sections for t in row.get('tables',[])],images=images)
    usage={'input_tokens':0,'output_tokens':0,'total_tokens':0}
    for event in trace:
        for key in usage:usage[key]+=event.get('usage',{}).get(key,0)
    return {'runId':str(uuid.uuid4()),'createdAt':datetime.now(timezone.utc).isoformat(),'startedAt':started_at,'completedAt':datetime.now(timezone.utc).isoformat(),'elapsedSeconds':round(time.perf_counter()-started_clock,3),'documentType':kind,
            'status':'strategy_writing_completed' if execution_scope=='strategy_writing' else ('validation1_failed' if failed else 'validation1_passed'),
            'message':'전략(F01~F15)과 작성(F16/F18)만 완료했습니다. 검증 1(F19)과 조립(F20)은 실행하지 않았습니다.' if execution_scope=='strategy_writing' else ('검증 1 미통과 항목이 있어 최종 조립을 보류했습니다.' if failed else '검증 1 통과 및 조립 완료. 원본 기반 표 포함. 실제 문서 페이지 수는 별도 확인이 필요합니다.'),
            'results':sections,'evaluationSummary':aggregate_scores(sections),'document':document,'trace':trace,'validation1':decisions,'usage':usage,
            'executionScope':execution_scope,
            'contextMetrics':{'selectedSectionChars':selected_chars,'fullCanonicalCharsIfRepeated':full_chars,'note':'문자 수 비교이며 토큰 청구량은 usage 참조'},
            'research':{'sources':list(evidence.values()),'availableFiles':web['availableFiles'],'issues':market_evidence['issues']+competitor_evidence['issues']+dev_evidence['issues'],'industryRefresh':industry_refresh},
            'skippedFunctions':[]}


def impact_plan(kind, section_id):
    """선택한 작성 항목과 표준 입력을 공유하는 항목을 반환한다."""
    specs = CONTRACT['documents'].get(kind)
    if not specs:
        raise ValueError('문서 유형 오류')
    target = next((spec for spec in specs if spec['sectionId'] == section_id), None)
    if not target:
        raise ValueError('사업계획서 항목 위치를 찾을 수 없습니다.')
    if not target['enabled']:
        raise ValueError('표 생성 제외 항목은 재시도할 수 없습니다.')
    roots = {key.split('.')[0] for key in target['sourceKeys']}
    affected = []
    for spec in specs:
        if not spec['enabled']:
            continue
        linked = sorted(roots & {key.split('.')[0] for key in spec['sourceKeys']})
        if linked:
            affected.append({'sectionId': spec['sectionId'], 'title': spec['title'], 'functionId': spec['functionId'], 'linkedSources': linked})
    upstream_by_root={
        'web_data':['F01'], 'item_spec':['F02'], 'market_analysis':['F03','F04','F10','F11','F12'],
        'team_capability':['F05'], 'development_goal':['F06'], 'development_method':['F07'],
        'development_plan':['F08','F09','F15'], 'production_plan':['F09'],
        'marketing_strategy':['F10'], 'growth_strategy':['F12'], 'resource_plan':['F13'],
        'budget':['F14'], 'schedule':['F15'], 'architecture':['F07']
    }
    upstream=[]
    for root in sorted(roots):
        for fid in upstream_by_root.get(root,[]):
            if fid not in upstream: upstream.append(fid)
    downstream=[]
    for row in affected:
        if row['functionId'] not in downstream: downstream.append(row['functionId'])
    selected_function=target['functionId']
    rewrite_functions={
        'selected':selected_function,
        'upstreamStrategy':upstream,
        'downstreamWriting':downstream,
        'validation':['F19'],
        'assembly':['F20'],
        'executionNote':'현재 재시도 API는 선택·연관 작성 항목과 F19/F20을 실행하며, upstreamStrategy는 영향 기록용 목록이다.'
    }
    return {'selected': {'sectionId':target['sectionId'], 'title':target['title'], 'sourceKeys':target['sourceKeys']},
            'affected': affected,
            'rewriteFunctions':rewrite_functions,
            'reason': '선택 항목과 같은 Canonical Data를 쓰는 항목을 함께 재생성합니다. 전략 F01~F15는 다시 호출하지 않습니다.'}


def _retry_context(raw, result):
    inp = raw.get('2_지금_입력받는값', raw)
    project = inp['POST_projects_body']
    plan = inp.get('project_plan_inputs') or {}
    budgets = inp.get('project_budget_items') or []
    schedules = inp.get('project_schedule_items') or []
    duration = 0
    if plan.get('dev_start_month') and plan.get('dev_end_month'):
        start=datetime.strptime(plan['dev_start_month'],'%Y-%m'); end=datetime.strptime(plan['dev_end_month'],'%Y-%m')
        duration=(end.year-start.year)*12+end.month-start.month+1
    outputs = {entry['functionId']: entry['output'] for entry in result['trace'] if entry['functionId'] in {f'F{i:02}' for i in range(1,16)}}
    canonical = {
        'web_data': compact(outputs.get('F01', {})), 'item_spec': compact(outputs['F02']),
        'market_analysis': compact(outputs['F03']), 'team_capability': compact(outputs['F05']),
        'development_goal': compact(outputs['F06']), 'development_method': compact(outputs['F07']),
        'development_plan': compact(outputs['F08']), 'production_plan': compact(outputs['F09']),
        'marketing_strategy': compact(outputs['F10']), 'growth_strategy': compact(outputs['F12']),
        'resource_plan': compact(outputs['F13']), 'budget': compact(outputs['F14']), 'schedule': compact(outputs['F15']),
    }
    canonical['architecture']=canonical['development_method'].get('architecture',{})
    canonical['feasibility_plan']={'goal':canonical['development_goal'],'development':canonical['development_plan'],'budget':canonical['budget']}
    item_input={key:project.get(key) for key in ['description','output_summary','tech_field','target_customer']}
    team_input={'representative':{'capabilities':plan.get('ceo_capability'),'careers':plan.get('ceo_careers',[])},
                'members':[{key:row.get(key) for key in ['role','experience']} for row in inp.get('team_members',[])]}
    resource_input={key:plan.get(key) for key in ['no_hires','hires','no_equipment','equipment','no_partners','partners','self_in_kind_resources']}
    original={'item':item_input,'period':{'start':plan.get('dev_start_month'),'end':plan.get('dev_end_month'),'durationMonths':duration},
              'team':team_input,'resources':resource_input,
              'budget':{key:canonical['budget'].get(key) for key in ['items','total','government_amount','self_cash_amount','self_in_kind_amount','phase']},
              'schedule':schedules}
    return canonical, original, duration


def retry_sections(raw, prior_result, section_id, retry_instruction='', progress=None, render_image=None, max_rewrites=1):
    started_at=datetime.now(timezone.utc).isoformat()
    started_clock=time.perf_counter()
    """선택 항목과 직접 표준 입력을 공유하는 항목을 함께 재생성한다."""
    kind=prior_result['documentType']
    plan=impact_plan(kind, section_id)
    result=copy.deepcopy(prior_result)
    canonical, original, duration=_retry_context(raw, result)
    if kind=='pre_startup':
        # 재시도는 저장된 F14 결과를 재사용하므로, 단계 구분이 없던 이전 실행 결과에도 현재 입력의 단계 정보를 반영한다.
        budget_items=raw.get('2_지금_입력받는값',raw).get('project_budget_items') or []
        canonical['budget']=_pre_startup_budget_phases(canonical['budget'],budget_items)
        canonical['feasibility_plan']['budget']=canonical['budget']
        original['budget']={key:canonical['budget'].get(key) for key in ['items','total','government_amount','self_cash_amount','self_in_kind_amount','phase']}
    specs={spec['sectionId']:copy.deepcopy(spec) for spec in CONTRACT['documents'][kind]}
    rows={row['sectionId']:row for row in result['results']}
    trace=result['trace']

    def call(fid,fn,**kwargs):
        if progress:progress(f'재시도: {fid} {fn.__name__} 실행 중',len(trace))
        started=time.monotonic(); value=fn(**kwargs)
        value=_attach_provenance(fid, value, kwargs)
        trace.append({'functionId':fid,'functionName':fn.__name__,'module':fn.__module__,
                      'durationMs':round((time.monotonic()-started)*1000),'inputChars':len(json.dumps(kwargs,ensure_ascii=False,separators=(',',':'))),
                      'inputKeys':list(kwargs),'output':value,'model':value.get('model'),'usage':value.get('usage',{}),'status':value.get('status','returned'),'retryOf':prior_result['runId']})
        return value

    evidence=result.get('research',{}).get('sources',[])
    for affected in plan['affected']:
        spec=specs[affected['sectionId']]
        spec['_documentType']=kind
        source=section_source(spec,canonical,original,evidence)
        if kind=='general' and duration>=12 and spec['sectionId'] in ['1.2.1','1.3.1']:
            spec['rules']['stages']=['1차','2차']
        previous=rows[spec['sectionId']]
        attempts=[]
        # 이 함수는 한 번의 회귀 재작성만 수행한다. 항목별 최대 횟수와
        # 자동 반복은 프런트의 통합 회귀 재작성 정책이 관리한다.
        retry_attempt_limit=2 if spec['functionId']=='F17' else 1
        for attempt in range(retry_attempt_limit):
            feedback=attempts[-1]['validation']['issues'] if attempts else []
            if spec['functionId']=='F17':
                image_outputs=[]
                output=call('F17',py.generate_table,**table_arguments(normalize_back_input(raw,kind),kind,spec,canonical))
            elif spec['functionId']=='F18':
                output=call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':feedback,'retryInstruction':retry_instruction},flow_type='USER_FLOW')
                image_outputs=[output,call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':feedback,'retryInstruction':retry_instruction},flow_type='SERVICE_ARCHITECTURE')]
            else:
                output=call('F16',gpt.generate_section,section_spec=spec,source_data=source,
                            writing_rules={'documentType':kind,'sectionCriteria':_writing_criteria(kind,spec['sectionId']),'tableGenerationEnabled':False,'retryInstruction':retry_instruction,
                                           'validationFeedback':feedback,'previousText':previous.get('generatedText') if not attempts else attempts[-1]['generatedText'],'preserveProvenance':True,'statusPolicy':['provided','proposed','needs_confirmation']})
                image_outputs=[output]
            if spec['functionId']=='F16':
                output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
            output=_normalize_section_output(output,spec,source,kind)
            if spec['functionId']=='F18':
                output=_normalize_image_output(output,'USER_FLOW')
                image_outputs[0]=output
                if len(image_outputs)>1:
                    image_outputs[1]=_normalize_image_output(image_outputs[1],'SERVICE_ARCHITECTURE')
                output['imageSpecs']=copy.deepcopy(image_outputs)
                output['imageTypes']=['USER_FLOW','SERVICE_ARCHITECTURE']
            validation=call('F19',py.validate_section,section_spec=spec,content=output,source_data=source)
            validation=_reconcile_validation(spec,output,validation)
            validation=_remove_roadmap_deadline_warnings(validation,source,kind)
            validation=_check_agreement_table_overrun(validation,spec,output,source,kind)
            if (kind=='early_startup' and spec['functionId']=='F17' and spec['sectionId'] == '3.5.3'
                    and output.get('tables') and output['tables'][0].get('rows')==[]
                    and output['tables'][0].get('rules',{}).get('unassignedOriginalRows')):
                validation['issues']=[i for i in validation.get('issues',[]) if '필수 표' not in str(i) and '예산' not in str(i)]
                validation.setdefault('warnings',[]).append('단계 미지정 원본 사업비가 보존되어 단계 확정이 필요함')
                validation['status']='warning' if not validation.get('issues') else validation.get('status','fail')
            attempts.append({'attempt':attempt+1,'generatedText':output['generatedText'],'validation':validation,'responseId':output.get('responseId')})
            if validation['status'] in {'pass','warning'}:break
        if spec['functionId']=='F17' and validation.get('status')=='fail':
            reason=' · '.join(str(x) for x in validation.get('issues',[]) if x) or '표 필수 구조 검증 실패'
            output['generatedText']=_table_fallback_text(output,spec)
            output['tables']=[]
            output['tableFallbackUsed']=True
            output['fallbackReason']=reason
        images=[]
        if spec['functionId']=='F18' and validation['status'] in {'pass','warning'} and render_image:
            images=[render_image(item) for item in image_outputs]
        output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
        rows[spec['sectionId']]={**previous,**spec,'generatedText':output['generatedText'],'tables':output.get('tables',[]), 'images':images,
                                 'validationSource':source,
                                 'functionOutput':output,'validation':validation,'evaluation':score_section(spec,output,validation,kind,source),'attempts':previous.get('attempts',[])+attempts,
                                 'sourceKeys':list(spec['sourceKeys']),'retryInstruction':retry_instruction}
    result['results']=[rows[row['sectionId']] for row in result['results']]
    result['evaluationSummary']=aggregate_scores(result['results'])
    failed=any(row['validation']['status']=='fail' for row in result['results'])
    images=[image for row in result['results'] for image in row.get('images',[])]
    result['document']=None if failed else call('F20',py.assemble_document,sections=result['results'],tables=[t for row in result['results'] for t in row.get('tables',[])],images=images)
    result['status']='validation1_failed' if failed else 'validation1_passed'
    result['message']='재시도 후 검증 1 미통과 항목이 있어 최종 조립을 보류했습니다.' if failed else '선택 항목과 연관 항목 재생성 및 검증 1 완료.'
    result['runId']=str(uuid.uuid4()); result['createdAt']=datetime.now(timezone.utc).isoformat(); result['startedAt']=started_at; result['completedAt']=datetime.now(timezone.utc).isoformat(); result['elapsedSeconds']=round(time.perf_counter()-started_clock,3)
    retry_event={'timestamp':result['createdAt'],'mode':'manual','selectedSectionId':section_id,'instruction':retry_instruction,'impact':plan,'status':result['status']}
    result['retryHistory']=list(prior_result.get('retryHistory',[]))+[retry_event]
    result['retry']={'parentRunId':prior_result['runId'],'selectedSectionId':section_id,'instruction':retry_instruction,'impact':plan}
    result['usage']={key:sum(event.get('usage',{}).get(key,0) for event in trace) for key in ['input_tokens','output_tokens','total_tokens']}
    return result




