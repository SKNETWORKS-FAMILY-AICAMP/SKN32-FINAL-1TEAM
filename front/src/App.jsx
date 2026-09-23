import React,{useState,useEffect,useRef,Suspense,lazy} from 'react';
import Landing,{MyPageNudge} from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import {LoginModal,fetchCurrentUser,logout} from './components/Login.jsx';
import AdminDashboard from './features/Admin.jsx';
import MyPage from './features/mypage/MyPage.jsx';
import {useMyPageStore} from './store/useMyPageStore.js';
import {IntakeForm,MatchProgress,MatchResults,EligibilityGate,PlanForm,ArtifactResult,FinalVerdict,ReviewScreen,GenerationProgress} from './features/Workflow.jsx';
import {createProject,getProject,getProjectResult,getProjectStatus} from './api.js';
import {useWorkflowStore} from './store/useWorkflowStore.js';

// [2026-09-15, 프론트 통합 임시 구현] "단가" 입력칸은 자유 텍스트("500원" 등)라서 서버가
// 기대하는 숫자(unit_price)를 뽑아내려면 이 정도 파싱이 필요하다 — 숫자를 못 찾으면 null(미정)로 보낸다.
// 사업계획서~검수 사이에서 나갔다가 "이어서 진행하기"로 돌아오면 항상 검수(끝)로
// 보내던 버그 수정용. 지금 더미 파이프라인은 공고를 고르는 순간 계획서·프로토타입·
// 최종판정을 한 번에 다 만들어 버려서(back/app/routers/projects.py의 generate_pipeline_result
// 주석 참고 — 실제 Agent 파이프라인이 생기기 전까지 stage는 항상 곧장 'done'이 됨) 서버
// status로는 마지막으로 보던 화면을 구분 못 한다. 그래서 화면 전환 자체를 프로젝트별로
// localStorage에 남겨두고, 다시 열 때 거기부터 이어서 보여준다.
const RESUMABLE_VIEWS=['plan-progress','plan-form','artifact-progress','artifact-result','final-verdict','review'];
// 저장된 화면이 없을 때 서버 진행 단계(match_results.stage)로 돌아갈 화면을 정한다.
const VIEW_BY_STAGE={plan_writing:'plan-progress',plan_review_pending:'plan-form',prototype_building:'artifact-progress'};
const lastViewKey=(projectId)=>`sbrain-last-view:${projectId}`;

function parsePrice(text){
 const digits=(text||'').replace(/[^0-9.]/g,'');
 if(!digits)return null;
 const n=Number(digits);
 return Number.isFinite(n)?n:null;
}

// 프로젝트 작성 화면의 나머지 입력값 — 요청 형식은 프론트가 확정했다(백엔드 전달사항 문서 참고).
// 서버 ProjectCreateRequest에 아직 필드가 없어 지금은 서버가 무시하고, 필드를 추가하면 그대로 저장된다.
// 선택지 값(성별·이력 구분·상태)은 화면 표시 문자열 그대로, 금액은 숫자, 월은 YYYY-MM.
function intakeDetailPayload(info){
 const text=(v)=>(v||'').trim()||null;
 const f=info.selfFunding;
 return {
  ceo_birth_date:info.birthDate||null,
  ceo_gender:info.gender||null,
  region_sido:info.region?.sido||null,
  region_sigungu:text(info.region?.sigungu),
  main_industry:text(info.industry),
  certifications:info.certs||[],
  ceo_careers:(info.careers||[]).map(c=>({type:c.type||null,title:text(c.title),period:text(c.period),has_proof:!!c.hasProof})),
  ceo_capability:text(info.skills),
  dev_start_month:info.devPeriod?.start||null,
  dev_end_month:info.devPeriod?.end||null,
  budget_scale_manwon:info.budgetScale?Number(info.budgetScale):null,
  self_funding_allowed:f?f.available:null,
  self_cash_limit:f?.available&&f.cashLimit?Number(f.cashLimit):null,
  self_in_kind_resources:f?.available?text(f.inKindResources):null,
  no_hires:!!info.noHires,
  hires:(info.hires||[]).map(h=>({job:text(h.job),headcount:text(h.count),required_skill:text(h.skill),hire_month:h.when||null})),
  no_equipment:!!info.noEquipment,
  equipment:(info.equipment||[]).map(e=>({name:text(e.name),status:e.status||null})),
  no_partners:!!info.noPartners,
  partners:(info.partners||[]).map(p=>({name:text(p.name),status:p.status||null})),
 };
}

