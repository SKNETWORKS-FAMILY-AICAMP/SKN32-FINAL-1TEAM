import React from 'react';
import {createRoot} from 'react-dom/client';
import Landing from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import * as W from './features/Workflow.jsx';
import {FileDeletionsPanel} from './features/Admin.jsx';
import MyPage from './features/mypage/MyPage.jsx';
import {useMyPageStore} from './store/useMyPageStore.js';
import {api} from './api.js';
import {scoresFromResult} from './features/workflow/utils.js';
import './styles.css';
const names=['landing','dashboard','empty','intake','match-progress','match-results','eligibility-gate','eligibility-fail','plan-progress','plan-form','artifact-progress','plan-failed','artifact-failed','artifact-result','artifact-gate-fail','artifact-partial','final-verdict','final-pass','review','admin-file-deletions','plan-form-tagged','final-verdict-tagged','mypage','mypage-empty','intake-filled','intake-profile'];
const page=new URLSearchParams(location.search).get('page')||'landing';
const noop=()=>{};
// 관리자 파일 삭제 대기열 견본 — 웹 API(SB-311 반영분)가 아직 sb-269에 없어 가짜 응답으로 본다.
// 모양은 실제 API(SB-318, 10-13 병합): GET 목록 → 줄 목록(전체 개수 없음, status를 안 거르면 파라미터 없음), POST 다시 시도 → 바뀐 줄.
if(page==='admin-file-deletions'){
 const rows=[
  {deletion_id:'12',run_id:'run-7f3a9c21',status:'포기',attempts:3,last_error_kind:'일시',created_at:'2026-10-09T01:10:00Z',next_at:'2026-10-09T01:50:00Z',last_tried_at:'2026-10-09T01:50:00Z',gave_up_at:'2026-10-09T01:50:00Z',retried_by:null,retried_at:null},
  {deletion_id:'9',run_id:'run-41be0d77',status:'포기',attempts:3,last_error_kind:'운영',created_at:'2026-10-08T05:00:00Z',next_at:'2026-10-08T06:40:00Z',last_tried_at:'2026-10-08T06:40:00Z',gave_up_at:'2026-10-08T06:40:00Z',retried_by:'1',retried_at:'2026-10-08T06:00:00Z'},
  {deletion_id:'13',run_id:'run-c09e5512',status:'대기',attempts:1,last_error_kind:'일시',created_at:'2026-10-10T02:00:00Z',next_at:'2026-10-10T02:20:00Z',last_tried_at:'2026-10-10T02:10:00Z',gave_up_at:null,retried_by:null,retried_at:null},
 ];
 api.get=async url=>{const status=new URL(url,location.origin).searchParams.get('status');return rows.filter(r=>!status||r.status===status)};
 api.post=async url=>{const row=rows.find(r=>url.includes(`/${r.deletion_id}/`));Object.assign(row,{status:'대기',attempts:0,gave_up_at:null,next_at:new Date(Date.now()+600000).toISOString(),retried_by:'1',retried_at:new Date().toISOString()});return {...row}};
}
// 새 응답 모양 견본(백엔드 응답모양변경 10-11) — 계획서 항목마다 section_code · tag · content_type, 점수 항목마다 tag,
// 그림 두 장(diagrams). 백엔드가 아직 올리지 않아 가짜 결과로 묶음별 화면(화면 6 점수 · 화면 9 계획서 보기)을 본다.
// 그림 주소는 가짜 SVG로 돌려준다. 그림 항목 하나는 tag '2-1'(실현가능성에 붙는 경우), 하나는 null로 둔다.
const TAGGED=page.endsWith('-tagged');
if(TAGGED){
 const svg=(t,c)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 160"><rect width="640" height="160" fill="#f4f7fb"/>${['방문','예약','결제','출석'].map((n,i)=>`<rect x="${20+i*155}" y="55" width="130" height="50" rx="10" fill="${c}"/><text x="${85+i*155}" y="86" font-size="16" text-anchor="middle" fill="#fff">${n}</text>`).join('')}<text x="20" y="32" font-size="15" fill="#1c2331">${t}</text></svg>`;
 const realFetch=window.fetch.bind(window);
 window.fetch=(url,opts)=>String(url).includes('/artifact-files/')?Promise.resolve(new Response(svg(String(url).includes('flow')?'서비스 흐름도':'서비스 구조도',String(url).includes('flow')?'#2f5597':'#3f8f6b'),{headers:{'content-type':'image/svg+xml'}})):realFetch(url,opts);
}
const sec=(section_code,tag,title,body,content_type='section')=>({section_code,tag,title,body,content_type});
const TAGGED_SECTIONS=[
 sec('1.1',null,'일반현황','대표자 김창업 · 개인사업자 · 2025년 1월 개업'),
 sec('1.2',null,'창업 아이템 개요','동네 헬스장의 회원 관리와 수업 예약을 한 화면에서 처리하는 서비스입니다.'),
 sec('2.1.1','1-1','창업 배경 및 개발 동기','소규모 헬스장 12곳을 방문해 보니 회원 관리를 종이 장부와 메신저로 하고 있었습니다.'),
 sec('2.1.2','1-1','목표 시장 현황','국내 소규모 체육시설은 약 1만 곳이며 그중 70%가 별도 관리 도구를 쓰지 않습니다.'),
 sec('2.1.3','1-1','고객 문제 정의','예약 누락과 노쇼로 월평균 8시간의 상담 시간이 낭비됩니다.'),
 sec('2.2.1','2-1','개발 방안','모바일 웹으로 예약 · 출석 · 결제를 한곳에서 처리합니다.'),
 sec('2.2.2','2-1','차별화 전략','기존 대형 프랜차이즈용 도구보다 설정 단계를 3단계로 줄였습니다.'),
 sec('2.3.6','2-1','서비스 흐름도','','image'),
 sec('2.3.7','2-1','추진 일정(협약기간 내)','2026.11 기획 완료\n2027.01 시범 운영\n2027.03 정식 출시','table'),
 sec('3.1.1','3-1','비즈니스 모델','월 구독료 29,000원, 결제 수수료 1.5%.'),
 sec('3.2.1','3-1','시장 진입 전략','지역 헬스장 협회와 함께 시범 매장 20곳을 모집합니다.'),
 sec('3.3.6',null,'서비스 구조도','','image'),
 sec('3.4.1','3-1','사업비 집행계획','외주 개발 1,500만 원 · 마케팅 500만 원 · 서버 200만 원','table'),
 sec('4.1.1','4-1','대표자 역량','헬스장 운영 5년 · 예약 서비스 개발 경험'),
 sec('4.1.2','4-1','팀 구성 현황','개발 1명 · 디자인 1명 · 영업 1명(채용 예정)'),
];
const rsn=(item_code,tag,score,max_score,reason_text)=>({item_code,tag,score,max_score,reason_text});
const TAGGED_RESULT={
 verdict:{doc_score:50,doc_max_score:70,code_score:11,code_max_score:15,plan_match_score:9,plan_match_max_score:15,artifact_score:20,artifact_max_score:30,total_score:70,pass_threshold:80,
  notices:['입력한 협약기간 일정이나 사업비가 기준(협약기간 최대 개월 수 · 개발 기간 · 공고 지원 금액 상한)을 벗어나 일부 항목이 검증을 통과하지 못했습니다. 이 항목은 다시 만들어도 고쳐지지 않습니다. 이대로 진행하거나, 입력을 고쳐 새 프로젝트로 다시 만들 수 있습니다.']},
 plan:{doc_max_score:70,sections:TAGGED_SECTIONS,table_fallbacks:[{section_code:'3.4.1',tag:'3-1',title:'사업비 집행계획',display_reason:'사업비 표를 만들지 못해 설명으로 표시합니다. 사업비 입력을 확인해 주세요.'}],
  diagrams:[{diagram_id:'2.3.6-USER_FLOW',flow_type:'USER_FLOW',title:'서비스 흐름도',source_ref:'2.3.6',nodes:['방문','예약','결제','출석'],image_url:'/projects/demo/artifact-files/flow.svg'},
   {diagram_id:'3.3.6-SERVICE_ARCHITECTURE',flow_type:'SERVICE_ARCHITECTURE',title:'서비스 구조도',source_ref:'3.3.6',nodes:['화면','예약 서버','결제'],image_url:'/projects/demo/artifact-files/arch.svg'}],
  score_reasons:[rsn('1.2',null,4,5,'개요가 핵심 기능 하나만 설명합니다.'),rsn('2.3.6','0-2',3,4,'흐름도에 결제 단계가 빠졌습니다.'),rsn('2.1.1','1-1',5,5,''),rsn('2.1.2','1-1',3,6,'시장 규모 근거가 한 건뿐입니다.'),rsn('2.1.3','1-1',4,6,'문제를 수치로 보인 근거가 약합니다.'),
   rsn('2.2.1','2-1',6,8,'개발 단계별 산출물이 빠졌습니다.'),rsn('2.2.2','2-1',4,6,'경쟁 서비스와 비교가 없습니다.'),rsn('2.3.7','2-1',4,4,''),
   rsn('3.1.1','3-1',5,6,'가격 근거가 부족합니다.'),rsn('3.2.1','3-1',4,6,'진입 일정이 모호합니다.'),rsn('3.4.1','3-1',4,6,'사업비 산출 근거가 없습니다.'),
   rsn('4.1.1','4-1',5,6,'대표자 경력 증빙이 없습니다.'),rsn('4.1.2','4-1',2,6,'채용 계획이 구체적이지 않습니다.')],
  artifacts:[{score_reasons:[{item_code:'CHECK-1',display_name:'문서 구조',score:2,max_score:2,reason_text:''},{item_code:'CHECK-5',display_name:'반응형',score:1,max_score:2,reason_text:'모바일 폭에서 표가 넘칩니다.'},{item_code:'CHECK-7',display_name:'외부 의존',score:0,max_score:0,applicable:false,reason_text:'외부 주소를 쓰지 않아 해당 없음'},{item_code:'FEATURE-1',score:0,max_score:3,reason_text:'회원권 결제'}]}]},
};
const TAGGED_SCORES=TAGGED?scoresFromResult(TAGGED_RESULT):null;
// 마이페이지 견본 — 채운 프로필 하나(mypage)와 빈 프로필(mypage-empty). 서버 없이 스토어에 바로 넣는다.
if(page==='mypage'||page==='intake-profile'){
 const st=useMyPageStore.getState();const p=st.profiles[0];
 useMyPageStore.setState({onboarded:true,profiles:[{...p,name:'헬스장 예약 서비스',profileId:1,
  basic:{...p.basic,applicantType:'individual',ceoName:'김창업',birthDate:'1992-03-14',gender:'남성',region:{sido:'서울특별시',sigungu:'강남구'},industry:'정보·통신',certs:['벤처기업'],bizNo:'1234567890',companyName:'(주)에스브레인',openedAt:'2025-01-10'},
  capability:{...p.capability,careers:[{type:'경력',title:'○○피트니스 · 운영 매니저',period:'2019-03 ~ 2024-02',hasProof:true},{type:'학력',title:'○○대학교 · 경영학',period:'2011-03 ~ 2017-02',hasProof:false}],skills:'헬스장 운영 5년, 예약 서비스 기획 경험',team:[{name:'이개발',role:'CTO · 개발',career:'백엔드 5년',status:'재직 중'}]}},
  {...p,localId:'p2',name:'프로필 2',profileId:2}],activeIndex:0});
}
if(page==='mypage-empty')useMyPageStore.setState({onboarded:false,profiles:[{...useMyPageStore.getState().profiles[0],name:'프로필 1',profileId:null}],activeIndex:0});
// 사전 정보 입력 견본 — 개인사업자로 칸을 채운 상태(유형을 골라야 보이는 사업비 · 일정 칸까지 본다).
const SAMPLE_INTAKE={applicantType:'individual',ceoName:'김창업',birthDate:'1992-03-14',gender:'남성',companyName:'(주)에스브레인',foundedAt:'2025-01-10',
 item:'동네 헬스장의 회원 관리와 수업 예약을 한 화면에서 처리하는 서비스',team:[{name:'이개발',role:'CTO · 개발',career:'백엔드 5년'}],
 pricing:[{item:'월 구독료',price:'29,000원'}],region:{sido:'서울특별시',sigungu:'강남구'},industry:'정보·통신',certs:['벤처기업'],
 careers:[{type:'경력',title:'○○피트니스 · 운영 매니저',period:'2019-03 ~ 2024-02',hasProof:true}],skills:'헬스장 운영 5년',
 devPeriod:{start:'2026-11',end:'2027-06'},selfFunding:{available:true,cashLimit:'10000000',inKindResources:'사무실 공간'},hires:[{job:'프론트엔드 개발',count:'1명',skill:'React',when:'2027-01'}],
 noEquipment:true,noPartners:true,
 budget:[{phase:'',category:'외주용역비',plan:'예약 앱 개발',gov:'15000000',cash:'3000000',inKind:'0'}],
 schedule:{feasibility:[{category:'개발',content:'예약 기능 개발',period:'2026.11 ~ 2027.02',detail:''}],growth:[]}};
