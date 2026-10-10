"""Local research / exact calculations; Luna only for interpretation, 검증 1 for F19."""
from __future__ import annotations
from typing import Any
from ..runtime.llm_runtime import request_json, compact   # [S-Brain] import 경로를 패키지 상대 경로로
from ..runtime.research_context import retrieve

# F01 collect_web_data() — 실제 Web connector 연동 전 어댑터 자리
def collect_web_data(query: str, source_type: str, target_fields: list[str]) -> dict[str, Any]:
    research=retrieve(query)
    if research['sources']:
        analysis=request_json('F01',{'query':query,'target_fields':target_fields,'research_data':research})
        research['analysis']=compact(analysis)
        # [S-Brain] 기록용 칸(model · responseId · usage · inputChars) 옮기기 삭제 — request_json이 더는 싣지 않는다(spec 4.17)
    return research
# F14 calculate_budget()
def calculate_budget(items: list[dict], quantity: list[int], unit_price: list[int], phase: str, rules: dict) -> dict:
    if not len(items)==len(quantity)==len(unit_price):raise ValueError('예산 목록 길이 불일치')
    total=sum(q*p for q,p in zip(quantity,unit_price))
    totals={key:sum(row.get(key,0) for row in items) for key in ['government_amount','self_cash_amount','self_in_kind_amount']}
    analysis=request_json('F14',{'originalFacts':{'items':items,'total':total,**totals},'rules':rules})
    return {**analysis,'phase':phase,'items':items,'total':total,**totals,'phase_1':None,'phase_2':None,'rules':rules}
# F15 create_schedule()
def create_schedule(tasks: list, duration: int, milestones: list) -> dict:
    rows=[{'task':task,'period':next((m.get('period','미정') for m in milestones if isinstance(m,dict) and m.get('category')==task),'미정')} for task in tasks]
    analysis=request_json('F15',{'originalFacts':{'duration':duration,'rows':rows,'milestones':milestones}})
    return {**analysis,'duration':duration,'milestones':milestones,'rows':rows}
# F17 generate_table() — 설계만 완료, 현재 호출하지 않음
def generate_table(columns: list[str], rows: list[dict], rules: dict) -> dict:
    import copy, json
    table={'columns':columns,'rows':copy.deepcopy(rows),'rules':rules,'sourcePriority':'user_input'}
    text=' | '.join(columns)+'\n'+'\n'.join(' | '.join(str(row.get(col,'확인 필요')) for col in columns) for row in rows)
    if rules.get('narrativeRequired'):
        heading='개발계획 서술' if rules.get('narrativeType')=='schedule' else '사업비 집행계획 서술'
        if rules.get('narrativeType')=='schedule':
            lines=[f'{i+1}. {row.get("추진내용",row.get("task","확인 필요"))}을(를) {row.get("추진기간",row.get("period","미정"))} 동안 추진하며, {row.get("세부내용",row.get("details","세부내용 확인 필요"))}.' for i,row in enumerate(rows)]
        else:
            lines=[f'{i+1}. {row.get("비목","확인 필요")}: {row.get("산출근거",row.get("집행계획","산출근거 확인 필요"))}, 정부지원사업비 {row.get("정부지원사업비","확인 필요")}.' for i,row in enumerate(rows)]
        if len(lines)<3: lines += [f'{i}. 원본 입력에 없는 세부 항목은 협약 후 확인함.' for i in range(len(lines)+1,4)]
        text+='\n\n'+heading+':\n'+'\n'.join(lines)
    if rules.get('unassignedOriginalRows'):
        text+='\n단계 미지정 원본 (단계별 합계에 미포함):\n'+json.dumps(rules['unassignedOriginalRows'],ensure_ascii=False,indent=2)
    return {'status':'generated','model':'Python','generatedText':text,'tables':[table],
            'issues':[] if rows else ['원본 행 없음: 입력 확인 필요'],'sourceRefs':[]}
# F19 validate_section()
def validate_section(section_spec: dict, content: dict, source_data: dict) -> dict:
    from ...agent_validation_1.validation_1 import validate_section as validation1   # [S-Brain] 패키지 상대 경로
    return validation1(section_spec,content,source_data)
# F20 assemble_document()
def assemble_document(sections: list, tables: list, images: list) -> dict:
    # Warnings are non-blocking review notes; only hard failures prevent
    # document assembly.
    if any(s['validation']['status'] not in ['pass','warning','skipped'] for s in sections):raise ValueError('검증 1 미통과 항목은 조립할 수 없습니다.')
    return {'status':'validation1_passed','sections':sections,'tables':tables,'images':images,'pageCountVerified':False}

