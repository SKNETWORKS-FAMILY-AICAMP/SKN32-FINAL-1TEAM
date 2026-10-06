import React from 'react';
import {createRoot} from 'react-dom/client';
import Landing from './components/Landing.jsx';
import {WorkspaceShell,Dashboard} from './components/Workspace.jsx';
import * as W from './features/Workflow.jsx';
import './styles.css';
const names=['landing','dashboard','empty','intake','match-progress','match-results','eligibility-gate','eligibility-fail','plan-progress','plan-form','artifact-progress','plan-failed','artifact-failed','artifact-result','final-verdict','final-pass','review'];
const page=new URLSearchParams(location.search).get('page')||'landing';
const noop=()=>{};
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
const props={announcement:W.ANNOUNCEMENTS[0],itemInfo:info,onBack:noop,onSubmit:noop,onProceed:noop,onLeave:noop,onGenerate:noop,onFinalize:noop,onGoDashboard:noop,onCheckEligibility:noop,onComplete:noop,candidates:SAMPLE_CANDIDATES,onCandidatesLoaded:noop,docOutcome:page==='final-pass'?'pass':'fail',artifactOutcome:page==='final-pass'?'pass':'fail',setDocOutcome:noop,setArtifactOutcome:noop};
const components={'intake':W.IntakeForm,'match-progress':W.MatchProgress,'match-results':W.MatchResults,'eligibility-gate':W.EligibilityGate,'eligibility-fail':W.EligibilityGate,'plan-progress':W.PipelineProgress,'plan-form':W.PlanForm,'artifact-progress':W.ArtifactProgress,'artifact-result':W.ArtifactResult,'final-verdict':W.FinalVerdict,'final-pass':W.FinalVerdict,'review':W.ReviewScreen};
// 완전 실패 카드 — 실제 흐름에선 서버가 status='failed'를 줘야 떠서 로컬 더미로는 재현이 어렵다.
Object.assign(components,{'plan-failed':p=><W.GenerationFailed kind="plan" onLeave={noop}/>,'artifact-failed':p=><W.GenerationFailed kind="artifact" onLeave={noop}/>});
const C=components[page];
createRoot(document.getElementById('root')).render(<><nav aria-label="화면 검토" style={{padding:10,background:'#fff',display:'flex',flexWrap:'wrap',gap:12,position:'relative',zIndex:100,fontSize:12}}>{names.map(n=><a key={n} href={'?page='+n}>{n}</a>)}</nav>{page==='landing'?<Landing onStart={noop}/>:<WorkspaceShell view={page==='empty'?'dashboard':page} notifyEnabled onToggleNotify={noop} onHome={noop} onDashboard={noop} onNewProject={noop} onLogout={noop}>{C?<C {...props}/>:<Dashboard onNewProject={noop} onOpenProject={noop} isNewUser={page==='empty'} onToggleNewUser={noop}/>}</WorkspaceShell>}</>);
