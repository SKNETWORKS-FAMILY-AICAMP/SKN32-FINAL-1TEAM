import React,{useState,useEffect,Suspense,lazy} from 'react';
import Landing from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import {LoginModal,fetchCurrentUser,logout} from './components/Login.jsx';
import AdminDashboard from './features/Admin.jsx';
import MyPage from './features/mypage/MyPage.jsx';
import {useMyPageStore} from './store/useMyPageStore.js';
import {IntakeForm,MatchProgress,MatchResults,EligibilityGate,PlanForm,ArtifactResult,FinalVerdict,ReviewScreen,SIMILAR_ANNOUNCEMENT_ALERTS} from './features/Workflow.jsx';
import {createProject,getProjectResult} from './api.js';
import {useWorkflowStore} from './store/useWorkflowStore.js';

// [2026-09-15, 프론트 통합 임시 구현] "단가" 입력칸은 자유 텍스트("500원" 등)라서 서버가
// 기대하는 숫자(unit_price)를 뽑아내려면 이 정도 파싱이 필요하다 — 숫자를 못 찾으면 null(미정)로 보낸다.
function parsePrice(text){
 const digits=(text||'').replace(/[^0-9.]/g,'');
 if(!digits)return null;
 const n=Number(digits);
 return Number.isFinite(n)?n:null;
}