export default function App(){
 const projectRequest=useRef(0);
 const [view,setViewState]=useState('landing');
 // 화면을 떠나는 즉시 진행 중이던 요청의 화면 갱신 권한을 무효화한다.
 const setView=(next)=>{projectRequest.current++;setViewState(next)};
 const [notifyEnabled,setNotifyEnabled]=useState(true);
 const [user,setUser]=useState(null);const [loginOpen,setLoginOpen]=useState(false);const [authChecked,setAuthChecked]=useState(false);
 const [myPageNudgeOpen,setMyPageNudgeOpen]=useState(false);
 // 현재 진행 중인 프로젝트/워크플로우 데이터(itemInfo, announcement, projectId, pipelineResult,
 // matchCandidates, checkedFailedTitles, returnToDashboard, scoreOutcome/docOutcome/artifactOutcome)는
 // 전역 스토어(store/useWorkflowStore.js, Zustand)가 들고 있다 — 아래 화면들에는 지금처럼 그대로
 // props로 넘긴다. 매칭 후보(matchCandidates)는 여기서 들고 있는다 — MatchResults 안에 두면 자격
 // 확인 화면을 다녀올 때마다 컴포넌트가 다시 마운트되면서 후보를 새로 받아오고, 임시 백엔드가
 // 매번 random으로 점수를 매겨서 공고 목록과 적합도가 통째로 바뀌어 버린다(사용자 지적). 프로젝트가
 // 바뀔 때만 비운다. projectId/pipelineResult는 eligibility-gate부터 화면에 그대로 뿌린다
 // (app/routers/projects.py _build_demo_response 참고).
 const {
  itemInfo,announcement,checkedFailedTitles,returnToDashboard,scoreOutcome,docOutcome,artifactOutcome,
  projectId,pipelineResult,matchCandidates,
  setItemInfo,setAnnouncement,setCheckedFailedTitles,setReturnToDashboard,setDocOutcome,setArtifactOutcome,
  setProjectId,setPipelineResult,setMatchCandidates,setVerdictPending,resetScoreOutcome,resetProject,
 }=useWorkflowStore();
 useEffect(()=>{window.scrollTo({top:0});document.title=(view==='landing'?'아이디어를 다음 단계로':'나의 워크스페이스')+' | S-Brain'},[view]);
 // 위 RESUMABLE_VIEWS 화면에 머무는 동안엔 매번 "지금 보던 화면"을 기록해둔다 — 검수는
 // 편도(4-7)라 한 번 도달하면 그 뒤로도 계속 검수로 남는 게 맞다.
 useEffect(()=>{
  if(projectId&&RESUMABLE_VIEWS.includes(view)){
   const saved=localStorage.getItem(lastViewKey(projectId));
   if(saved!=='review')localStorage.setItem(lastViewKey(projectId),view);
  }
 },[view,projectId]);
 // 새로고침해도 로그인 상태가 유지되게, 마운트 시 세션 쿠키가 아직 유효한지 GET /auth/me로
 // 한 번 확인한다. 유효하면(200) 그 응답으로 user를 복원 — 로그인 화면도, 동의 화면도 다시
 // 안 거친다(백엔드가 users 테이블에 이미 행이 있다는 것 자체를 "예전에 필수 동의를 마쳤다"는
 // 근거로 취급하는 셈 — 필수 동의 자체를 저장하는 컬럼은 없어서 이게 최선). 401이면(로그인
 // 안 된 상태) fetchCurrentUser가 null을 돌려주므로 아무 것도 안 하고 기존처럼 로그인 버튼을 보여준다.
 useEffect(()=>{
  let cancelled=false;
  fetchCurrentUser().then(u=>{
   if(cancelled)return;
   if(!u){useMyPageStore.getState().reset();return}
   setUser(u);setNotifyEnabled(u.notify_enabled);
   // 마이페이지 정보 슬롯을 서버에서 끌어온다 — 이걸 안 하면 다른 기기에서 저장한 값이
   // 이 브라우저의 로컬 캐시(onboarded:false)에 가려서 또 저장하라고 뜬다(useMyPageStore.js
   // loadProfiles 주석 참고).
   useMyPageStore.getState().loadProfiles();
  }).finally(()=>{if(!cancelled)setAuthChecked(true)});
  return ()=>{cancelled=true};
 },[]);
 // 마이페이지를 "저장"으로 확정하기 전까지는 실제 기능 화면으로 못 들어가게 막는다 —
 // user.has_profile은 서버가 /auth/me·로그인 응답마다 계산해서 내려주는 값이라(정재희님
 // 인계서, back/app/routers/profile.py compute_has_profile) 로그아웃 후 재로그인하거나
 // 다른 기기에서 로그인해도 정확하다 — 브라우저 로컬 상태(예전 useMyPageStore의 onboarded)
 // 에만 의존하면 로그아웃 시 로컬을 비우는 순간 "저장 안 한 것"처럼 보이는 문제가 있었다.
 // 랜딩은 예외라 로그인만 하고 정보 저장 전에도 자유롭게 구경할 수 있다 — 실제로 막는
 // 시점은 "시작하기"를 눌러 대시보드로 들어가려는 순간(아래 startFlow)이다. 이 effect는
 // 그 이후에도 저장 없이 다른 메뉴로 나가려 하면(홈 제외) 다시 막아주는 안전망이다.
 // 관리자 계정은 예외로 둔다.
 useEffect(()=>{
  if(!authChecked||!user||user.role==='admin'){setMyPageNudgeOpen(false);return}
  if(view==='landing'||view==='mypage'){setMyPageNudgeOpen(false);return}
  setMyPageNudgeOpen(!user.has_profile);
 },[view,user,authChecked]);
 const startNewProject=()=>{projectRequest.current++;resetProject();resetScoreOutcome('fail');setView('intake')};

 const handleIntakeSubmit=async(info)=>{
  setItemInfo({...info});
  setCheckedFailedTitles([]);
  setMatchCandidates(null);
  resetScoreOutcome('fail');
  setProjectId(null);
  setView('match-progress');
  const request=projectRequest.current;
  try{
   const payload={
    // [2026-09-17] applicant_type(신청자 유형)은 IntakeForm이 필수로 물어보는데도 지금까지
    // 여기서 빠져 있어서, 화면에서 고른 값이 서버로 안 가고 그냥 버려지고 있었다(하정원님
    // 지적으로 발견) — companies.applicant_type 컬럼/저장 로직 추가(app/models.py,
    // app/routers/projects.py)와 같이 고쳤다.
    applicant_type:info.applicantType||null,
    // [2026-09-17 삭제] start_type/notify_region/notify_industry는 IntakeForm이 입력칸 자체를
    // 안 물어보는데도 팀 테스트 스크립트와 맞추려고 '온라인'/'전국'/'기타' 고정값을 계속
    // 보내고 있었다(하정원님이 실제 INSERT 로그를 보고 지적, "지워" 지시). 백엔드도 더 이상
    // 이 필드들을 받지 않으므로(app/schemas.py ProjectCreateRequest 참고) 여기서도 뺐다.
    // 나중에 진짜 입력칸이 생기면 그때 다시 추가.
    biz_type:null,
    ceo_name:info.ceoName||null,
    founded_at:info.foundedAt||null,
    description:info.item,
    team_members:(info.team||[]).map(t=>({name:t.name,role:t.role||null,experience:t.career||t.experience||null})),
    pricing_items:(info.pricing||[]).map(p=>({service_name:p.item,unit_price:parsePrice(p.price)})),
    ...intakeDetailPayload(info),
   };
   const project=await createProject(payload,info.files||[]);
   if(request!==projectRequest.current)return;
   setProjectId(project.project_id);
  }catch(err){
   if(request!==projectRequest.current)return;
   console.error('프로젝트를 만들지 못했어요',err);
   window.alert(err.message||'프로젝트를 만들지 못했어요. 다시 시도해 주세요.');
   setView('intake');
  }
 };

 // targetView: 알림에서 열 때처럼 특정 화면으로 바로 가야 할 때만 넘긴다.
 const handleOpenProject=async(project,targetView)=>{
  // 이전 프로젝트 화면을 먼저 닫아 요청 중인 작업과 마지막 화면 기록을 분리한다.
  setView('dashboard');
  const request=++projectRequest.current;
  setReturnToDashboard(true);
  setMatchCandidates(null);
  setCheckedFailedTitles([]);
  try{
   const detail=await getProject(project.id);
   if(request!==projectRequest.current)return;
   setItemInfo({
    item:detail.description, applicantType:detail.company?.applicant_type||'',
    ceoName:detail.company?.ceo_name||'', foundedAt:detail.company?.founded_at||'',
    team:(detail.team_members||[]).map(t=>({name:t.name,role:t.role||'',career:t.experience||''})),
    pricing:(detail.pricing_items||[]).map(p=>({item:p.service_name,price:p.unit_price==null?'':String(p.unit_price)})),
    files:[], attachments:detail.attachments||[],
   });
  }catch(err){
   if(request!==projectRequest.current)return;
   window.alert('프로젝트 정보를 불러오지 못했어요. 다시 시도해 주세요.');
   return;
  }
  // [2026-09-19] 예전엔 project.progress>=100(=stage==='done')로 "이미 공고 매칭까지
  // 끝났으니 결과를 불러오자"를 판단했는데, Dashboard가 progress를 "review 화면까지 본
  // 적 있음" 기준으로 바꾸면서(사용자 지적: 사업계획서만 쓰고 나가도 준비완료로 잘못
  // 뜨던 버그) 이 조건이 같이 깨졌다 — 매칭은 됐지만 아직 review 전인 프로젝트를 다시
  // "공고 찾기"로 보내버리는 회귀가 생겨서, 매칭 여부(project.matched)로 따로 판단한다.
  if(project.matched){
   try{
    const [result,status]=await Promise.all([getProjectResult(project.id),getProjectStatus(project.id)]);
    if(request!==projectRequest.current)return;
    setPipelineResult(result);
    setAnnouncement({title:project.announcementTitle,org:'',deadline:'',amount:'',fit:result.match.fit_score,reason:result.match.reason,eligibility:{},originalUrl:''});
    // [2026-09-23, 백엔드 전달사항 3번] verdict는 산출물 채점까지 끝나야 나오므로 계획서만
    // 완성되고 프로토타입이 아직이면 null로 내려온다(app/schemas.py DemoGenerateResponse).
    // 예전엔 이 경우 GET /result가 통째로 404여서 틈이 안 드러났는데, 지금은 정상 응답이라
    // null을 그대로 'fail'로 접으면 채점도 안 한 프로젝트가 화면에 "내부 기준 미달"로 뜬다.
    // 판정이 나온 경우에만 결과를 반영하고, 판정 전이라는 사실은 따로 남긴다.
    setVerdictPending(result.verdict==null);
    if(result.verdict)resetScoreOutcome(result.verdict.overall_passed?'pass':'fail');
    const savedView=localStorage.getItem(lastViewKey(project.id));
    const stageView=status.stage==null?'eligibility-gate':VIEW_BY_STAGE[status.stage]||'plan-form';
    setProjectId(project.id);
    setView(savedView==='review'||status.stage==='reviewing'?'review':targetView||(RESUMABLE_VIEWS.includes(savedView)?savedView:stageView));
   }catch(err){
    if(request!==projectRequest.current)return;
    console.error('결과를 불러오지 못했어요',err);
    window.alert('이 프로젝트 결과를 불러오지 못했어요.');
    setView('dashboard');
   }
  }else{
   setProjectId(project.id);
   setView('match-results');
  }
 };

 // MatchResults가 후보 선택 시 자체적으로 POST /generate까지 호출한 뒤(app/routers/projects.py
 // generate_pipeline_result) 그 응답을 여기로 올려준다 — eligibility-gate는 이 결과를 그대로 쓴다.
 const eligibilityRequest=projectRequest.current;
 const handleCheckEligibility=(candidate,generateResult)=>{
  if(eligibilityRequest!==projectRequest.current)return;
  setAnnouncement({title:candidate.title,org:candidate.org||'',deadline:candidate.apply_end||'',amount:'',fit:candidate.bonus_score,reason:candidate.reason,eligibility:{},originalUrl:candidate.url||''});
  setPipelineResult(generateResult);
  setView('eligibility-gate');
 };

 // 로그인 안 된 상태면 로그인부터. 로그인된 상태에서 "시작하기"를 누른 시점에만 마이페이지
 // 저장 여부를 검사한다 — 랜딩을 보는 동안은 막지 않고, 실제로 기능을 쓰려는 순간(여기)에
 // 저장 안 됐으면 대시보드로 보내는 대신 강제 모달을 띄운다(관리자는 예외).
 const startFlow=()=>{
  if(!user){setLoginOpen(true);return}
  if(user.role!=='admin'&&!user.has_profile){setMyPageNudgeOpen(true);return}
  setView('dashboard');
 };
 // acc는 백엔드가 돌려준 실제 UserOut(POST /auth/google 응답) — notify_enabled도 여기 들어있어서
 // 로컬 동의 체크박스값(consent.notifyAgreed) 대신 서버가 실제로 저장한 값을 신뢰한다.
 const handleLoginSuccess=acc=>{setUser(acc);setLoginOpen(false);setNotifyEnabled(acc.notify_enabled);useMyPageStore.getState().loadProfiles()};
 // 로그아웃은 화면 전환이 먼저 느껴지도록 user state부터 지우고, 서버 세션 쿠키 삭제(POST
 // /auth/logout)는 기다리지 않고 백그라운드로 보낸다 — 실패해도(오프라인 등) 어차피 프론트
 // 쪽에서는 로그아웃된 것처럼 보여주면 되고, logout() 내부에서 에러를 삼키게 해뒀다.
 // 마이페이지 값은 localStorage에 남으므로 같은 브라우저의 다음 사용자에게 보이지 않게 비운다.
 const handleLogout=()=>{projectRequest.current++;logout();useMyPageStore.getState().reset();resetProject();setUser(null);setView('landing')};
 // 관리자 판별은 프론트 이메일 목록이 아니라 백엔드가 내려주는 실제 role로 한다.
 const isAdmin=user?.role==='admin';
 if(!authChecked)return null; // 세션 확인 전 깜빡임(로그인 화면 잠깐 보였다 사라짐) 방지
 let body;
 if(view==='admin')body=<AdminDashboard user={user} onExit={()=>setView('landing')}/>;
 else if(view==='landing')body=<React.Fragment><Landing onStart={startFlow} user={user} isAdmin={isAdmin} onOpenAdmin={()=>setView('admin')} onMyPage={()=>setView('mypage')} onLogin={()=>setLoginOpen(true)} onLogout={handleLogout} notifyEnabled={notifyEnabled} onToggleNotify={()=>setNotifyEnabled(x=>!x)} onOpenProject={handleOpenProject}/><LoginModal open={loginOpen} onClose={()=>setLoginOpen(false)} onSuccess={handleLoginSuccess}/></React.Fragment>;
 else body=<WorkspaceShell view={view} user={user} onHome={()=>setView('landing')} onDashboard={()=>setView('dashboard')} onMyPage={()=>setView('mypage')} onNewProject={startNewProject} onLogout={handleLogout} notifyEnabled={notifyEnabled} onToggleNotify={()=>setNotifyEnabled(x=>!x)} onOpenProject={handleOpenProject}>
  {/* onSaved: 저장 성공 시 /auth/me를 다시 불러 user.has_profile을 최신값으로 갱신한다 —
      안 하면 로그인 시점에 false였던 값이 이번 세션 내내 그대로 남아 "시작하기"가 계속
      막힌다(방금 막 저장했는데도). */}
  {view==='mypage'&&<MyPage onSaved={()=>fetchCurrentUser().then(u=>{if(u)setUser(u)})}/>}
  {view==='dashboard'&&<Dashboard onNewProject={startNewProject} onOpenProject={handleOpenProject}/>}
  {view==='intake'&&<IntakeForm initialValues={itemInfo} onSubmit={handleIntakeSubmit} onBack={()=>setView('dashboard')} backLabel="내 프로젝트로 돌아가기"/>}
  {view==='match-progress'&&<MatchProgress ready={!!projectId} onComplete={()=>setView('match-results')}/>}
  {view==='match-results'&&<MatchResults projectId={projectId} candidates={matchCandidates} onCandidatesLoaded={setMatchCandidates} onBack={()=>setView(returnToDashboard?'dashboard':'intake')} backLabel={returnToDashboard?'내 프로젝트로 돌아가기':'아이템 정보 다시 입력하기'} onCheckEligibility={handleCheckEligibility} disabledTitles={checkedFailedTitles}/>}
  {view==='eligibility-gate'&&<EligibilityGate announcement={announcement} eligibility={pipelineResult?.eligibility} onProceed={()=>setView('plan-progress')} onLeave={(title,failed)=>{if(failed)setCheckedFailedTitles(p=>[...new Set([...p,title])]);setView('match-results')}}/>}
  {view==='plan-progress'&&<GenerationProgress kind="plan" projectId={projectId} onDone={()=>setView('plan-form')} onLeave={()=>setView('dashboard')}/>}
  {view==='plan-form'&&<PlanForm announcement={announcement} onGenerate={()=>setView('artifact-progress')} scoreOutcome={scoreOutcome} itemInfo={itemInfo} projectId={projectId}/>}
  {view==='artifact-progress'&&<GenerationProgress kind="artifact" projectId={projectId} itemInfo={itemInfo} onDone={()=>setView('artifact-result')} onLeave={()=>setView('dashboard')}/>}
  {view==='artifact-result'&&<ArtifactResult announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('plan-form')} onFinalize={()=>setView('final-verdict')} scoreOutcome={scoreOutcome} projectId={projectId}/>}
  {view==='final-verdict'&&<FinalVerdict announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('artifact-result')} onProceed={()=>setView('review')} docOutcome={docOutcome} artifactOutcome={artifactOutcome} setDocOutcome={setDocOutcome} setArtifactOutcome={setArtifactOutcome} projectId={projectId}/>}
  {view==='review'&&<ReviewScreen announcement={announcement} itemInfo={itemInfo} docOutcome={docOutcome} artifactOutcome={artifactOutcome} onGoDashboard={()=>setView('dashboard')} projectId={projectId} verdict={pipelineResult?.verdict}/>}
 </WorkspaceShell>;
 // 저장 전 강제 이동 모달은 view가 무엇이든(랜딩·워크스페이스 어느 화면 위에도) 뜰 수 있어야
 // 하므로 세 분기 바깥, 최상위에서 한 번만 렌더한다.
 return <React.Fragment>{body}<MyPageNudge open={myPageNudgeOpen} onGo={()=>setView('mypage')}/></React.Fragment>;
}
