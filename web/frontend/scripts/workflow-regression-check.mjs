// Controlled request/lifecycle checks. All HTTP calls are mocked; no server data is changed.
import assert from 'node:assert/strict';
import React from 'react';
import {createServer} from 'vite';

const cache=new Map();
globalThis.localStorage={getItem:k=>cache.get(k)??null,setItem:(k,v)=>cache.set(k,v),removeItem:k=>cache.delete(k)};
globalThis.window={localStorage,scrollTo:()=>{},alert:()=>{},confirm:()=>true};
globalThis.document={title:'test',getElementById:()=>null};
const originalFetch=globalThis.fetch;
const server=await createServer({configFile:false,resolve:{preserveSymlinks:true},server:{middlewareMode:true},appType:'custom'});
const response=(data,status=200)=>({ok:status<400,status,text:async()=>JSON.stringify(data),json:async()=>data});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const internals=React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;

function mount(Component,props={}){
  const slots=[];let cursor=0,tree,dirty=true,effects=[];
  const memo=(fn,deps)=>{const i=cursor++;if(!slots[i]||deps.some((d,k)=>!Object.is(d,slots[i].deps[k])))slots[i]={deps,value:fn()};return slots[i].value};
  const dispatcher={
    useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:typeof initial==='function'?initial():initial};return [slots[i].value,v=>{slots[i].value=typeof v==='function'?v(slots[i].value):v;dirty=true}];},
    useRef(initial){const i=cursor++;return (slots[i]??={current:initial});},
    useEffect(fn,deps){const i=cursor++;const old=slots[i];if(!old||!deps||deps.some((d,k)=>!Object.is(d,old.deps[k]))){slots[i]={deps,cleanup:old?.cleanup};effects.push(()=>{slots[i].cleanup?.();slots[i].cleanup=fn()});}},
    useSyncExternalStore(subscribe,getSnapshot){const i=cursor++;if(!slots[i])slots[i]={cleanup:subscribe(()=>{dirty=true})};return getSnapshot();},
    useCallback(fn,deps){return memo(()=>fn,deps)},useMemo:memo,useDebugValue(){},
  };
  const render=()=>{cursor=0;dirty=false;const previous=internals.ReactCurrentDispatcher.current;internals.ReactCurrentDispatcher.current=dispatcher;try{tree=Component(props)}finally{internals.ReactCurrentDispatcher.current=previous}const pending=effects;effects=[];pending.forEach(fn=>fn());};
  const flush=async()=>{for(let i=0;i<8;i++){if(dirty)render();await tick();}};
  const nodes=()=>{const all=[];const visit=x=>{if(Array.isArray(x))x.forEach(visit);else if(x&&typeof x==='object'&&x.props){all.push(x);visit(x.props.children)}};visit(tree);return all;};
  const find=predicate=>{const node=nodes().find(predicate);assert.ok(node,'Expected control not found');return node};
  return {flush,nodes,find,component:name=>find(n=>n.type?.name===name),unmount:()=>slots.forEach(s=>s?.cleanup?.())};
}

