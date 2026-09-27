import React,{useState,useEffect,useRef} from 'react';
import {Brand,Icon} from '../components/Icons.jsx';
import {api,ApiError} from '../api.js';

// 관리자 판별은 이제 App.jsx에서 /auth/me가 내려주는 실제 role로 한다(props.user.role).
// 이 파일 안에서는 이미 관리자로 확인된 사용자만 보고 있다고 가정한다.

// [2026-09-18] 7개 탭 전부 실제 백엔드(/admin/*)에 연동됐다 — "검증 정책"(policy+
// checklist), "사용자 관리·FAQ"(users+faqs), "에이전트 테스크"의 Execution별 보기
// (agent-executions)·Task별 보기(agent-tasks)·운영 지표 요약(agent-ops-summary),
// "진행 현황"(items+items/{id}/archive+items/{id}/score-history), "공고 관리"
// (notices+collection-status), "운영 현황"(ops-summary), "검수 회수 문단"
// (recovery-items) 전부.
// - "진행 현황"의 "지금 Agent가 뭘 하는지"/"오류 로그"는 여전히 안 내려준다 — 실시간
//   오케스트레이터 상태를 저장하는 테이블이 없다(app/schemas.py ItemOut 주석 참고).
// - "에이전트 테스크"의 "배치 기준"(모델 선택) 열은 2026-09-18에 아예 뺐다 — 저장할
//   백엔드가 없어 고르는 척만 하고 실제로 반영되지 않는 값이었다(AGENT_ROWS 주석 참고).
// - "공고 관리"의 "공고 수집 현황"은 목업의 3번째 카드("지자체 통합공고")가 빠졌다 —
//   실제 notices.source 값은 kstartup/bizinfo 둘뿐이다(NoticeSourceStatusOut 주석 참고).
//   "재수집"/"임베딩 재생성" 액션도 다른 팀원의 수집 파이프라인 스크립트를 여기서
//   실행시킬 방법이 없어 만들지 않았다. "수집 실패 이력"도 "최근 수집 실행 이력"으로
//   바꿨다 — 실제 배치 기록엔 "실패"가 아니라 데이터 품질 이슈만 있어서다(ImportRunOut
//   주석 참고).
// - "운영 현황"의 채점 편차(1회→2회)·"보호 토큰 위반율"은 이제 실제 값이다 —
//   retry_task가 verification_score_history/proofread_logs에 이력을 남기도록
//   고쳤다(app/routers/projects.py retry_task, OpsSummaryOut 주석 참고).
// - "검수 회수 문단"은 proofread_logs.passed=False(보호 토큰 위반 반려 시도)를 그대로
//   라벨링 대기열로 쓴다 — model_version은 그 plan의 최종 verdicts.model_version을
//   붙인 근사치다(RecoveryItemOut 주석 참고).

const TABS=[['ann','공고 관리'],['ops','운영 현황'],['progress','진행 현황'],['agents','에이전트 테스크'],['policy','검증 정책'],['recovery','검수 회수 문단'],['users','사용자 관리·FAQ']];

// (key, 표시 라벨, 배점) — verification_score_history.layer 값과 1:1 대응. ProgressTab의
// "이력보기" 모달과 OpsTab의 "채점 편차" 카드가 공유한다.
const DEVIATION_CATEGORIES=[['doc','문서층 검증',70],['code','코드 기준 검증',15],['plan','계획서 대조',15]];

// key는 실제 DB agent_executions.agent_name 값(app/models.py FIXED_TASK_SEQUENCE) — GET
// /admin/agent-tasks 응답과 매칭하는 데 쓴다. name은 화면 표시용(괄호 설명 포함), work는
// API가 안 내려주는 정적 설명이라 그대로 둔다 — tasks/recent/tone은 이제 서버 값으로
// 대체되어 여기서 뺐다.
// [2026-09-18 삭제] 에이전트별 "사용 모델"/"배치 기준"(모델 선택) 열은 그 설정을 저장할
// 백엔드가 없어 로컬 상태로만 유지되던 기능이었는데, 실제로 값을 만들려면 배치 설정
// 테이블·저장 API까지 새로 설계해야 해서 일이 커진다는 판단으로 뺐다(하정원님 지시) —
// 화면에서만 고르는 척하고 저장도 안 되는 값이라 없는 게 낫다.
const AGENT_ROWS=[
  {key:'조율',name:'조율 (Supervisor)',work:'요구사항 해석·공고 매칭·자격 확인, 실행할 Agent 선정과 작업 분해, 결과 통합'},
  {key:'전략',name:'전략',work:'요구사항 분석, 목표시장 분석'},
  {key:'작성',name:'작성',work:'사업계획서 본문 작성 — 서술, 표, 그래프'},
  {key:'구현',name:'구현',work:'프로토타입 제작 — HTML 실행 파일, 인포그래픽'},
  {key:'검증-1',name:'검증-1 (문서)',work:'문서층 검증. 공개된 평가항목 기준으로 계획서 서술 충족 여부 판정'},
  {key:'검증-2',name:'검증-2 (산출물)',work:'산출물층 검증. 코드 기준 자동 검증과 계획서 대조'},
  {key:'검수',name:'검수 (표현)',work:'사업계획서 문장 형식 적합성 검수 및 한국어 윤문. 자체 파인튜닝 모델을 사용'},
];

// GET /admin/agent-executions 응답(dict 목록, AgentExecutionOut 고정 스키마가 아니라 유연한 형태)을
// 이 화면 행 모양으로 바꾼다. project(프로젝트명)는 API가 안 내려줘서 match_id로 대신 표시한다.
const executionRowFromServer=r=>({
  id:'EXEC-'+r.execution_id,matchId:r.match_id,agent:r.agent_name,tokens:Number(r.token_usage).toLocaleString(),
  rerun:r.rerun_type,rerunTone:r.rerun_type==='rerun'?'primary':'muted',
  status:r.status,statusTone:['completed','success','성공'].includes(r.status)?'ok':'danger',
  tone:!['completed','success','성공'].includes(r.status)?'danger':undefined,
});

// GET /admin/notices(NoticeAdminOut 목록) -> "공고 전체 관리" 표 행. notices는 공고 수집
// 파이프라인(다른 팀원 레포) 소유라 source 원본값(kstartup/bizinfo)만 내려온다 — 화면
// 표기용 한글 라벨은 여기서만 붙인다. "공고 수집 현황"/"최근 수집 실행 이력" 카드는
// GET /admin/collection-status가 담당한다(AnnouncementTab 안에서 직접 매핑).
const NOTICE_SOURCE_LABEL={kstartup:'K-Startup','k-startup':'K-Startup',bizinfo:'기업마당'};
const noticeRowFromServer=n=>{
  const shortDate=d=>d?d.slice(5).replace('-','.'):null;
  const closed=n.recruitment_status==='closed';
  return {
    id:n.notice_id,title:n.title,src:NOTICE_SOURCE_LABEL[n.source]||n.source,
    period:n.apply_start&&n.apply_end?`${shortDate(n.apply_start)}~${shortDate(n.apply_end)}`:'-',
    embed:n.has_embedding?'완료':'미생성',embedTone:n.has_embedding?'ok':'warn',
    status:n.recruitment_status==='open'?'모집중':closed?'마감':n.recruitment_status,
    statusTone:n.recruitment_status==='open'?'ok':'muted',dim:closed,
  };
};

const REPRODUCIBILITY=[
  ['평가항목 Rubric 고정','검증-1은 상수로 고정된 rubric 밖의 기준으로는 감점하지 않습니다.','고정됨','muted'],
  ['근거 위치 출력 필수','항목 점수마다 계획서 원문의 근거 위치를 함께 출력하며, 근거를 제시하지 못한 감점은 무효 처리합니다.','필수','ok'],
  ['채점 온도(temperature)','재현성을 위해 0으로 고정되며 변경할 수 없습니다.','0 (고정)','muted'],
];

const RECOVERY_LABELS={pending:'라벨링 대기',labeled:'라벨링 완료',excluded:'동의 없음(제외)'};

// GET /admin/users, GET /admin/faqs 응답 -> 이 화면 행 모양. 목업 시절엔 가입일/실행건수/
// 보관 산출물 컬럼이 있었는데, UserOut엔 그 필드가 없어서(오케스트레이터·프로젝트 집계 쪽
// 작업 영역) 뺐다. 얼굴 인증(관리자 전환 게이트)은 팀 결정으로 아예 안 하기로 해서
// 화면에도 넣지 않는다 — role 변경은 바로 반영된다.
const userRowFromServer=u=>({id:u.user_id,name:u.name,email:u.email,
  notify:u.notify_enabled?'수신중':'알림 꺼짐',notifyTone:u.notify_enabled?'ok':'muted',
  status:u.status==='active'?'활성':u.status==='suspended'?'정지':'휴면',statusRaw:u.status,
  role:u.role==='admin'?'관리자':'일반 유저',roleRaw:u.role});
// FaqOut엔 작성자 정보가 없어서(faqs 테이블에 user_id는 있지만 관리자 응답에 조인해 내려주지
// 않음) 목업의 "작성자" 컬럼은 뺐다.
const faqRowFromServer=(f,idx,total)=>({id:f.faq_id,no:total-idx,question:f.question,
  date:f.created_at?.slice(0,10),answer:f.answer||'',visible:f.is_visible,answered:f.answer!=null});

// GET /admin/recovery-items(RecoveryItemOut 목록) -> 이 화면 행 모양. 동의(consent)가
// False면 백엔드 recovery_status(pending 기본값)와 무관하게 화면 status는 무조건
// 'excluded'로 취급한다 — "동의 없음(제외)"는 관리자가 고르는 상태가 아니라 계정의
// 학습데이터 활용 동의 여부에 따라 자동으로 정해지는 상태이기 때문이다.
const recoveryItemFromServer=r=>({
  id:r.log_id, project:r.project_description||'(삭제된 프로젝트)', model:r.model_version||'—',
  violation:r.violation_type||'—', occurredAt:r.occurred_at.slice(0,16).replace('T',' '),
  consent:r.consent, original:r.original, attempt:r.attempt,
  status:r.consent?r.recovery_status:'excluded', label:r.label||'',
});

const toneText={ok:'text-[var(--ok)]',warn:'text-[var(--warn)]',danger:'text-[var(--danger)]',muted:'text-[var(--muted-fg)]',primary:'text-[var(--primary)]'};
const toneBg={ok:'bg-[color-mix(in_srgb,var(--ok)_12%,white)] text-[var(--ok)]',warn:'bg-[color-mix(in_srgb,var(--warn)_12%,white)] text-[var(--warn)]',
  danger:'bg-[color-mix(in_srgb,var(--danger)_10%,white)] text-[var(--danger)]',muted:'bg-[var(--muted)] text-[var(--muted-fg)]'};

const Card=({label,value,sub,tone})=>(
  <div className="rounded-2xl border border-[var(--border)] bg-white p-4">
    <p className="text-[12px] text-[var(--muted-fg)] mb-1">{label}</p>
    <p className={'text-[22px] font-bold leading-none '+(tone?toneText[tone]:'')}>{value}</p>
    {sub&&<p className="text-[11px] text-[var(--muted-fg)] mt-1.5">{sub}</p>}
  </div>
);

const Panel=({children,className=''})=>(
  <div className={'rounded-2xl border border-[var(--border)] bg-white overflow-hidden '+className}>{children}</div>
);

