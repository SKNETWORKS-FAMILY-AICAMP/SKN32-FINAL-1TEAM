// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useEffect,useCallback,useRef} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {getMatchCandidates,rematchCandidates,generatePipeline} from '../../api.js';
import {BonusScore,formatBonus} from './shared.jsx';
import {AI_SUMMARY_SOURCE_NOTICE,RESULTS_SHOWN_COUNT} from './data.js';

export function MatchProgress({onComplete,ready=true}){return <Preparation kind="match" progress={ready?undefined:0} onComplete={onComplete}/>;}

// 한 묶음(첫 매칭 또는 재실행) — 상위 RESULTS_SHOWN_COUNT건만 펼치고 나머지는 "더 보기"로 연다.
function CandidateGroup({title,rows,selected,onSelect,disabledTitles}){
 const [expanded,setExpanded]=useState(false);
 const visible=expanded?rows:rows.slice(0,RESULTS_SHOWN_COUNT);
 const hiddenCount=rows.length-RESULTS_SHOWN_COUNT;
 return <div className="matched-group">
  {title&&<p className="matched-group-title">{title}</p>}
  {visible.map((r,i)=>{
   const disabled=disabledTitles.includes(r.title);
   return <button key={r.notice_id} type="button" disabled={disabled} aria-pressed={selected===r.notice_id}
     className={'matched-row matched-select '+(selected===r.notice_id?'selected':'')+(disabled?' disabled':'')}
     onClick={()=>onSelect(r.notice_id)}>
    <span className="match-rank">{i+1}</span>
    <div><span className="match-org">{r.org||'주관기관 정보 없음'}</span><h3>{r.title}</h3><p>{r.apply_end?`${r.apply_end} 마감`:'마감일 정보 없음'}</p></div>
    <span className="match-fit"><b>{formatBonus(r.bonus_score)}<small>점</small></b><span>가산점</span></span>
   </button>;
  })}
  {hiddenCount>0&&<button type="button" className="matched-more" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>
   {expanded?'접기':`나머지 ${hiddenCount}건 더 보기`}<Icon name="chevron" size={15} className={expanded?'-rotate-90':'rotate-90'}/>
  </button>}
 </div>;
}