try{
  const {IntakeForm}=await server.ssrLoadModule('/src/features/workflow/IntakeForm.jsx');
  const {MatchResults}=await server.ssrLoadModule('/src/features/workflow/MatchResults.jsx');
  const {default:GenerationProgress}=await server.ssrLoadModule('/src/features/workflow/GenerationProgress.jsx');
  const {default:App}=await server.ssrLoadModule('/src/App.jsx');
  const {PlanForm}=await server.ssrLoadModule('/src/features/workflow/PlanForm.jsx');
  const {useWorkflowStore:store}=await server.ssrLoadModule('/src/store/useWorkflowStore.js');
  const file=new Blob(['attachment']);
  const draft={applicantType:'individual',ceoName:'대표',birthDate:'1990-01-01',gender:'남성',foundedAt:'2024-01-01',companyName:'테스트상사',
    item:'아이디어 상세 설명',files:[file],team:[],noTeam:true,pricing:[{item:'서비스',price:'1000'}],region:{sido:'서울특별시',sigungu:'강남구'},
    industry:'정보·통신',careers:[{type:'경력',title:'개발',period:'2020-2024',hasProof:true}],skills:'개발 역량',certs:['벤처기업'],
    devPeriod:{start:'2026-10',end:'2026-12'},selfFunding:{available:true,cashLimit:'1000000',inKindResources:'보유 장비'},
    noHires:true,hires:[],noEquipment:true,equipment:[],noPartners:true,partners:[]};
  let submitted;
  let ui=mount(IntakeForm,{initialValues:draft,onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
  assert.equal(submitted.item,draft.item);assert.equal(submitted.files[0],file);assert.deepEqual(submitted.selfFunding,draft.selfFunding);
  assert.equal(submitted.noTeam,true);assert.equal(submitted.region.sigungu,'강남구');
  ui.component('Segmented').props.onChange('preliminary');await ui.flush();
  ui.component('Segmented').props.onChange('individual');await ui.flush();
  assert.equal(ui.find(n=>n.props.label==='설립일').props.value,'2024-01-01');
  ui.find(n=>n.props.label==='설립일').props.onChange('');await ui.flush();submitted=null;
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
  assert.ok(ui.find(n=>n.props.id==='intake-founded').props.error);ui.unmount();

  let completed=0;
  const confirmation=deferred();
  globalThis.fetch=()=>confirmation.promise;
  const candidate={notice_id:'notice-1',title:'공고',batch:1};
  ui=mount(MatchResults,{projectId:1,candidates:{candidates:[candidate]},onCheckEligibility:()=>completed++});await ui.flush();
  ui.component('CandidateGroup').props.onSelect('notice-1');await ui.flush();
  const confirming=ui.find(n=>n.type==='button'&&n.props.children==='신청 자격 확인하기').props.onClick();
  ui.unmount();confirmation.resolve(response({eligibility:{passed:true}}));await confirming;assert.equal(completed,0);

  let statusCalls=0;
  globalThis.fetch=async url=>{
    if(String(url).endsWith('/start'))return response({stage:'plan_writing',progress_percent:10});
    if(++statusCalls===1)throw new Error('simulated temporary disconnect');
    return response({stage:'plan_review_pending',progress_percent:100});
  };
  // 첫 상태 조회가 끊기면 바로 '연결이 잠시 끊겼어요' 안내 → 1.5초 뒤 다시 조회해 회복하고, 진행률이 끝까지 간다.
  ui=mount(GenerationProgress,{kind:'plan',projectId:1});await ui.flush();
  assert.ok(ui.nodes().some(n=>n.props.role==='alert'));
  await wait(1600);await ui.flush();await wait(1600);await ui.flush();assert.equal(ui.component('Preparation').props.progress,100);
  assert.ok(!ui.nodes().some(n=>n.props.role==='alert'));ui.unmount();

  let startCalls=0;
  globalThis.fetch=async()=>++startCalls===1?response({detail:'retry needed'},400):response({stage:'plan_review_pending',progress_percent:100});
  ui=mount(GenerationProgress,{kind:'plan',projectId:1});await ui.flush();
  ui.find(n=>n.type==='button'&&n.props.children==='다시 시도').props.onClick();await ui.flush();
  assert.equal(ui.component('Preparation').props.progress,100);ui.unmount();

  let createRequest;
  globalThis.fetch=async(url,options={})=>{
    const path=new URL(url).pathname;
    if(path==='/auth/me')return response({user_id:1,name:'Tester',role:'user',has_profile:true,notify_enabled:true});
    if(path==='/profile')return response([]);
    if(path==='/auth/logout')return response({});
    if(path==='/projects'&&options.method==='POST'){createRequest=deferred();return createRequest.promise;}
    if(path==='/projects/2')return response({description:'B project',company:{},team_members:[],pricing_items:[]});
    if(path==='/projects/2/result')return response({match:{fit_score:0},verdict:{overall_passed:true}});
    if(path==='/projects/2/status')return response({screen:11,stage:'done',match_status:'completed'});
    throw new Error('Unexpected request: '+path);
  };
  store.getState().resetProject();
  ui=mount(App);await ui.flush();ui.component('Landing').props.onStart();await ui.flush();
  ui.component('Dashboard').props.onNewProject();await ui.flush();
  let saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  assert.equal(ui.component('MatchProgress').props.ready,false);
  createRequest.resolve(response({detail:'simulated failure'},500));await saving;await ui.flush();
  assert.equal(ui.component('IntakeForm').props.initialValues.files[0],file);
  saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  ui.component('WorkspaceShell').props.onLogout();await ui.flush();
  createRequest.resolve(response({project_id:99}));await saving;await ui.flush();
  assert.equal(store.getState().projectId,null);assert.equal(store.getState().itemInfo,null);
  assert.ok(ui.component('Landing'));ui.unmount();

  ui=mount(App);await ui.flush();ui.component('Landing').props.onStart();await ui.flush();
  ui.component('Dashboard').props.onNewProject();await ui.flush();
  saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  ui.component('WorkspaceShell').props.onDashboard();await ui.flush();
  await ui.component('Dashboard').props.onOpenProject({id:2,matched:true,announcementTitle:'B notice'});await ui.flush();
  assert.ok(ui.component('ReviewScreen'));
  createRequest.resolve(response({project_id:99}));await saving;await ui.flush();
  assert.equal(store.getState().projectId,2);assert.equal(store.getState().itemInfo.item,'B project');ui.unmount();
  // A delayed profile refresh must not log the user back in after logout.
  ui=mount(App);await ui.flush();ui.component('Landing').props.onMyPage();await ui.flush();
  const refresh=deferred();const appFetch=globalThis.fetch;
  globalThis.fetch=(url,options)=>String(url).endsWith('/auth/me')?refresh.promise:appFetch(url,options);
  const refreshing=ui.component('MyPage').props.onSaved();
  ui.component('WorkspaceShell').props.onLogout();await ui.flush();
  refresh.resolve(response({user_id:1,name:'Old session',has_profile:true}));await refreshing;await ui.flush();
  assert.equal(ui.component('Landing').props.user,null);ui.unmount();

  // The server's resume screen (GET /status screen) must select the correct view.
  for(const [stage,screenNo,screen] of [['artifact_review',8,'ArtifactResult'],['final_review_pending',9,'FinalVerdict']]){
    globalThis.fetch=(url,options)=>String(url).endsWith('/projects/2/status')?Promise.resolve(response({screen:screenNo,stage,match_status:'user_waiting'})):appFetch(url,options);
    ui=mount(App);await ui.flush();ui.component('Landing').props.onStart();await ui.flush();
    await ui.component('Dashboard').props.onOpenProject({id:2,matched:true});await ui.flush();
    assert.ok(ui.component(screen));ui.unmount();
  }

  // A polling error must not permanently lock the prototype button; failed jobs also unlock it.
  let planPolls=0;
  globalThis.fetch=async()=>{
    planPolls++;
    if(planPolls===2)throw new Error('simulated plan status disconnect');
    return response({stage:'prototype_building',match_status:planPolls>=3?'failed':'processing'});
  };
  ui=mount(PlanForm,{projectId:2});await ui.flush();
  assert.equal(ui.find(n=>n.type==='button'&&n.props.children==='프로토타입 생성 중…').props.disabled,true);
  await wait(2100);await ui.flush();await wait(2100);await ui.flush();
  assert.equal(ui.find(n=>n.type==='button'&&n.props.children==='프로토타입 생성').props.disabled,false);ui.unmount();

  // Rewriting a plan and generating its prototype must not run concurrently.
  const rewrite=deferred();let generated=0;
  globalThis.fetch=(url)=>String(url).endsWith('/retry-task')?rewrite.promise
    :String(url).endsWith('/rework-result')?Promise.resolve(response({cycle_id:'C1',status:'완료',screen:6,bundles:['문제인식'],changed:{}}))
    :Promise.resolve(response({stage:'plan_review_pending'}));
  ui=mount(PlanForm,{projectId:2,onGenerate:()=>generated++});await ui.flush();
  ui.find(n=>n.type==='button'&&n.props.children==='프로토타입 생성').props.onClick();await ui.flush();
  ui.find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange();await ui.flush();
  const rewriting=ui.find(n=>n.type==='button'&&n.props.children==='선택 항목 재작성').props.onClick();await ui.flush();
  assert.equal(ui.find(n=>n.type==='button'&&n.props.children==='프로토타입 생성').props.disabled,true);
  const proceed=ui.find(n=>n.type==='button'&&n.props.children==='그래도 진행하기');
  assert.equal(proceed.props.disabled,true);proceed.props.onClick();assert.equal(generated,0);
  rewrite.resolve(response({cycle_id:'C1',screen:6,bundles:['문제인식'],collect_until:'2026-10-06T00:00:02Z'}));await rewriting;await ui.flush();
  assert.equal(ui.find(n=>n.type==='button'&&n.props.children==='프로토타입 생성').props.disabled,false);ui.unmount();

  // ── 오케스트레이터 연동 흐름(2026-10-06) ─────────────────────────────────────────────
  const flat=t=>{const o=[];const v=x=>{if(typeof x==='string'||typeof x==='number')o.push(String(x));else if(Array.isArray(x))x.forEach(v);else if(x&&x.props)v(x.props.children)};v(t);return o.join('')};
  const route=handlers=>async(url,opt={})=>{const key=(opt.method||'GET')+' '+new URL(url).pathname+new URL(url).search;
    for(const [prefix,fn] of handlers)if(key.startsWith(prefix))return fn(opt,key);
    return response({detail:'not mocked: '+key},404);};
  const alerts=[];window.alert=m=>alerts.push(m);

  // 이어하기 — 서버 복귀 화면 번호(GET /status의 screen) → 화면
  const appSource=(await import('node:fs')).readFileSync(new URL('../src/App.jsx',import.meta.url),'utf8');
  const resumeViewOf=new Function(appSource.slice(appSource.indexOf('const VIEW_BY_SCREEN'),appSource.indexOf('\n}\n',appSource.indexOf('function resumeViewOf'))+3)+';return resumeViewOf;')();
  for(const [status,view] of [
    [{screen:3},'match-results'],
    [{screen:3,stage:null,match_status:'user_waiting'},'match-results'],
    [{screen:5,stage:'plan_writing',match_status:'user_waiting'},'eligibility-gate'],
    [{screen:5,stage:'plan_writing',match_status:'in_progress'},'plan-progress'],
    [{screen:5,stage:'plan_writing',match_status:'failed'},'plan-progress'],
    [{screen:7,stage:'prototype_building',match_status:'failed'},'artifact-progress'],
    [{screen:9,stage:'final_review_pending',match_status:'user_waiting'},'final-verdict'],
    [{screen:10,stage:'reviewing',match_status:'in_progress'},'review-progress'],
    [{screen:10,stage:'reviewing',match_status:'failed'},'review-progress'],
    [{screen:11,stage:'done',match_status:'completed'},'review'],
  ])assert.equal(resumeViewOf(status),view,JSON.stringify(status));

  // 공고 후보 — 막힌 공고는 서버 ID 목록으로, 후보 조회 pending이면 다시 부른다
  const cand={status:'ready',rematch_used:false,blocked_notice_ids:['N-2'],notices:[],
    candidates:[{notice_id:'N-1',title:'공고1',batch:1},{notice_id:'N-2',title:'공고2',batch:1}]};
  let candidateCalls=0,loaded=null;
  globalThis.fetch=route([['GET /projects/1/match-candidates',()=>response(++candidateCalls<2?{status:'pending',candidates:[],rematch_used:false}:cand)]]);
  ui=mount(MatchResults,{projectId:1,candidates:null,onCandidatesLoaded:v=>{loaded=v},onCheckEligibility(){}});await ui.flush();
  await wait(1700);await ui.flush();assert.equal(candidateCalls,2);assert.equal(loaded.status,'ready');ui.unmount();
  ui=mount(MatchResults,{projectId:1,candidates:cand,onCandidatesLoaded(){},onCheckEligibility(){}});await ui.flush();
  assert.deepEqual(ui.component('CandidateGroup').props.blockedIds,['N-2']);ui.unmount();

  // 자격 확인 — pending이면 방금 고른 공고 ID로 GET /eligibility, 이전 공고 결과가 오면 화면 4로 가지 않는다
  const pickAndConfirm=async(props)=>{ui=mount(MatchResults,props);await ui.flush();
    ui.component('CandidateGroup').props.onSelect('N-1');await ui.flush();
    await ui.find(n=>n.type==='button'&&n.props.children==='신청 자격 확인하기').props.onClick();await ui.flush();};
  let eligibilityPaths=[],checked=null;
  globalThis.fetch=route([
    ['POST /projects/1/generate',()=>response({status:'pending'})],
    ['GET /projects/1/eligibility',(opt,key)=>{eligibilityPaths.push(key);return response({status:'ready',match:{notice_id:'N-1'},eligibility:{passed:true}})}],
  ]);
  await pickAndConfirm({projectId:1,candidates:cand,onCandidatesLoaded(){},onCheckEligibility:(c,r)=>{checked=[c,r]}});
  assert.equal(checked[0].notice_id,'N-1');assert.equal(checked[1].status,'ready');
  assert.deepEqual(eligibilityPaths,['GET /projects/1/eligibility?notice_id=N-1']);ui.unmount();
  checked=null;
  globalThis.fetch=route([
    ['POST /projects/1/generate',()=>response({status:'pending'})],
    ['GET /projects/1/eligibility?notice_id=N-1',()=>response({status:'ready',match:{notice_id:'N-9'},eligibility:{passed:true}})],
    ['GET /projects/1/status',()=>response({screen:5,match_status:'user_waiting'})],
  ]);
  await pickAndConfirm({projectId:1,candidates:cand,onCandidatesLoaded(){},onCheckEligibility:(c,r)=>{checked=[c,r]}});
  assert.equal(checked,null);assert.ok(ui.find(n=>n.type==='button'&&n.props.children==='이전에 확인한 공고로 계속하기'));ui.unmount();
  // 409(막힌 공고 등)면 안내 후 후보를 다시 받는다
  let reloaded=false;
  globalThis.fetch=async()=>response({detail:'신청 자격에 맞지 않는 공고예요. 다른 공고를 선택해 주세요.',code:'ANNOUNCEMENT_BLOCKED'},409);
  await pickAndConfirm({projectId:1,candidates:cand,onCandidatesLoaded:v=>{if(v===null)reloaded=true},onCheckEligibility(){}});
  assert.ok(reloaded);ui.unmount();

  // 자격 확인 화면 — 확인 필요 조건 · 업력 · can_start_writing
  const {EligibilityGate}=await server.ssrLoadModule('/src/features/workflow/EligibilityGate.jsx');
  const gate=(eligibility)=>flat(EligibilityGate({announcement:{title:'공고'},eligibility,notices:[],onProceed(){},onLeave(){}}));
  let gateText=gate({passed:true,unknown_conditions:['업력'],business_age_years:2.5,can_start_writing:true});
  assert.ok(gateText.includes('공고문을 직접 확인해 주세요')&&gateText.includes('업력 2.5년')&&gateText.includes('사업계획서 작성하기'),gateText);
  assert.ok(gate({passed:true,can_start_writing:false}).includes('다른 공고 다시 보기'));
  assert.ok(gate({passed:false,failed_conditions:[],missing_inputs:['foundedAt']}).includes('설립일'));

  // 화면 8 → 9 — final-review/start, 실패한 실행(200 + failed)이면 넘어가지 않는다
  const {ArtifactResult}=await server.ssrLoadModule('/src/features/workflow/ArtifactResult.jsx');
  const artifactBase={announcement:{title:'공고'},itemInfo:{item:'웹 서비스'},projectId:7,reworkCounts:{}};
  for(const [matchStatus,expected] of [['user_waiting',1],['failed',0]]){
    let finalized=0;
    globalThis.fetch=route([['POST /projects/7/final-review/start',()=>response({stage:'final_review_pending',match_status:matchStatus})],['GET /projects/7/status',()=>response({stage:'artifact_review'})]]);
    ui=mount(ArtifactResult,{...artifactBase,onFinalize:()=>{finalized++}});await ui.flush();
    await ui.find(n=>n.type==='button'&&String(n.props.children).includes('종합 평가 확인하기')).props.onClick();await ui.flush();
    assert.equal(finalized,expected,matchStatus);ui.unmount();
  }

  // 화면 9 → 10 — review/start, 미달이면 서버 409 확인 내용 → confirmed=true, 끝날 때까지 상태 확인
  const {FinalVerdict}=await server.ssrLoadModule('/src/features/workflow/FinalVerdict.jsx');
  const verdictBase={announcement:{title:'공고'},itemInfo:{item:'웹 서비스'},projectId:7,docOutcome:'fail',artifactOutcome:'fail',setDocOutcome(){},setArtifactOutcome(){},onRework(){},onScoresRefresh:async()=>{}};
  let reviewBodies=[],proceeded=0,statusPolls=0;
  globalThis.fetch=route([
    ['POST /projects/7/review/start',opt=>{reviewBodies.push(opt.body);return reviewBodies.length===1
      ?response({detail:{confirmation_required:true,reason:'검수 진입 확인',items:{'현재 점수':72,'기준':80,'남는 미달 항목':['문제 근거 부족']}},code:'CONFIRMATION_REQUIRED'},409)
      :response({stage:'reviewing',match_status:'in_progress',progress_percent:10})}],
    ['GET /projects/7/status',()=>response(++statusPolls<2?{stage:'reviewing',match_status:'in_progress'}:{stage:'done',match_status:'completed'})],
  ]);
  ui=mount(FinalVerdict,{...verdictBase,scores:{total:72,threshold:80},onProceed:async()=>{proceeded++}});await ui.flush();
  await ui.find(n=>n.type==='button'&&n.props.children==='이대로 진행하기').props.onClick();await ui.flush();
  assert.ok(flat(ui.nodes()[0]).includes('문제 근거 부족'));
  await ui.find(n=>n.type==='button'&&n.props.children==='그래도 진행하기').props.onClick();
  assert.deepEqual(reviewBodies,['{"confirmed":false}','{"confirmed":true}']);assert.equal(proceeded,1);ui.unmount();

  // 재작성(화면 6) — 실패면 되돌림 안내 · 횟수 안 셈, 화면을 다시 열면 /status rework_screen으로 진행 중을 이어 본다
  let reworked=null,reworkReads=0;
  globalThis.fetch=route([
    ['POST /projects/2/retry-task',()=>response({cycle_id:'C2',screen:6,bundles:['문제인식'],collect_until:'2026-10-06T00:00:02Z'})],
    ['GET /projects/2/rework-result',()=>response({cycle_id:'C2',status:'실패',screen:6,bundles:['문제인식'],rolled_back:true})],
    ['GET /projects/2/status',()=>response({stage:'plan_review_pending',rework_screen:null})],
  ]);
  ui=mount(PlanForm,{projectId:2,onRework:p=>{reworked=p}});await ui.flush();
  ui.find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange();await ui.flush();
  alerts.length=0;await ui.find(n=>n.type==='button'&&n.props.children==='선택 항목 재작성').props.onClick();await ui.flush();
  assert.equal(reworked,null);assert.ok(alerts.some(m=>m.includes('이전 결과로 되돌렸습니다')),alerts.join());ui.unmount();
  globalThis.fetch=route([
    ['GET /projects/2/status',()=>response({stage:'plan_review_pending',rework_screen:6,collecting:false})],
    ['GET /projects/2/rework-result',()=>response(++reworkReads<2?{cycle_id:'C3',status:'진행중',screen:6,bundles:['성장전략']}:{cycle_id:'C3',status:'완료',screen:6,bundles:['성장전략'],changed:{}})],
  ]);
  reworked=null;ui=mount(PlanForm,{projectId:2,onRework:p=>{reworked=p}});await ui.flush();await wait(2200);await ui.flush();
  assert.deepEqual(reworked,['성장전략']);ui.unmount();

  // 검수 진행 화면 — 시작 API 없이 상태만, 재개 대기면 다음 시도 시각(한국 시간), 끝나면 100%
  let reviewCalls=[],reviewPolls=0;
  globalThis.fetch=async(url,opt={})=>{reviewCalls.push(opt.method||'GET');
    return response(++reviewPolls<2?{stage:'reviewing',match_status:'waiting_resume',resume_count:1,next_retry_at:'2026-10-06T06:15:00Z'}:{stage:'done',match_status:'completed'})};
  ui=mount(GenerationProgress,{kind:'review',projectId:3});await ui.flush();
  assert.ok(flat(ui.nodes().find(n=>n.props.role==='status')).includes('오후 3:15에 자동으로 다시 시도해요 (1/5)'));
  await wait(1600);await ui.flush();assert.equal(ui.component('Preparation').props.progress,100);
  assert.ok(reviewCalls.every(m=>m==='GET'));ui.unmount();

  console.log('PASS: orchestrator flows — resume screen map, candidates pending · blocked ids, eligibility pending · stale result · 409, gate fields, screen 8 · 9 proceed, rework rollback · resume, review progress');
  console.log('PASS: intake restoration, stale responses, final-stage lock, polling recovery, profile logout race, resume-screen routing, rewrite/generation exclusion');
}finally{globalThis.fetch=originalFetch;await server.close()}
