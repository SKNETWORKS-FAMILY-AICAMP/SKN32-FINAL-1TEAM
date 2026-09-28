import React,{useState,useEffect} from 'react';
import {Brand,Icon} from './Icons.jsx';
import {NotificationBell} from '../features/Workflow.jsx';
import {listProjects,deleteProject,deleteProjectPermanently,startPlanGeneration,startPrototypeGeneration} from '../api.js';
export const steps=[['intake','아이템 입력'],['match-results','공고 찾기'],['plan-form','사업계획서'],['artifact-result','프로토타입'],['final-verdict','제출 전 점검'],['review','최종 결과물']];
export function WorkspaceShell({view,user,onHome,onDashboard,onMyPage,onNewProject,onLogout,notifyEnabled,onToggleNotify,onOpenProject,children}){
 const index=['match-progress','eligibility-gate','eligibility-fail'].includes(view)?1:view==='plan-progress'?2:view==='artifact-progress'?3:view==='final-pass'?4:steps.findIndex(x=>x[0]===view);
 // [2026-09-19] nav를 좌측 끝까지 넓히면서 상단 중앙에 빈 공간이 생겨서(사용자 지적),
 // 예전엔 topbar 아래 별도 줄이던 진행 단계(flow-navigation)를 topbar 안 중앙으로
 // 옮겨 그 공간을 쓴다 — 화면마다 줄 하나씩 줄어드는 효과도 겸한다.
 return <div className={'workspace view-'+view}><header className="workspace-topbar"><div className="workspace-nav"><div className="workspace-nav-left"><Brand onClick={onHome}/><button className={view==='dashboard'?'nav-active':''} onClick={onDashboard}>내 프로젝트</button><button className={view==='mypage'?'nav-active':''} onClick={onMyPage}>마이페이지</button></div><span className="workspace-nav-center">{index>=0&&<ol className="flow-steps-inline" aria-label="프로젝트 진행 단계">{steps.map(([key,label],i)=><li key={key} className={i===index?'current':i<index?'complete':''} aria-current={i===index?'step':undefined}><span>{i<index?<Icon name="check" size={11}/>:i+1}</span>{label}</li>)}</ol>}</span><div className="workspace-nav-right"><NotificationBell enabled={notifyEnabled} onToggle={onToggleNotify} onOpenProject={onOpenProject} refreshKey={view}/><span className="profile-group"><span className="profile-name">{user?.name||'김창업'} 님</span><button className="logout-button" onClick={onLogout}>로그아웃</button></span></div></div></header><main className={'workflow-content '+(view==='dashboard'?'is-dashboard':'')} data-view={view} key={view}>{children}</main></div>
}
// [2026-09-15, 프론트 통합] 예전엔 features/Workflow.jsx의 하드코딩된 MY_PROJECTS를 그대로
// 그렸는데, 이제 마운트 시 GET /projects(api.js listProjects)로 실제 내 프로젝트 목록을
// 받아온다. "신규 사용자 보기" 체크박스(사람이 데모용으로 직접 토글하던 것)는 없앴다 —
// 로딩이 끝났는데 목록이 비어있으면 그게 곧 신규 사용자라는 뜻이라, isNewUser는 실제
// 데이터에서 그대로 계산한다.
// [2026-09-19] 더미 파이프라인은 공고를 고르는 순간 계획서·프로토타입·최종판정을 한 번에
// 다 만들어 stage가 곧장 'done'이 된다(app/routers/projects.py generate_pipeline_result) —
// 그래서 stage만 보면 사용자가 프로토타입 생성도, 검증도 안 열어봤는데 "준비 완료"로
// 뜨는 버그가 있었다(사용자 지적: 공고매칭에서 나가면 "진행 중"으로 뜨는데 사업계획서
// 이후 화면에서 나가면 그걸 인식 못 하고 무조건 완료로 뜸). App.jsx가 화면 전환마다
// project별로 남겨두는 마지막 화면(localStorage `sbrain-last-view:{id}`, RESUMABLE_VIEWS)을
// 같이 봐서 실제로 최종 결과물(review) 화면까지 가본 적 있는 프로젝트만 완료로 친다.
const lastViewKey=(id)=>`sbrain-last-view:${id}`;
const isActuallyDone=(projectId,stage)=>{
 if(stage!=='done')return false;
 try{return localStorage.getItem(lastViewKey(projectId))==='review'}catch(e){return false}
};
const GENERATING_LABEL={plan_writing:'계획서 작성 중',prototype_building:'프로토타입 제작 중'};
export function Dashboard({onNewProject,onOpenProject}){
 const [query,setQuery]=useState('');const [filter,setFilter]=useState('전체');const [guard,setGuard]=useState(false);
 const [projects,setProjects]=useState([]);const [loading,setLoading]=useState(true);const [loadError,setLoadError]=useState(false);
 const [confirmingId,setConfirmingId]=useState(null);const [deletingId,setDeletingId]=useState(null);
 // "완전히 삭제"는 되돌릴 수 없어서 한 단계를 더 둔다 — 이 값이 그 프로젝트 id면 확인 자리가
 // 완전 삭제 최종 확인으로 바뀐다.
 const [permanentId,setPermanentId]=useState(null);
 const [retryingId,setRetryingId]=useState(null);const [retryError,setRetryError]=useState('');

 useEffect(()=>{
  let cancelled=false;let timer=null;
  setLoading(true);setLoadError(false);
  // 계획서·프로토타입이 서버에서 만들어지는 중이면 진행률이 보이도록 주기적으로 다시 불러온다.
  const load=()=>listProjects().then(rows=>{
   if(cancelled)return;
   setProjects(rows.map(r=>({
    id:r.project_id,
    name:r.description,
    announcementTitle:r.notice_title||'아직 매칭된 공고가 없어요',
    matched:!!r.notice_title,
    progress:isActuallyDone(r.project_id,r.stage)?100:0,
    failed:r.match_status==='failed',failedStage:r.stage,
    generating:r.match_status!=='failed'&&GENERATING_LABEL[r.stage]?`${GENERATING_LABEL[r.stage]} ${r.progress_percent??0}%`:null,
    updatedAt:(r.created_at||'').slice(0,10),
   })));
   setLoading(false);
   if(rows.some(r=>r.match_status!=='failed'&&GENERATING_LABEL[r.stage]))timer=setTimeout(load,5000);
  }).catch(err=>{
   console.error('내 프로젝트 목록을 불러오지 못했어요', err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  load();
  return ()=>{cancelled=true;clearTimeout(timer)};
 },[]);

 const isNewUser=!loading&&!loadError&&projects.length===0;
 const filtered=projects.filter(p=>(p.name+' '+p.announcementTitle).includes(query)&&(filter==='전체'||(filter==='진행 중'?p.progress<100:p.progress===100)));
 const inProgress=projects.find(p=>p.progress<100)||null;
 const start=()=>{if(inProgress)setGuard(true);else onNewProject()};
 const retryProject=async p=>{
  if(retryingId!=null)return;
  setRetryError('');setRetryingId(p.id);
  try{
   const startTask=p.failedStage==='plan_writing'?startPlanGeneration:startPrototypeGeneration;
   await startTask(p.id);
   onOpenProject(p,p.failedStage==='plan_writing'?'plan-progress':'artifact-progress');
  }catch(err){setRetryError(err.message||'재실행하지 못했어요. 다시 시도해 주세요.');}
  finally{setRetryingId(null)}
 };

 // 휴지통 버튼 — 실수로 바로 지워지지 않게 한 번 더 확인을 거친다. 확인 자리에서 둘 중
 // 하나를 고른다(기획서 6-7 "건별 삭제" 대응):
 //  · 목록에서 숨기기 = DELETE /projects/{id}. 매칭 전이면 서버가 진짜 지우고, 매칭
 //    이후면 보관 처리(archived_at)만 한다 — 관리자 "진행 현황" 탭에서 복원할 수 있다.
 //  · 완전히 삭제 = DELETE /projects/{id}/permanent. 입력값·첨부·계획서·산출물·실행
 //    이력까지 한 번에 지우고 되돌릴 수 없다.
 // 어느 쪽이든 프론트는 내 목록에서 빼면 된다.
 const handleDelete=async(id,permanent)=>{
  setDeletingId(id);
  try{
   await (permanent?deleteProjectPermanently(id):deleteProject(id));
   setProjects(list=>list.filter(p=>p.id!==id));
   try{localStorage.removeItem(lastViewKey(id))}catch(e){}
  }catch(err){
   console.error('프로젝트를 지우지 못했어요',err);
   window.alert('프로젝트를 지우지 못했어요. 다시 시도해 주세요.');
  }finally{
   setDeletingId(null);setConfirmingId(null);setPermanentId(null);
  }
 };

 return <div className="dashboard">
  <div className="dashboard-heading"><div><p>내 프로젝트</p><h1>{isNewUser?'첫 아이디어를 들려주세요':'이어서 준비해 볼까요?'}</h1></div><button className="btn" onClick={start}><Icon name="plus" size={19}/>새 프로젝트</button></div>

  {loading&&<p className="workspace-note">내 프로젝트를 불러오는 중이에요…</p>}
  {loadError&&<p className="workspace-note">프로젝트 목록을 불러오지 못했어요. 새로고침해 주세요.</p>}

  {!loading&&inProgress&&<div className={'continue-card'+(inProgress.failed?' is-failed':'')}>
   <button className="continue-open" onClick={()=>onOpenProject(inProgress)}><span className="continue-icon"><Icon name={inProgress.failed?'close':'file'} size={32}/></span><div><p>{inProgress.failed?'작업이 중단됐어요':'이어서 준비하기'}</p><h2>{inProgress.name}</h2><span>{inProgress.failed?(inProgress.failedStage==='plan_writing'?'사업계획서':'프로토타입')+' 작성 중 실패하였습니다.':inProgress.matched?'계획서·프로토타입 준비를 이어서 진행해요':'공고 선택부터 이어서 진행해요'}</span></div></button>
   <div className="continue-status"><span>{inProgress.failed?'실패했습니다':inProgress.generating||(inProgress.matched?'진행 중':'매칭 대기 중')}</span>{inProgress.failed?<button type="button" className="continue-retry" disabled={retryingId===inProgress.id} onClick={()=>retryProject(inProgress)}>{retryingId===inProgress.id?'재실행 중…':'재실행'} <Icon name="chevron" size={19}/></button>:<button type="button" onClick={()=>onOpenProject(inProgress)}>이어서 진행하기 <Icon name="chevron" size={19}/></button>}</div>
  </div>}
  {retryError&&<p role="alert" className="workspace-retry-error">{retryError}</p>}

  {guard&&<div className="project-guard" role="status"><div><b>먼저 진행 중인 프로젝트를 확인해 주세요</b><p>한 번에 하나의 프로젝트를 준비할 수 있어요.</p></div><button className="btn small" onClick={()=>onOpenProject(inProgress||projects[0])}>이어서 준비하기</button><button className="btn btn-muted small" onClick={()=>{setGuard(false);onNewProject()}}>중단하고 새로 시작</button><button className="icon-button" aria-label="안내 닫기" onClick={()=>setGuard(false)}><Icon name="close"/></button></div>}

  <div className="projects-heading"><h2>전체 프로젝트 <span>{projects.length}</span></h2></div>
  <div className="project-toolbar"><div className="filter-tabs" role="group" aria-label="프로젝트 상태">{['전체','진행 중','완료'].map(f=><button key={f} aria-pressed={filter===f} onClick={()=>setFilter(f)} className={filter===f?'active':''}>{f}</button>)}</div>{!isNewUser&&<label className="project-search"><Icon name="search" size={19}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="프로젝트 검색" aria-label="프로젝트 검색"/></label>}</div>

  <div className="project-list">
   {filtered.map(p=><div className="project-row" key={p.id}>
     <button className="project-row-main" onClick={()=>onOpenProject(p)}>
      <span className={'project-symbol '+(p.failed?'failed':p.progress===100?'done':'')}><Icon name={p.failed?'close':p.progress===100?'check':'folder'} size={26}/></span>
      <div className="project-title"><h3>{p.name}</h3><p>{p.announcementTitle}<span>·</span>{(p.updatedAt||'').replaceAll('-','.')} 수정</p></div>
      <span className={'status-pill '+(p.failed?'failed':p.progress===100?'done':'')}>{p.failed?'실패했습니다':p.progress===100?'준비 완료':p.generating||(p.matched?'진행 중':'공고 선택 대기')}</span>
      <Icon name="chevron" size={21}/>
     </button>
     {confirmingId===p.id?(
      /* "지울까요?"는 한 번만 묻고, 자료까지 지울지는 체크 하나로 고르게 한다 — 버튼 두
         개를 나란히 두면 사용자가 둘의 차이부터 해석해야 해서(사용자 지적) 그냥 지우고
         싶은 사람까지 멈춰 세운다. 체크를 켜면 문구와 버튼이 같이 바뀌어서, 지금 무엇을
         누르는지가 누르기 전에 보인다. */
      <div className="project-row-confirm">
       <span>{permanentId===p.id
        ?'계획서·프로토타입·첨부까지 모두 지워요. 되돌릴 수 없어요.'
        :'이 프로젝트를 지울까요?'}</span>
       {/* 생성이 도는 중에 자료를 지우면 서버 백그라운드 작업이 없는 행을 계속 쓴다
           (app/routers/projects.py _simulate_generation) — 끝난 뒤에 지우게 막는다. */}
       <label className={'confirm-check'+(p.generating?' is-off':'')}
         title={p.generating?'만드는 중에는 자료를 지울 수 없어요. 끝난 뒤에 지워 주세요':undefined}>
        <input type="checkbox" checked={permanentId===p.id} disabled={deletingId===p.id||!!p.generating}
          onChange={e=>setPermanentId(e.target.checked?p.id:null)}/>
        자료까지 지우기
       </label>
       <button className={'text-link'+(permanentId===p.id?' is-danger':'')} disabled={deletingId===p.id}
         onClick={()=>handleDelete(p.id,permanentId===p.id)}>
        {deletingId===p.id?'지우는 중…':permanentId===p.id?'완전히 삭제':'삭제'}
       </button>
       <button className="icon-button" aria-label="삭제 취소" onClick={()=>{setConfirmingId(null);setPermanentId(null)}}><Icon name="close" size={15}/></button>
      </div>
     ):(
      <button className="project-row-delete" aria-label={`${p.name} 삭제`} onClick={()=>{setConfirmingId(p.id);setPermanentId(null)}}><Icon name="trash" size={17}/></button>
     )}
    </div>)}
   {isNewUser
    ? <div className="new-user"><span className="new-user-symbol"><Icon name="folder" size={45}/></span><h3>어떤 아이디어를 준비하고 있나요?</h3><p>아이템을 알려주시면 맞는 공고부터 찾아드릴게요.</p><button className="btn" onClick={onNewProject}>첫 프로젝트 만들기</button></div>
    : !loading&&filtered.length===0
    ? <div className="search-empty"><h3>검색 결과가 없어요</h3><p>다른 이름으로 검색해 보세요.</p><button className="btn btn-muted" onClick={()=>{setQuery('');setFilter('전체')}}>전체 보기</button></div>
    : null}
  </div>
  <p className="workspace-note">작성한 문서는 초안이에요. 제출 전 공고 요건과 내용을 직접 확인해 주세요.</p>
 </div>
}
