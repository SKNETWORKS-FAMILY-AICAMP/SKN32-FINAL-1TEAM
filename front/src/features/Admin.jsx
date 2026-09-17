import React,{useState,useMemo,useEffect} from 'react';
import {Brand,Icon} from '../components/Icons.jsx';
import {api,ApiError} from '../api.js';

// 관리자 판별은 이제 App.jsx에서 /auth/me가 내려주는 실제 role로 한다(props.user.role).
// 이 파일 안에서는 이미 관리자로 확인된 사용자만 보고 있다고 가정한다.

// 아래 7개 탭 중 실제 백엔드(/admin/*)가 있는 건 "검증 정책"(policy+checklist),
// "사용자 관리·FAQ"(users+faqs), "에이전트 테스크"의 Execution별 보기(agent-executions)뿐이다.
// 나머지(공고 관리/운영 현황/진행 현황/검수 회수 문단, 그리고 에이전트 테스크의 Task별 보기)는
// 대응하는 API 자체가 없어서(다른 팀원의 오케스트레이터/공고수집 파이프라인 작업 영역) 지금도
// 아래 예시 데이터 그대로 둔다 — 실제 연동 시점에 이 파일에서 해당 탭만 바꾸면 된다.

const TABS=[['ann','공고 관리'],['ops','운영 현황'],['progress','진행 현황'],['agents','에이전트 테스크'],['policy','검증 정책'],['recovery','검수 회수 문단'],['users','사용자 관리·FAQ']];

const SOURCES=[
  {id:'1',name:'K-Startup',tone:'ok',badge:'［정상］',lastSuccess:'2026-09-09 06:00',count:'128건',embed:'완료',action:'수동 재수집'},
  {id:'2',name:'지자체 통합공고',tone:'warn',badge:'［임베딩 실패 · 매칭·알림에서 누락됨］',lastSuccess:'2026-09-09 06:00',count:'14건 (금일)',embed:'14건 중 3건 실패',
   cause:'원인: 임베딩 모델 레이트리밋 초과. 수집 자체는 정상이며, 이 3건만 벡터가 없어 매칭 대상에서 조용히 빠짐',action:'임베딩만 재생성'},
  {id:'3',name:'기업마당',tone:'danger',badge:'［실패 · 전일 데이터로 동작 중］',lastSuccess:'2026-09-07 06:00 (2일 전)',count:'0건 (금일)',embed:'미생성',
   cause:'원인: 응답 타임아웃 (3회 재시도 실패)',action:'지금 재수집'},
];

const COLLECT_FAILURES=[
  ['2026-09-07 06:00','기업마당','응답 타임아웃 (3회 재시도 실패)','관리자 수동 재수집 대기 중','danger'],
  ['2026-09-05 06:00','지자체 통합공고','임베딩 모델 레이트리밋 초과 (3건)','임베딩 재생성 완료','ok'],
  ['2026-08-30 06:00','기업마당','응답 타임아웃 (2회 재시도 실패)','자동 복구 (익일 정상화)','muted'],
  ['2026-08-22 06:00','K-Startup','API 502 오류','자동 복구 (당일 재시도 성공)','muted'],
];

const ANNOUNCEMENT_ROWS=[
  {title:'2026 초기창업패키지',src:'K-Startup',period:'09.01~09.30',embed:'완료',embedTone:'ok',status:'모집중',statusTone:'ok'},
  {title:'기술개발사업 2차',src:'기업마당',period:'09.05~09.25',embed:'지연',embedTone:'warn',status:'모집중',statusTone:'ok'},
  {title:'지역특화 스마트상점 지원',src:'중소벤처기업부',period:'08.01~08.31',embed:'완료',embedTone:'ok',status:'마감 (자동 제외)',statusTone:'muted',dim:true},
];

const SCORE_HISTORY={
  '1':{title:'2026 초기창업패키지 매칭',
    doc:[{date:'2026-09-05',score:58,note:'평가항목 충족률 개선 (시장분석 챕터 보완)',rerun:true},{date:'2026-08-20',score:50,note:'1차 문서 검증'},{date:'2026-08-01',score:44,note:'최초 문서 검증'}],
    code:[{date:'2026-09-04',score:12,note:'프로토타입 코드 자동 검증'},{date:'2026-08-19',score:10,note:'1차 코드 검증'},{date:'2026-08-01',score:8,note:'최초 코드 검증'}],
    plan:[{date:'2026-09-04',score:12,note:'계획서 대조 결과 반영'},{date:'2026-08-19',score:10,note:'1차 계획서 대조'},{date:'2026-08-01',score:8,note:'최초 계획서 대조'}]},
  '2':{title:'기술개발사업 매칭',
    doc:[{date:'2026-08-28',score:65,note:'평가항목 전량 충족'},{date:'2026-08-10',score:60,note:'2차 문서 검증'},{date:'2026-07-15',score:54,note:'최초 문서 검증'}],
    code:[{date:'2026-08-27',score:13,note:'코드 기준 자동 검증 통과'},{date:'2026-08-09',score:12,note:'2차 코드 검증'},{date:'2026-07-15',score:10,note:'최초 코드 검증'}],
    plan:[{date:'2026-08-27',score:13,note:'계획서 대조 전량 일치'},{date:'2026-08-09',score:12,note:'2차 계획서 대조'},{date:'2026-07-15',score:10,note:'최초 계획서 대조'}]},
  '3':{title:'지자체 통합공고 매칭',
    doc:[{date:'2026-06-01',score:48,note:'중단 시점 문서 검증'},{date:'2026-05-20',score:33,note:'2차 문서 검증 (채점 편차 발생)'},{date:'2026-05-10',score:53,note:'최초 문서 검증'}],
    code:[{date:'2026-05-25',score:8,note:'산출물 저장소 연결 실패로 검증 미완료'},{date:'2026-05-15',score:9,note:'1차 코드 검증'},{date:'2026-05-05',score:10,note:'최초 코드 검증'}],
    plan:[{date:'2026-05-25',score:9,note:'계획서 대조 보류'},{date:'2026-05-15',score:10,note:'1차 계획서 대조'},{date:'2026-05-05',score:10,note:'최초 계획서 대조'}]},
  '4':{title:'스마트상점 지원 매칭',
    doc:[{date:'2026-08-31',score:54,note:'최종 심사 반영'},{date:'2026-08-15',score:50,note:'2차 문서 검증'},{date:'2026-08-01',score:47,note:'최초 문서 검증'}],
    code:[{date:'2026-08-30',score:10,note:'프로토타입 최종 검증'},{date:'2026-08-14',score:9,note:'2차 코드 검증'},{date:'2026-08-01',score:8,note:'최초 코드 검증'}],
    plan:[{date:'2026-08-30',score:10,note:'계획서 대조 최종 반영'},{date:'2026-08-14',score:9,note:'2차 계획서 대조'},{date:'2026-08-01',score:8,note:'최초 계획서 대조'}]},
  '5':{title:'기업마당 매칭',
    doc:[{date:'2026-09-01',score:42,note:'매칭 재계산 후 재검증',rerun:true},{date:'2026-08-20',score:44,note:'1차 문서 검증'},{date:'2026-08-05',score:40,note:'최초 문서 검증'}],
    code:[{date:'2026-08-31',score:8,note:'산출물 재검증 (매칭 변경 반영)',rerun:true},{date:'2026-08-19',score:3,note:'1차 코드 검증 (채점 편차 발생)'},{date:'2026-08-05',score:7,note:'최초 코드 검증'}],
    plan:[{date:'2026-08-31',score:8,note:'계획서 대조 재검증',rerun:true},{date:'2026-08-19',score:9,note:'1차 계획서 대조'},{date:'2026-08-05',score:7,note:'최초 계획서 대조'}]},
  '6':{title:'기술개발사업 2차 매칭',
    doc:[{date:'2026-09-08',score:62,note:'1차 문서 검증 완료 (Threshold 미달, 사용자 판단 대기 중)'}],code:[],plan:[]},
};

