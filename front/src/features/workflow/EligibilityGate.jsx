// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React from 'react';
import {Icon} from '../../components/Icons.jsx';
import {BackButton} from './shared.jsx';

export function EligibilityGate({announcement,eligibility,onProceed,onLeave}){
 const passed=eligibility?.passed??false;
 const undecidable=eligibility?.undecidable??false;
 const failedConditions=eligibility?.failed_conditions||[];
 const missingInputs=eligibility?.missing_inputs||[];
 const leave=()=>onLeave(announcement.title,!passed);
 return <><section data-screen="eligibility" className="eligibility-page">
  <BackButton onClick={leave} label="매칭 결과로 돌아가기"/>
  <div className={'eligibility-symbol '+(passed?'':'failed')}><Icon name={passed?'check':'file'} size={32}/></div>
  <p className="section-label">{announcement.title}</p>
  <h1>{passed?'신청 조건을 충족해요':undecidable?'자격 판정을 확정하지 못했어요':'확인이 필요한 조건이 있어요'}</h1>
  <p>{passed?'입력한 정보로 확인했어요. 이제 사업계획서를 준비해 볼까요?':undecidable?'입력한 정보만으로는 판단하기 어려운 항목이 있어요.':'이 공고의 조건과 맞지 않는 항목이 있어요. 다른 공고를 확인해 주세요.'}</p>
  {(failedConditions.length>0||missingInputs.length>0)&&<div className="eligibility-list">
   {failedConditions.map((c,i)=><div className="eligibility-row" key={'fail-'+i}><div><b>충족하지 않는 조건</b><p>{typeof c==='string'?c:JSON.stringify(c)}</p></div><div><small className="fail-text">미충족</small></div></div>)}
   {missingInputs.map((m,i)=><div className="eligibility-row" key={'missing-'+i}><div><b>추가로 필요한 정보</b><p>{typeof m==='string'?m:JSON.stringify(m)}</p></div><div><small className="fail-text">확인 필요</small></div></div>)}
  </div>}
  <div className="eligibility-action"><p>등록하신 정보를 기준으로 AI가 확인한 결과예요.</p><button className="btn" onClick={()=>passed?onProceed():leave()}>{passed?'사업계획서 작성하기':'다른 공고 다시 보기'}</button></div>
 </section></>;
}
