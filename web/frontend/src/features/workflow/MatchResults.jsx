// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useEffect,useCallback,useRef} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {getMatchCandidates,rematchCandidates,generatePipeline,getEligibility,getProjectStatus} from '../../api.js';
import {BonusScore,BonusBadge} from './shared.jsx';
import {AI_SUMMARY_SOURCE_NOTICE,RESULTS_SHOWN_COUNT} from './data.js';

export function MatchProgress({onComplete,ready=true}){return <Preparation kind="match" progress={ready?undefined:0} onComplete={onComplete}/>;}

// 후보 응답(MatchCandidatesOut)의 status — 'ready' 말고는 candidates가 비어 있다(백엔드 SB-242).
//  pending: 공고 매칭이 아직 도는 중 — 잠시 뒤 다시 부른다. failed · no_match: message · notices로 안내만.
const PENDING_RETRY_MS=1500;
// 자격 확인을 기다리는 최대 횟수 — 서버가 한 번에 25초까지 기다려 주므로 이 정도면 공고 서버 제한 시간(30초)을 넘는다.
const ELIGIBILITY_MAX_POLLS=6;
// 화면 3 안내 가운데 이 화면에 보여 줄 것. 실행 건의 안내는 계속 쌓이는 목록이라(명세 4.1) 지난 추가 조회의 실패 안내가
// 다음 조회에도 남아 있다 — 다시 찾기 실패 안내(X-C2-FAIL · E-C2-STALE)는 방금 한 다시 찾기 응답에서만 보여 준다.
const ALWAYS_NOTICES=['E-C2-EMBED','E-C1-DOC'];
const REMATCH_NOTICES=['X-C2-FAIL','E-C2-STALE'];
function noticesToShow(data,codes){
 const byCode=new Map();
 for(const n of data?.notices||[])if(codes.includes(n.code))byCode.set(n.code,n.message);
 return [...byCode.values()];
}
// 마감일이 없는 공고(예산 소진 · 상시 · 선착순)는 모집 형태를 보여 준다(공고연동_변경사항_웹팀전달.md 1.2).
function deadlineText(r){
 if(r.apply_end)return `${r.apply_end} 마감`;
 if(r.apply_period_type&&r.apply_period_type!=='모름'&&r.apply_period_type!=='기간 있음')return r.apply_period_type;
 return '마감일 정보 없음';
}

// 한 묶음(첫 매칭 또는 재실행) — 상위 RESULTS_SHOWN_COUNT건만 펼치고 나머지는 "더 보기"로 연다.
function CandidateGroup({title,rows,selected,onSelect,blockedIds}){
 const [expanded,setExpanded]=useState(false);
 const visible=expanded?rows:rows.slice(0,RESULTS_SHOWN_COUNT);
 const hiddenCount=rows.length-RESULTS_SHOWN_COUNT;
 return <div className="matched-group">
  {title&&<p className="matched-group-title">{title}</p>}
  {visible.map((r,i)=>{
   const disabled=blockedIds.includes(r.notice_id);
   return <button key={r.notice_id} type="button" disabled={disabled} aria-pressed={selected===r.notice_id}
     className={'matched-row matched-select '+(selected===r.notice_id?'selected':'')+(disabled?' disabled':'')}
     onClick={()=>onSelect(r.notice_id)}>
    <span className="match-rank">{i+1}</span>
    <div>
     <span className="match-org">{r.org||'주관기관 정보 없음'}</span>
     {/* 다시 찾기에서 다시 나온 공고의 내용이 바뀜 — 자격 결과를 뜻하지 않는다(공고연동 2.2) */}
     {r.content_changed&&<span className="match-changed">내용이 바뀌었어요, 다시 확인해 보세요</span>}
     <h3>{r.title}</h3><p>{deadlineText(r)}</p>
    </div>
    <BonusBadge value={r.bonus_score}/>
   </button>;
  })}
  {hiddenCount>0&&<button type="button" className="matched-more" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>
   {expanded?'접기':`나머지 ${hiddenCount}건 더 보기`}<Icon name="chevron" size={15} className={expanded?'-rotate-90':'rotate-90'}/>
  </button>}
 </div>;
}