const info={item:'동네 헬스장 예약 서비스',ceoName:'김창업',foundedAt:page==='eligibility-fail'?'2010-01-10':'2025-01-10',applicantType:'individual',files:[],team:[],pricing:[]};
// 공고 후보 견본 — 오케스트레이터 응답 모양(MatchCandidatesOut). 가산점 null · 0 · 값, 마감일 없음, 내용 바뀜, 막힌 공고를 한 화면에 담았다.
const SAMPLE_CANDIDATES={status:'ready',rematch_used:false,blocked_notice_ids:['N-3'],
 notices:[{code:'E-C2-EMBED',message:'추천 정확도가 낮아질 수 있습니다.'}],
 candidates:[
  {notice_id:'N-1',title:'2026년 초기창업패키지 (일반형) 창업기업 모집',org:'창업진흥원',apply_end:'2026-10-31',bonus_score:2,bonus_items:[{name:'청년 창업자',points:1},{name:'지역 소재 기업',points:1}],reason:'아이템 분야와 업력이 공고의 지원 대상과 맞습니다.',url:'https://example.com',batch:1,rank:1,fit_score:0.82,source_notice:'본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.'},
  {notice_id:'N-2',title:'소상공인 스마트상점 기술보급 사업',org:'소상공인시장진흥공단',apply_end:null,apply_period_type:'예산 소진 시까지',bonus_score:null,bonus_items:[],reason:'지역과 업종이 지원 범위에 들어갑니다.',batch:1,rank:2,fit_score:0.71,content_changed:true,source_notice:'본 AI 요약 정보는 기업마당 공고 내용을 바탕으로 생성되었습니다.'},
  {notice_id:'N-3',title:'예비창업패키지 특화분야',org:'중소벤처기업부',apply_end:'2026-11-15',bonus_score:0,bonus_items:[],reason:'아이템 분야가 특화분야와 맞습니다.',batch:1,rank:3,fit_score:0.65},
  {notice_id:'N-4',title:'지역 혁신 창업 지원사업',org:'-',apply_end:null,apply_period_type:'상시·수시',bonus_score:null,reason:'마감이 가까운 신청 가능 공고입니다.',batch:1,rank:4,fit_score:0},
 ]};