const Bar=({label,pct,tone,right,sub})=>(
  <div className="flex items-center gap-3">
    <span className="text-[12px] text-[var(--muted-fg)] w-24 flex-shrink-0">{label}</span>
    <div className="flex-1 h-3 rounded-full bg-[var(--muted)] overflow-hidden">
      <div className={'h-full rounded-full '+(tone==='ok'?'bg-[var(--ok)]':tone==='warn'?'bg-[var(--warn)]':tone==='danger'?'bg-[var(--danger)]':'bg-[var(--muted-fg)]')} style={{width:pct+'%'}}/>
    </div>
    <span className="text-[12px] font-medium w-12 text-right flex-shrink-0">{right}</span>
    {sub!==undefined&&<span className="text-[11px] text-[var(--muted-fg)] w-20 text-right flex-shrink-0">{sub}</span>}
  </div>
);

// 네이티브 <select>는 브라우저 기본 스타일이 그대로 튀어나와 나머지 커스텀 UI와 안 어울린다
// (사용자 지적) — 버튼+목록으로 된 이 컴포넌트로 관리자 대시보드의 select를 전부 대체한다.
function Select({value,onChange,options,className='',ariaLabel}){
  const [open,setOpen]=useState(false);
  const opts=options.map(o=>typeof o==='string'?{value:o,label:o}:o);
  const current=opts.find(o=>o.value===value)||opts[0];
  return (
    <div className="relative inline-block">
      <button type="button" aria-label={ariaLabel} aria-haspopup="listbox" aria-expanded={open} onClick={()=>setOpen(v=>!v)}
        className={'flex items-center justify-between gap-2 bg-white text-[var(--fg)] outline-none focus:border-[var(--primary)] transition-colors '+className}>
        <span className="truncate">{current?current.label:''}</span>
        <Icon name="chevron" size={12} className="flex-shrink-0 text-[var(--muted-fg)]" style={{transform:open?'rotate(-90deg)':'rotate(90deg)',transition:'transform .15s ease-out'}}/>
      </button>
      {open&&(<React.Fragment>
        <div className="fixed inset-0 z-40" onClick={()=>setOpen(false)}/>
        <ul role="listbox" aria-label={ariaLabel}
          className="soft-scroll absolute left-0 top-full mt-1.5 z-50 min-w-full w-max max-h-64 overflow-y-auto rounded-xl border border-[var(--border)] bg-white py-1 shadow-[0_16px_40px_-16px_rgba(20,23,31,.25)]">
          {opts.map(o=>(
            <li key={o.value} role="option" aria-selected={o.value===value}>
              <button type="button" onClick={()=>{onChange(o.value);setOpen(false)}}
                className={'w-full whitespace-nowrap px-3 py-2 text-left text-[13px] hover:bg-[var(--muted)] '+(o.value===value?'font-semibold text-[var(--primary)]':'text-[var(--fg)]')}>
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      </React.Fragment>)}
    </div>
  );
}

function Modal({title,onClose,children,wide}){
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center px-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" onClick={onClose} aria-hidden="true"/>
      <div className={'soft-scroll relative w-full max-h-[85vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)] '+(wide?'max-w-3xl':'max-w-lg')}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-[18px]">{title}</h3>
          <button onClick={onClose} aria-label="닫기" className="text-[var(--muted-fg)] hover:text-[var(--fg)]"><Icon name="close" size={20}/></button>
        </div>
        {children}
      </div>
    </div>
  );
}

const ADMIN_ALERT_SEEN_KEY='sbrain-admin-alerts-seen';
const readAdminSeen=()=>{try{return new Set(JSON.parse(localStorage.getItem(ADMIN_ALERT_SEEN_KEY)||'[]'))}catch{return new Set()}};
const TASK_STATUS_FAILED=new Set(['failed','error','실패']);
function adminAlertsFrom(items,executions){
  const alerts=[];
  const byMatch=new Map(items.filter(i=>i.match_id!=null).map(i=>[i.match_id,i]));
  for(const item of items){
    if(item.archived)continue;
    if(item.match_status==='failed'){
      const kind=item.stage==='plan_writing'?'사업계획서':item.stage==='prototype_building'?'프로토타입':'프로젝트';
      alerts.push({key:`project:${item.match_id}:failed`,kind:'실패',title:`${kind} 생성 실패`,detail:item.failure_reason||'실패 원인을 확인해 주세요.',project:item.description,projectId:item.project_id,tab:'progress',time:item.last_updated});
    }else if(item.stalled){
      alerts.push({key:`project:${item.match_id}:stalled`,kind:'정체',title:'작업 진행이 멈춰 있습니다',detail:'마지막 갱신 이후 48시간이 지났습니다.',project:item.description,projectId:item.project_id,tab:'progress',time:item.last_updated});
    }
  }
  const latest=new Map();
  for(const row of executions){
    const key=`${row.match_id}:${row.task_key||row.agent_name}`;
    if(!latest.has(key))latest.set(key,row);
  }
  for(const row of latest.values()){
    if(!TASK_STATUS_FAILED.has(row.status))continue;
    const item=byMatch.get(row.match_id);
    if(item?.archived)continue;
    alerts.push({key:`task:${row.execution_id}`,kind:'실패',title:`${row.task_key||row.agent_name} Task 오류`,detail:`실행 상태: ${row.status}`,project:item?.description||`매칭 #${row.match_id}`,matchId:row.match_id,tab:'agents',time:row.started_at});
  }
  return alerts.sort((a,b)=>(b.time||'').localeCompare(a.time||''));
}

function AdminNotificationBell({onNavigate}){
  const [open,setOpen]=useState(false);
  const [alerts,setAlerts]=useState([]);
  const [seen,setSeen]=useState(readAdminSeen);
  const [error,setError]=useState('');
  useEffect(()=>{
    let cancelled=false,timer;
    const load=()=>Promise.all([api.get('/admin/items'),api.get('/admin/agent-executions?limit=500')])
      .then(([items,executions])=>{if(!cancelled){setAlerts(adminAlertsFrom(items,executions));setError('')}})
      .catch(()=>{if(!cancelled)setError('알림을 불러오지 못했어요.')})
      .finally(()=>{if(!cancelled)timer=setTimeout(load,15000)});
    load();
    return()=>{cancelled=true;clearTimeout(timer)};
  },[]);
  const toggle=()=>{
    if(!open){
      const next=new Set([...seen,...alerts.map(a=>a.key)]);
      setSeen(next);
      try{localStorage.setItem(ADMIN_ALERT_SEEN_KEY,JSON.stringify([...next]))}catch{}
    }
    setOpen(v=>!v);
  };
  return <div className="relative">
    <button type="button" aria-label="관리자 알림 현황" aria-expanded={open} onClick={toggle} className="relative w-9 h-9 rounded-full flex items-center justify-center text-[var(--muted-fg)] hover:bg-[var(--muted)]">
      <svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>
      {alerts.some(a=>!seen.has(a.key))&&<span className="absolute top-1 right-1 w-2.5 h-2.5 rounded-full bg-[var(--danger)]"/>}
    </button>
    {open&&<React.Fragment><button type="button" aria-label="알림 닫기" className="fixed inset-0 z-40 cursor-default" onClick={()=>setOpen(false)}/>
      <div className="absolute right-0 top-11 z-50 w-[360px] max-w-[calc(100vw-32px)] rounded-2xl border border-[var(--border)] bg-white shadow-[0_20px_48px_-16px_rgba(20,23,31,.25)] overflow-hidden">
        <div className="px-4 py-3.5 border-b border-[var(--border)] flex items-center justify-between"><h2 className="text-[13.5px] font-bold">알림 현황</h2><span className="text-[11px] text-[var(--muted-fg)]">관리 필요 {alerts.length}건</span></div>
        {error&&<p role="alert" className="px-4 py-2 text-[12px] text-[var(--danger)]">{error}</p>}
        {!error&&alerts.length===0?<p className="px-4 py-6 text-center text-[12.5px] text-[var(--muted-fg)]">현재 확인이 필요한 작업이 없어요.</p>:
          <div className="soft-scroll max-h-80 overflow-y-auto divide-y divide-[var(--border)]">{alerts.map(a=><button type="button" key={a.key} onClick={()=>{setOpen(false);onNavigate(a)}} className="block w-full text-left px-4 py-3 hover:bg-[#f9fafb]">
            <p className="text-[11px] text-[var(--muted-fg)] truncate">『{a.project}』</p><div className="flex gap-2 items-center mt-1"><strong className="text-[12.5px]">{a.title}</strong><span className={'ml-auto text-[11px] font-semibold '+(a.kind==='실패'?'text-[var(--danger)]':'text-[var(--warn)]')}>{a.kind}</span></div><p className="text-[11.5px] text-[var(--muted-fg)] mt-1 break-words line-clamp-2">{a.detail}</p>
          </button>)}</div>}
      </div>
    </React.Fragment>}
  </div>;
}

export default function AdminDashboard({user,onExit}){
  const [tab,setTab]=useState('ann');
  const [selectedAlert,setSelectedAlert]=useState(null);
  const [toasts,setToasts]=useState([]);
  const closeToast=id=>setToasts(t=>t.filter(x=>x.id!==id));
  // 10초 뒤 자동으로 닫힌다 — 안 닫으면 계속 쌓여서 다른 작업을 가린다(사용자 지적).
  const pushToast=(title,message,tone)=>{
    const id=Date.now()+Math.random();
    setToasts(t=>[...t,{id,title,message,tone}]);
    setTimeout(()=>closeToast(id),10000);
  };

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      <header className="sticky top-0 z-40 bg-white/95 backdrop-blur border-b border-[var(--border)]">
        <div className="w-[min(1180px,calc(100%-48px))] mx-auto flex items-center gap-4 h-[72px]">
          <Brand onClick={onExit}/>
          <span className="text-[11.5px] font-semibold text-[var(--primary)] border border-[var(--primary)] rounded-full px-2.5 py-0.5">관리자</span>
          <nav className="hidden md:flex items-center gap-5 ml-4 text-[13.5px] text-[var(--muted-fg)] overflow-x-auto">
            {TABS.map(([key,label])=>(
              <button key={key} onClick={()=>setTab(key)} className={'whitespace-nowrap '+(tab===key?'text-[var(--fg)] font-semibold':'hover:text-[var(--fg)]')}>{label}</button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <AdminNotificationBell onNavigate={alert=>{setSelectedAlert(alert);setTab(alert.tab)}}/>
            <span className="hidden sm:block text-[13px] text-[var(--muted-fg)]">{user?.name||'관리자'}</span>
            <button onClick={onExit} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--muted)]">서비스 화면</button>
          </div>
        </div>
        <div className="md:hidden w-[min(1180px,calc(100%-48px))] mx-auto flex gap-4 pb-3 text-[13px] overflow-x-auto">
          {TABS.map(([key,label])=>(
            <button key={key} onClick={()=>setTab(key)} className={'whitespace-nowrap '+(tab===key?'text-[var(--fg)] font-semibold':'text-[var(--muted-fg)]')}>{label}</button>
          ))}
        </div>
      </header>

      <main className="w-[min(1180px,calc(100%-48px))] mx-auto py-12">
        {tab==='ann'&&<AnnouncementTab/>}
        {tab==='ops'&&<OpsTab/>}
        {tab==='progress'&&<ProgressTab key={selectedAlert?.tab==='progress'?selectedAlert.key:'progress'} focusProjectId={selectedAlert?.tab==='progress'?selectedAlert.projectId:null}/>}
        {tab==='agents'&&<AgentsTab key={selectedAlert?.tab==='agents'?selectedAlert.key:'agents'} focusMatchId={selectedAlert?.tab==='agents'?selectedAlert.matchId:null}/>}
        {tab==='policy'&&<PolicyTab pushToast={pushToast}/>}
        {tab==='recovery'&&<RecoveryTab pushToast={pushToast}/>}
        {tab==='users'&&<UsersTab pushToast={pushToast}/>}
      </main>

      <div className="fixed bottom-5 right-5 z-[95] flex flex-col gap-2 items-end w-full max-w-sm px-4 sm:px-0 pointer-events-none">
        {toasts.map(t=>(
          <div key={t.id} className={'pointer-events-auto w-full bg-white rounded-xl shadow-lg p-3.5 flex items-start gap-2.5 border '+(t.tone==='danger'?'border-[var(--danger)]':'border-[var(--border)]')}>
            <span className={'flex-shrink-0 mt-0.5 text-[14px] '+(t.tone==='danger'?'text-[var(--danger)]':'text-[var(--ok)]')}>{t.tone==='danger'?'⚠':'✓'}</span>
            <div className="flex-1 min-w-0">
              <p className="text-[12.5px] font-semibold">{t.title}</p>
              <p className="text-[11.5px] text-[var(--muted-fg)] mt-0.5">{t.message}</p>
            </div>
            <button onClick={()=>closeToast(t.id)} aria-label="알림 닫기" className="flex-shrink-0 text-[var(--muted-fg)] hover:text-[var(--fg)]"><Icon name="close" size={14}/></button>
          </div>
        ))}
      </div>
    </div>
  );
}

// GET /admin/collection-status의 issue_counts({"unparsed_period": 53} 등) 딕셔너리를
// "unparsed_period 53건" 식의 짧은 문자열 목록으로 바꾼다.
const formatIssueCounts=issues=>Object.entries(issues||{}).map(([k,v])=>`${k} ${v}건`);

function AnnouncementTab(){
  const [query,setQuery]=useState('');
  const [notices,setNotices]=useState(null);
  const [noticesError,setNoticesError]=useState('');
  const [collection,setCollection]=useState(null);
  const [collectionError,setCollectionError]=useState('');
  useEffect(()=>{
    api.get('/admin/collection-status').then(setCollection)
      .catch(e=>setCollectionError(e instanceof ApiError?String(e.detail):'수집 현황을 불러오지 못했어요'));
  },[]);
  // 검색어를 입력할 때마다 바로 요청을 쏘지 않고 300ms 디바운스한다 — notices가 2천 건대라
  // 타이핑 중간중간 불필요한 요청이 쌓이는 걸 막는다.
  useEffect(()=>{
    let active=true;
    setNotices(null);setNoticesError('');
    const timer=setTimeout(()=>{
      const search=query?`?q=${encodeURIComponent(query)}`:'';
      api.get(`/admin/notices${search}`).then(rows=>{if(active)setNotices(rows.map(noticeRowFromServer))})
        .catch(e=>{if(active)setNoticesError(e instanceof ApiError?String(e.detail):'공고 목록을 불러오지 못했어요')});
    },300);
    return ()=>{active=false;clearTimeout(timer)};
  },[query]);
  const rows=notices||[];
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-1">공고 수집 현황</h1>
      <p className="text-[12px] text-[var(--muted-fg)] mb-6">notices.source 기준 실제 출처만 보여줍니다 — "재수집"/"임베딩 재생성"은 다른 팀원의 수집 파이프라인 스크립트를 이 화면에서 실행시킬 방법이 없어 만들지 않았습니다.</p>
      {collectionError?<p className="text-[13px] text-[var(--danger)]">{collectionError}</p>
      :collection===null?<p className="text-[13px] text-[var(--muted-fg)]">불러오는 중…</p>
      :(<>
      <Panel className="divide-y divide-[var(--border)]">
        {collection.sources.length===0&&<p className="p-6 text-[13px] text-[var(--muted-fg)]">수집된 공고가 없습니다.</p>}
        {collection.sources.map((s,i)=>{
          const fullyEmbedded=s.total_count>0&&s.embedded_count===s.total_count;
          const tone=s.total_count===0?'muted':fullyEmbedded?'ok':'warn';
          return (
          <div key={s.source} className={'grid grid-cols-[auto_1fr] items-start gap-5 px-6 py-5 '+
            (tone==='warn'?'bg-[color-mix(in_srgb,var(--warn)_6%,white)] border-l-4 border-l-[var(--warn)]':'')}>
            <span className={'text-[20px] font-semibold pt-0.5 '+toneText[tone==='ok'?'muted':tone]} aria-hidden="true">{String(i+1).padStart(2,'0')}</span>
            <div className="min-w-0">
              <div className="flex items-center gap-3 flex-wrap mb-2">
                <h3 className="font-bold text-[16px]">{s.label}</h3>
                <span className={'text-[12.5px] font-bold '+toneText[tone]}>{fullyEmbedded?'［정상］':s.total_count===0?'［수집된 공고 없음］':'［임베딩 미완료 있음］'}</span>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[13px] text-[var(--muted-fg)]">
                <p>누적 수집 <span className="text-[var(--fg)] font-medium">{s.total_count}건</span></p>
                {s.latest_run_input_count!=null&&<p>최근 배치 입력 <span className="text-[var(--fg)] font-medium">{s.latest_run_input_count}건</span></p>}
                <p>임베딩 생성 <span className={'font-semibold '+toneText[tone]}>{s.embedded_count}/{s.total_count}건</span></p>
              </div>
            </div>
          </div>
          );
        })}
      </Panel>

      <div className="mt-10">
        <h2 className="text-[20px] font-bold mb-1">최근 수집 실행 이력</h2>
        <p className="text-[12px] text-[var(--muted-fg)] mb-4">import_runs 실제 배치 기록입니다. "생성"은 수집 파이프라인이 이 배치를 만든 시각, "반영"은 우리 쪽에 실제로 적재된 시각입니다(둘의 차이가 수집→반영 지연 시간). "이슈"는 그 배치에서 일부 항목이 파싱되지 않은 데이터 품질 문제이지, 배치 자체의 실패가 아닙니다 — 지금까지 배치 자체가 실패한 이력은 없습니다.</p>
        <Panel>
          <div className="grid grid-cols-[1.2fr_1.2fr_1fr_1fr_1.6fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4">생성 시각</div><div className="p-4">반영 시각</div><div className="p-4 text-center">입력 건수</div><div className="p-4 text-center">반영 건수</div><div className="p-4">이슈</div>
          </div>
          {collection.recent_runs.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)] border-t border-[var(--border)]">실행 기록이 없습니다.</p>}
          {collection.recent_runs.map(r=>{
            const issues=formatIssueCounts(r.issue_counts);
            const inputTotal=Object.values(r.input_counts||{}).reduce((a,b)=>a+b,0);
            return (
            <div key={r.run_id} className="grid grid-cols-[1.2fr_1.2fr_1fr_1fr_1.6fr] text-[13px] border-t border-[var(--border)] items-center">
              <div className="p-4 text-[var(--muted-fg)]">{r.generated_at?r.generated_at.slice(0,16).replace('T',' '):'-'}</div>
              <div className="p-4 text-[var(--muted-fg)]">{r.imported_at.slice(0,16).replace('T',' ')}</div>
              <div className="p-4 text-center font-medium">{inputTotal}건</div>
              <div className="p-4 text-center font-medium">{r.accepted_count}건</div>
              <div className={'p-4 '+(issues.length?'text-[var(--warn)]':'text-[var(--muted-fg)]')}>{issues.length?issues.join(', '):'없음'}</div>
            </div>
            );
          })}
        </Panel>
      </div>
      </>)}

      <div className="mt-10">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h2 className="text-[20px] font-bold">공고 전체 관리</h2>
          <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="공고명 검색"
            className="border border-[var(--border)] rounded-lg px-3 py-2 text-[13.5px] w-56 outline-none focus:border-[var(--primary)]"/>
        </div>
        <Panel>
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr_170px] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4">공고명</div><div className="p-4 text-center">출처</div><div className="p-4 text-center">접수기간</div>
            <div className="p-4 text-center">임베딩</div><div className="p-4 text-center">상태</div><div className="p-4"/>
          </div>
          {noticesError?<p className="p-6 text-[13px] text-[var(--danger)]">{noticesError}</p>
          :notices===null?<p className="p-6 text-[13px] text-[var(--muted-fg)]">불러오는 중…</p>
          :(<>
            {rows.map(r=>(
              <div key={r.id} className={'grid grid-cols-[2fr_1fr_1fr_1fr_1fr_170px] text-[13px] border-t border-[var(--border)] items-center '+(r.dim?'opacity-50':'')}>
                <div className="p-4 font-medium">{r.title}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{r.src}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{r.period}</div>
                <div className={'p-4 text-center font-semibold '+toneText[r.embedTone]}>{r.embed}</div>
                <div className={'p-4 text-center font-semibold '+toneText[r.statusTone]}>{r.status}</div>
                {/* 상세·삭제 액션은 안 만들었다 — notices는 이 앱이 아니라 공고 수집
                    파이프라인이 소유한 테이블이라(app/schemas.py NoticeAdminOut 주석 참고),
                    그 팀과 상의 없이 여기서 지우는 기능부터 넣는 건 위험하다고 판단했다. */}
                <div className="p-4"/>
              </div>
            ))}
            {rows.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)] border-t border-[var(--border)]">검색 결과가 없어요.</p>}
          </>)}
        </Panel>
      </div>
    </div>
  );
}