export function MatchResults({projectId,candidates,onCandidatesLoaded,onBack,onCheckEligibility,backLabel='아이템 정보 다시 입력하기'}){
 const requestVersion=useRef(0);
 useEffect(()=>{requestVersion.current++;return()=>{requestVersion.current++}},[projectId]);
 const [selected,setSelected]=useState(null);
 const [loading,setLoading]=useState(!candidates);
 const [loadError,setLoadError]=useState(false);
 const [confirming,setConfirming]=useState(false);
 const [confirmError,setConfirmError]=useState('');
 // 자격 통과 뒤(화면 5)에 다른 공고를 골랐다가 자격 확인이 실패하면, 이미 통과한 이전 공고로 작성을 시작할 수 있다(공고연동 3.3).
 const [canResumePrevious,setCanResumePrevious]=useState(false);
 // 다시 찾기 중엔 첫 매칭과 같은 로딩 화면을 보여준다 — 로딩 연출(prepDone)과 서버 응답(data)이
 // 둘 다 끝나야 결과로 돌아온다.
 const [rematchPhase,setRematchPhase]=useState(null);
 const [rematchError,setRematchError]=useState('');
 // 방금 한 다시 찾기의 안내(새 공고 0건 · 실패) — 다음 다시 찾기 때 지운다.
 const [rematchNotice,setRematchNotice]=useState(null);
 const results=candidates?.candidates||[];
 // 자격 불통과로 막힌 공고 ID — 서버가 관리한다(새로고침 · 다시 열기에도 그대로). 예전엔 제목을 브라우저 메모리에 남겼다.
 const blockedIds=candidates?.blocked_notice_ids||[];
 const listStatus=candidates?.status||'ready';
 const rematchUsed=!!candidates?.rematch_used;
 const newRows=results.filter(r=>r.batch===2);
 const oldRows=results.filter(r=>r.batch!==2);

 // 다시 찾기도 공고 매칭이 워커에서 돌아 'pending'으로 올 수 있다 — 그때는 다시 찾기를 또 부르지 않고 후보 조회로 기다린다.
 const waitReady=async(data,request)=>{
  while(data?.status==='pending'){
   await new Promise(resolve=>setTimeout(resolve,PENDING_RETRY_MS));
   if(request!==requestVersion.current)return null;
   data=await getMatchCandidates(projectId);
  }
  return data;
 };
 const rematch=async()=>{
  const request=++requestVersion.current;
  setRematchError('');setRematchNotice(null);setRematchPhase({prepDone:false,data:null});
  try{
   const data=await waitReady(await rematchCandidates(projectId),request);
   if(request!==requestVersion.current||!data)return;
   // 새 공고 0건이면 message('더 보여드릴 공고가 없어요' 계열), 실패면 X-C2-FAIL · E-C2-STALE 안내 — 기회는 돌려받는다.
   setRematchNotice([data.message,...noticesToShow(data,REMATCH_NOTICES)].filter(Boolean).join(' ')||null);
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
  let cancelled=false;let timer=null;
  setLoading(true);setLoadError(false);
  const load=()=>getMatchCandidates(projectId).then(data=>{
   if(cancelled)return;
   if(data?.status==='pending'){timer=setTimeout(load,PENDING_RETRY_MS);return}
   onCandidatesLoaded(data);
   setLoading(false);
  }).catch(err=>{
   console.error('매칭 후보를 불러오지 못했어요',err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  load();
  return ()=>{cancelled=true;clearTimeout(timer)};
 },[projectId,candidates,onCandidatesLoaded]);

 // 공고 선택 → 자격 확인. 응답 status: ready(결과) · pending(아직 확인 중 — GET /eligibility로 다시 읽는다) ·
 // failed(공고 없음 X-C2-GONE · 공고 서버 오류 X-C2-FAIL — 고르기 전 화면으로 돌아가고, 그 공고는 막히지 않아 다시 고를 수 있다).
 const confirm=async(r)=>{
  if(confirming||!projectId)return;
  const request=++requestVersion.current;
  setConfirming(true);setConfirmError('');setCanResumePrevious(false);
  try{
   let result=await generatePipeline(projectId,r.notice_id);
   for(let i=0;result?.status==='pending'&&i<ELIGIBILITY_MAX_POLLS;i++){
    await new Promise(resolve=>setTimeout(resolve,PENDING_RETRY_MS));
    if(request!==requestVersion.current)return;
    result=await getEligibility(projectId);
   }
   if(request!==requestVersion.current)return;
   if(result?.status==='pending'){
    setConfirmError('신청 자격을 확인하는 데 시간이 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
    setConfirming(false);
    return;
   }
   if(result?.status==='failed'){
    setConfirmError(result.message||'공고를 확인하지 못했어요. 잠시 뒤 다시 시도해 주세요.');
    setConfirming(false);
    const status=await getProjectStatus(projectId).catch(()=>null);
    if(request!==requestVersion.current)return;
    setCanResumePrevious(status?.screen===5&&status.match_status==='user_waiting');
    return;
   }
   onCheckEligibility(r,result);
  }catch(err){
   if(request!==requestVersion.current)return;
   console.error('신청 자격을 확인하지 못했어요',err);
   setConfirmError(err.message||'신청 자격을 확인하지 못했어요. 다시 시도해 주세요.');
   setConfirming(false);
   // 409(자격 불통과로 막힌 공고 등) — 서버의 막힌 공고 목록이 바뀌었을 수 있어 후보를 다시 받는다.
   if(err.status===409)onCandidatesLoaded(null);
  }
 };
 // 이전에 통과한 공고로 돌아가 작성을 시작한다 — 자격 결과를 다시 읽어 자격 확인 화면을 연다.
 const resumePrevious=async()=>{
  const request=++requestVersion.current;
  setConfirming(true);setConfirmError('');
  try{
   const result=await getEligibility(projectId);
   if(request!==requestVersion.current)return;
   const noticeId=result?.match?.notice_id;
   const previous=results.find(c=>c.notice_id===noticeId)||{notice_id:noticeId,title:'이전에 확인한 공고'};
   onCheckEligibility(previous,result);
  }catch(err){
   if(request!==requestVersion.current)return;
   setConfirmError(err.message||'이전 공고를 불러오지 못했어요. 다시 시도해 주세요.');
   setConfirming(false);
  }
 };

 // 후보 3건을 하나씩 확인하다 보면 셋 다 자격 미달로 끝나는 경우가 생긴다 — 그때
 // 각 행이 조용히 회색으로 바뀌는 것만으로는 "이제 뭘 해야 하지"가 안 보여서
 // (사용자 지적), 셋 다 막히면 전체 상황을 알려주는 배너를 따로 보여준다.
 const allDisabled=results.length>0&&results.every(r=>blockedIds.includes(r.notice_id));

 if(rematchPhase)return <Preparation kind="match" onComplete={onRematchPrepDone}/>;

 const selectedResult=results.find(r=>r.notice_id===selected)||null;
 const selectedDisabled=!!selectedResult&&blockedIds.includes(selectedResult.notice_id);
 const notices=noticesToShow(candidates,ALWAYS_NOTICES);

 return <section data-screen="matches" className="matches-page">
  <p className="section-label">공고 찾기</p>
  <h1>이런 공고가 잘 맞아요</h1>
  {/* 순서는 공고팀 순위(rank) 그대로다 — 가산점 순이 아니다(공고연동 1.3). 순위 기준 문구는 공고팀 회신 뒤 정한다. */}
  <p>아이템과 신청 조건에 맞는 공고 {oldRows.length||10}건을 골랐어요. 상위 {RESULTS_SHOWN_COUNT}건을 먼저 보여드리고, 후보를 누르면 오른쪽에서 자세한 근거를 볼 수 있어요.</p>
  {loading&&<p className="matched-note">공고를 찾는 중이에요…</p>}
  {notices.map(m=><p key={m} className="matched-note" role="status">{m}</p>)}
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
  {!loading&&!loadError&&results.length===0&&(listStatus==='failed'||listStatus==='no_match'?(
   <div className="matches-all-failed" role="alert">
    <span className="matches-all-failed-icon" aria-hidden="true">!</span>
    <div>
     <b>{listStatus==='no_match'?'지금 신청할 수 있는 공고를 찾지 못했어요':'공고를 찾지 못했어요'}</b>
     <p>{candidates?.message||(listStatus==='no_match'?'아이디어 설명이나 신청자 정보를 다시 확인해 주세요.':'잠시 후 다시 시도해 주세요.')}</p>
    </div>
    {/* 다시 시도할 수 있는 실패면 서버가 후보 조회 때 시작 요청을 다시 넣는다(백엔드 _candidates_response) */}
    {listStatus==='failed'?<button className="btn small" onClick={()=>onCandidatesLoaded(null)}>다시 시도</button>
     :<button className="btn small" onClick={onBack}>{backLabel}</button>}
   </div>
  ):<p className="matched-note">지금은 모집 중인 공고가 없어요.</p>)}

  {results.length>0&&(
   <div className="matches-layout">
    <div className="matched-list">
     {newRows.length>0&&<CandidateGroup title={`다시 찾은 공고 ${newRows.length}건`} rows={newRows} selected={selected} onSelect={setSelected} blockedIds={blockedIds}/>}
     <CandidateGroup title={newRows.length>0?`이전에 찾은 공고 ${oldRows.length}건`:null} rows={oldRows} selected={selected} onSelect={setSelected} blockedIds={blockedIds}/>
     <div className="matched-rematch">
      {rematchUsed?(
       <p>공고 다시 찾기는 한 번만 할 수 있어요. 이전 결과와 함께 비교해 보세요.</p>
      ):(
       <>
        <p>마음에 드는 공고가 없나요? 한 번 더 찾아볼 수 있어요. <b>(1회)</b></p>
        <button type="button" className="btn btn-muted small" disabled={confirming} onClick={rematch}>공고 다시 찾기</button>
       </>
      )}
      {rematchNotice&&<p className="matched-note" role="status">{rematchNotice}</p>}
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
         <p className="matched-evidence-gauge-label">{selectedResult.bonus_score==null?'가산점 정보 없음':selectedResult.bonus_score===0?'이 공고에서 해당하는 가점이 없어요':'이 공고에서 받을 수 있는 가산점'}</p>
         <p className="matched-evidence-gauge-sub">{deadlineText(selectedResult)}</p>
        </div>
       </div>

       {selectedDisabled?(
        <p className="matched-evidence-fail">신청 자격에 맞지 않는 공고예요. 다른 공고를 선택해 주세요.</p>
       ):(
        <div className="matched-evidence-reason">
         <p className="matched-evidence-reason-label">매칭 근거</p>
         <p>{selectedResult.reason}</p>
         {/* 가산점 항목별 근거 — 합계와 맞는다(공고연동 1.4) */}
         {selectedResult.bonus_items?.length>0&&<ul className="match-bonus-items">
          {selectedResult.bonus_items.map(b=><li key={b.name}><span>{b.name}</span><b>+{b.points}점</b></li>)}
         </ul>}
         {/* 출처 고지는 카드마다 서버 문구(기업마당 등). 없으면 예전 고정 문구 */}
         <span className="match-source-notice">{selectedResult.source_notice||AI_SUMMARY_SOURCE_NOTICE}</span>
        </div>
       )}

       {selectedResult.url&&<a className="matched-evidence-link" href={selectedResult.url} target="_blank" rel="noopener noreferrer">공고 사이트 확인 <Icon name="chevron" size={14}/></a>}

       {!selectedDisabled&&<div className="matched-action">
        <span>{confirming?'신청 자격을 확인하는 중이에요…':'이 공고의 신청 조건을 확인할까요?'}</span>
        <button className="btn" disabled={confirming} onClick={()=>confirm(selectedResult)}>{confirming?'확인 중…':'신청 자격 확인하기'}</button>
       </div>}
       {confirmError&&<p className="matched-note" role="alert">{confirmError}</p>}
       {canResumePrevious&&<button type="button" className="btn btn-muted small" disabled={confirming} onClick={resumePrevious}>이전에 확인한 공고로 계속하기</button>}
      </React.Fragment>
     )}
    </aside>
   </div>
  )}

  <p className="matched-note">AI가 임시로 생성한 공고와 가산점이에요. 실제 접수 여부는 공고 사이트에서 확인해 주세요.</p>
  <button className="text-link back-link" onClick={onBack}>{backLabel}</button>
 </section>;
}