const DEVIATION_CATEGORIES=[['doc','문서층 검증',70],['code','코드 기준 검증',15],['plan','계획서 대조',15]];

const PROJECT_STEPS=['전략','작성','구현','검증-1','검증-2','검수'];

const PROJECT_DETAIL={
  '1':{title:'2026 초기창업패키지 매칭',user:'김도윤',ann:'2026 초기창업패키지',score:82,status:'진행중',currentStep:1,step:'작성',attempts:1,lastUpdated:'2026-09-09 07:40',shortUpdated:'09-09 07:40',stalled:false,
    agent:{name:'작성',task:'사업계획서 본문 작성 중 (시장분석 챕터 서술·표)',running:true},supervisorTask:'작성 Agent에게 본문 작성을 위임하고 진행 상황을 모니터링 중',errors:[]},
  '2':{title:'기술개발사업 매칭',user:'박서연',ann:'기술개발사업 2차',score:91,status:'완료',currentStep:6,step:'검수',attempts:1,lastUpdated:'2026-08-30 16:20',shortUpdated:'08-30 16:20',stalled:false,
    agent:null,supervisorTask:'모든 하위 Agent의 산출물과 검수 결과를 통합 완료',errors:[]},
  '3':{title:'지자체 통합공고 매칭',user:'이하늘',ann:'지자체 통합공고',score:65,status:'중단',currentStep:2,step:'구현',attempts:2,lastUpdated:'2026-06-01 09:12',shortUpdated:'06-01 09:12',stalled:true,
    agent:{name:'구현',task:'프로토타입 HTML 실행 파일 생성',running:false,haltReason:'산출물 저장소 연결 실패로 구현 Agent 작업이 중단되었습니다. 조율(Supervisor)이 재실행 대기 중입니다.'},
    supervisorTask:'구현 Agent 재실행 대기 및 대체 경로 탐색 중',
    errors:[{time:'2026-06-01 09:12',message:'구현 Agent 산출물 저장소 연결 타임아웃'},{time:'2026-05-25 14:03',message:'검증-2(산출물) 자동 검증 실패 (재시도 후에도 실패)'}]},
  '4':{title:'스마트상점 지원 매칭',user:'최민준',ann:'지역특화 스마트상점 지원',score:74,status:'완료',currentStep:6,step:'검수',attempts:1,lastUpdated:'2026-08-14 10:05',shortUpdated:'08-14 10:05',stalled:false,
    agent:null,supervisorTask:'모든 하위 Agent의 산출물과 검수 결과를 통합 완료',errors:[],archived:true},
  '5':{title:'기업마당 매칭',user:'김도윤',ann:'기업마당 공고',score:58,status:'진행중',currentStep:0,step:'전략',attempts:2,lastUpdated:'2026-08-25 03:05',shortUpdated:'08-25 03:05',stalled:true,
    agent:{name:'전략',task:'요구사항 분석 및 목표시장 분석',running:true},supervisorTask:'공고 매칭·자격 확인 후 전략 Agent에게 분석 작업을 위임 중',
    errors:[{time:'2026-08-25 03:00',message:'조율(Supervisor) 공고 매칭 실행 실패 (1회 재시도 후 성공)'}]},
  '6':{title:'기술개발사업 2차 매칭',user:'박서연',ann:'기술개발사업 2차',score:74,status:'판단 대기',currentStep:3,step:'검증-1',attempts:1,lastUpdated:'2026-09-08 14:32',shortUpdated:'09-08 14:32',stalled:false,
    agent:null,supervisorTask:'문서 평가 결과를 사용자에게 안내하고 재작성·재제작 여부 선택을 기다리는 중',errors:[]},
};

