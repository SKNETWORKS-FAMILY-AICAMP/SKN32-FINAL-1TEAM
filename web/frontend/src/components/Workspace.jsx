import React,{useState,useEffect} from 'react';
import {Brand,Icon} from './Icons.jsx';
import {NotificationBell} from '../features/Workflow.jsx';
import {listProjects,deleteProject,deleteProjectPermanently} from '../api.js';
import {formatKstDate} from '../time.js';
export const steps=[['intake','아이템 입력'],['match-results','공고 찾기'],['plan-form','사업계획서'],['artifact-result','프로토타입'],['final-verdict','제출 전 점검'],['review','최종 결과물']];
export function WorkspaceShell({view,user,onHome,onDashboard,onMyPage,onNewProject,onLogout,notifyEnabled,onToggleNotify,onOpenProject,children}){
 const index=['match-progress','eligibility-gate','eligibility-fail'].includes(view)?1:view==='plan-progress'?2:view==='artifact-progress'?3:view==='final-pass'?4:view==='review-progress'?5:steps.findIndex(x=>x[0]===view);
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
// 완료(준비 완료)는 서버 stage='done'(오케스트레이터 결과물 · 완료 — 표현 검수까지 끝남)으로 본다. 예전 더미 파이프라인은
// 공고를 고르는 순간 stage가 곧장 'done'이 돼서 브라우저에 남긴 마지막 화면(localStorage)으로 다시 걸렀는데,
// 오케스트레이터는 단계를 실제로 밟아 그 우회가 필요 없다.
const GENERATING_LABEL={plan_writing:'계획서 작성 중',prototype_building:'프로토타입 제작 중'};
export function Dashboard({onNewProject,onOpenProject}){
 const [query,setQuery]=useState('');const [filter,setFilter]=useState('전체');const [guard,setGuard]=useState(false);
 const [projects,setProjects]=useState([]);const [loading,setLoading]=useState(true);const [loadError,setLoadError]=useState(false);
 const [confirmingId,setConfirmingId]=useState(null);const [deletingId,setDeletingId]=useState(null);
 // "완전히 삭제"는 되돌릴 수 없어서 한 단계를 더 둔다 — 이 값이 그 프로젝트 id면 확인 자리가
 // 완전 삭제 최종 확인으로 바뀐다.
 const [permanentId,setPermanentId]=useState(null);

 // 목록을 즉시 다시 받아야 할 때 쓴다(예: 삭제가 409로 거절당해 내 목록이 서버와 어긋났을 때).
 const [reloadKey,setReloadKey]=useState(0);
 const reload=()=>setReloadKey(k=>k+1);
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
    progress:r.stage==='done'?100:0,
    failed:r.match_status==='failed',failedStage:r.stage,
    generating:r.match_status!=='failed'&&GENERATING_LABEL[r.stage]?`${GENERATING_LABEL[r.stage]} ${r.progress_percent??0}%`:null,
    updatedAt:formatKstDate(r.created_at),
   })));
   setLoading(false);
   if(rows.some(r=>r.match_status!=='failed'&&GENERATING_LABEL[r.stage]))timer=setTimeout(load,5000);
  }).catch(err=>{
   console.error('내 프로젝트 목록을 불러오지 못했어요', err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  load();
  return ()=>{cancelled=true;clearTimeout(timer)};
 },[reloadKey]);

 const isNewUser=!loading&&!loadError&&projects.length===0;
 const filtered=projects.filter(p=>(p.name+' '+p.announcementTitle).includes(query)&&(filter==='전체'||(filter==='진행 중'?p.progress<100:p.progress===100)));
 const inProgress=projects.find(p=>p.progress<100)||null;
 // 실패한 프로젝트는 진행 중으로 세지 않는다 — 실패한 작업은 다시 시작할 수 없고 새 작업으로 시작한다
 // (웹연동_변경사항_웹팀전달.md 3.2 · 5절, E-RUN-FAIL).
 const start=()=>{if(inProgress&&!inProgress.failed)setGuard(true);else onNewProject()};

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
  }catch(err){
   console.error('프로젝트를 지우지 못했어요',err);
   // 서버가 409로 거절할 때는 detail에 사유가 온다(예: 생성 중엔 완전 삭제 불가).
   // 아래 체크박스는 p.generating(5초 폴링 스냅샷)으로 막지만, 다른 탭에서 방금 생성이
   // 시작된 직후처럼 폴링이 아직 안 돈 순간엔 열려 있을 수 있다 — 그 틈으로 눌렀을 때
   // "다시 시도해 주세요"만 뜨면 왜 안 되는지 알 수가 없다. 사유가 오면 그대로 띄운다.
   const detail=typeof err?.detail==='string'?err.detail:null;
   // BUSY — 워커가 단계를 도는 중이라 지금은 못 지운다(서버는 아무것도 지우지 않았다). 잠시 뒤 다시 누르면 된다.
   if(err?.code==='BUSY'){window.alert('지금 작업이 진행 중이라 지우지 못했어요. 잠시 뒤 다시 시도해 주세요.');return;}
   window.alert(detail||'프로젝트를 지우지 못했어요. 다시 시도해 주세요.');
   // 거절당했다는 건 내 목록이 서버와 어긋나 있다는 뜻이라 즉시 다시 받아온다.
   if(err?.status===409)reload();
  }finally{
   setDeletingId(null);setConfirmingId(null);setPermanentId(null);
  }
 };

 return <div className="dashboard">
  <div className="dashboard-heading"><div><p>내 프로젝트</p><h1>{isNewUser?'첫 아이디어를 들려주세요':'이어서 준비해 볼까요?'}</h1></div><button className="btn" onClick={start}><Icon name="plus" size={19}/>새 프로젝트</button></div>

  {loading&&<p className="workspace-note">내 프로젝트를 불러오는 중이에요…</p>}
  {loadError&&<p className="workspace-note">프로젝트 목록을 불러오지 못했어요. 새로고침해 주세요.</p>}

  {!loading&&inProgress&&<div className={'continue-card'+(inProgress.failed?' is-failed':'')}>
   <button className="continue-open" onClick={()=>onOpenProject(inProgress)}><span className="continue-icon"><Icon name={inProgress.failed?'close':'file'} size={32}/></span><div><p>{inProgress.failed?'작업이 중단됐어요':'이어서 준비하기'}</p><h2>{inProgress.name}</h2><span>{inProgress.failed?'일시적인 문제로 작업을 완료하지 못했습니다. 새 작업으로 다시 시작해주세요.':inProgress.matched?'계획서·프로토타입 준비를 이어서 진행해요':'공고 선택부터 이어서 진행해요'}</span></div></button>
   <div className="continue-status"><span>{inProgress.failed?'실패했습니다':inProgress.generating||(inProgress.matched?'진행 중':'매칭 대기 중')}</span>{inProgress.failed?<button type="button" className="continue-retry" onClick={onNewProject}>새로 시작하기 <Icon name="chevron" size={19}/></button>:<button type="button" onClick={()=>onOpenProject(inProgress)}>이어서 진행하기 <Icon name="chevron" size={19}/></button>}</div>
  </div>}

  {guard&&<div className="project-guard" role="status"><div><b>먼저 진행 중인 프로젝트를 확인해 주세요</b><p>한 번에 하나의 프로젝트를 준비할 수 있어요.</p></div><button className="btn small" onClick={()=>onOpenProject(inProgress||projects[0])}>이어서 준비하기</button><button className="btn btn-muted small" onClick={()=>{setGuard(false);onNewProject()}}>중단하고 새로 시작</button><button className="icon-button" aria-label="안내 닫기" onClick={()=>setGuard(false)}><Icon name="close"/></button></div>}

  <div className="projects-heading"><h2>전체 프로젝트 <span>{projects.length}</span></h2></div>
  <div className="project-toolbar"><div className="filter-tabs" role="group" aria-label="프로젝트 상태">{['전체','진행 중','완료'].map(f=><button key={f} aria-pressed={filter===f} onClick={()=>setFilter(f)} className={filter===f?'active':''}>{f}</button>)}</div>{!isNewUser&&<label className="project-search"><Icon name="search" size={19}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="프로젝트 검색" aria-label="프로젝트 검색"/></label>}</div>

  <div className="project-list">
   {filtered.map(p=><div className="project-row" key={p.id}>
     <button className="project-row-main" onClick={()=>onOpenProject(p)}>
      <span className={'project-symbol '+(p.failed?'failed':p.progress===100?'done':'')}><Icon name={p.failed?'close':p.progress===100?'check':'folder'} size={26}/></span>
      <div className="project-title"><h3>{p.name}</h3><p>{p.announcementTitle}<span>·</span><span className="project-date">{(p.updatedAt||'').replaceAll('-','.')} 수정</span></p></div>
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
