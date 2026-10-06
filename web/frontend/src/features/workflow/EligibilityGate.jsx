// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React from 'react';
import {Icon} from '../../components/Icons.jsx';
import {BackButton} from './shared.jsx';

// 자격 결과(POST /generate · GET /eligibility의 eligibility, 오케스트레이터 화면 4 gateResult)의 조건 이름 → 화면 문구.
// 조건 이름은 '지원대상 유형' · '업력', 누락 입력은 'foundedAt'이다(공고연동_변경사항_웹팀전달.md 4절).
const INPUT_LABEL = {foundedAt: '설립일'};
const labelOf = (v) => (typeof v === 'string' ? INPUT_LABEL[v] || v : JSON.stringify(v));
// 화면 4에 함께 보일 안내 — 확인 필요(E-G1-UNPARSED) · 불통과(E-G1-REJECT) · 설립일 없음(E-G1-MISSING)
const GATE_NOTICES = ['E-G1-UNPARSED', 'E-G1-REJECT', 'E-G1-MISSING'];

export function EligibilityGate({announcement,eligibility,notices=[],onProceed,onLeave}){
 const passed=eligibility?.passed??false;
 const failedConditions=eligibility?.failed_conditions||[];
 const missingInputs=eligibility?.missing_inputs||[];
 // 공고 서버가 읽지 못해 통과로 본 조건 — 진행을 막지 않고 공고문을 직접 확인하라고만 안내한다.
 // (예전의 '판정 불가(undecidable)'는 없어졌다 — 오케스트레이터는 늘 거짓으로 준다)
 const unknownConditions=eligibility?.unknown_conditions||[];
 // 작성 시작 가능 여부는 서버 값(can_start_writing, SB-274)을 따른다 — 없으면(예전 응답 · 화면 검토 견본) 통과 여부로.
 // 확인 필요 조건이 있을 때 true로 둘지는 기획 확인 중(잠정)이라 서버 결정을 그대로 따른다.
 const canStart=eligibility?.can_start_writing??passed;
 // 업력(년, 소수 한 자리). 예비창업자 · 모르면 null이라 표시하지 않는다.
 const businessAge=eligibility?.business_age_years;
 const missingOnly=!passed&&failedConditions.length===0&&missingInputs.length>0;
 const gateNotices=[...new Map(notices.filter(n=>GATE_NOTICES.includes(n.code)).map(n=>[n.code,n.message])).values()];
 const leave=()=>onLeave(announcement.title,!passed);
 const rows=failedConditions.length>0||missingInputs.length>0||unknownConditions.length>0;
 return <><section data-screen="eligibility" className="eligibility-page">
  <BackButton onClick={leave} label="매칭 결과로 돌아가기"/>
  <div className={'eligibility-symbol '+(passed?'':'failed')}><Icon name={passed?'check':'file'} size={32}/></div>
  <p className="section-label">{announcement.title}</p>
  <h1>{passed?'신청 조건을 충족해요':missingOnly?'추가로 필요한 정보가 있어요':'확인이 필요한 조건이 있어요'}</h1>
  <p>{passed
   ?(unknownConditions.length>0?'입력한 정보로 확인했어요. 자동으로 확인하지 못한 조건은 공고문에서 직접 확인해 주세요.':'입력한 정보로 확인했어요. 이제 사업계획서를 준비해 볼까요?')
   :missingOnly?'입력한 정보에 아래 항목이 없어 자격을 확인하지 못했어요. 정보를 채운 뒤 다시 확인해 주세요.'
   :'이 공고의 조건과 맞지 않는 항목이 있어요. 다른 공고를 확인해 주세요.'}</p>
  {gateNotices.map(m=><p key={m} className="matched-note" role="status">{m}</p>)}
  {businessAge!=null&&<p className="matched-note">등록하신 정보 기준 업력 {businessAge}년</p>}
  {rows&&<div className="eligibility-list">
   {failedConditions.map((c,i)=><div className="eligibility-row" key={'fail-'+i}><div><b>충족하지 않는 조건</b><p>{labelOf(c)}</p></div><div><small className="fail-text">미충족</small></div></div>)}
   {missingInputs.map((m,i)=><div className="eligibility-row" key={'missing-'+i}><div><b>추가로 필요한 정보</b><p>{labelOf(m)}</p></div><div><small className="fail-text">입력 필요</small></div></div>)}
   {unknownConditions.map((c,i)=><div className="eligibility-row" key={'unknown-'+i}><div><b>{labelOf(c)}</b><p>공고문을 직접 확인해 주세요</p></div><div><small className="fail-text">확인 필요</small></div></div>)}
  </div>}
  <div className="eligibility-action"><p>등록하신 정보를 기준으로 AI가 확인한 결과예요.</p><button className="btn" onClick={()=>canStart?onProceed():leave()}>{canStart?'사업계획서 작성하기':'다른 공고 다시 보기'}</button></div>
 </section></>;
}
