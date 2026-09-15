import React,{useState,useEffect} from 'react';
import {Brand,Icon} from './Icons.jsx';
import {NotificationBell,SIMILAR_ANNOUNCEMENT_ALERTS} from '../features/Workflow.jsx';
import {listProjects} from '../api.js';
export const steps=[['intake','아이템 입력'],['match-results','공고 찾기'],['plan-form','사업계획서'],['artifact-result','프로토타입'],['final-verdict','제출 전 점검'],['review','최종 결과물']];
export function WorkspaceShell({view,user,onHome,onDashboard,onNewProject,onLogout,notifyEnabled,onToggleNotify,children}){
 const index=['match-progress','eligibility-gate','eligibility-fail'].includes(view)?1:view==='plan-progress'?2:view==='artifact-progress'?3:view==='final-pass'?4:steps.findIndex(x=>x[0]===view);
 return <div className={'workspace view-'+view}><header className="workspace-topbar"><div className="workspace-nav"><Brand onClick={onHome}/><button className={view==='dashboard'?'nav-active':''} onClick={onDashboard}>내 프로젝트</button><span className="nav-spacer"/><span className="demo-badge">체험 모드</span><NotificationBell alerts={SIMILAR_ANNOUNCEMENT_ALERTS} enabled={notifyEnabled} onToggle={onToggleNotify}/><span className="profile-group"><span className="profile-name">{user?.name||'김창업'} 님</span><button className="logout-button" onClick={onLogout}>로그아웃</button></span></div></header>{index>=0&&<nav className="flow-navigation" aria-label="프로젝트 진행 단계"><ol>{steps.map(([key,label],i)=><li key={key} className={i===index?'current':i<index?'complete':''} aria-current={i===index?'step':undefined}><span>{i<index?<Icon name="check" size={13}/>:i+1}</span>{label}</li>)}</ol></nav>}<main className={'workflow-content '+(view==='dashboard'?'is-dashboard':'')} data-view={view} key={view}>{children}</main><footer className="workspace-footer"><span>S-Brain</span><p>체험용 예시 데이터예요. 실제 공고 조회·AI 생성·서버 저장은 연결되지 않았어요.</p></footer></div>
}
// [2026-09-15, 프론트 통합] 예전엔 features/Workflow.jsx의 하드코딩된 MY_PROJECTS를 그대로
// 그렸는데, 이제 마운트 시 GET /projects(api.js listProjects)로 실제 내 프로젝트 목록을
// 받아온다. "신규 사용자 보기" 체크박스(사람이 데모용으로 직접 토글하던 것)는 없앴다 —
// 로딩이 끝났는데 목록이 비어있으면 그게 곧 신규 사용자라는 뜻이라, isNewUser는 실제
// 데이터에서 그대로 계산한다. 파이프라인이 더미로라도 한 번에 끝까지 돌아가는 구조라
// (app/routers/projects.py generate_pipeline_result 주석 참고) 실제로 관측되는 진행률은
// 0(아직 공고 미선택) 아니면 100(stage==='done') 둘 중 하나뿐이다 — 중간 화면에서
// 이어하기는 지원하지 않는다.
export function Dashboard({onNewProject,onOpenProject,notifyEnabled,alerts}){
 const [query,setQuery]=useState('');const [filter,setFilter]=useState('전체');const [guard,setGuard]=useState(false);
 const [projects,setProjects]=useState([]);const [loading,setLoading]=useState(true);const [loadError,setLoadError]=useState(false);

 useEffect(()=>{
  let cancelled=false;
  setLoading(true);setLoadError(false);
  listProjects().then(rows=>{
   if(cancelled)return;
   setProjects(rows.map(r=>({
    id:r.project_id,
    name:r.description,
    announcementTitle:r.notice_title||'아직 매칭된 공고가 없어요',
    progress:r.stage==='done'?100:0,
    updatedAt:(r.created_at||'').slice(0,10),
   })));
   setLoading(false);
  }).catch(err=>{
   console.error('내 프로젝트 목록을 불러오지 못했어요', err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  return ()=>{cancelled=true};
 },[]);

 const isNewUser=!loading&&!loadError&&projects.length===0;
 const filtered=projects.filter(p=>(p.name+' '+p.announcementTitle).includes(query)&&(filter==='전체'||(filter==='진행 중'?p.progress<100:p.progress===100)));
 const inProgress=projects.find(p=>p.progress<100)||null;
 const start=()=>{if(inProgress)setGuard(true);else onNewProject()};

 return <div className="dashboard">
  <div className="dashboard-heading"><div><p>내 프로젝트</p><h1>{isNewUser?'첫 아이디어를 들려주세요':'이어서 준비해 볼까요?'}</h1></div><button className="btn" onClick={start}><Icon name="plus" size={19}/>새 프로젝트</button></div>

  {loading&&<p className="workspace-note">내 프로젝트를 불러오는 중이에요…</p>}
  {loadError&&<p className="workspace-note">프로젝트 목록을 불러오지 못했어요. 새로고침해 주세요.</p>}

  {!loading&&inProgress&&<button className="continue-card" onClick={()=>onOpenProject(inProgress)}><span className="continue-icon"><Icon name="file" size={32}/></span><div><p>이어서 준비하기</p><h2>{inProgress.name}</h2><span>공고 선택부터 이어서 진행해요</span></div><div className="continue-status"><span>매칭 대기 중</span><b>이어서 진행하기 <Icon name="chevron" size={19}/></b></div></button>}

  {guard&&<div className="project-guard" role="status"><div><b>먼저 진행 중인 프로젝트를 확인해 주세요</b><p>한 번에 하나의 프로젝트를 준비할 수 있어요.</p></div><button className="btn small" onClick={()=>onOpenProject(inProgress||projects[0])}>이어서 준비하기</button><button className="btn btn-muted small" onClick={()=>{setGuard(false);onNewProject()}}>중단하고 새로 시작</button><button className="icon-button" aria-label="안내 닫기" onClick={()=>setGuard(false)}><Icon name="close"/></button></div>}

  {!isNewUser&&notifyEnabled&&<div className="match-notice"><span className="notice-mini"><Icon name="file" size={19}/></span><p>비슷한 아이템의 새 공고 <b>{alerts.length}건</b>이 있어요.</p><span>상단 알림에서 확인해 주세요</span></div>}

  <div className="projects-heading"><h2>전체 프로젝트 <span>{projects.length}</span></h2></div>
  <div className="project-toolbar"><div className="filter-tabs" role="group" aria-label="프로젝트 상태">{['전체','진행 중','완료'].map(f=><button key={f} aria-pressed={filter===f} onClick={()=>setFilter(f)} className={filter===f?'active':''}>{f}</button>)}</div>{!isNewUser&&<label className="project-search"><Icon name="search" size={19}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="프로젝트 검색" aria-label="프로젝트 검색"/></label>}</div>

  <div className="project-list">
   {filtered.map(p=><button className="project-row" key={p.id} onClick={()=>onOpenProject(p)}><span className={'project-symbol '+(p.progress===100?'done':'')}><Icon name={p.progress===100?'check':'folder'} size={26}/></span><div className="project-title"><h3>{p.name}</h3><p>{p.announcementTitle}<span>·</span>{(p.updatedAt||'').replaceAll('-','.')} 수정</p></div><span className={'status-pill '+(p.progress===100?'done':'')}>{p.progress===100?'준비 완료':'공고 선택 대기'}</span><Icon name="chevron" size={21}/></button>)}
   {isNewUser
    ? <div className="new-user"><span className="new-user-symbol"><Icon name="folder" size={45}/></span><h3>어떤 아이디어를 준비하고 있나요?</h3><p>아이템을 알려주시면 맞는 공고부터 찾아드릴게요.</p><button className="btn" onClick={onNewProject}>첫 프로젝트 만들기</button></div>
    : !loading&&filtered.length===0
    ? <div className="search-empty"><h3>검색 결과가 없어요</h3><p>다른 이름으로 검색해 보세요.</p><button className="btn btn-muted" onClick={()=>{setQuery('');setFilter('전체')}}>전체 보기</button></div>
    : null}
  </div>
  <p className="workspace-note">작성한 문서는 초안이에요. 제출 전 공고 요건과 내용을 직접 확인해 주세요.</p>
 </div>
}