// status_label(_build_item_out/ItemOut) -> "운영 현황" 실행건수 카드 표시 순서.
const OPS_STATUS_ORDER=['진행중','실패','판단 대기','완료','중단','공고 매칭 전'];
const formatStatusCounts=counts=>{
  const parts=OPS_STATUS_ORDER.filter(k=>counts[k]).map(k=>`${k} ${counts[k]}`);
  return parts.length?parts.join(' · '):'실행 없음';
};
const DEVIATION_LAYER_LABEL={doc:'문서층 검증',code:'코드 기준 검증',plan:'계획서 대조'};

function OpsTab(){
  const [summary,setSummary]=useState(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    api.get('/admin/ops-summary').then(setSummary)
      .catch(e=>setError(e instanceof ApiError?String(e.detail):'운영 현황을 불러오지 못했어요'));
  },[]);

  if(error)return <div><h1 className="text-[28px] font-bold mb-4">운영 현황</h1><p className="text-[13.5px] text-[var(--danger)]">{error}</p></div>;
  if(!summary)return <div><h1 className="text-[28px] font-bold mb-4">운영 현황</h1><p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p></div>;

  const totalProjects=Object.values(summary.status_counts).reduce((a,b)=>a+b,0);
  const maxBucket=Math.max(1,...summary.score_buckets.map(b=>b.count));

  return (
    <div>
      <h1 className="text-[28px] font-bold mb-2">운영 현황</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8">business_plans·artifacts·verdicts·agent_executions·proofread_logs 실제 집계입니다. 실행 건 하나하나의 현재 진행 상태는 "진행 현황" 탭에서 확인하세요.</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
        <Card label="전체 프로젝트" value={totalProjects+'건'} sub={formatStatusCounts(summary.status_counts)}/>
        <Card label="문서평가 평균점수" value={summary.doc_avg!=null?summary.doc_avg+'점':'-'} sub={'만점 70점 · '+summary.doc_count+'건 기준'}/>
        <Card label="종합평가 평균점수" value={summary.total_avg!=null?summary.total_avg+'점':'-'} sub={'만점 100점 · 평가가 모두 끝난 '+summary.total_count+'건 기준'}/>
        <Card label="통과율" value={summary.pass_rate!=null?summary.pass_rate+'%':'-'} sub={'통과 '+summary.pass_count+' / '+summary.total_count+'건 (기준 '+summary.pass_threshold+'점)'}/>
        <Card label="재수행 발생률" value={summary.rerun_rate!=null?summary.rerun_rate+'%':'-'} sub={'재수행 발생 '+summary.rerun_matches+' / '+summary.matches_with_execution+'건'}/>
        <Card label="보호 토큰 위반율" value={summary.token_violation_rate!=null?summary.token_violation_rate+'%':'-'}
          tone={summary.token_violation_rate>0?'warn':undefined}
          sub={'위반 '+summary.token_violation_count+' / 검수 시도 '+summary.token_check_count+'건 (전체 프로젝트 평균)'}/>
      </div>

      <Panel className="p-5 mb-8">
        <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-4">검증 점수 분포</p>
        {summary.total_count===0
          ?<p className="text-[13px] text-[var(--muted-fg)]">아직 종합 평가가 끝난 프로젝트가 없습니다.</p>
          :<div className="flex flex-col gap-2.5">
            {summary.score_buckets.map(b=>(
              <Bar key={b.label} label={b.label} pct={b.count/maxBucket*100}
                tone={b.label.includes('미만')?'danger':b.label.startsWith('9')||b.label.startsWith('8')?'ok':'warn'}
                right={b.count+'건'}/>
            ))}
          </div>}
      </Panel>

      <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">채점 편차 현황 (1회 → 2회 평균 증감)</p>
      <p className="text-[11px] text-[var(--muted-fg)] mb-3">같은 층을 두 번 이상 채점한 기록이 있어야 계산됩니다 — 개별 프로젝트의 이력은 "진행 현황"의 이력보기에서 확인할 수 있습니다.</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {summary.deviations.map(d=>d.sample_count===0
          ?<Card key={d.layer} label={DEVIATION_LAYER_LABEL[d.layer]} tone="muted" value="-" sub="재채점 이력이 아직 없습니다"/>
          :<Card key={d.layer} label={DEVIATION_LAYER_LABEL[d.layer]} tone={d.delta_avg>0?'ok':d.delta_avg<0?'danger':'muted'}
              value={(d.delta_avg>0?'▲ +':d.delta_avg<0?'▼ ':'— ')+d.delta_avg+'점'}
              sub={'1회 '+d.round1_avg+'점 → 2회 '+d.round2_avg+'점 · '+d.sample_count+'건 기준'}/>
        )}
      </div>
    </div>
  );
}