const AGENT_ROWS=[
  {name:'조율 (Supervisor)',work:'요구사항 해석·공고 매칭·자격 확인, 실행할 Agent 선정과 작업 분해, 결과 통합',tasks:'5개',recent:'2026 초기창업패키지 매칭',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Opus 5',policy:'추론성능 우선'},
  {name:'전략',work:'요구사항 분석, 목표시장 분석',tasks:'3개',recent:'기업마당 매칭',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Sonnet 5',policy:'균형'},
  {name:'작성',work:'사업계획서 본문 작성 — 서술, 표, 그래프',tasks:'4개',recent:'2026 초기창업패키지 매칭',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Sonnet 5',policy:'균형'},
  {name:'구현',work:'프로토타입 제작 — HTML 실행 파일, 인포그래픽',tasks:'3개',recent:'지자체 통합공고 매칭 (중단)',recentTone:'danger',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Sonnet 5',policy:'균형',tone:'danger'},
  {name:'검증-1 (문서)',work:'문서층 검증. 공개된 평가항목 기준으로 계획서 서술 충족 여부 판정',tasks:'2개',recent:'전체 프로젝트',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Haiku 4.5',policy:'비용효율 우선',note:'온도 0 고정 (재현성)'},
  {name:'검증-2 (산출물)',work:'산출물층 검증. 코드 기준 자동 검증과 계획서 대조',tasks:'3개',recent:'전체 프로젝트',models:['Claude Opus 5','Claude Sonnet 5','Claude Haiku 4.5'],model:'Claude Haiku 4.5',policy:'비용효율 우선'},
  {name:'검수 (표현)',work:'사업계획서 문장 형식 적합성 검수 및 한국어 윤문. 자체 파인튜닝 모델을 사용',tasks:'2개',recent:'전체 프로젝트',models:['자체 파인튜닝 모델 v1','자체 파인튜닝 모델 v2','자체 파인튜닝 모델 v3 (최신)'],model:'자체 파인튜닝 모델 v3 (최신)',policy:'비용효율 우선'},
];

// GET /admin/agent-executions 응답(dict 목록, AgentExecutionOut 고정 스키마가 아니라 유연한 형태)을
// 이 화면 행 모양으로 바꾼다. project(프로젝트명)는 API가 안 내려줘서 match_id로 대신 표시한다.
const executionRowFromServer=r=>({
  id:'EXEC-'+r.execution_id,matchId:r.match_id,agent:r.agent_name,tokens:Number(r.token_usage).toLocaleString(),
  rerun:r.rerun_type,rerunTone:r.rerun_type==='rerun'?'primary':'muted',
  status:r.status,statusTone:r.status==='completed'||r.status==='성공'?'ok':'danger',
  tone:(r.status!=='completed'&&r.status!=='성공')?'danger':undefined,
});

const TOKEN_VIOLATION_RATES=[{ver:'v1',rate:18,note:'기준'},{ver:'v2',rate:11,note:'▼ -7%p',good:true},{ver:'v3 (사용 중)',rate:6,note:'▼ -5%p',good:true,current:true}];

const REPRODUCIBILITY=[
  ['평가항목 Rubric 고정','검증-1은 상수로 고정된 rubric 밖의 기준으로는 감점하지 않습니다.','고정됨','muted'],
  ['근거 위치 출력 필수','항목 점수마다 계획서 원문의 근거 위치를 함께 출력하며, 근거를 제시하지 못한 감점은 무효 처리합니다.','필수','ok'],
  ['채점 온도(temperature)','재현성을 위해 0으로 고정되며 변경할 수 없습니다.','0 (고정)','muted'],
];

const RECOVERY_SEED={
  '1':{project:'2026 초기창업패키지 매칭',model:'v3',violation:'날짜',occurredAt:'2026-09-08 14:20',consent:true,
    original:'2026년 3월까지 결제 기능을 구현한다.',attempt:'내년 봄까지 결제 기능을 구현한다.',label:'',status:'pending'},
  '2':{project:'기업마당 매칭',model:'v3',violation:'수치·금액',occurredAt:'2026-09-07 09:05',consent:false,
    original:'초기 투자금은 3천만원이며 월 매출 목표는 500만원이다.',attempt:'초기 투자금은 약 3,000만원이며 월 매출 목표는 500만원 수준이다.',label:'',status:'excluded'},
  '3':{project:'스마트상점 지원 매칭',model:'v2',violation:'기능명',occurredAt:'2026-08-30 11:40',consent:true,
    original:'결제 기능과 재고 관리 기능을 우선 구현한다.',attempt:'결제 기능과 재고 확인 기능을 우선 구현한다.',label:'결제 기능과 재고 관리 기능을 우선 구현한다.',status:'labeled'},
  '4':{project:'기술개발사업 매칭',model:'v3',violation:'고유명사',occurredAt:'2026-09-06 17:52',consent:true,
    original:'본 사업은 기술개발사업 2차 공고 기준으로 작성되었다.',attempt:'본 사업은 정부 기술개발 지원사업 공고 기준으로 작성되었다.',label:'',status:'pending'},
  '5':{project:'지자체 통합공고 매칭',model:'v1',violation:'날짜',occurredAt:'2026-08-22 10:11',consent:true,
    original:'접수 마감일인 2026년 9월 30일 이전에 신청을 완료한다.',attempt:'접수 마감일 이전에 신청을 완료한다.',label:'접수 마감일인 2026년 9월 30일 이전에 신청을 완료한다.',status:'labeled'},
};
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

const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:0;
const latest=e=>e&&e.length?e[0].score:null;
const roundDelta=e=>{if(!e||e.length<2)return null;const r1=e[e.length-1].score,r2=e[e.length-2].score;return {round1:r1,round2:r2,delta:Math.abs(r2-r1)}};
const categoryAvgDelta=key=>{const d=[];Object.keys(SCORE_HISTORY).forEach(id=>{const r=roundDelta(SCORE_HISTORY[id][key]);if(r)d.push(r.delta)});return avg(d)};
const deviationOf=(entries,key)=>{const r=roundDelta(entries);if(!r)return null;return {...r,isWarning:r.delta>categoryAvgDelta(key)}};
const hasRerun=e=>!!(e&&e.some(x=>x.rerun));

export default function AdminDashboard({user,onExit}){
  const [tab,setTab]=useState('ann');
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
        {tab==='ann'&&<AnnouncementTab pushToast={pushToast}/>}
        {tab==='ops'&&<OpsTab/>}
        {tab==='progress'&&<ProgressTab/>}
        {tab==='agents'&&<AgentsTab/>}
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

function AnnouncementTab({pushToast}){
  const [sources,setSources]=useState(SOURCES);
  const [busy,setBusy]=useState(null);
  const [query,setQuery]=useState('');
  const reload=id=>{
    setBusy(id);
    setTimeout(()=>{
      setBusy(null);
      setSources(list=>list.map(s=>s.id===id?{...s,tone:'ok',badge:'［정상］',embed:'완료',count:'18건 (금일)',cause:null,lastSuccess:new Date().toISOString().slice(0,16).replace('T',' ')}:s));
      pushToast('재수집이 완료되었습니다','수집과 임베딩 생성이 정상 처리됐어요.','info');
    },1400);
  };
  const rows=ANNOUNCEMENT_ROWS.filter(r=>r.title.includes(query));
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-8">공고 수집 현황</h1>
      <Panel className="divide-y divide-[var(--border)]">
        {sources.map((s,i)=>(
          <div key={s.id} className={'grid grid-cols-[auto_1fr_auto] items-start gap-5 px-6 py-5 '+
            (s.tone==='warn'?'bg-[color-mix(in_srgb,var(--warn)_6%,white)] border-l-4 border-l-[var(--warn)]':s.tone==='danger'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)]':'')}>
            <span className={'text-[20px] font-semibold pt-0.5 '+toneText[s.tone==='ok'?'muted':s.tone]} aria-hidden="true">{String(i+1).padStart(2,'0')}</span>
            <div className="min-w-0">
              <div className="flex items-center gap-3 flex-wrap mb-2">
                <h3 className="font-bold text-[16px]">{s.name}</h3>
                <span className={'text-[12.5px] font-bold '+toneText[s.tone]}>{s.badge}</span>
              </div>
              <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-[13px] text-[var(--muted-fg)]">
                <p>마지막 성공일 <span className={'font-medium '+(s.tone==='danger'?'text-[var(--danger)]':'text-[var(--fg)]')}>{s.lastSuccess}</span></p>
                <p>수집건수 <span className="text-[var(--fg)] font-medium">{s.count}</span></p>
                <p>임베딩 생성 <span className={'font-semibold '+toneText[s.tone]}>{s.embed}</span></p>
              </div>
              {s.cause&&<p className="text-[12.5px] text-[var(--muted-fg)] mt-2">{s.cause}</p>}
            </div>
            <button onClick={()=>reload(s.id)} disabled={busy===s.id}
              className={'flex-shrink-0 self-center min-w-[128px] rounded-xl px-4 py-2 text-[13px] font-semibold disabled:opacity-60 disabled:cursor-wait '+
                (s.tone==='danger'?'bg-[var(--primary)] text-white hover:bg-[var(--primary-dim)]':s.tone==='warn'?'bg-[var(--warn)] text-white hover:opacity-90':'border border-[var(--border)] text-[var(--muted-fg)] hover:bg-[var(--bg)]')}>
              {busy===s.id?'처리 중…':s.action}
            </button>
          </div>
        ))}
      </Panel>
      <p className="mt-3 text-[12px] text-[var(--muted-fg)]"><span className="text-[var(--warn)]">⚠</span> 수집 실패 시 전일 수집된 데이터로 동작합니다.</p>

      <div className="mt-10">
        <h2 className="text-[20px] font-bold mb-1">수집 실패 이력</h2>
        <p className="text-[12px] text-[var(--muted-fg)] mb-4">위 카드는 지금 진행 중인 실패만 보여줍니다. 과거에 언제, 몇 번, 왜 실패했는지는 여기서 확인합니다.</p>
        <Panel>
          <div className="grid grid-cols-[1.3fr_1fr_2.2fr_1.5fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4">발생 시각</div><div className="p-4 text-center">출처</div><div className="p-4">사유</div><div className="p-4 text-center">처리 결과</div>
          </div>
          {COLLECT_FAILURES.map(([time,src,reason,result,tone])=>(
            <div key={time+src} className="grid grid-cols-[1.3fr_1fr_2.2fr_1.5fr] text-[13px] border-t border-[var(--border)] items-center">
              <div className="p-4 text-[var(--muted-fg)]">{time}</div>
              <div className="p-4 text-center font-medium">{src}</div>
              <div className="p-4 text-[var(--muted-fg)]">{reason}</div>
              <div className={'p-4 text-center font-semibold '+toneText[tone]}>{result}</div>
            </div>
          ))}
        </Panel>
      </div>

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
          {rows.map(r=>(
            <div key={r.title} className={'grid grid-cols-[2fr_1fr_1fr_1fr_1fr_170px] text-[13px] border-t border-[var(--border)] items-center '+(r.dim?'opacity-50':'')}>
              <div className="p-4 font-medium">{r.title}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{r.src}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{r.period}</div>
              <div className={'p-4 text-center font-semibold '+toneText[r.embedTone]}>{r.embed}</div>
              <div className={'p-4 text-center font-semibold '+toneText[r.statusTone]}>{r.status}</div>
              <div className="p-4 flex items-center justify-center gap-3">
                <button className="text-[12.5px] font-semibold text-[var(--primary)] hover:underline">상세</button>
                <button className="text-[12.5px] font-semibold text-[var(--muted-fg)] hover:text-[var(--danger)]">삭제</button>
              </div>
            </div>
          ))}
          {rows.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)] border-t border-[var(--border)]">검색 결과가 없어요.</p>}
        </Panel>
      </div>
    </div>
  );
}

function OpsTab(){
  const threshold=70;
  const stats=useMemo(()=>{
    const docScores=[],totals=[];let pass=0,rerun=0;
    Object.keys(SCORE_HISTORY).forEach(id=>{
      const d=SCORE_HISTORY[id];const doc=latest(d.doc),code=latest(d.code),plan=latest(d.plan);
      if(doc!==null)docScores.push(doc);
      if(doc!==null&&code!==null&&plan!==null){const t=doc+code+plan;totals.push(t);if(t>=threshold)pass++}
      if(hasRerun(d.doc)||hasRerun(d.code)||hasRerun(d.plan))rerun++;
    });
    const projects=Object.keys(SCORE_HISTORY).length;
    return {docAvg:avg(docScores).toFixed(1),docCount:docScores.length,totalAvg:totals.length?avg(totals).toFixed(1):null,totalCount:totals.length,
      pass,passRate:totals.length?Math.round(pass/totals.length*100):0,rerun,rerunRate:projects?Math.round(rerun/projects*100):0,projects};
  },[]);
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-2">운영 현황</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8">기간을 기준으로 집계한 실행건수·평균 점수·통과율입니다. 실행 건 하나하나의 현재 진행 상태는 "진행 현황" 탭에서 확인하세요.</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
        <Card label="기간 내 실행건수" value="6건" sub="진행중 2 · 완료 2 · 중단 1 · 판단 대기 1"/>
        <Card label="문서평가 평균점수" value={stats.docAvg+'점'} sub={'만점 70점 · '+stats.docCount+'건 기준'}/>
        <Card label="종합평가 평균점수" value={stats.totalAvg?stats.totalAvg+'점':'-'} sub={'만점 100점 · 평가가 모두 끝난 '+stats.totalCount+'건 기준'}/>
        <Card label="통과율" value={stats.totalCount?stats.passRate+'%':'-'} sub={'통과 '+stats.pass+' / '+stats.totalCount+'건 (Threshold '+threshold+'점 기준)'}/>
        <Card label="재수행 발생률" value={stats.rerunRate+'%'} sub={'재수행 발생 '+stats.rerun+' / '+stats.projects+'건'}/>
        <Card label="보호 토큰 위반율" value="6%" sub="검수 모델 v3 기준"/>
      </div>

      <Panel className="p-5 mb-8">
        <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-4">검증 점수 분포</p>
        <div className="flex flex-col gap-2.5">
          <Bar label="90~100점" pct={20} tone="ok" right="1건"/>
          <Bar label="80~89점" pct={20} tone="ok" right="1건"/>
          <Bar label="70~79점" pct={20} tone="warn" right="1건"/>
          <Bar label="60~69점" pct={20} tone="warn" right="1건"/>
          <Bar label="60점 미만" pct={20} tone="danger" right="1건"/>
        </div>
      </Panel>

      <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">채점 편차 현황 (1회 → 2회 평균 증감)</p>
      <p className="text-[11px] text-[var(--muted-fg)] mb-3">개별 프로젝트의 편차는 "진행 현황"의 이력보기에서 확인할 수 있습니다.</p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {DEVIATION_CATEGORIES.map(([key,label,max])=>{
          const r1=[],r2=[];let warn=0;
          Object.keys(SCORE_HISTORY).forEach(id=>{const d=deviationOf(SCORE_HISTORY[id][key],key);if(d){r1.push(d.round1);r2.push(d.round2);if(d.isWarning)warn++}});
          const a1=Math.round(avg(r1)*10)/10,a2=Math.round(avg(r2)*10)/10,delta=Math.round((a2-a1)*10)/10;
          return <Card key={key} label={label} tone={delta>0?'ok':delta<0?'danger':'muted'}
            value={(delta>0?'▲ +':delta<0?'▼ ':'— ')+delta+'점'}
            sub={'1회 '+a1+'점 → 2회 '+a2+'점 (만점 '+max+'점) · 경고 '+warn+'/'+r1.length+'건'}/>;
        })}
      </div>
    </div>
  );
}

function ProgressTab(){
  const [scoreId,setScoreId]=useState(null);
  const [detailId,setDetailId]=useState(null);
  const [archived,setArchived]=useState(()=>Object.fromEntries(Object.entries(PROJECT_DETAIL).map(([id,d])=>[id,!!d.archived])));
  const ids=Object.keys(PROJECT_DETAIL);
  const statusTone=s=>s==='진행중'?'ok':s==='중단'?'danger':s==='판단 대기'?'warn':'muted';
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-2">진행 현황</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8">실행 건 하나하나의 현재 단계·시도 횟수·마지막 갱신 시각을 봅니다. 집계된 평균·통과율은 "운영 현황" 탭에서 확인하세요.</p>
      <Panel>
        <div className="grid grid-cols-[1.7fr_0.8fr_0.85fr_0.6fr_1.15fr_0.9fr_0.85fr_90px] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
          <div className="p-4">프로젝트명</div><div className="p-4 text-center">사용자</div><div className="p-4 text-center">현재 단계</div><div className="p-4 text-center">시도</div>
          <div className="p-4 text-center">마지막 갱신</div><div className="p-4 text-center">점수</div><div className="p-4 text-center">상태</div><div className="p-4 text-center">관리</div>
        </div>
        {ids.map(id=>{
          const p=PROJECT_DETAIL[id];const isArchived=archived[id];
          const warn=Object.keys(SCORE_HISTORY[id]||{}).length?['doc','code','plan'].some(k=>{const d=deviationOf(SCORE_HISTORY[id][k],k);return d&&d.isWarning}):false;
          return (
            <div key={id} className={'grid grid-cols-[1.7fr_0.8fr_0.85fr_0.6fr_1.15fr_0.9fr_0.85fr_90px] text-[13px] border-t border-[var(--border)] items-center '+
              (isArchived?'opacity-50 ':'')+(p.status==='중단'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)] ':p.status==='판단 대기'?'bg-[color-mix(in_srgb,var(--warn)_5%,white)] border-l-4 border-l-[var(--warn)] ':'')}>
              <div className="p-4 font-medium">{p.title}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.user}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.step}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{p.attempts}회</div>
              <div className="p-4 text-center text-[var(--muted-fg)] text-[12px]">
                {p.shortUpdated}
                {p.stalled&&<span className="block text-[10.5px] font-semibold text-[var(--warn)] mt-0.5">⏱ 정체</span>}
              </div>
              <div className="p-4 text-center">
                <p className="font-semibold">{p.score}점 {warn&&<span className="text-[var(--warn)]" title="채점 편차가 다른 프로젝트 평균보다 큽니다">⚠</span>}</p>
                <button onClick={()=>setScoreId(id)} className="text-[11.5px] text-[var(--primary)] hover:underline">이력보기</button>
              </div>
              <div className={'p-4 text-center font-semibold '+(isArchived?'text-[var(--muted-fg)]':toneText[statusTone(p.status)])}>{isArchived?'보관중':p.status}</div>
              <div className="p-4 flex justify-center">
                <button onClick={()=>setDetailId(id)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">관리</button>
              </div>
            </div>
          );
        })}
      </Panel>
      <p className="mt-3 text-[12px] text-[var(--muted-fg)]"><span className="text-[var(--warn)]">●</span> "판단 대기"는 평가 결과가 나와 사용자의 재작성·재제작 선택을 기다리는 정상 상태이며, 오류(중단)가 아닙니다.</p>
      <p className="mt-1.5 text-[12px] text-[var(--muted-fg)]"><span className="text-[var(--warn)]">⏱</span> "정체"는 마지막 갱신으로부터 48시간이 지났는데도 '진행중' 또는 '판단 대기' 상태가 유지되는 경우입니다.</p>

      {scoreId&&<Modal wide title={SCORE_HISTORY[scoreId].title+' 점수 이력'} onClose={()=>setScoreId(null)}>
        <p className="text-[12.5px] text-[var(--muted-fg)] mb-4">검증 단계별 이력이 삭제되지 않고 누적됩니다. 최근 변경 순으로 표시됩니다.</p>
        <div className="grid sm:grid-cols-3 gap-4">
          {DEVIATION_CATEGORIES.map(([key,label,max])=>(
            <div key={key}>
              <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-2">{label} <span className="font-normal">({max}점 만점)</span></p>
              <div className="soft-scroll rounded-xl border border-[var(--border)] divide-y divide-[var(--border)] max-h-64 overflow-y-auto">
                {(SCORE_HISTORY[scoreId][key]||[]).length===0
                  ?<div className="p-3 text-[12px] text-[var(--muted-fg)]">누적된 이력이 없습니다.</div>
                  :SCORE_HISTORY[scoreId][key].map((e,i,arr)=>(
                    <div key={e.date+i} className="p-2.5">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11.5px] text-[var(--muted-fg)]">{e.date}</span>
                        <span className="font-semibold text-[13px]">
                          {e.rerun&&i+1<arr.length&&<span className="text-[var(--muted-fg)] font-normal">{arr[i+1].score}점 → </span>}{e.score}점
                        </span>
                      </div>
                      {e.rerun&&<p className="text-[10.5px] text-[var(--primary)] font-semibold mb-0.5">재수행 결과</p>}
                      <p className="text-[11.5px] text-[var(--muted-fg)]">{e.note}</p>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </Modal>}

      {detailId&&(()=>{
        const p=PROJECT_DETAIL[detailId];const isArchived=archived[detailId];
        return (
          <Modal title={p.title} onClose={()=>setDetailId(null)}>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-5">{p.user} · 기준 공고: {p.ann} · 현재 점수 {p.score}점</p>
            <div className="flex items-start mb-6">
              {PROJECT_STEPS.map((label,idx)=>{
                const done=idx<p.currentStep,current=idx===p.currentStep;
                const circle=done?'bg-[var(--ok)] text-white':current&&p.status==='중단'?'border-2 border-[var(--danger)] text-[var(--danger)]'
                  :current&&p.status==='판단 대기'?'border-2 border-[var(--warn)] text-[var(--warn)]':current?'bg-[var(--primary)] text-white':'bg-[var(--muted)] text-[var(--muted-fg)]';
                return (
                  <React.Fragment key={label}>
                    <div className="flex flex-col items-center gap-1 flex-shrink-0 w-[52px]">
                      <div className={'w-6 h-6 rounded-full flex items-center justify-center text-[10.5px] font-semibold '+circle}>{done?'✓':idx+1}</div>
                      <span className="text-[10px] text-[var(--muted-fg)] text-center leading-tight">{label}</span>
                    </div>
                    {idx<PROJECT_STEPS.length-1&&<div className="flex-1 h-0.5 mt-3" style={{background:idx<p.currentStep?'var(--ok)':'var(--border)'}}/>}
                  </React.Fragment>
                );
              })}
            </div>
            <div className="grid grid-cols-3 gap-3 mb-5 text-[12.5px]">
              <div className="rounded-xl border border-[var(--border)] p-3"><p className="text-[var(--muted-fg)] mb-1">시도 횟수</p><p className="font-semibold text-[14px]">{p.attempts}회</p></div>
              <div className="rounded-xl border border-[var(--border)] p-3"><p className="text-[var(--muted-fg)] mb-1">마지막 갱신</p><p className="font-semibold text-[13px]">{p.lastUpdated}</p></div>
              <div className={'rounded-xl border p-3 '+(p.stalled?'border-[var(--warn)] bg-[color-mix(in_srgb,var(--warn)_6%,white)]':'border-[var(--border)]')}>
                <p className="text-[var(--muted-fg)] mb-1">정체 여부</p>
                <p className={'font-semibold text-[14px] '+(p.status==='완료'||isArchived?'text-[var(--muted-fg)]':p.stalled?'text-[var(--warn)]':'text-[var(--ok)]')}>
                  {p.status==='완료'||isArchived?'해당 없음':p.stalled?'정체':'정상'}
                </p>
              </div>
            </div>
            <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-2">에이전트 실행 현황</p>
            <div className="rounded-xl border border-[var(--border)] p-3.5 text-[13px] mb-5">
              <p className="font-semibold mb-1">조율 (Supervisor)</p>
              <p className="text-[var(--muted-fg)] mb-2 pb-2 border-b border-[var(--border)]">현재 태스크: {p.supervisorTask}</p>
              {p.status==='판단 대기'
                ?<p className="text-[var(--muted-fg)]">평가 결과가 나와 사용자가 재작성·재제작 여부를 선택하기를 기다리는 정상 대기 상태입니다.</p>
                :!p.agent?<p className="text-[var(--muted-fg)]">모든 단계가 완료되어 실행 중인 하위 Agent가 없습니다.</p>
                :p.agent.running?<><p className="font-semibold mb-1">{p.agent.name} <span className="text-[var(--ok)]">· 진행중</span></p><p className="text-[var(--muted-fg)]">현재 태스크: {p.agent.task}</p></>
                :<><p className="font-semibold mb-1">{p.agent.name} <span className="text-[var(--danger)]">· 에러로 중단됨</span></p>
                   <p className="text-[var(--muted-fg)] mb-1">중단된 태스크: {p.agent.task}</p><p className="text-[var(--danger)]">사유: {p.agent.haltReason}</p></>}
            </div>
            <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-2">오류 로그</p>
            <div className="rounded-xl border border-[var(--border)] divide-y divide-[var(--border)] max-h-40 overflow-y-auto soft-scroll">
              {p.errors.length===0?<div className="p-3 text-[12.5px] text-[var(--muted-fg)]">누적된 오류가 없습니다.</div>
                :p.errors.map(e=>(
                  <div key={e.time} className="p-3 flex items-start gap-2 text-[12.5px]">
                    <span className="text-[var(--danger)]">⚠</span>
                    <span className="text-[var(--muted-fg)] whitespace-nowrap">{e.time}</span>
                    <span>{e.message}</span>
                  </div>
                ))}
            </div>
            <div className="mt-5 pt-4 border-t border-[var(--border)]">
              {isArchived
                ?<div className="flex items-center justify-between gap-4">
                   <div>
                     <span className="inline-block text-[12px] font-semibold px-3 py-1 rounded-full bg-[var(--muted)] text-[var(--muted-fg)] mb-1.5">보관중 · 사용자 삭제</span>
                     <p className="text-[11.5px] text-[var(--muted-fg)]">사용자가 삭제해 보관중입니다. 데이터는 보존되며 관리자만 조회·복원할 수 있습니다.</p>
                   </div>
                   <button onClick={()=>setArchived(a=>({...a,[detailId]:false}))} className="flex-shrink-0 rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">복원</button>
                 </div>
                :<p className="text-[11.5px] text-[var(--muted-fg)]">보관 처리는 관리자가 직접 하지 않습니다. 사용자가 프로젝트를 삭제하면 "보관중"으로 표시되며 데이터는 보존됩니다.</p>}
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}

// 배치 기준은 백엔드 연동이 없는 예시 값이라(주석 참고) 로컬 상태로만 선택을 유지한다.
function AgentPolicyCell({policy}){
  const [value,setValue]=useState(policy);
  return <Select value={value} onChange={setValue} options={['비용효율 우선','균형','추론성능 우선']}
    className="rounded-lg border border-[var(--border)] px-2 py-1.5 text-[12.5px] w-[130px]"/>;
}

function AgentsTab(){
  const [view,setView]=useState('task');
  const [executions,setExecutions]=useState(null);
  const [execError,setExecError]=useState('');
  useEffect(()=>{
    if(view!=='execution'||executions!==null)return;
    api.get('/admin/agent-executions?limit=100').then(rows=>setExecutions(rows.map(executionRowFromServer)))
      .catch(e=>setExecError(e instanceof ApiError?String(e.detail):'실행 세션을 불러오지 못했어요'));
  },[view,executions]);
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
          <span>운영 지표 요약 (실행 세션·토큰 절감률·보호 토큰 위반율)</span>
          <Icon name="chevron" size={16}/>
        </summary>
        <div className="px-5 pb-5 pt-1 border-t border-[var(--border)]">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6 mt-4">
            <Card label="총 실행 세션" value="6건" sub="최근 7일 기준"/>
            <Card label="선별 재수행" value="4건" sub="전체 재실행 1건 · 최초 실행 1건"/>
            <Card label="토큰 절감률" value="▼ 77%" tone="ok" sub="선별 재수행 기준"/>
            <Card label="전체 재실행 대비" value="15,000 → 3,500" sub="토큰 (구현 Agent 기준)"/>
          </div>
          <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">보호 토큰 위반율</p>
          <p className="text-[11px] text-[var(--muted-fg)] mb-4">재시도 없이 1차 검수에서 수치·날짜·고유명사·기능명 등 보호 토큰이 훼손된 문단의 비율입니다. 버전 교체 시 이 값이 낮아졌는지로 비교합니다.</p>
          <div className="flex flex-col gap-2.5">
            {TOKEN_VIOLATION_RATES.map(v=>(
              <Bar key={v.ver} label={v.ver} pct={v.rate} tone={v.good?'ok':'muted'} right={v.rate+'%'} sub={v.note}/>
            ))}
          </div>
          <p className="mt-3 pt-3 border-t border-[var(--border)] text-[11px] text-[var(--muted-fg)]">
            <span className="text-[var(--warn)]">⚠</span> 위반 문단은 지시를 보강해 재시도하며, 상한을 넘어서도 남으면 해당 문단만 원문을 유지하고 관리자 로그에 기록합니다.
          </p>
        </div>
      </details>

      {view==='task'?(
        <>
          <h2 className="text-[20px] font-bold mb-4">Agent별 테스크 구성</h2>
          <Panel>
            <div className="grid grid-cols-[1fr_1.6fr_0.6fr_1.1fr_0.9fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
              <div className="p-4">Agent</div><div className="p-4">담당 업무</div><div className="p-4 text-center">정의된 태스크</div>
              <div className="p-4 text-center">최근 실행 프로젝트</div><div className="p-4 text-center">배치 기준</div>
            </div>
            {AGENT_ROWS.map(a=>(
              <div key={a.name} className={'grid grid-cols-[1fr_1.6fr_0.6fr_1.1fr_0.9fr] text-[13px] border-t border-[var(--border)] items-center '+
                (a.tone==='danger'?'bg-[color-mix(in_srgb,var(--danger)_5%,white)] border-l-4 border-l-[var(--danger)]':'')}>
                <div className="p-4 font-medium">{a.name}</div>
                <div className="p-4 text-[var(--muted-fg)]">{a.work}</div>
                <div className="p-4 text-center text-[var(--muted-fg)]">{a.tasks}</div>
                <div className={'p-4 text-center '+(a.recentTone==='danger'?'text-[var(--danger)] font-semibold':'text-[var(--muted-fg)]')}>{a.recent}</div>
                <div className="p-4 flex justify-center">
                  <AgentPolicyCell policy={a.policy}/>
                </div>
              </div>
            ))}
          </Panel>
        </>
      ):(
        <>
          <h2 className="text-[20px] font-bold mb-4">실행 세션</h2>
          {execError?<p className="text-[13.5px] text-[var(--danger)]">{execError}</p>
          :executions===null?<p className="text-[13.5px] text-[var(--muted-fg)]">불러오는 중…</p>
          :(<Panel>
            <div className="grid grid-cols-[1fr_1fr_1.6fr_1fr_1.2fr_0.9fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
              <div className="p-4">세션 ID</div><div className="p-4 text-center">Agent</div><div className="p-4 text-center">매칭 ID</div>
              <div className="p-4 text-center">토큰 사용량</div><div className="p-4 text-center">재수행 여부</div><div className="p-4 text-center">상태</div>
            </div>
            {executions.length===0&&<p className="p-6 text-center text-[13px] text-[var(--muted-fg)]">실행 로그가 아직 없어요.</p>}
            {executions.map(r=>(
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
  const weightSum=items.filter(i=>i.on).reduce((s,i)=>s+Number(i.weight||0),0);

  // 체크를 해제·재선택하면 사용 중인 항목끼리 기준 가중치 비율대로 합 100을 다시 배분한다.
  // 반올림 오차는 최대 나머지법으로 나눠 정확히 100을 맞춘다.
  const redistribute=list=>{
    const on=list.filter(i=>i.on);const totalBase=on.reduce((s,i)=>s+i.base,0);
    if(totalBase<=0)return list;
    const plans=on.map(i=>{const exact=i.base/totalBase*100;const floor=Math.floor(exact);return {id:i.id,floor,rem:exact-floor}});
    let leftover=100-plans.reduce((s,p)=>s+p.floor,0);
    plans.slice().sort((a,b)=>b.rem-a.rem).slice(0,Math.max(leftover,0)).forEach(p=>{p.floor+=1});
    const map=Object.fromEntries(plans.map(p=>[p.id,p.floor]));
    return list.map(i=>i.on?{...i,weight:map[i.id]}:{...i,weight:i.base});
  };
  const toggleItem=id=>setItems(list=>redistribute(list.map(i=>i.id===id?{...i,on:!i.on}:i)));
  const setWeight=(id,v)=>setItems(list=>list.map(i=>i.id===id?{...i,weight:v,base:Number(v)||0}:i));

  const saveScores=async()=>{
    if(scoreSum!==100){pushToast('배점을 저장하지 못했습니다','문서층·코드 기준·계획서 대조 배점의 합이 100점이어야 합니다. (현재 '+scoreSum+'점)','danger');return}
    try{
      await api.put('/admin/policy/scores',{doc_weight:Number(scores.doc),code_weight:Number(scores.code),plan_weight:Number(scores.plan)});
      pushToast('배점이 저장되었습니다','문서층 '+scores.doc+'점 · 코드 기준 '+scores.code+'점 · 계획서 대조 '+scores.plan+'점으로 반영됩니다.','info');
    }catch(e){pushToast('배점을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const saveLimits=async()=>{
    try{
      await api.put('/admin/policy/thresholds',{pass_threshold:Number(limits.threshold),rerun_cap:Number(limits.rerun),deviation_cap:Number(limits.recheck),token_retry_cap:Number(limits.tokenRetry)});
      pushToast('판정 기준이 저장되었습니다','통과 Threshold '+limits.threshold+'점 · 재수행 상한 '+limits.rerun+'회 · 검수 재시도 상한 '+limits.tokenRetry+'회 · 재채점 편차 상한 '+limits.recheck+'점으로 반영됩니다.','info');
    }catch(e){pushToast('판정 기준을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const saveItems=async()=>{
    if(weightSum!==100){pushToast('검증 항목을 저장하지 못했습니다','사용 중인 항목의 가중치 합이 100점이어야 합니다. (현재 '+weightSum+'점) 체크박스를 한 번 더 토글하면 100점에 맞게 재배분됩니다.','danger');return}
    try{
      await api.put('/admin/checklist',items.map(i=>({check_item_id:i.id,weight:Number(i.weight),enabled:i.on})));
      pushToast('검증 항목이 저장되었습니다',items.filter(i=>i.on).length+' / '+items.length+'개 항목이 사용되며 가중치 합계 100점으로 반영됩니다.','info');
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
          <div className="flex items-center gap-2">
            <span className={'text-[12px] font-semibold px-2.5 py-0.5 rounded-full '+(weightSum===100?toneBg.ok:toneBg.danger)}>사용 중 가중치 합계 {weightSum}점</span>
            <span className="text-[11.5px] text-[var(--muted-fg)]">모든 항목은 파싱·계산으로만 판정하며 LLM을 호출하지 않습니다.</span>
          </div>
        </div>
        <Panel>
          <div className="grid grid-cols-[1.6fr_2fr_0.9fr_0.9fr_0.8fr] text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            <div className="p-4">검증 항목</div><div className="p-4">판정 방식</div><div className="p-4 text-center">구분</div><div className="p-4 text-center">가중치</div><div className="p-4 text-center">사용 여부</div>
          </div>
          {items.map(i=>(
            <div key={i.id} className={'grid grid-cols-[1.6fr_2fr_0.9fr_0.9fr_0.8fr] text-[13px] border-t border-[var(--border)] items-center '+(i.on?'':'opacity-50')}>
              <div className="p-4 font-medium">{i.name}</div>
              <div className="p-4 text-[var(--muted-fg)]">{i.how}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{i.kind}</div>
              <div className="p-4 flex justify-center">
                <input type="number" value={i.weight} disabled={!i.on} onChange={e=>setWeight(i.id,e.target.value)}
                  className={'w-16 border border-[var(--border)] rounded-lg px-2 py-1 text-center text-[13px] outline-none focus:border-[var(--primary)] '+(i.on?'':'bg-[var(--muted)]')}/>
              </div>
              <div className="p-4 flex justify-center">
                <input type="checkbox" checked={i.on} onChange={()=>toggleItem(i.id)} aria-label={i.name+' 사용'} className="w-4 h-4 accent-[var(--primary)]"/>
              </div>
            </div>
          ))}
          <div className="p-4 border-t border-[var(--border)] flex justify-end">
            <button onClick={saveItems} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">검증 항목 저장</button>
          </div>
        </Panel>
        <p className="mt-2 text-[11px] text-[var(--muted-fg)]">체크를 해제하면 해당 항목은 채점에서 제외되고, 가중치는 사용 중인 항목끼리 다시 배분됩니다.</p>
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
  const [items,setItems]=useState(RECOVERY_SEED);
  const [openId,setOpenId]=useState(null);
  const [draft,setDraft]=useState('');
  const [filter,setFilter]=useState('전체 상태');
  const open=id=>{setOpenId(id);setDraft(items[id].label)};
  const save=id=>{
    if(!draft.trim()){pushToast('저장하지 못했습니다','정답 교정문을 입력해주세요.','danger');return}
    setItems(s=>({...s,[id]:{...s[id],label:draft.trim(),status:'labeled'}}));
    setOpenId(null);
    pushToast('학습 데이터로 저장되었습니다','원문과 정답 교정문 쌍이 재학습 데이터셋 후보에 추가되었습니다.','info');
  };
  const ids=Object.keys(items).filter(id=>filter==='전체 상태'||RECOVERY_LABELS[items[id].status]===filter);
  const count=s=>Object.values(items).filter(i=>i.status===s).length;
  return (
    <div>
      <h1 className="text-[28px] font-bold mb-3">검수 회수 문단</h1>
      <p className="text-[13px] text-[var(--muted-fg)] mb-8 max-w-3xl leading-relaxed">재시도 상한을 넘겨도 보호 토큰(수치·날짜·고유명사·기능명)이 훼손된 채 남은 문단을 모읍니다. 원문에 정답 교정문을 붙이는 라벨링을 거쳐야 재학습에 쓸 수 있고, 학습 데이터 편입에 동의하지 않은 계정의 문단은 제외됩니다.</p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        <Card label="전체 회수 문단" value={Object.keys(items).length+'건'} sub="최근 30일 기준"/>
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
        {ids.map(id=>{
          const it=items[id];
          return (
            <button key={id} onClick={()=>open(id)}
              className={'w-full text-left grid grid-cols-[1fr_1.6fr_0.8fr_0.9fr_1fr_0.9fr_0.9fr] text-[13px] border-t border-[var(--border)] items-center hover:bg-[var(--bg)] '+(it.consent?'':'opacity-60')}>
              <div className="p-4 font-medium">PARA-{id}</div>
              <div className="p-4 text-[var(--muted-fg)]">{it.project}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{it.model}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{it.violation}</div>
              <div className="p-4 text-center text-[var(--muted-fg)]">{it.occurredAt.slice(5)}</div>
              <div className={'p-4 text-center font-semibold '+(it.consent?'text-[var(--ok)]':'text-[var(--muted-fg)]')}>{it.consent?'동의':'미동의'}</div>
              <div className={'p-4 text-center font-semibold '+(it.status==='labeled'?'text-[var(--ok)]':it.status==='pending'?'text-[var(--warn)]':'text-[var(--muted-fg)]')}>{RECOVERY_LABELS[it.status]}</div>
            </button>
          );
        })}
      </Panel>
      <p className="mt-3 text-[11px] text-[var(--muted-fg)]">동의 없음(제외) 행은 열람만 가능하며 저장되지 않습니다.</p>

      {openId&&(()=>{
        const it=items[openId];
        return (
          <Modal wide title="문단 라벨링" onClose={()=>setOpenId(null)}>
            <p className="text-[12.5px] text-[var(--muted-fg)] mb-5">{it.project} · 모델 {it.model} · {it.occurredAt}</p>
            <div className="grid sm:grid-cols-2 gap-4 mb-4">
              <div>
                <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-1.5">원문 문단</p>
                <div className="rounded-xl bg-[var(--muted)] p-3.5 text-[13px] leading-relaxed min-h-[88px]">{it.original}</div>
              </div>
              <div>
                <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-1.5">1차 검수 시도 (위반 발생)</p>
                <div className="rounded-xl bg-[color-mix(in_srgb,var(--danger)_6%,white)] border border-[var(--danger)]/30 p-3.5 text-[13px] leading-relaxed min-h-[88px]">{it.attempt}</div>
              </div>
            </div>
            <p className="text-[12px] text-[var(--danger)] font-semibold mb-4">⚠ 보호 토큰 위반: {it.violation} 값이 재시도 후에도 소실·변조된 상태로 남았습니다.</p>
            {it.consent?(
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
              <span className={'text-[12px] font-semibold px-3 py-1 rounded-full '+(it.status==='labeled'?toneBg.ok:it.status==='pending'?toneBg.warn:toneBg.muted)}>{RECOVERY_LABELS[it.status]}</span>
              <div className="flex gap-2">
                <button onClick={()=>setOpenId(null)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">닫기</button>
                {it.consent&&<button onClick={()=>save(openId)} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">학습 데이터로 저장</button>}
              </div>
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}

function UsersTab({pushToast}){
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
    if(!answer.trim()){pushToast('답변을 저장하지 못했습니다','답변 내용을 입력해주세요.','danger');return}
    const cur=faq.find(f=>f.id===id);
    try{
      const updated=await api.put('/admin/faqs/'+id,{answer:answer.trim(),is_visible:cur.visible});
      setFaq(list=>list.map(f=>f.id===id?{...f,answer:updated.answer,answered:true,visible:updated.is_visible}:f));
      pushToast('답변이 저장되었습니다','노출로 전환해야 사용자에게 공개됩니다.','info');
    }catch(e){pushToast('답변을 저장하지 못했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
  };
  const toggleVisible=async(id)=>{
    const item=faq.find(f=>f.id===id);
    if(!item.visible&&!item.answered){pushToast('노출로 전환하지 못했습니다','답변을 먼저 저장한 뒤 노출로 전환할 수 있습니다.','danger');return}
    try{
      const updated=await api.put('/admin/faqs/'+id,{answer:item.answer,is_visible:!item.visible});
      setFaq(list=>list.map(f=>f.id===id?{...f,visible:updated.is_visible}:f));
    }catch(e){pushToast('노출 전환에 실패했습니다',e instanceof ApiError?String(e.detail):'서버에 연결할 수 없어요','danger')}
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
              <button onClick={()=>toggleVisible(faqId)} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12.5px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">
                {f.visible?'비노출로 전환':'노출로 전환'}
              </button>
            </div>
            <div className="flex justify-end gap-2 mt-6 pt-5 border-t border-[var(--border)]">
              <button onClick={()=>setFaqId(null)} className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:bg-[var(--bg)]">닫기</button>
              <button onClick={()=>saveAnswer(faqId)} className="rounded-xl bg-[var(--primary)] text-white px-4 py-2 text-[13px] font-semibold hover:bg-[var(--primary-dim)]">답변 저장</button>
            </div>
          </Modal>
        );
      })()}
    </div>
  );
}