export function MatchResults({projectId,candidates,onCandidatesLoaded,onBack,onCheckEligibility,disabledTitles=[],backLabel='아이템 정보 다시 입력하기'}){
 const requestVersion=useRef(0);
 useEffect(()=>{requestVersion.current++;return()=>{requestVersion.current++}},[projectId]);
 const [selected,setSelected]=useState(null);
 const [loading,setLoading]=useState(!candidates);
 const [loadError,setLoadError]=useState(false);
 const [confirming,setConfirming]=useState(false);
 const [confirmError,setConfirmError]=useState('');
 // 다시 찾기 중엔 첫 매칭과 같은 로딩 화면을 보여준다 — 로딩 연출(prepDone)과 서버 응답(data)이
 // 둘 다 끝나야 결과로 돌아온다.
 const [rematchPhase,setRematchPhase]=useState(null);
 const [rematchError,setRematchError]=useState('');
 const results=candidates?.candidates||[];
 const rematchUsed=!!candidates?.rematch_used;
 const newRows=results.filter(r=>r.batch===2);
 const oldRows=results.filter(r=>r.batch!==2);

 const rematch=async()=>{
  const request=++requestVersion.current;
  setRematchError('');setRematchPhase({prepDone:false,data:null});
  try{
   const data=await rematchCandidates(projectId);
   if(request!==requestVersion.current)return;
   setRematchPhase(p=>p&&{...p,data});
  }catch(err){
   if(request!==requestVersion.current)return;
   console.error('공고를 다시 찾지 못했어요',err);
   setRematchPhase(null);
   setRematchError(err.message||'공고를 다시 찾지 못했어요. 잠시 후 다시 시도해 주세요.');
  }
 };
 const onRematchPrepDone=useCallback(()=>setRematchPhase(p=>p&&!p.prepDone?{...p,prepDone:true}:p),[]);

 useEffect(()=>{
  if(!rematchPhase?.prepDone||!rematchPhase.data)return;
  onCandidatesLoaded(rematchPhase.data);
  setRematchPhase(null);setSelected(null);
  window.scrollTo({top:0});
 },[rematchPhase,onCandidatesLoaded]);

 useEffect(()=>{
  if(!projectId||candidates)return;
  let cancelled=false;
  setLoading(true);setLoadError(false);
  getMatchCandidates(projectId).then(data=>{
   if(cancelled)return;
   onCandidatesLoaded(data);
   setLoading(false);
  }).catch(err=>{
   console.error('매칭 후보를 불러오지 못했어요',err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  return ()=>{cancelled=true};
 },[projectId,candidates,onCandidatesLoaded]);

 const confirm=async(r)=>{
  if(confirming||!projectId)return;
  const request=++requestVersion.current;
  setConfirming(true);setConfirmError('');
  try{
   const generateResult=await generatePipeline(projectId,r.notice_id);
   if(request!==requestVersion.current)return;
   onCheckEligibility(r,generateResult);
  }catch(err){
   if(request!==requestVersion.current)return;
   console.error('신청 자격을 확인하지 못했어요',err);
   setConfirmError(err.message||'신청 자격을 확인하지 못했어요. 다시 시도해 주세요.');
   setConfirming(false);
  }
 };

 // 후보 3건을 하나씩 확인하다 보면 셋 다 자격 미달로 끝나는 경우가 생긴다 — 그때
 // 각 행이 조용히 회색으로 바뀌는 것만으로는 "이제 뭘 해야 하지"가 안 보여서
 // (사용자 지적), 셋 다 막히면 전체 상황을 알려주는 배너를 따로 보여준다.
 const allDisabled=results.length>0&&results.every(r=>disabledTitles.includes(r.title));

 if(rematchPhase)return <Preparation kind="match" onComplete={onRematchPrepDone}/>;

 const selectedResult=results.find(r=>r.notice_id===selected)||null;
 const selectedDisabled=!!selectedResult&&disabledTitles.includes(selectedResult.title);

 return <section data-screen="matches" className="matches-page">
  <p className="section-label">공고 찾기</p>
  <h1>이런 공고가 잘 맞아요</h1>
  <p>아이템과 맞는 공고 {oldRows.length||10}건을 가산점이 높은 순서로 골랐어요. 상위 {RESULTS_SHOWN_COUNT}건을 먼저 보여드리고, 후보를 누르면 오른쪽에서 자세한 근거를 볼 수 있어요.</p>
  {loading&&<p className="matched-note">공고를 찾는 중이에요…</p>}
  {allDisabled&&(
   <div className="matches-all-failed" role="alert">
    <span className="matches-all-failed-icon" aria-hidden="true">!</span>
    <div>
     <b>추천드린 공고 {results.length}건 모두 신청 자격 요건에 맞지 않아요</b>
     <p>아이디어 설명이나 신청자 정보를 다시 확인해서 새로 찾아보는 걸 추천해요.</p>
    </div>
    <button className="btn small" onClick={onBack}>{backLabel}</button>
   </div>
  )}
  {loadError&&<p className="matched-note">공고를 불러오지 못했어요. 새로고침해 주세요.</p>}
  {!loading&&!loadError&&results.length===0&&<p className="matched-note">지금은 모집 중인 공고가 없어요.</p>}

  {results.length>0&&(
   <div className="matches-layout">
    <div className="matched-list">
     {newRows.length>0&&<CandidateGroup title={`다시 찾은 공고 ${newRows.length}건`} rows={newRows} selected={selected} onSelect={setSelected} disabledTitles={disabledTitles}/>}
     <CandidateGroup title={newRows.length>0?`이전에 찾은 공고 ${oldRows.length}건`:null} rows={oldRows} selected={selected} onSelect={setSelected} disabledTitles={disabledTitles}/>
     <div className="matched-rematch">
      {rematchUsed?(
       <p>공고 다시 찾기는 한 번만 할 수 있어요. 이전 결과와 함께 비교해 보세요.</p>
      ):(
       <>
        <p>마음에 드는 공고가 없나요? 한 번 더 찾아볼 수 있어요. <b>(1회)</b></p>
        <button type="button" className="btn btn-muted small" disabled={confirming} onClick={rematch}>공고 다시 찾기</button>
       </>
      )}
      {rematchError&&<p className="matched-note">{rematchError}</p>}
     </div>
    </div>

    <aside className="matched-evidence">
     {!selectedResult?(
      <div className="matched-evidence-empty">
       <Icon name="file" size={28}/>
       <p>왼쪽에서 공고를 선택하면<br/>매칭 근거를 자세히 보여드려요</p>
      </div>
     ):(
      <React.Fragment>
       <div className="matched-evidence-head">
        <span className="match-org">{selectedResult.org||'주관기관 정보 없음'}</span>
        <h2>{selectedResult.title}</h2>
       </div>

       <div className="matched-evidence-gauge">
        <BonusScore value={selectedResult.bonus_score}/>
        <div>
         <p className="matched-evidence-gauge-label">이 공고에서 받을 수 있는 가산점</p>
         <p className="matched-evidence-gauge-sub">{selectedResult.apply_end?`${selectedResult.apply_end} 마감`:'마감일 정보 없음'}</p>
        </div>
       </div>

       {selectedDisabled?(
        <p className="matched-evidence-fail">신청 자격에 맞지 않는 공고예요. 다른 공고를 선택해 주세요.</p>
       ):(
        <div className="matched-evidence-reason">
         <p className="matched-evidence-reason-label">매칭 근거</p>
         <p>{selectedResult.reason}</p>
         <span className="match-source-notice">{AI_SUMMARY_SOURCE_NOTICE}</span>
        </div>
       )}

       {selectedResult.url&&<a className="matched-evidence-link" href={selectedResult.url} target="_blank" rel="noopener noreferrer">공고 사이트 확인 <Icon name="chevron" size={14}/></a>}

       {!selectedDisabled&&<div className="matched-action">
        <span>{confirming?'신청 자격을 확인하는 중이에요…':'이 공고의 신청 조건을 확인할까요?'}</span>
        <button className="btn" disabled={confirming} onClick={()=>confirm(selectedResult)}>{confirming?'확인 중…':'신청 자격 확인하기'}</button>
       </div>}
       {confirmError&&<p className="matched-note">{confirmError}</p>}
      </React.Fragment>
     )}
    </aside>
   </div>
  )}

  <p className="matched-note">AI가 임시로 생성한 공고와 가산점이에요. 실제 접수 여부는 공고 사이트에서 확인해 주세요.</p>
  <button className="text-link back-link" onClick={onBack}>{backLabel}</button>
 </section>;
}
