import React,{useState,useEffect,Suspense,lazy} from 'react';
import Landing from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import {LoginModal} from './components/Login.jsx';
import AdminDashboard from './features/Admin.jsx';
import {IntakeForm,MatchProgress,MatchResults,EligibilityGate,PlanForm,ArtifactResult,FinalVerdict,ReviewScreen,SIMILAR_ANNOUNCEMENT_ALERTS,ANNOUNCEMENTS} from './features/Workflow.jsx';
import {api} from './api.js';
export default function App(){
 const [view,setView]=useState('landing');
 const [itemInfo,setItemInfo]=useState(null); const [announcement,setAnnouncement]=useState(null);
 const [checkedFailedTitles,setCheckedFailedTitles]=useState([]);const [notifyEnabled,setNotifyEnabled]=useState(true);
 const [savedProject,setSavedProject]=useState(null);const [checkingProject,setCheckingProject]=useState(false);
 const [returnToDashboard,setReturnToDashboard]=useState(false);
 const [scoreOutcome,setScoreOutcome]=useState('fail');const [docOutcome,setDocOutcome]=useState('fail');const [artifactOutcome,setArtifactOutcome]=useState('fail');
 const [user,setUser]=useState(null);const [loginOpen,setLoginOpen]=useState(false);const [authChecked,setAuthChecked]=useState(false);
 useEffect(()=>{window.scrollTo({top:0});document.title=(view==='landing'?'아이디어를 다음 단계로':'나의 워크스페이스')+' | S-Brain'},[view]);
 // 새로고침해도 로그인이 풀리지 않게, 처음 뜰 때 세션 쿠키가 아직 유효한지 확인한다.
 // 401이면 그냥 로그아웃 상태로 두면 되니 에러를 화면에 보여줄 필요는 없다.
 useEffect(()=>{api.get('/auth/me').then(setUser).catch(()=>{}).finally(()=>setAuthChecked(true))},[]);
 // "신규 사용자"인지는 더 이상 사람이 데모용으로 토글하는 게 아니라, 실제로 이 계정이
 // 프로젝트를 만든 적 있는지 서버(GET /projects)에 직접 물어봐서 판단한다 — 로그인/세션
 // 복원으로 user가 바뀔 때마다 다시 확인한다. 여러 개면 최신 것(응답이 이미 최신순)만 쓴다.
 useEffect(()=>{
  if(!user){setSavedProject(null);setCheckingProject(false);return}
  setCheckingProject(true);
  api.get('/projects').then(list=>setSavedProject(list[0]||null)).catch(()=>setSavedProject(null)).finally(()=>setCheckingProject(false));
 },[user]);
 const resetScoreOutcome=v=>{setScoreOutcome(v);setDocOutcome(v);setArtifactOutcome(v)};
 const startNewProject=()=>{setReturnToDashboard(false);resetScoreOutcome('fail');setView('intake')};
 const handleIntakeSubmit=info=>{
  setItemInfo({...info});setCheckedFailedTitles([]);resetScoreOutcome('fail');
  if(info.projectId)setSavedProject({project_id:info.projectId,description:info.item});
  setView('match-progress');
 };
 const handleOpenProject=project=>{
  if(project.project_id){
   // 실제로 만든 프로젝트 이어가기 — 매칭 이후(공고 매칭~산출물 생성)는 아직 그 결과를
   // 만드는 API 자체가 없어서(다른 팀원 오케스트레이터 작업 영역) 데모 흐름으로 이어간다.
   setAnnouncement(null);setItemInfo({item:project.description,ceoName:'',foundedAt:''});
   setReturnToDashboard(true);resetScoreOutcome('fail');setView('match-progress');
   return;
  }
  setAnnouncement(ANNOUNCEMENTS.find(a=>a.title===project.announcementTitle)||null);setItemInfo({item:project.name,ceoName:'김창업',foundedAt:'2025-01-10'});setReturnToDashboard(true);resetScoreOutcome(project.scoreOutcome||'fail');setView(project.view);
 };
 // 로그인 안 된 상태면 로그인부터, 이미 로그인돼 있으면 바로 내 프로젝트 목록으로 보낸다.
 const startFlow=()=>{if(user)setView('dashboard');else setLoginOpen(true)};
 const handleLoginSuccess=(realUser,consent)=>{setUser(realUser);setLoginOpen(false);if(consent)setNotifyEnabled(consent.notifyAgreed)};
 const handleLogout=()=>{api.post('/auth/logout').catch(()=>{}).finally(()=>{setUser(null);setView('landing')})};
 // 관리자 판별은 이제 프론트 이메일 목록이 아니라 백엔드가 내려주는 실제 role로 한다.
 const isAdmin=user?.role==='admin';
 if(!authChecked)return null; // 세션 확인 전 깜빡임(로그인 화면 잠깐 보였다 사라짐) 방지
 if(view==='admin')return <AdminDashboard user={user} onExit={()=>setView('landing')}/>;
 if(view==='landing')return <React.Fragment><Landing onStart={startFlow} user={user} isAdmin={isAdmin} onOpenAdmin={()=>setView('admin')} onLogin={()=>setLoginOpen(true)} onLogout={handleLogout}/><LoginModal open={loginOpen} onClose={()=>setLoginOpen(false)} onSuccess={handleLoginSuccess}/></React.Fragment>;
 return <WorkspaceShell view={view} user={user} onHome={()=>setView('landing')} onDashboard={()=>setView('dashboard')} onNewProject={startNewProject} onLogout={handleLogout} notifyEnabled={notifyEnabled} onToggleNotify={()=>setNotifyEnabled(x=>!x)}>
  {view==='dashboard'&&<Dashboard onNewProject={startNewProject} onOpenProject={handleOpenProject} notifyEnabled={notifyEnabled} alerts={SIMILAR_ANNOUNCEMENT_ALERTS} savedProject={savedProject} checkingProject={checkingProject}/>}
  {view==='intake'&&<IntakeForm onSubmit={handleIntakeSubmit} onBack={()=>setView('dashboard')} backLabel="내 프로젝트로 돌아가기"/>}
  {view==='match-progress'&&<MatchProgress onComplete={()=>setView('match-results')}/>}
  {view==='match-results'&&<MatchResults itemInfo={itemInfo} onBack={()=>setView(returnToDashboard?'dashboard':'intake')} backLabel={returnToDashboard?'내 프로젝트로 돌아가기':'아이템 정보 다시 입력하기'} onCheckEligibility={r=>{setAnnouncement(r);setView('eligibility-gate')}} disabledTitles={checkedFailedTitles}/>}
  {view==='eligibility-gate'&&<EligibilityGate announcement={announcement} itemInfo={itemInfo} onProceed={()=>setView('plan-form')} onLeave={(title,failed)=>{if(failed)setCheckedFailedTitles(p=>[...new Set([...p,title])]);setView('match-results')}}/>}
  {view==='plan-form'&&<PlanForm announcement={announcement} onGenerate={()=>setView('artifact-result')} scoreOutcome={scoreOutcome} itemInfo={itemInfo}/>}
  {view==='artifact-result'&&<ArtifactResult announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('plan-form')} onFinalize={()=>setView('final-verdict')} scoreOutcome={scoreOutcome}/>}
  {view==='final-verdict'&&<FinalVerdict announcement={announcement} itemInfo={itemInfo} onBack={()=>setView('artifact-result')} onProceed={()=>setView('review')} docOutcome={docOutcome} artifactOutcome={artifactOutcome} setDocOutcome={setDocOutcome} setArtifactOutcome={setArtifactOutcome}/>}
  {view==='review'&&<ReviewScreen announcement={announcement} docOutcome={docOutcome} artifactOutcome={artifactOutcome} onGoDashboard={()=>setView('dashboard')}/>}
 </WorkspaceShell>
}
