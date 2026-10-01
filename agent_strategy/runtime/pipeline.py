"""Canonical strategy once; narrow section inputs; validation 1 and bounded rewrite."""
import copy
import json
import os
import re
import time
import uuid
from datetime import datetime,timezone
from agent_strategy import gpt_functions as gpt, python_functions as py
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


def refresh_user_industry_research(project):
    """Optionally refresh KIET data for the current user's industry keyword."""
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
    """Mark strategy facts as provided/proposed/needs_confirmation for downstream F16/F19."""
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
            'strategyProvenance':strategy_provenance,'sourceRefs':sorted(set(refs))}


def _won(value):
    """Convert a back table amount such as '12,000,000원' to an integer."""
    if isinstance(value,(int,float)) and not isinstance(value,bool): return value
    digits=''.join(ch for ch in str(value or '') if ch.isdigit())
    return int(digits) if digits else 0


def _month(value):
    import re
    match=re.search(r'(20\d{2})[-./]?(\d{1,2})',str(value or ''))
    return f'{match.group(1)}-{int(match.group(2)):02d}' if match else None


def normalize_back_input(raw,kind):
    """Accept the back tableData/sectionText contract as pipeline input."""
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
        status=table.get('generalStatus',{}); summary=table.get('itemSummary',{}); schedules=(table.get('implementationSchedule') or [])+(table.get('fullScaleSchedule') or [])
        project={'description':summary.get('아이템개요') or summary.get('명칭'),'output_summary':status.get('산출물'),'tech_field':status.get('전문기술분야'),'target_customer':'확인 필요'}
        plan={'main_industry':status.get('지원분야'),'dev_start_month':_month(schedules[0].get('추진기간')) if schedules else None,'dev_end_month':_month(schedules[-1].get('추진기간')) if schedules else None,'ceo_capability':None,'ceo_careers':[],'strategy_limits':limits,'no_partners':not bool(table.get('partnerPlan')),'partners':table.get('partnerPlan',[])}
        budget_rows=(table.get('budgetPlanStep1') or [])+(table.get('budgetPlanStep2') or []); members=table.get('teamPlan',[])
    elif kind=='early_startup':
        status=table.get('일반현황',{}); summary=table.get('창업아이템개요',{}); schedules=(table.get('실현가능성_일정') or [])+(table.get('성장전략_일정') or [])
        project={'description':summary.get('아이템_개요') or status.get('창업아이템명'),'output_summary':status.get('산출물'),'tech_field':status.get('전문기술분야'),'target_customer':'확인 필요'}
        plan={'main_industry':status.get('지원분야'),'dev_start_month':_month(schedules[0].get('추진기간')) if schedules else None,'dev_end_month':_month(schedules[-1].get('추진기간')) if schedules else None,'ceo_capability':None,'ceo_careers':[],'strategy_limits':limits,'no_partners':not bool(table.get('협력기관')),'partners':table.get('협력기관',[])}
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
        if total: parsed_budget.append({'category':row.get('비목','확인 필요'),'execution_plan':row.get('집행계획',''),'total_amount':total,'government_amount':government,'self_cash_amount':cash,'self_in_kind_amount':in_kind})
    return {'2_지금_입력받는값':{'POST_projects_body':project,'project_plan_inputs':plan,'project_budget_items':parsed_budget,'project_schedule_items':schedules,'team_members':members,'_back_source':raw}}


def table_arguments(raw,kind,spec,canonical):
    original=raw.get('2_지금_입력받는값',{}).get('_back_source',raw)
    tables=original.get('tableData',{})
    suffix='.'.join(spec['sectionId'].split('.')[1:])
    rows=[]; rules={'sectionId':spec['sectionId'],'additions':[], 'note':'원본 우선. 미입력 수량·단가·단계는 임의 생성하지 않음'}
    if kind!='general':
        key=({'5.2':'실현가능성_일정','6.2':'성장전략_일정','5.3':'사업비_집행계획','5.4':'사업비_집행계획'} if kind=='early_startup' else {'5.2':'implementationSchedule','6.2':'fullScaleSchedule','5.3':'budgetPlanStep1','5.4':'budgetPlanStep2'})[suffix]
        rows=copy.deepcopy(tables.get(key,[]))
        if suffix in ('5.3','5.4'):
            if kind=='early_startup':
                phase='1단계' if suffix=='5.3' else '2단계'
                unassigned=[r for r in rows if not r.get('단계')]
                rows=[r for r in rows if r.get('단계')==phase]
                rules.update(unassignedOriginalRows=unassigned,note='단계 미지정 원본은 별도 보존. 각 단계에 중복 배정하지 않음')
            for row in rows:row.setdefault('산출근거',row.get('집행계획','확인 필요'))
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