// 화면 8 서버 응답 견본 — 필수 조건 미통과 · 누락 · 부분 인정(실제 서버의 대역 채점으로는 잘 나오지 않아 여기서 본다)
const SAMPLE_ARTIFACT={'artifact-gate-fail':{category:'webdev',gate_failures:[{code:'secret',display_name:'비밀값'}],missing_features:[],partial_features:[]},
 'artifact-partial':{category:'webdev',gate_failures:[],missing_features:['회원권 결제'],partial_features:['출석 체크']}}[page]||null;
const props={announcement:W.ANNOUNCEMENTS[0],itemInfo:info,onBack:noop,onSubmit:noop,onProceed:noop,onLeave:noop,onGenerate:noop,onFinalize:noop,onGoDashboard:noop,onCheckEligibility:noop,onComplete:noop,candidates:SAMPLE_CANDIDATES,onCandidatesLoaded:noop,docOutcome:page==='final-pass'?'pass':'fail',artifactOutcome:page==='final-pass'?'pass':'fail',setDocOutcome:noop,setArtifactOutcome:noop,artifact:SAMPLE_ARTIFACT,...(page==='intake-filled'?{initialValues:SAMPLE_INTAKE}:{}),...(TAGGED?{scores:TAGGED_SCORES,plan:TAGGED_RESULT.plan,reworkBudget:{cap:1,remaining:{'일반현황 · 개요':1,'그림':1,'문제인식':1,'실현가능성':1,'성장전략':1,'팀 구성':1,'실행 파일 제작':1,'인포그래픽 제작':1}}}:{})};
const components={'intake':W.IntakeForm,'intake-filled':W.IntakeForm,'intake-profile':W.IntakeForm,'match-progress':W.MatchProgress,'match-results':W.MatchResults,'eligibility-gate':W.EligibilityGate,'eligibility-fail':W.EligibilityGate,'plan-progress':W.PipelineProgress,'plan-form':W.PlanForm,'artifact-progress':W.ArtifactProgress,'artifact-result':W.ArtifactResult,'artifact-gate-fail':W.ArtifactResult,'artifact-partial':W.ArtifactResult,'final-verdict':W.FinalVerdict,'final-verdict-tagged':W.FinalVerdict,'plan-form-tagged':W.PlanForm,'final-pass':W.FinalVerdict,'review':W.ReviewScreen};
// 완전 실패 카드 — 실제 흐름에선 서버가 status='failed'를 줘야 떠서 로컬 더미로는 재현이 어렵다.
Object.assign(components,{'plan-failed':p=><W.GenerationFailed onLeave={noop}/>,'artifact-failed':p=><W.GenerationFailed onLeave={noop}/>});
const C=components[page];
createRoot(document.getElementById('root')).render(<><nav aria-label="화면 검토" style={{padding:10,background:'#fff',display:'flex',flexWrap:'wrap',gap:12,position:'relative',zIndex:100,fontSize:12}}>{names.map(n=><a key={n} href={'?page='+n}>{n}</a>)}</nav>{page==='landing'?<Landing onStart={noop}/>:page.startsWith('mypage')?<WorkspaceShell view="mypage" notifyEnabled onToggleNotify={noop} onHome={noop} onDashboard={noop} onNewProject={noop} onLogout={noop}><MyPage user={{email:'kim@example.com'}} onSaved={noop}/></WorkspaceShell>:page==='admin-file-deletions'?<main className="w-[min(1180px,calc(100%-48px))] mx-auto py-12"><FileDeletionsPanel pushToast={(title,message)=>console.info(title,message)}/></main>:<WorkspaceShell view={page==='empty'?'dashboard':page.replace(/-tagged$|-filled$|-profile$/,'')} notifyEnabled onToggleNotify={noop} onHome={noop} onDashboard={noop} onNewProject={noop} onLogout={noop}>{C?<C {...props}/>:<Dashboard onNewProject={noop} onOpenProject={noop} isNewUser={page==='empty'} onToggleNewUser={noop}/>}</WorkspaceShell>}</>);