export default function App(){
 const [view,setView]=useState('landing');
 const [notifyEnabled,setNotifyEnabled]=useState(true);
 const [user,setUser]=useState(null);const [loginOpen,setLoginOpen]=useState(false);const [authChecked,setAuthChecked]=useState(false);
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
  setProjectId,setPipelineResult,setMatchCandidates,resetScoreOutcome,resetProject,
 }=useWorkflowStore();
 useEffect(()=>{window.scrollTo({top:0});document.title=(view==='landing'?'아이디어를 다음 단계로':'나의 워크스페이스')+' | S-Brain'},[view]);
 // 새로고침해도 로그인 상태가 유지되게, 마운트 시 세션 쿠키가 아직 유효한지 GET /auth/me로
 // 한 번 확인한다. 유효하면(200) 그 응답으로 user를 복원 — 로그인 화면도, 동의 화면도 다시
 // 안 거친다(백엔드가 users 테이블에 이미 행이 있다는 것 자체를 "예전에 필수 동의를 마쳤다"는
 // 근거로 취급하는 셈 — 필수 동의 자체를 저장하는 컬럼은 없어서 이게 최선). 401이면(로그인
 // 안 된 상태) fetchCurrentUser가 null을 돌려주므로 아무 것도 안 하고 기존처럼 로그인 버튼을 보여준다.
 useEffect(()=>{
  let cancelled=false;
  fetchCurrentUser().then(u=>{if(!cancelled&&u){setUser(u);setNotifyEnabled(u.notify_enabled)}})
   .finally(()=>{if(!cancelled)setAuthChecked(true)});
  return ()=>{cancelled=true};
 },[]);
 const startNewProject=()=>{resetProject();resetScoreOutcome('fail');setView('intake')};

 const handleIntakeSubmit=async(info)=>{
  setItemInfo({...info});
  setCheckedFailedTitles([]);
  setMatchCandidates(null);
  resetScoreOutcome('fail');
  setView('match-progress');
  try{
   const payload={
    // IntakeForm은 신청자 유형(예비창업자/개인/법인)만 물을 뿐 "온라인/오프라인" 같은
    // start_type을 따로 묻지 않아서, 팀 테스트 스크립트(create_test_project.py)와 같은
    // 고정값을 임시로 채운다 — notify_region/notify_industry도 아직 입력칸이 없어 마찬가지다.
    start_type:'온라인',
    biz_type:null,
    ceo_name:info.ceoName||null,
    founded_at:info.foundedAt||null,
    description:info.item,
    notify_region:'전국',
    notify_industry:'기타',
    team_members:(info.team||[]).map(t=>({name:t.name,role:t.role||null,experience:t.experience||null})),
    pricing_items:(info.pricing||[]).map(p=>({service_name:p.item,unit_price:parsePrice(p.price)})),
   };
   const project=await createProject(payload,info.files||[]);
   setProjectId(project.project_id);
  }catch(err){
   console.error('프로젝트를 만들지 못했어요',err);
   window.alert(err.message||'프로젝트를 만들지 못했어요. 다시 시도해 주세요.');
   setView('intake');
  }
 };

 const handleOpenProject=async(project)=>{
  setReturnToDashboard(true);
  setProjectId(project.id);
  setMatchCandidates(null);
  setItemInfo({item:project.name});
  if(project.progress>=100){
   try{
    const result=await getProjectResult(project.id);
    setPipelineResult(result);
    setAnnouncement({title:project.announcementTitle,org:'',deadline:'',amount:'',fit:result.match.fit_score,reason:result.match.reason,eligibility:{},originalUrl:''});
    resetScoreOutcome(result.verdict?.overall_passed?'pass':'fail');
    setView('review');
   }catch(err){
    console.error('결과를 불러오지 못했어요',err);
    window.alert('이 프로젝트 결과를 불러오지 못했어요.');
    setView('dashboard');
   }
  }else{
   setView('match-results');
  }
 };

 // MatchResults가 후보 선택 시 자체적으로 POST /generate까지 호출한 뒤(app/routers/projects.py
 // generate_pipeline_result) 그 응답을 여기로 올려준다 — eligibility-gate는 이 결과를 그대로 쓴다.
 const handleCheckEligibility=(candidate,generateResult)=>{
  setAnnouncement({title:candidate.title,org:candidate.org||'',deadline:candidate.apply_end||'',amount:'',fit:candidate.fit_score,reason:candidate.reason,eligibility:{},originalUrl:candidate.url||''});
  setPipelineResult(generateResult);
  setView('eligibility-gate');
 };

 // 로그인 안 된 상태면 로그인부터, 이미 로그인돼 있으면 바로 내 프로젝트 목록으로 보낸다.
 const startFlow=()=>{if(user)setView('dashboard');else setLoginOpen(true)};
 // acc는 백엔드가 돌려준 실제 UserOut(POST /auth/google 응답) — notify_enabled도 여기 들어있어서
 // 로컬 동의 체크박스값(consent.notifyAgreed) 대신 서버가 실제로 저장한 값을 신뢰한다.
 const handleLoginSuccess=acc=>{setUser(acc);setLoginOpen(false);setNotifyEnabled(acc.notify_enabled)};
 // 로그아웃은 화면 전환이 먼저 느껴지도록 user state부터 지우고, 서버 세션 쿠키 삭제(POST
 // /auth/logout)는 기다리지 않고 백그라운드로 보낸다 — 실패해도(오프라인 등) 어차피 프론트
 // 쪽에서는 로그아웃된 것처럼 보여주면 되고, logout() 내부에서 에러를 삼키게 해뒀다.
 // 마이페이지 값은 localStorage에 남으므로 같은 브라우저의 다음 사용자에게 보이지 않게 비운다.
 const handleLogout=()=>{logout();useMyPageStore.getState().reset();setUser(null);setView('landing')};
 // 관리자 판별은 프론트 이메일 목록이 아니라 백엔드가 내려주는 실제 role로 한다.
 const isAdmin=user?.role==='admin';
 if(!authChecked)return null; // 세션 확인 전 깜빡임(로그인 화면 잠깐 보였다 사라짐) 방지
 if(view==='admin')return <AdminDashboard user={user} onExit={()=>setView('landing')}/>;
 if(view==='landing')return <React.Fragment><Landing onStart={startFlow} user={user} isAdmin={isAdmin} onOpenAdmin={()=>setView('admin')} onLogin={()=>setLoginOpen(true)} onLogout={handleLogout}/><LoginModal open={loginOpen} onClose={()=>setLoginOpen(false)} onSuccess={handleLoginSuccess}/></React.Fragment>;
 return <WorkspaceShell view={view} user={user} onHome={()=>setView('landing')} onDashboard={()=>setView('dashboard')} onMyPage={()=>setView('mypage')} onNewProject={startNewProject} onLogout={handleLogout} notifyEnabled={notifyEnabled} onToggleNotify={()=>setNotifyEnabled(x=>!x)}>
  {view==='mypage'&&<MyPage/>}
  {view==='dashboard'&&<Dashboard onNewProject={startNewProject} onOpenProject={handleOpenProject} notifyEnabled={notifyEnabled} alerts={SIMILAR_ANNOUNCEMENT_ALERTS}/>}
  {view==='intake'&&<IntakeForm onSubmit={handleIntakeSubmit} onBack={()=>setView('dashboard')} backLabel="내 프로젝트로 돌아가기"/>}
  {view==='match-progress'&&<MatchProgress onComplete={()=>setView('match-results')}/>}
  {view==='match-results'&&<MatchResults projectId={projectId} candidates={matchCandidates} onCandidatesLoaded={setMatchCandidates} onBack={()=>setView(returnToDashboard?'dashboard':'intake')} backLabel={returnToDashboard?'내 프로젝트로 돌아가기':'아이템 정보 다시 입력하기'} onCheckEligibility={handleCheckEligibility} disabledTitles={checkedFailedTitles}/>}
  {view==='eligibility-gate'&&<EligibilityGate announcement={announcement} eligibility={pipelineResult?.eligibility} onProceed={()=>setView('plan-form')} onLeave={(title,failed)=>{if(failed)setCheckedFailedTitles(p=>[...new Set([...p,title])]);setView('match-results')}}/>}
  {view==='plan-form'&&<PlanForm announcement={announcement} onGenerate={()=>setView('artifact-result')} scoreOutcome={scoreOutcome} itemInfo={itemInfo}/>}
  {view==='artifact-result'&&<ArtifactResult announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('plan-form')} onFinalize={()=>setView('final-verdict')} scoreOutcome={scoreOutcome}/>}
  {view==='final-verdict'&&<FinalVerdict announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('artifact-result')} onProceed={()=>setView('review')} docOutcome={docOutcome} artifactOutcome={artifactOutcome} setDocOutcome={setDocOutcome} setArtifactOutcome={setArtifactOutcome}/>}
  {view==='review'&&<ReviewScreen announcement={announcement} itemInfo={itemInfo} docOutcome={docOutcome} artifactOutcome={artifactOutcome} onGoDashboard={()=>setView('dashboard')} projectId={projectId}/>}
 </WorkspaceShell>
}