// GET /admin/items 응답의 last_updated(ISO)를 "MM-DD HH:mm" 짧은 표기로 바꾼다.
const shortUpdated=iso=>iso?iso.slice(5,16).replace('T',' '):'-';

function ProgressTab({focusProjectId=null}){
  const [items,setItems]=useState([]);
  const [loading,setLoading]=useState(true);
  const [loadError,setLoadError]=useState(false);
  const [scoreId,setScoreId]=useState(null);
  const [scoreHistory,setScoreHistory]=useState(null);
  const [scoreError,setScoreError]=useState('');
  const [detailId,setDetailId]=useState(focusProjectId);
  const [restoring,setRestoring]=useState(null);

  const loadItems=()=>{
    setLoading(true);setLoadError(false);
    api.get('/admin/items').then(rows=>{setItems(rows);setLoading(false)}).catch(()=>{setLoadError(true);setLoading(false)});
  };
  useEffect(loadItems,[]);

  useEffect(()=>{
    if(scoreId==null)return;
    let active=true;
    setScoreHistory(null);
    setScoreError('');
    api.get(`/admin/items/${scoreId}/score-history`)
      .then(data=>{if(active)setScoreHistory(data)})
      .catch(()=>{if(active)setScoreError('점수 이력을 불러오지 못했어요. 창을 닫고 다시 열어 주세요.')});
    return ()=>{active=false};
  },[scoreId]);

  const handleRestore=async id=>{
    setRestoring(id);
    try{
      const updated=await api.put(`/admin/items/${id}/archive`,{archived:false});
      setItems(list=>list.map(it=>it.project_id===id?updated:it));
    }catch(e){
      window.alert('복원하지 못했어요. 다시 시도해 주세요.');
    }finally{
      setRestoring(null);
    }
  };

  const statusTone=s=>s==='진행중'?'ok':s==='중단'||s==='실패'?'danger':s==='판단 대기'?'warn':'muted';
  const detail=items.find(i=>i.project_id===detailId);

  return (
    <div>
      <h1 className="text-[28px] font-bold mb-2">진행 현황</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8">실행 건 하나하나의 현재 단계·시도 횟수·마지막 갱신 시각을 봅니다. 집계된 평균·통과율은 "운영 현황" 탭에서 확인하세요.</p>
      {loading&&<p className="text-[13px] text-[var(--muted-fg)]">불러오는 중…</p>}
      {loadError&&<p className="text-[13px] text-[var(--danger)]">목록을 불러오지 못했어요. 새로고침해 주세요.</p>}
      {!loading&&!loadError&&(
      <Panel>
        <div className="grid grid-cols-[1.7fr_0.8fr_0.85fr_0.6fr_1.15fr_0.9fr_0.85fr_90px] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
          <div className="p-4">프로젝트명</div><div className="p-4 text-center">사용자</div><div className="p-4 text-center">현재 단계</div><div className="p-4 text-center">시도</div>
          <div className="p-4 text-center">마지막 갱신</div><div className="p-4 text-center">점수</div><div className="p-4 text-center">상태</div><div className="p-4 text-center">관리</div>
        </div>
        {items.length===0&&<div className="p-6 text-[13px] text-[var(--muted-fg)]">등록된 프로젝트가 없습니다.</div>}
        {items.map(p=>{
          const id=p.project_id,isArchived=p.archived;
          return (
            <div key={id} className={'grid grid-cols-[1.7fr_0.8fr_0.85fr_0.6fr_1.15fr_0.9fr_0.85fr_90px] text-[13px] border-t border-[var(--border)] items-center '+
              (isArchived?'opacity-50 ':'')+(['중단','실패'].includes(p.status_label)?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)] ':p.status_label==='판단 대기'?'bg-[color-mix(in_srgb,var(--warn)_5%,white)] border-l-4 border-l-[var(--warn)] ':'')}>
              <div className="p-4 font-medium">{p.description}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.user_name}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.step||'-'}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.attempts!=null?p.attempts+'회':'-'}</div>
              <div className="p-4 text-center text-[var(--muted-fg)] text-[12px]">
                {shortUpdated(p.last_updated)}
                {p.stalled&&<span className="block text-[10.5px] font-semibold text-[var(--warn)] mt-0.5">⏱ 정체</span>}
              </div>
              <div className="p-4 text-center">
                <p className="font-semibold">{p.score!=null?p.score+'점':'-'}</p>
                <button onClick={()=>setScoreId(id)} className="text-[11.5px] text-[var(--primary)] hover:underline">이력보기</button>
              </div>
              <div className={'p-4 text-center font-semibold '+(isArchived?'text-[var(--muted-fg)]':toneText[statusTone(p.status_label)])}>{isArchived?'보관중':p.status_label}</div>
              <div className="p-4 flex justify-center">
                <button onClick={()=>setDetailId(id)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">관리</button>
              </div>
            </div>
          );
        })}
      </Panel>
      )}
      <p className="mt-3 text-[12px] text-[var(--muted-fg)]"><span className="text-[var(--warn)]">●</span> "판단 대기"는 평가 결과가 나와 사용자의 재작성·재제작 선택을 기다리는 정상 상태이며, 오류(중단)가 아닙니다.</p>
      <p className="mt-1.5 text-[12px] text-[var(--muted-fg)]"><span className="text-[var(--warn)]">⏱</span> "정체"는 마지막 갱신으로부터 48시간이 지났는데도 '진행중' 상태가 유지되는 경우입니다.</p>

      {scoreId!=null&&<Modal wide title={(items.find(i=>i.project_id===scoreId)?.description||'')+' 점수 이력'} onClose={()=>{setScoreId(null);setScoreHistory(null)}}>
        <p className="text-[12.5px] text-[var(--muted-fg)] mb-4">검증 단계별 이력이 삭제되지 않고 누적됩니다. 최근 변경 순으로 표시됩니다.</p>
        {scoreError?<p role="alert" className="text-[13px] text-[var(--danger)]">{scoreError}</p>:!scoreHistory?<p className="text-[13px] text-[var(--muted-fg)]">불러오는 중…</p>:(
        <div className="grid sm:grid-cols-3 gap-4">
          {DEVIATION_CATEGORIES.map(([key,label,max])=>(
            <div key={key}>
              <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-2">{label} <span className="font-normal">({max}점 만점)</span></p>
              <div className="soft-scroll rounded-xl border border-[var(--border)] divide-y divide-[var(--border)] max-h-64 overflow-y-auto">
                {(scoreHistory[key]||[]).length===0
                  ?<div className="p-3 text-[12px] text-[var(--muted-fg)]">누적된 이력이 없습니다.</div>
                  :scoreHistory[key].map((e,i,arr)=>(
                    <div key={e.scored_at+i} className="p-2.5">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11.5px] text-[var(--muted-fg)]">{e.scored_at.slice(0,10)}</span>
                        <span className="font-semibold text-[13px]">
                          {e.is_rerun&&i+1<arr.length&&<span className="text-[var(--muted-fg)] font-normal">{arr[i+1].score}점 → </span>}{e.score}점
                        </span>
                      </div>
                      {e.is_rerun&&<p className="text-[10.5px] text-[var(--primary)] font-semibold">재수행 결과</p>}
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
        )}
      </Modal>}

      {detail&&(()=>{
        const isArchived=detail.archived;
        return (
          <Modal title={detail.description} onClose={()=>setDetailId(null)}>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-5">{detail.user_name} · 현재 점수 {detail.score!=null?detail.score+'점':'—'}</p>
            <div className="grid grid-cols-3 gap-3 mb-5 text-[12.5px]">
              <div className="rounded-xl border border-[var(--border)] p-3"><p className="text-[var(--muted-fg)] mb-1">현재 단계</p><p className="font-semibold text-[14px]">{detail.step||'-'}</p></div>
              <div className="rounded-xl border border-[var(--border)] p-3"><p className="text-[var(--muted-fg)] mb-1">시도 횟수</p><p className="font-semibold text-[14px]">{detail.attempts!=null?detail.attempts+'회':'-'}</p></div>
              <div className={'rounded-xl border p-3 '+(detail.stalled?'border-[var(--warn)] bg-[color-mix(in_srgb,var(--warn)_6%,white)]':'border-[var(--border)]')}>
                <p className="text-[var(--muted-fg)] mb-1">정체 여부</p>
                <p className={'font-semibold text-[14px] '+(detail.stalled?'text-[var(--warn)]':'text-[var(--ok)]')}>{detail.stalled?'정체':'정상'}</p>
              </div>
            </div>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-5">마지막 갱신: {shortUpdated(detail.last_updated)}</p>
            {detail.match_status==='failed'&&<div role="alert" className="rounded-xl border border-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-3.5 text-[13px] mb-5 text-[var(--danger)]"><strong>작업 실패</strong><p className="mt-1 break-words">{detail.failure_reason||'실패 원인이 기록되지 않았습니다.'}</p></div>}
            {/* 지금 어느 Agent가 뭘 하고 있는지·오류 로그는 실시간 오케스트레이터가 아직 없어
                지어낼 수 없다(schemas.py ItemOut 주석 참고) — 안내 문구로만 그 사실을 알린다. */}
            <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-2">실시간 실행 상태</p>
            <div className="rounded-xl border border-[var(--border)] p-3.5 text-[13px] mb-5 text-[var(--muted-fg)]">
              현재는 마지막 실행 단계와 시도 횟수를 확인할 수 있습니다. 작업 실패 사유는 위에 표시되며, Agent별 상세 오류 로그는 아직 저장되지 않습니다.
            </div>
            <div className="pt-4 border-t border-[var(--border)]">
              {isArchived
                ?<div className="flex items-center justify-between gap-4">
                   <div>
                     <span className="inline-block text-[12px] font-semibold px-3 py-1 rounded-full bg-[var(--muted)] text-[var(--muted-fg)] mb-1.5">보관중 · 사용자 삭제</span>
                     <p className="text-[11.5px] text-[var(--muted-fg)]">사용자가 삭제해 보관중입니다. 데이터는 보존되며 관리자만 조회·복원할 수 있습니다.</p>
                   </div>
                   <button onClick={()=>handleRestore(detailId)} disabled={restoring===detailId}
                     className="flex-shrink-0 rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)] disabled:opacity-50">
                     {restoring===detailId?'복원 중…':'복원'}
                   </button>
                 </div>
                :<p className="text-[11.5px] text-[var(--muted-fg)]">보관 처리는 관리자가 직접 하지 않습니다. 사용자가 프로젝트를 삭제하면 "보관중"으로 표시되며 데이터는 보존됩니다.</p>}
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}

// GET /admin/agent-tasks 응답(AgentTaskOut 목록) -> 이 화면 행 모양. recent_status가
// completed/success가 아니면(지금 더미 파이프라인에서는 사실상 안 나오지만, 실패 로그가
// 남으면 대비) 최근 실행 칸을 강조한다.
const agentTaskFromServer=r=>({
  agentName:r.agent_name,definedTasks:r.defined_task_count+'개',totalExecutions:r.total_executions,
  recent:r.recent_project_description||'실행 이력 없음',
  recentTone:(r.recent_status&&r.recent_status!=='completed'&&r.recent_status!=='success')?'danger':undefined,
});

function AgentsTab({focusMatchId=null}){
  const [view,setView]=useState(focusMatchId==null?'task':'execution');
  const [matchFilter,setMatchFilter]=useState(focusMatchId);
  const [executions,setExecutions]=useState(null);
  const [execError,setExecError]=useState('');
  const [agentTasks,setAgentTasks]=useState(null);
  const [agentTaskError,setAgentTaskError]=useState('');
  const [opsSummary,setOpsSummary]=useState(null);
  const [opsSummaryError,setOpsSummaryError]=useState('');
  useEffect(()=>{
    if(view!=='execution'||executions!==null)return;
    let active=true;
    setExecError('');
    api.get('/admin/agent-executions?limit=500').then(rows=>{if(active)setExecutions(rows.map(executionRowFromServer))})
      .catch(e=>{if(active)setExecError(e instanceof ApiError?String(e.detail):'실행 세션을 불러오지 못했어요')});
    return ()=>{active=false};
  },[view,executions]);
  useEffect(()=>{
    if(view!=='task'||agentTasks!==null)return;
    let active=true;
    setAgentTaskError('');
    api.get('/admin/agent-tasks').then(rows=>{if(active)setAgentTasks(rows.map(agentTaskFromServer))})
      .catch(e=>{if(active)setAgentTaskError(e instanceof ApiError?String(e.detail):'Task 현황을 불러오지 못했어요')});
    return ()=>{active=false};
  },[view,agentTasks]);
  useEffect(()=>{
    api.get('/admin/agent-ops-summary').then(setOpsSummary)
      .catch(e=>setOpsSummaryError(e instanceof ApiError?String(e.detail):'운영 지표를 불러오지 못했어요'));
  },[]);
  return (
    <div>
      <div className="flex items-center justify-between mb-8 flex-wrap gap-4">
        <h1 className="text-[28px] font-bold">에이전트 테스크 현황</h1>
        <div className="inline-flex items-center gap-1 p-1 rounded-full bg-[var(--muted)]">
          {[['task','Task별 보기'],['execution','Execution별 보기']].map(([key,label])=>(
            <button key={key} onClick={()=>setView(key)}
              className={'px-4 py-1.5 rounded-full text-[13.5px] font-semibold '+(view===key?'bg-white text-[var(--fg)] shadow-sm':'text-[var(--muted-fg)] hover:text-[var(--fg)]')}>{label}</button>
          ))}
        </div>
      </div>

      {/* 표(Task별 보기/Execution별 보기)를 먼저 보여주는 게 우선이라, 통계 요약은
          기본적으로 접어두고 필요할 때만 펼쳐보게 한다. */}
      <details className="admin-accordion mb-8 rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
        <summary className="flex items-center justify-between gap-3 px-5 py-4 text-[13px] font-semibold text-[var(--muted-fg)] cursor-pointer select-none">
          <span>운영 지표 요약 (실행 세션·토큰 사용량·보호 토큰 위반율)</span>
          <Icon name="chevron" size={16}/>
        </summary>
        <div className="px-5 pb-5 pt-1 border-t border-[var(--border)]">
          {opsSummaryError?<p className="text-[13px] text-[var(--danger)] mb-6 mt-4">{opsSummaryError}</p>
          :opsSummary===null?<p className="text-[13px] text-[var(--muted-fg)] mb-6 mt-4">불러오는 중…</p>
          :<>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6 mt-4">
            <Card label="총 실행 세션" value={opsSummary.total_executions+'건'} sub="전체 누적 기준"/>
            <Card label="재시도 실행" value={opsSummary.rerun_executions+'건'} sub={'최초 실행 '+opsSummary.initial_executions+'건'}/>
            <Card label="최초 실행 평균 토큰" value={opsSummary.initial_avg_tokens!=null?Math.round(opsSummary.initial_avg_tokens).toLocaleString():'-'} sub="token_usage 평균"/>
            <Card label="재시도 평균 토큰" value={opsSummary.rerun_avg_tokens!=null?Math.round(opsSummary.rerun_avg_tokens).toLocaleString():'-'} sub="token_usage 평균"/>
          </div>
          {/* "선별/전체 재실행" 구분은 여전히 예시가 아니라 "만들지 않음"이다(그 값을
              남기는 컬럼이 없음, AgentOpsSummaryOut 주석 참고) — 보호 토큰 위반율은
              2026-09-18부터 proofread_logs.passed 기준 실제 값이다. 모델 버전별
              비교(v1/v2/v3)는 그 시도를 만든 모델 버전을 남기는 컬럼이 없어서 못 하고,
              "운영 현황" 탭과 같은 전체 프로젝트 평균 하나만 보여준다. */}
          <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">보호 토큰 위반율</p>
          <p className="text-[11px] text-[var(--muted-fg)] mb-4">검수 시도 중 수치·날짜·고유명사·기능명 등 보호 토큰이 훼손된 채 반려된 비율입니다(전체 프로젝트 평균). 반려된 시도는 "검수 회수 문단" 탭에서 라벨링합니다.</p>
          <Bar label="전체 평균" pct={opsSummary.token_violation_rate||0}
            tone={opsSummary.token_violation_rate>0?'warn':'ok'}
            right={opsSummary.token_violation_rate!=null?opsSummary.token_violation_rate+'%':'-'}
            sub={opsSummary.token_violation_count+' / '+opsSummary.token_check_count+'건'}/>
          <p className="mt-3 pt-3 border-t border-[var(--border)] text-[11px] text-[var(--muted-fg)]">
            <span className="text-[var(--warn)]">⚠</span> 위반 문단은 지시를 보강해 재시도하며, 상한을 넘어서도 남으면 해당 문단만 원문을 유지하고 "검수 회수 문단" 탭에 기록합니다.
          </p>
          </>}
        </div>
      </details>

      {view==='task'?(
        <>
          <h2 className="text-[20px] font-bold mb-4">Agent별 테스크 구성</h2>
          {agentTaskError?<p className="text-[13.5px] text-[var(--danger)]">{agentTaskError}</p>
          :agentTasks===null?<p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p>
          :<Panel>
            <div className="grid grid-cols-[1fr_1.8fr_0.7fr_1.3fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
              <div className="p-4">Agent</div><div className="p-4">담당 업무</div><div className="p-4 text-center">정의된 태스크</div>
              <div className="p-4 text-center">최근 실행 프로젝트</div>
            </div>
            {AGENT_ROWS.map(a=>{
              const live=agentTasks.find(t=>t.agentName===a.key);
              return (
              <div key={a.name} className={'grid grid-cols-[1fr_1.8fr_0.7fr_1.3fr] text-[13px] border-t border-[var(--border)] items-center '+
                (live?.recentTone==='danger'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)]':'')}>
                <div className="p-4 font-medium">{a.name}</div>
                <div className="p-4 text-[var(--muted-fg)]">{a.work}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{live?.definedTasks??'-'}</div>
                <div className={'p-4 text-center '+(live?.recentTone==='danger'?'text-[var(--danger)] font-semibold':'text-[var(--muted-fg)]')}>{live?.recent??'-'}</div>
              </div>
              );
            })}
          </Panel>}
        </>
      ):(
        <>
          <h2 className="text-[20px] font-bold mb-4">실행 세션</h2>
          {matchFilter!=null&&<button type="button" className="text-[12px] text-[var(--primary)] mb-3" onClick={()=>setMatchFilter(null)}>매칭 #{matchFilter} 오류 확인 중 · 전체 실행 보기</button>}
          {execError?<p className="text-[13.5px] text-[var(--danger)]">{execError}</p>
          :executions===null?<p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p>
          :(<Panel>
            <div className="grid grid-cols-[1fr_1fr_1.6fr_1fr_1.2fr_0.9fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
              <div className="p-4">세션 ID</div><div className="p-4 text-center">Agent</div><div className="p-4 text-center">매칭 ID</div>
              <div className="p-4 text-center">토큰 사용량</div><div className="p-4 text-center">재수행 여부</div><div className="p-4 text-center">상태</div>
            </div>
            {executions.filter(r=>matchFilter==null||r.matchId===matchFilter).length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)]">해당 실행 로그가 없어요.</p>}
            {executions.filter(r=>matchFilter==null||r.matchId===matchFilter).map(r=>(
              <div key={r.id} className={'grid grid-cols-[1fr_1fr_1.6fr_1fr_1.2fr_0.9fr] text-[13px] border-t border-[var(--border)] items-center '+
                (r.tone==='danger'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)] ':'')}>
                <div className="p-4 font-medium">{r.id}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{r.agent}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{r.matchId??'—'}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{r.tokens}</div>
                <div className={'p-4 text-center font-semibold '+toneText[r.rerunTone]}>{r.rerun}</div>
                <div className={'p-4 text-center font-semibold '+toneText[r.statusTone]}>{r.status}</div>
              </div>
            ))}
          </Panel>)}
        </>
      )}
    </div>
  );
}

// 서버 필드명 <-> 이 화면 상태 키. GET/PUT /admin/policy가 doc_weight/code_weight/... 처럼
// snake_case로 주고받아서, 화면 안에서는 기존 mock 시절 키(doc/code/plan, threshold/rerun/...)
// 그대로 쓰고 여기서만 변환한다.
const policyFromServer=p=>({scores:{doc:p.doc_weight,code:p.code_weight,plan:p.plan_weight},
  limits:{threshold:p.pass_threshold,rerun:p.rerun_cap,tokenRetry:p.token_retry_cap,recheck:p.deviation_cap}});
const checklistFromServer=list=>list.map(i=>({id:i.check_item_id,name:i.name,how:i.method,kind:i.category,weight:i.weight,base:i.weight,on:i.enabled}));
// [2026-09-23, 백엔드 전달사항 10번] 기획서 v1.8 5-4 — 체크리스트는 전체 합이 아니라
// 산출물 카테고리마다 따로 15점 만점이다(app/routers/admin.py _CHECKLIST_CATEGORY_MAX_SCORE).
// 예전엔 이 화면이 "전체 합 100점"으로 맞춰 보내서 서버가 항상 422로 되돌려보냈다.
const CHECKLIST_CATEGORY_MAX=15;
// 라벨은 표시용일 뿐이라, 서버가 카테고리를 늘리면 키 그대로 묶여서 보인다.
const CHECKLIST_CATEGORY_LABEL={html:'HTML — 웹개발 · AI API',svg:'SVG — 원페이지'};
const validNumber=(value,max=Infinity,integer=false)=>String(value).trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=0&&Number(value)<=max&&(!integer||Number.isInteger(Number(value)));

function PolicyTab({pushToast}){
  const [scores,setScores]=useState(null);
  const [limits,setLimits]=useState(null);
  const [items,setItems]=useState(null);
  const [loadError,setLoadError]=useState('');

  useEffect(()=>{
    Promise.all([api.get('/admin/policy'),api.get('/admin/checklist')])
      .then(([policy,checklist])=>{const {scores,limits}=policyFromServer(policy);setScores(scores);setLimits(limits);setItems(checklistFromServer(checklist))})
      .catch(e=>setLoadError(e instanceof ApiError?String(e.detail):'검증 정책을 불러오지 못했어요'));
  },[]);

  if(loadError)return <div><h1 className="text-[28px] font-bold mb-4">검증 정책</h1><p className="text-[13.5px] text-[var(--danger)]">{loadError}</p></div>;
  if(!scores||!limits||!items)return <div><h1 className="text-[28px] font-bold mb-4">검증 정책</h1><p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p></div>;

  const scoreSum=Number(scores.doc)+Number(scores.code)+Number(scores.plan);
  // 항목이 등장한 순서대로 카테고리를 묶는다 — 서버가 카테고리를 늘려도 화면이 따라간다.
  const categories=[...new Set(items.map(i=>i.kind))];
  const categoryLabel=kind=>CHECKLIST_CATEGORY_LABEL[kind]||kind;
  const sumOfCategory=kind=>items.filter(i=>i.on&&i.kind===kind).reduce((s,i)=>s+Number(i.weight||0),0);
  const isCategoryUsed=kind=>items.some(i=>i.on&&i.kind===kind);
  // 사용 중인 항목이 하나도 없는 카테고리는 서버도 검사하지 않는다(admin.py save_checklist).
  const isCategoryOk=kind=>!isCategoryUsed(kind)||Math.round(sumOfCategory(kind)*100)===CHECKLIST_CATEGORY_MAX*100;

  // 체크를 해제·재선택하면 "같은 카테고리" 항목끼리만 기준 가중치 비율대로 15점을 다시
  // 배분한다 — 카테고리를 넘나들며 점수를 주고받으면 서버 검증에 그대로 걸린다.
  // 반올림 오차는 최대 나머지법으로 나눠 정확히 15점을 맞춘다.
  const redistribute=(list,kind)=>{
    const on=list.filter(i=>i.on&&i.kind===kind);const totalBase=on.reduce((s,i)=>s+i.base,0);
    if(totalBase<=0)return list;
    const plans=on.map(i=>{const exact=i.base/totalBase*CHECKLIST_CATEGORY_MAX;const floor=Math.floor(exact);return {id:i.id,floor,rem:exact-floor}});
    let leftover=CHECKLIST_CATEGORY_MAX-plans.reduce((s,p)=>s+p.floor,0);
    plans.slice().sort((a,b)=>b.rem-a.rem).slice(0,Math.max(leftover,0)).forEach(p=>{p.floor+=1});
    const map=Object.fromEntries(plans.map(p=>[p.id,p.floor]));
    return list.map(i=>i.kind!==kind?i:(i.on?{...i,weight:map[i.id]}:{...i,weight:i.base}));
  };
  const toggleItem=id=>setItems(list=>{
    const target=list.find(i=>i.id===id);
    if(!target)return list;
    return redistribute(list.map(i=>i.id===id?{...i,on:!i.on}:i),target.kind);
  });
  const setWeight=(id,v)=>setItems(list=>list.map(i=>i.id===id?{...i,weight:v,base:Number(v)||0}:i));

  const saveScores=async()=>{
    if(!Object.values(scores).every(v=>validNumber(v,100))){pushToast('배점을 저장하지 못했습니다','각 배점에 0~100 사이의 숫자를 입력해 주세요.','danger');return}
    if(Math.round(scoreSum*100)!==10000){pushToast('배점을 저장하지 못했습니다','문서층·코드 기준·계획서 대조 배점의 합이 100점이어야 합니다. (현재 '+scoreSum+'점)','danger');return}
    try{
      await api.put('/admin/policy/scores',{doc_weight:Number(scores.doc),code_weight:Number(scores.code),plan_weight:Number(scores.plan)});
      pushToast('배점이 저장되었습니다','문서층 '+scores.doc+'점 · 코드 기준 '+scores.code+'점 · 계획서 대조 '+scores.plan+'점으로 반영됩니다.','info');
    }catch(e){pushToast('배점을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const saveLimits=async()=>{
    if(!validNumber(limits.threshold,100)||!validNumber(limits.recheck,100)||!validNumber(limits.rerun,Infinity,true)||!validNumber(limits.tokenRetry,Infinity,true)){
      pushToast('판정 기준을 저장하지 못했습니다','점수는 0~100, 횟수는 0 이상의 정수로 입력해 주세요. 빈칸은 저장할 수 없습니다.','danger');return;
    }
    try{
      await api.put('/admin/policy/thresholds',{pass_threshold:Number(limits.threshold),rerun_cap:Number(limits.rerun),deviation_cap:Number(limits.recheck),token_retry_cap:Number(limits.tokenRetry)});
      pushToast('판정 기준이 저장되었습니다','통과 Threshold '+limits.threshold+'점 · 재수행 상한 '+limits.rerun+'회 · 검수 재시도 상한 '+limits.tokenRetry+'회 · 재채점 편차 상한 '+limits.recheck+'점으로 반영됩니다.','info');
    }catch(e){pushToast('판정 기준을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const saveItems=async()=>{
    if(!items.every(i=>validNumber(i.weight,100))){pushToast('검증 항목을 저장하지 못했습니다','각 가중치에 0~100 사이의 숫자를 입력해 주세요.','danger');return}
    const badCategories=categories.filter(k=>!isCategoryOk(k));
    if(badCategories.length){
      const detail=badCategories.map(k=>categoryLabel(k)+' '+sumOfCategory(k)+'점').join(', ');
      pushToast('검증 항목을 저장하지 못했습니다','묶음마다 사용 중인 항목의 가중치 합이 '+CHECKLIST_CATEGORY_MAX+'점이어야 합니다. (현재 '+detail+') 해당 묶음의 체크박스를 한 번 더 토글하면 '+CHECKLIST_CATEGORY_MAX+'점에 맞게 재배분됩니다.','danger');
      return;
    }
    try{
      await api.put('/admin/checklist',items.map(i=>({check_item_id:i.id,weight:Number(i.weight),enabled:i.on})));
      pushToast('검증 항목이 저장되었습니다',items.filter(i=>i.on).length+' / '+items.length+'개 항목이 사용되며 묶음마다 가중치 합계 '+CHECKLIST_CATEGORY_MAX+'점으로 반영됩니다.','info');
    }catch(e){pushToast('검증 항목을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };

  return (
    <div>
      <h1 className="text-[28px] font-bold mb-8">검증 정책</h1>

      <Panel className="p-5 mb-8">
        <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
          <p className="text-[13px] font-semibold text-[var(--muted-fg)]">2차 검증 배점 구성</p>
          <span className={'text-[12px] font-semibold px-2.5 py-0.5 rounded-full '+(scoreSum===100?toneBg.ok:toneBg.danger)}>합계 {scoreSum}점</span>
        </div>
        <p className="text-[11px] text-[var(--muted-fg)] mb-4">배점은 상수가 아니라 관리자 설정값입니다. 합이 100점이 아니면 저장되지 않습니다.</p>
        <div className="grid sm:grid-cols-3 gap-4">
          {[['doc','문서층','검증대상: 사업계획서 서술(원문)'],['code','산출물층 · 코드 기준 자동 검증','검증대상: 프로토타입 산출물'],['plan','산출물층 · 계획서 대조','검증대상: 산출물 ↔ 계획서 일치 여부']].map(([key,label,sub])=>(
            <div key={key} className="rounded-xl border border-[var(--border)] p-4">
              <p className="text-[12px] text-[var(--muted-fg)] mb-1">{label}</p>
              <div className="flex items-baseline gap-1">
                <input type="number" value={scores[key]} onChange={e=>setScores(s=>({...s,[key]:e.target.value}))}
                  className="w-16 text-[20px] font-bold border border-[var(--border)] rounded-lg px-2 py-0.5 outline-none focus:border-[var(--primary)]"/>
                <span className="text-[13px] text-[var(--muted-fg)]">점</span>
              </div>
              <p className="text-[11px] text-[var(--muted-fg)] mt-1">{sub}</p>
            </div>
          ))}
        </div>
        <div className="flex justify-end mt-4">
          <button onClick={saveScores} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">배점 저장</button>
        </div>
      </Panel>

      <Panel className="mb-8">
        <div className="p-5 border-b border-[var(--border)]">
          <p className="text-[13px] font-semibold text-[var(--muted-fg)]">판정 기준</p>
          <p className="text-[11px] text-[var(--muted-fg)] mt-1">배점과 마찬가지로 상수가 아닌 관리자 설정값이며, 운영 중 조정할 수 있습니다.</p>
        </div>
        {[['threshold','통과 Threshold','100점 만점 중 이 점수 이상이면 통과로 판정합니다.','점'],
          ['rerun','재수행 횟수 상한','미달 항목이 발생한 Task만 선별 재수행할 때의 최대 횟수입니다.','회'],
          ['tokenRetry','검수 문단 재시도 상한','검수(표현) Task 내부에서 보호 토큰 위반 문단을 재시도하는 최대 횟수입니다.','회'],
          ['recheck','문서층 재채점 편차 상한','동일 입력을 다시 채점했을 때 총점 편차가 이 값을 넘으면 알림을 띄웁니다.','점']].map(([key,label,desc,unit])=>(
          <div key={key} className="grid grid-cols-[1.6fr_2.4fr_1fr] text-[13px] border-t border-[var(--border)] items-center">
            <div className="p-4 font-medium">{label}</div>
            <div className="p-4 text-[var(--muted-fg)]">{desc}</div>
            <div className="p-4 flex items-center justify-center gap-1.5">
              <input type="number" value={limits[key]} onChange={e=>setLimits(l=>({...l,[key]:e.target.value}))}
                className="w-14 border border-[var(--border)] rounded-lg px-2 py-1 text-center text-[13px] outline-none focus:border-[var(--primary)]"/>
              <span className="text-[12.5px] text-[var(--muted-fg)]">{unit}</span>
            </div>
          </div>
        ))}
        <div className="p-4 border-t border-[var(--border)] flex justify-end">
          <button onClick={saveLimits} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">판정 기준 저장</button>
        </div>
      </Panel>

      <div className="mb-8">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-[20px] font-bold">코드 기준 자동 검증 항목</h2>
          <span className="text-[11.5px] text-[var(--muted-fg)]">모든 항목은 파싱·계산으로만 판정하며 LLM을 호출하지 않습니다.</span>
        </div>
        <Panel>
          <div className="grid grid-cols-[1.9fr_2.4fr_0.9fr_0.8fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4">검증 항목</div><div className="p-4">판정 방식</div><div className="p-4 text-center">가중치</div><div className="p-4 text-center">사용 여부</div>
          </div>
          {/* 산출물 카테고리(html/svg)마다 따로 15점을 맞춰야 저장되므로, 합계도 묶음별로
              보여준다 — 한 덩어리로 늘어놓으면 어느 묶음이 모자란지 화면만 보고는 알 수 없다. */}
          {categories.map(kind=>(
            <React.Fragment key={kind}>
              <div className="border-t border-[var(--border)] bg-[var(--bg)] px-4 py-3 flex items-center justify-between gap-2 flex-wrap">
                <p className="text-[13px] font-bold">{categoryLabel(kind)}</p>
                <span className={'text-[12px] font-semibold px-2.5 py-0.5 rounded-full '+(isCategoryOk(kind)?toneBg.ok:toneBg.danger)}>
                  {isCategoryUsed(kind)?'사용 중 합계 '+sumOfCategory(kind)+' / '+CHECKLIST_CATEGORY_MAX+'점':'사용 중인 항목 없음'}
                </span>
              </div>
              {items.filter(i=>i.kind===kind).map(i=>(
                <div key={i.id} className={'grid grid-cols-[1.9fr_2.4fr_0.9fr_0.8fr] text-[13px] border-t border-[var(--border)] items-center '+(i.on?'':'opacity-50')}>
                  <div className="p-4 font-medium">{i.name}</div>
                  <div className="p-4 text-[var(--muted-fg)]">{i.how}</div>
                  <div className="p-4 flex justify-center">
                    <input type="number" value={i.weight} disabled={!i.on} onChange={e=>setWeight(i.id,e.target.value)}
                      className={'w-16 border border-[var(--border)] rounded-lg px-2 py-1 text-center text-[13px] outline-none focus:border-[var(--primary)] '+(i.on?'':'bg-[var(--muted)]')}/>
                  </div>
                  <div className="p-4 flex justify-center">
                    <input type="checkbox" checked={i.on} onChange={()=>toggleItem(i.id)} aria-label={i.name+' 사용'} className="w-4 h-4 accent-[var(--primary)]"/>
                  </div>
                </div>
              ))}
            </React.Fragment>
          ))}
          <div className="p-4 border-t border-[var(--border)] flex justify-end">
            <button onClick={saveItems} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">검증 항목 저장</button>
          </div>
        </Panel>
        <p className="mt-2 text-[11px] text-[var(--muted-fg)]">체크를 해제하면 해당 항목은 채점에서 제외되고, 가중치는 <b>같은 묶음 안에서만</b> 다시 배분됩니다. 묶음마다 합계가 {CHECKLIST_CATEGORY_MAX}점이어야 저장됩니다.</p>
      </div>

      <Panel>
        <div className="p-5 border-b border-[var(--border)]">
          <p className="text-[13px] font-semibold text-[var(--muted-fg)]">문서층 채점 재현성 장치</p>
          <p className="text-[11px] text-[var(--muted-fg)] mt-1">동일한 계획서를 다시 채점해도 같은 점수가 나오도록 하는 안전장치입니다.</p>
        </div>
        {REPRODUCIBILITY.map(([label,desc,badge,tone])=>(
          <div key={label} className="grid grid-cols-[1.6fr_2.4fr_1fr] text-[13px] border-t border-[var(--border)] items-center">
            <div className="p-4 font-medium">{label}</div>
            <div className="p-4 text-[var(--muted-fg)]">{desc}</div>
            <div className="p-4 flex justify-center"><span className={'text-[12px] font-semibold px-3 py-1 rounded-full '+toneBg[tone]}>{badge}</span></div>
          </div>
        ))}
      </Panel>
      <p className="mt-2 text-[11px] text-[var(--muted-fg)]">이 항목들은 재현성을 위한 고정값이라 별도로 저장할 설정이 없습니다.</p>
    </div>
  );
}

function RecoveryTab({pushToast}){
  const [items,setItems]=useState(null);
  const [loadError,setLoadError]=useState('');
  const [openId,setOpenId]=useState(null);
  const [draft,setDraft]=useState('');
  const [filter,setFilter]=useState('전체 상태');
  const [saving,setSaving]=useState(false);

  useEffect(()=>{
    api.get('/admin/recovery-items').then(rows=>setItems(rows.map(recoveryItemFromServer)))
      .catch(e=>setLoadError(e instanceof ApiError?String(e.detail):'회수 문단을 불러오지 못했어요'));
  },[]);

  const open=id=>{setOpenId(id);setDraft(items.find(i=>i.id===id).label)};
  const save=async id=>{
    if(!draft.trim()){pushToast('저장하지 못했습니다','정답 교정문을 입력해주세요.','danger');return}
    setSaving(true);
    try{
      await api.put(`/admin/recovery-items/${id}`,{recovery_status:'labeled',label:draft.trim()});
      setItems(list=>list.map(it=>it.id===id?{...it,label:draft.trim(),status:'labeled'}:it));
      setOpenId(null);
      pushToast('학습 데이터로 저장되었습니다','원문과 정답 교정문 쌍이 재학습 데이터셋 후보에 추가되었습니다.','info');
    }catch(e){
      pushToast('저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger');
    }finally{
      setSaving(false);
    }
  };

  if(loadError)return <div><h1 className="text-[28px] font-bold mb-4">검수 회수 문단</h1><p className="text-[13.5px] text-[var(--danger)]">{loadError}</p></div>;
  if(items===null)return <div><h1 className="text-[28px] font-bold mb-4">검수 회수 문단</h1><p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p></div>;

  const filtered=items.filter(it=>filter==='전체 상태'||RECOVERY_LABELS[it.status]===filter);
  const count=s=>items.filter(i=>i.status===s).length;
  const openItem=openId!=null?items.find(i=>i.id===openId):null;
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-3">검수 회수 문단</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8 max-w-3xl leading-relaxed">보호 토큰(수치·날짜·고유명사·기능명)이 훼손된 채 반려된 검수 시도(proofread_logs.passed=False)를 모읍니다. 원문에 정답 교정문을 붙이는 라벨링을 거쳐야 재학습에 쓸 수 있고, 학습 데이터 편입에 동의하지 않은 계정의 문단은 제외됩니다.</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <Card label="전체 회수 문단" value={items.length+'건'} sub="누적 기준"/>
        <Card label="라벨링 대기" value={count('pending')+'건'} tone="warn" sub="정답 교정문 미입력"/>
        <Card label="라벨링 완료" value={count('labeled')+'건'} tone="ok" sub="재학습 데이터셋 후보로 편입"/>
        <Card label="동의 없음(제외)" value={count('excluded')+'건'} sub="학습 데이터 편입 미동의 계정"/>
      </div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="text-[20px] font-bold">회수 문단 목록</h2>
        <Select value={filter} onChange={setFilter} options={['전체 상태','라벨링 대기','라벨링 완료','동의 없음(제외)']}
          className="rounded-lg border border-[var(--border)] px-3 py-2 text-[13.5px]"/>
      </div>
      <Panel>
        <div className="grid grid-cols-[1fr_1.6fr_0.8fr_0.9fr_1fr_0.9fr_0.9fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
          <div className="p-4">문단 ID</div><div className="p-4">발생 프로젝트</div><div className="p-4 text-center">모델 버전</div><div className="p-4 text-center">위반 항목</div>
          <div className="p-4 text-center">발생일시</div><div className="p-4 text-center">학습 동의</div><div className="p-4 text-center">상태</div>
        </div>
        {filtered.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)] border-t border-[var(--border)]">회수된 문단이 없습니다.</p>}
        {filtered.map(it=>(
          <button key={it.id} onClick={()=>open(it.id)}
            className={'w-full text-left grid grid-cols-[1fr_1.6fr_0.8fr_0.9fr_1fr_0.9fr_0.9fr] text-[13px] border-t border-[var(--border)] items-center hover:bg-[var(--bg)] '+(it.consent?'':'opacity-60')}>
            <div className="p-4 font-medium">PARA-{it.id}</div>
            <div className="p-4 text-[var(--muted-fg)]">{it.project}</div>
            <div className="p-4 text-center text-[var(--muted-fg)]">{it.model}</div>
            <div className="p-4 text-center text-[var(--muted-fg)]">{it.violation}</div>
            <div className="p-4 text-center text-[var(--muted-fg)]">{it.occurredAt.slice(5)}</div>
            <div className={'p-4 text-center font-semibold '+(it.consent?'text-[var(--ok)]':'text-[var(--muted-fg)]')}>{it.consent?'동의':'미동의'}</div>
            <div className={'p-4 text-center font-semibold '+(it.status==='labeled'?'text-[var(--ok)]':it.status==='pending'?'text-[var(--warn)]':'text-[var(--muted-fg)]')}>{RECOVERY_LABELS[it.status]}</div>
          </button>
        ))}
      </Panel>
      <p className="mt-3 text-[11px] text-[var(--muted-fg)]">동의 없음(제외) 행은 열람만 가능하며 저장되지 않습니다.</p>

      {openItem&&(
          <Modal wide title="문단 라벨링" onClose={()=>setOpenId(null)}>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-5">{openItem.project} · 모델 {openItem.model} · {openItem.occurredAt}</p>
            <div className="grid sm:grid-cols-2 gap-4 mb-4">
              <div>
                <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-1.5">원문 문단</p>
                <div className="rounded-xl bg-[var(--muted)] p-3.5 text-[13px] leading-relaxed min-h-[88px]">{openItem.original}</div>
              </div>
              <div>
                <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-1.5">검수 시도 (위반 발생)</p>
                <div className="rounded-xl bg-[color-mix(in_srgb,var(--danger)_6%,white)] border border-[var(--danger)]/30 p-3.5 text-[13px] leading-relaxed min-h-[88px]">{openItem.attempt}</div>
              </div>
            </div>
            <p className="text-[12px] text-[var(--danger)] font-semibold mb-4">⚠ 보호 토큰 위반: {openItem.violation} 값이 재시도 후에도 소실·변조된 상태로 남았습니다.</p>
            {openItem.consent?(
              <>
                <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1.5">정답 교정문 (학습 데이터용)</p>
                <p className="text-[11px] text-[var(--muted-fg)] mb-2">보호 토큰을 보존하면서 원문 문체를 교정한 정답 문장을 입력합니다.</p>
                <textarea rows={4} value={draft} onChange={e=>setDraft(e.target.value)} placeholder="정답 교정문을 입력하세요"
                  className="w-full border border-[var(--border)] rounded-lg p-3 text-[13px] outline-none focus:border-[var(--primary)] resize-none mb-3"/>
              </>
            ):(
              <div className="rounded-xl border border-[var(--border)] bg-[var(--bg)] p-3.5 text-[12.5px] text-[var(--muted-fg)] mb-3">
                이 계정은 교정 이력의 학습 데이터 편입에 동의하지 않았습니다(선택 동의). 열람만 가능하며 라벨링·저장은 할 수 없습니다.
              </div>
            )}
            <div className="flex items-center justify-between gap-4">
              <span className={'text-[12px] font-semibold px-3 py-1 rounded-full '+(openItem.status==='labeled'?toneBg.ok:openItem.status==='pending'?toneBg.warn:toneBg.muted)}>{RECOVERY_LABELS[openItem.status]}</span>
              <div className="flex gap-2">
                <button onClick={()=>setOpenId(null)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">닫기</button>
                {openItem.consent&&<button onClick={()=>save(openId)} disabled={saving} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-50">{saving?'저장 중…':'학습 데이터로 저장'}</button>}
              </div>
            </div>
          </Modal>
      )}
    </div>
  );
}

function UsersTab({pushToast}){
  const faqRequest=useRef(false);
  const [faqSaving,setFaqSaving]=useState(false);
  const [users,setUsers]=useState(null);
  const [usersError,setUsersError]=useState('');
  const [faq,setFaq]=useState(null);
  const [faqError,setFaqError]=useState('');
  const [faqId,setFaqId]=useState(null);
  const [answer,setAnswer]=useState('');
  const [query,setQuery]=useState('');

  useEffect(()=>{
    api.get('/admin/users').then(rows=>setUsers(rows.map(userRowFromServer))).catch(e=>setUsersError(e instanceof ApiError?String(e.detail):'사용자 목록을 불러오지 못했어요'));
    api.get('/admin/faqs').then(rows=>setFaq(rows.map((f,i)=>faqRowFromServer(f,i,rows.length)))).catch(e=>setFaqError(e instanceof ApiError?String(e.detail):'FAQ를 불러오지 못했어요'));
  },[]);

  const changeRole=(id,roleLabel)=>saveRole(id,roleLabel==='관리자'?'admin':'user');
  const saveRole=async(id,roleRaw)=>{
    try{
      const updated=await api.put('/admin/users/'+id,{role:roleRaw});
      setUsers(list=>list.map(u=>u.id===id?userRowFromServer(updated):u));
      if(roleRaw==='admin')pushToast('관리자 권한이 부여되었습니다','','info');
    }catch(e){pushToast('권한 변경에 실패했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const toggleStatus=async(u)=>{
    const nextStatus=u.statusRaw==='suspended'?'active':'suspended';
    try{
      const updated=await api.put('/admin/users/'+u.id,{status:nextStatus});
      setUsers(list=>list.map(x=>x.id===u.id?userRowFromServer(updated):x));
    }catch(e){pushToast('상태 변경에 실패했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const openFaq=id=>{setFaqId(id);setAnswer(faq.find(f=>f.id===id).answer)};
  const saveAnswer=async(id)=>{
    if(faqRequest.current)return;
    if(!answer.trim()){pushToast('답변을 저장하지 못했습니다','답변 내용을 입력해주세요.','danger');return}
    const cur=faq.find(f=>f.id===id);
    faqRequest.current=true;setFaqSaving(true);
    try{
      const updated=await api.put('/admin/faqs/'+id,{answer:answer.trim(),is_visible:cur.visible});
      setFaq(list=>list.map(f=>f.id===id?{...f,answer:updated.answer,answered:true,visible:updated.is_visible}:f));
      pushToast('답변이 저장되었습니다','노출로 전환해야 사용자에게 공개됩니다.','info');
    }catch(e){pushToast('답변을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
    finally{faqRequest.current=false;setFaqSaving(false)}
  };
  const toggleVisible=async(id)=>{
    if(faqRequest.current)return;
    const item=faq.find(f=>f.id===id);
    if(!item.visible&&!item.answered){pushToast('노출로 전환하지 못했습니다','답변을 먼저 저장한 뒤 노출로 전환할 수 있습니다.','danger');return}
    faqRequest.current=true;setFaqSaving(true);
    try{
      const updated=await api.put('/admin/faqs/'+id,{answer:item.answer,is_visible:!item.visible});
      setFaq(list=>list.map(f=>f.id===id?{...f,visible:updated.is_visible}:f));
    }catch(e){pushToast('노출 전환에 실패했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
    finally{faqRequest.current=false;setFaqSaving(false)}
  };
  const shown=(users||[]).filter(u=>(u.name+u.email).includes(query));

  return (
    <div>
      <h1 className="text-[28px] font-bold mb-8">사용자 관리</h1>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h2 className="text-[20px] font-bold">전체 사용자</h2>
        <input value={query} onChange={e=>setQuery(e.target.value)} placeholder="이름 또는 이메일 검색"
          className="border border-[var(--border)] rounded-lg px-3 py-2 text-[13.5px] w-56 outline-none focus:border-[var(--primary)]"/>
      </div>
      {usersError?<p className="text-[13.5px] text-[var(--danger)]">{usersError}</p>
      :users===null?<p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p>
      :(<Panel>
        <div className="grid grid-cols-[1.8fr_0.9fr_0.8fr_0.9fr_170px] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
          <div className="p-4">이름 / 이메일</div><div className="p-4 text-center">매칭 알림</div>
          <div className="p-4 text-center">상태</div><div className="p-4 text-center">권한</div><div className="p-4"/>
        </div>
        {shown.map(u=>(
          <div key={u.id} className={'grid grid-cols-[1.8fr_0.9fr_0.8fr_0.9fr_170px] text-[13px] border-t border-[var(--border)] items-center '+
            (u.status==='정지'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)] ':'')+(u.status==='휴면'?'opacity-60':'')}>
            <div className="p-4"><p className="font-medium">{u.name}</p><p className="text-[12px] text-[var(--muted-fg)]">{u.email}</p></div>
            <div className={'p-4 text-center font-semibold '+toneText[u.notifyTone]}>{u.notify}</div>
            <div className={'p-4 text-center font-semibold '+(u.status==='활성'?'text-[var(--ok)]':u.status==='정지'?'text-[var(--danger)]':'text-[var(--warn)]')}>{u.status}</div>
            <div className="p-4 flex justify-center">
              <Select value={u.role} onChange={v=>changeRole(u.id,v)} options={['일반 유저','관리자']} ariaLabel={u.name+' 권한'}
                className="rounded-lg border border-[var(--border)] px-2 py-1.5 text-[12.5px] w-[104px]"/>
            </div>
            <div className="p-4 flex items-center justify-center gap-3">
              <button onClick={()=>toggleStatus(u)} className={'text-[12.5px] font-semibold hover:underline '+(u.status==='정지'?'text-[var(--ok)]':'text-[var(--muted-fg)] hover:text-[var(--danger)]')}>
                {u.status==='정지'?'정지 해제':'정지'}
              </button>
            </div>
          </div>
        ))}
        {shown.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)]">검색 결과가 없어요.</p>}
      </Panel>)}

      <div className="mt-12">
        <h2 className="text-[20px] font-bold mb-4">FAQ 관리</h2>
        {faqError?<p className="text-[13.5px] text-[var(--danger)]">{faqError}</p>
        :faq===null?<p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p>
        :(<Panel>
          <div className="grid grid-cols-[0.5fr_3.4fr_1fr_1fr_0.8fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4 text-center">번호</div><div className="p-4">질문</div>
            <div className="p-4 text-center">작성일</div><div className="p-4 text-center">상태</div><div className="p-4 text-center">관리</div>
          </div>
          {faq.map(f=>(
            <div key={f.id} className="grid grid-cols-[0.5fr_3.4fr_1fr_1fr_0.8fr] text-[13px] border-t border-[var(--border)] items-center">
              <div className="p-4 text-center text-[var(--muted-fg)]">{f.no}</div>
              <div className="p-4 font-medium truncate">{f.question}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{f.date}</div>
              <div className={'p-4 text-center font-semibold '+(f.visible?'text-[var(--ok)]':'text-[var(--muted-fg)]')}>{f.visible?'노출중':f.answered?'비노출':'답변 대기'}</div>
              <div className="p-4 flex justify-center">
                <button onClick={()=>openFaq(f.id)} className="text-[12.5px] font-semibold text-[var(--primary)] hover:underline">답변</button>
              </div>
            </div>
          ))}
          {faq.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)]">등록된 질문이 없어요.</p>}
        </Panel>)}
        <p className="mt-3 text-[11px] text-[var(--muted-fg)]">답변이 없는 질문은 자동으로 비노출이며, 답변을 저장한 뒤 노출로 전환해야 공개됩니다.</p>
      </div>

      {faqId&&faq&&(()=>{
        const f=faq.find(x=>x.id===faqId);
        return (
          <Modal title="질문 상세 · 답변" onClose={()=>setFaqId(null)}>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-4">{f.date}</p>
            <div className="rounded-xl bg-[var(--muted)] p-3.5 mb-4"><p className="text-[13.5px] font-medium">{f.question}</p></div>
            <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1.5">답변</p>
            <textarea rows={4} value={answer} onChange={e=>setAnswer(e.target.value)} placeholder="답변을 입력하세요"
              className="w-full border border-[var(--border)] rounded-lg p-3 text-[13px] outline-none focus:border-[var(--primary)] resize-none mb-4"/>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-[11px] text-[var(--muted-fg)] mb-1.5">노출 상태</p>
                <span className={'inline-block text-[12px] font-semibold px-3 py-1 rounded-full '+(f.visible?toneBg.ok:toneBg.muted)}>{f.visible?'노출중':'비노출'}</span>
              </div>
              <button disabled={faqSaving} onClick={()=>toggleVisible(faqId)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)] disabled:opacity-50">
                {f.visible?'비노출로 전환':'노출로 전환'}
              </button>
            </div>
            <div className="flex justify-end gap-2 mt-6 pt-5 border-t border-[var(--border)]">
              <button onClick={()=>setFaqId(null)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">닫기</button>
              <button disabled={faqSaving} onClick={()=>saveAnswer(faqId)} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-50">{faqSaving?'처리 중…':'답변 저장'}</button>
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}
