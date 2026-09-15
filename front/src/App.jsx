import React,{useState,useEffect,Suspense,lazy} from 'react';
import Landing from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import {LoginModal} from './components/Login.jsx';
import AdminDashboard,{isAdminEmail} from './features/Admin.jsx';
import {IntakeForm,MatchProgress,MatchResults,EligibilityGate,PlanForm,ArtifactResult,FinalVerdict,ReviewScreen,SIMILAR_ANNOUNCEMENT_ALERTS,ANNOUNCEMENTS} from './features/Workflow.jsx';
export default function App(){
 const [view,setView]=useState('landing');
 const [itemInfo,setItemInfo]=useState(null); const [announcement,setAnnouncement]=useState(null);
 const [checkedFailedTitles,setCheckedFailedTitles]=useState([]);const [notifyEnabled,setNotifyEnabled]=useState(true);
 const [isNewUser,setIsNewUser]=useState(false);const [returnToDashboard,setReturnToDashboard]=useState(false);
 const [scoreOutcome,setScoreOutcome]=useState('fail');const [docOutcome,setDocOutcome]=useState('fail');const [artifactOutcome,setArtifactOutcome]=useState('fail');
 const [user,setUser]=useState(null);const [loginOpen,setLoginOpen]=useState(false);
 useEffect(()=>{window.scrollTo({top:0});document.title=(view==='landing'?'아이디어를 다음 단계로':'나의 워크스페이스')+' | S-Brain'},[view]);
 const resetScoreOutcome=v=>{setScoreOutcome(v);setDocOutcome(v);setArtifactOutcome(v)};
 const startNewProject=()=>{setReturnToDashboard(false);resetScoreOutcome('fail');setView('intake')};
 const handleIntakeSubmit=info=>{setItemInfo({...info});setCheckedFailedTitles([]);resetScoreOutcome('fail');setView('match-progress')};
 const handleOpenProject=project=>{setAnnouncement(ANNOUNCEMENTS.find(a=>a.title===project.announcementTitle)||null);setItemInfo({item:project.name,ceoName:'김창업',foundedAt:'2025-01-10'});setReturnToDashboard(true);resetScoreOutcome(project.scoreOutcome||'fail');setView(project.view)};
 // 로그인 안 된 상태면 로그인부터, 이미 로그인돼 있으면 바로 내 프로젝트 목록으로 보낸다.
 const startFlow=()=>{if(user)setView('dashboard');else setLoginOpen(true)};
 const handleLoginSuccess=(acc,consent)=>{setUser(acc);setLoginOpen(false);if(consent)setNotifyEnabled(consent.notifyAgreed)};
 const handleLogout=()=>{setUser(null);setView('landing')};
 const isAdmin=isAdminEmail(user?.email);
 if(view==='admin')return <AdminDashboard user={user} onExit={()=>setView('landing')}/>;
 if(view==='landing')return <React.Fragment><Landing onStart={startFlow} user={user} isAdmin={isAdmin} onOpenAdmin={()=>setView('admin')} onLogin={()=>setLoginOpen(true)} onLogout={handleLogout}/><LoginModal open={loginOpen} onClose={()=>setLoginOpen(false)} onSuccess={handleLoginSuccess}/></React.Fragment>;
 return <WorkspaceShell view={view} user={user} onHome={()=>setView('landing')} onDashboard={()=>setView('dashboard')} onNewProject={startNewProject} onLogout={handleLogout} notifyEnabled={notifyEnabled} onToggleNotify={()=>setNotifyEnabled(x=>!x)}>
  {view==='dashboard'&&<Dashboard onNewProject={startNewProject} onOpenProject={handleOpenProject} notifyEnabled={notifyEnabled} alerts={SIMILAR_ANNOUNCEMENT_ALERTS} isNewUser={isNewUser} onToggleNewUser={setIsNewUser}/>}
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