def _attach_provenance(fid, value, kwargs):
    """Persist upstream evidence/facts on every F02-F15 canonical result."""
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

def run_pipeline(raw,kind,progress=None,render_image=None,max_rewrites=1,execution_scope='full'):
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
    def call(fid,fn,**kwargs):
        if progress:progress(f'{fid} {fn.__name__} 실행 중',len(trace))
        started=time.monotonic()
        try: value=fn(**kwargs)
        except Exception as exc:
            exc.partial_trace=trace
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
    c['schedule']=compact(call('F15',py.create_schedule,tasks=[r['category'] for r in schedules],duration=duration,milestones=schedules))
    c['feasibility_plan']={'goal':c['development_goal'],'development':c['development_plan'],'budget':c['budget']}
    original={'item':item_input,'period':{'start':plan.get('dev_start_month'),'end':plan.get('dev_end_month'),'durationMonths':duration},'strategy_limits':plan.get('strategy_limits',{}),'team':team_input,'resources':resource_input,
              'budget':{k:c['budget'][k] for k in ['items','total','government_amount','self_cash_amount','self_in_kind_amount','phase']},'schedule':schedules,'strategyOutputs':{k:_provenance(v) for k,v in c.items() if not k.startswith('_')}}
    sections=[]; images=[]; decisions=[]; selected_chars=0; full_chars=0
    for base_spec in CONTRACT['documents'][kind]:
        spec=copy.deepcopy(base_spec)
        sid=spec['sectionId']
        if not spec['enabled']:
            sections.append({**spec,'generatedText':'표 생성 제외 (사용자 지정)','tables':[],'images':[],'validation':{'status':'skipped','agent':'검증 1','issues':[]},'status':'skipped'})
            continue
        source=section_source(spec,c,original,list(evidence.values()))
        if kind=='general' and duration>=12 and sid in ['1.2.1','1.3.1']:
            spec['rules']['stages']=['1차','2차']
        full_chars+=len(json.dumps(c,ensure_ascii=False)); selected_chars+=len(json.dumps(source,ensure_ascii=False))
        attempts=[]
        attempt_limit=max_rewrites if execution_scope=='full' else 0
        for attempt in range(attempt_limit+1):
            if spec['functionId']=='F17':
                image_outputs=[]
                output=call('F17',py.generate_table,**table_arguments(raw,kind,spec,c))
            elif spec['functionId']=='F18':
                output=call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':attempts[-1]['validation']['issues'] if attempts else []},flow_type='USER_FLOW')
                image_outputs=[output,call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':attempts[-1]['validation']['issues'] if attempts else []},flow_type='SERVICE_ARCHITECTURE')]
            else:
                output=call('F16',gpt.generate_section,section_spec=spec,source_data=source,writing_rules={'documentType':kind,'tableGenerationEnabled':False,
                            'validationFeedback':attempts[-1]['validation']['issues'] if attempts else [],'previousText':attempts[-1]['generatedText'] if attempts else None,'preserveProvenance':True,'statusPolicy':['provided','proposed','needs_confirmation']})
                image_outputs=[output]
            validation=(call('F19',py.validate_section,section_spec=spec,content=output,source_data=source)
                        if execution_scope=='full' else {'status':'not_run','agent':'검증 1','issues':[]})
            attempts.append({'attempt':attempt+1,'generatedText':output['generatedText'],'validation':validation,'responseId':output.get('responseId')})
            if execution_scope!='full' or validation['status']=='pass':break
        rendered=[]
        if spec['functionId']=='F18' and validation['status'] in {'pass','not_run'} and render_image:
            rendered=[render_image(item) for item in image_outputs];images.extend(rendered)
        output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
        sections.append({**spec,'generatedText':output['generatedText'],'tables':output.get('tables',[]),'images':rendered,'functionOutput':output,'validationSource':source,'validation':validation,'attempts':attempts,'sourceKeys':list(spec['sourceKeys'])})
        decisions.append({'sectionId':sid,'status':validation['status'],'attemptCount':len(attempts)})
    failed=execution_scope=='full' and any(s['validation']['status']=='fail' for s in sections)
    document=None if execution_scope!='full' or failed else call('F20',py.assemble_document,sections=sections,tables=[t for row in sections for t in row.get('tables',[])],images=images)
    usage={'input_tokens':0,'output_tokens':0,'total_tokens':0}
    for event in trace:
        for key in usage:usage[key]+=event.get('usage',{}).get(key,0)
    return {'runId':str(uuid.uuid4()),'createdAt':datetime.now(timezone.utc).isoformat(),'documentType':kind,
            'status':'strategy_writing_completed' if execution_scope=='strategy_writing' else ('validation1_failed' if failed else 'validation1_passed'),
            'message':'전략(F01~F15)과 작성(F16/F18)만 완료했습니다. 검증 1(F19)과 조립(F20)은 실행하지 않았습니다.' if execution_scope=='strategy_writing' else ('검증 1 미통과 항목이 있어 최종 조립을 보류했습니다.' if failed else '검증 1 통과 및 조립 완료. 원본 기반 표 포함. 실제 문서 페이지 수는 별도 확인이 필요합니다.'),
            'results':sections,'document':document,'trace':trace,'validation1':decisions,'usage':usage,
            'executionScope':execution_scope,
            'contextMetrics':{'selectedSectionChars':selected_chars,'fullCanonicalCharsIfRepeated':full_chars,'note':'문자 수 비교이며 토큰 청구량은 usage 참조'},
            'research':{'sources':list(evidence.values()),'availableFiles':web['availableFiles'],'issues':market_evidence['issues']+competitor_evidence['issues']+dev_evidence['issues'],'industryRefresh':industry_refresh},
            'skippedFunctions':[]}


def impact_plan(kind, section_id):
    """Return the selected writing section and sections sharing its canonical inputs."""
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
    """Regenerate one selected section and all sections sharing its direct canonical inputs."""
    kind=prior_result['documentType']
    plan=impact_plan(kind, section_id)
    result=copy.deepcopy(prior_result)
    canonical, original, duration=_retry_context(raw, result)
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
        source=section_source(spec,canonical,original,evidence)
        if kind=='general' and duration>=12 and spec['sectionId'] in ['1.2.1','1.3.1']:
            spec['rules']['stages']=['1차','2차']
        previous=rows[spec['sectionId']]
        attempts=[]
        for attempt in range(max_rewrites+1):
            feedback=attempts[-1]['validation']['issues'] if attempts else []
            if spec['functionId']=='F17':
                image_outputs=[]
                output=call('F17',py.generate_table,**table_arguments(normalize_back_input(raw,kind),kind,spec,canonical))
            elif spec['functionId']=='F18':
                output=call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':feedback,'retryInstruction':retry_instruction},flow_type='USER_FLOW')
                image_outputs=[output,call('F18',gpt.generate_image_spec,item=source['item_spec'],architecture={'design':source.get('architecture',{}),'validationFeedback':feedback,'retryInstruction':retry_instruction},flow_type='SERVICE_ARCHITECTURE')]
            else:
                output=call('F16',gpt.generate_section,section_spec=spec,source_data=source,
                            writing_rules={'documentType':kind,'tableGenerationEnabled':False,'retryInstruction':retry_instruction,
                                           'validationFeedback':feedback,'previousText':previous.get('generatedText') if not attempts else attempts[-1]['generatedText'],'preserveProvenance':True,'statusPolicy':['provided','proposed','needs_confirmation']})
                image_outputs=[output]
            validation=call('F19',py.validate_section,section_spec=spec,content=output,source_data=source)
            attempts.append({'attempt':attempt+1,'generatedText':output['generatedText'],'validation':validation,'responseId':output.get('responseId')})
            if validation['status']=='pass':break
        images=[]
        if spec['functionId']=='F18' and validation['status']=='pass' and render_image:
            images=[render_image(item) for item in image_outputs]
        output['generatedText']=_strip_section_heading(output.get('generatedText',''),spec)
        rows[spec['sectionId']]={**previous,**spec,'generatedText':output['generatedText'],'tables':output.get('tables',[]), 'images':images,
                                 'validationSource':source,
                                 'functionOutput':output,'validation':validation,'attempts':previous.get('attempts',[])+attempts,
                                 'sourceKeys':list(spec['sourceKeys']),'retryInstruction':retry_instruction}
    result['results']=[rows[row['sectionId']] for row in result['results']]
    failed=any(row['validation']['status']=='fail' for row in result['results'])
    images=[image for row in result['results'] for image in row.get('images',[])]
    result['document']=None if failed else call('F20',py.assemble_document,sections=result['results'],tables=[t for row in result['results'] for t in row.get('tables',[])],images=images)
    result['status']='validation1_failed' if failed else 'validation1_passed'
    result['message']='재시도 후 검증 1 미통과 항목이 있어 최종 조립을 보류했습니다.' if failed else '선택 항목과 연관 항목 재생성 및 검증 1 완료.'
    result['runId']=str(uuid.uuid4()); result['createdAt']=datetime.now(timezone.utc).isoformat()
    result['retry']={'parentRunId':prior_result['runId'],'selectedSectionId':section_id,'instruction':retry_instruction,'impact':plan}
    result['usage']={key:sum(event.get('usage',{}).get(key,0) for event in trace) for key in ['input_tokens','output_tokens','total_tokens']}
    return result

