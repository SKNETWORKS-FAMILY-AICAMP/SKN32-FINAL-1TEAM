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
  const draft={applicantType:'individual',ceoName:'대표',birthDate:'1990-01-01',gender:'남성',foundedAt:'2024-01-01',companyName:'테스트상사',
    item:'아이디어 상세 설명',targetCustomer:'  동네 헬스장 운영자  ',team:[],noTeam:true,pricing:[{item:'서비스',price:'1000'}],region:{sido:'서울특별시',sigungu:'강남구'},
    industry:'정보·통신',careers:[{type:'경력',title:'개발',period:'2020-2024',hasProof:true}],skills:'개발 역량',certs:['벤처기업'],
    devPeriod:{start:'2026-10',end:'2026-12'},selfFunding:{available:true,cashLimit:'1000000',inKindResources:'보유 장비'},
    noHires:true,hires:[],noEquipment:true,equipment:[],noPartners:true,partners:[],
    budget:[{phase:'',category:'재료비',plan:'부품 구입',gov:'1000000',cash:'200000',inKind:'0'}],
    schedule:{feasibility:[{category:'개발',content:'시제품',period:'2026.10 ~ 2026.12',detail:'첫 버전'}],growth:[]}};
  let submitted;
  let ui=mount(IntakeForm,{initialValues:draft,onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
  assert.equal(submitted.item,draft.item);assert.equal(submitted.targetCustomer,'동네 헬스장 운영자');assert.equal(submitted.files,undefined);assert.deepEqual(submitted.selfFunding,draft.selfFunding);
  assert.equal(submitted.noTeam,true);assert.equal(submitted.region.sigungu,'강남구');
  assert.deepEqual(submitted.budget,draft.budget);assert.deepEqual(Object.keys(submitted.schedule),['feasibility','growth']);
  ui.component('Segmented').props.onChange('preliminary');await ui.flush();
  ui.component('Segmented').props.onChange('individual');await ui.flush();
  assert.equal(ui.find(n=>n.props.label==='설립일').props.value,'2024-01-01');
  ui.find(n=>n.props.label==='설립일').props.onChange('');await ui.flush();submitted=null;
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
  assert.ok(ui.find(n=>n.props.id==='intake-founded').props.error);ui.unmount();
  // 협약기간 내 일정이 개발 기간 끝을 넘으면 막는다(조율 10-12 4번) — 끝나는 달은 검증-1과 같은 규칙으로 읽는다. 협약 이후 일정은 보지 않는다.
  const {periodEndMonth:pem,schedulePastDevEnd:spd}=await server.ssrLoadModule('/src/features/workflow/ProjectPlanFields.jsx');
  assert.equal(pem('2026.11 ~ 2027.02'),'2027-02');assert.equal(pem('2026년 11월 ~ 2027년 2월'),'2027-02');assert.equal(pem('2027-3'),'2027-03');assert.equal(pem('11월 ~ 1월'),null);
  assert.deepEqual(spd({feasibility:[{category:'개발',period:'2026.11 ~ 2027.02'},{category:'',period:'2027.05 ~ 2027.08'}],growth:[{period:'2028.01 ~ 2028.12'}]},'2027-06'),[{no:2,category:'',end:'2027-08'}]);
  assert.deepEqual(spd({feasibility:[{period:'2027.05 ~ 2027.08'}]},''),[]);
  submitted=null;ui=mount(IntakeForm,{initialValues:{...draft,devPeriod:{start:'2026-10',end:'2026-11'}},onSubmit:info=>{submitted=info}});await ui.flush();
  assert.ok(ui.nodes().some(n=>n.type==='p'&&[].concat(n.props.children).join('').includes('개발 기간 끝')));
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
  assert.ok(ui.find(n=>n.props.id==='intake-schedule').props.error);ui.unmount();
  // 협약기간 최대 개월 수(예비창업자 8 · 사업자 10, 조율 10-13) — 검증-1과 같은 셈: 협약기간 내 일정만, 월 1 ~ 12만, 첫 달 · 끝 달 모두 센다.
  const {scheduleSpan:ssp,agreementMaxMonths:amm}=await server.ssrLoadModule('/src/features/workflow/ProjectPlanFields.jsx');
  assert.deepEqual(ssp({feasibility:[{period:'2026.03 ~ 2026.05'},{period:'2026년 9월 ~ 2026년 10월'}],growth:[{period:'2028.01 ~ 2028.12'}]}),{start:'2026-03',end:'2026-10',months:8});
  assert.deepEqual(ssp({feasibility:[{period:'2026.11 ~ 2027.02'}]}),{start:'2026-11',end:'2027-02',months:4});
  assert.deepEqual(ssp({feasibility:[{period:'2026.13 ~ 2026.05'}]}),{start:'2026-05',end:'2026-05',months:1}); // 13월은 버린다
  assert.equal(ssp({feasibility:[{period:'11월 ~ 1월'}]}),null);assert.equal(ssp({feasibility:[]}),null);
  assert.deepEqual([amm(true),amm(false)],[8,10]);
  const longPlan={...draft,devPeriod:{start:'2026-01',end:'2026-12'},schedule:{feasibility:[{category:'개발',content:'시제품',period:'2026.01 ~ 2026.11',detail:''}],growth:[]}};
  submitted=null;ui=mount(IntakeForm,{initialValues:longPlan,onSubmit:info=>{submitted=info}});await ui.flush();
  assert.ok(ui.nodes().some(n=>n.type==='p'&&[].concat(n.props.children).join('').includes('11개월이에요')));
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
  assert.ok(ui.find(n=>n.props.id==='intake-schedule').props.error);ui.unmount();
  submitted=null;ui=mount(IntakeForm,{initialValues:{...longPlan,schedule:{feasibility:[{category:'개발',content:'시제품',period:'2026.01 ~ 2026.10',detail:''}],growth:[]}},onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.ok(submitted);ui.unmount(); // 사업자 10개월은 통과
  // 자기부담 한도(위 칸)와 사업비 집행 계획의 자기부담 금액(아래 표)이 어긋나면 안내만 — 막지 않는다.
  const {selfFundingMismatch:sfm}=await server.ssrLoadModule('/src/features/workflow/ProjectPlanFields.jsx');
  const rowsOf=(...cash)=>cash.map(c=>({cash:String(c),inKind:'0'}));
  assert.equal(sfm({available:true,cashLimit:'1000000'},rowsOf(400000,600000)),null);
  assert.ok(sfm({available:true,cashLimit:'1000000'},rowsOf(800000,600000)).includes('1,400,000원'));
  assert.equal(sfm({available:true,cashLimit:''},rowsOf(800000)),null);
  assert.ok(sfm({available:false},[{cash:'0',inKind:'300000'}]).includes('300,000원'));
  assert.equal(sfm({available:false},rowsOf(0)),null);
  assert.equal(sfm({available:null},rowsOf(5)),null);
  submitted=null;ui=mount(IntakeForm,{initialValues:{...draft,selfFunding:{available:true,cashLimit:'100000',inKindResources:''}},onSubmit:info=>{submitted=info}});await ui.flush();
  assert.ok(ui.nodes().some(n=>n.props?.role==='status'&&String(n.props.children).includes('현금 한도')));
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.ok(submitted);ui.unmount();
  // 화면 순서(① 아이디어 → ② 신청자 정보 → ③ 사업 계획, 디자인 점검 10-12) — 빈 칸 검사도 아이디어부터, 입력 현황은 묶음 셋.
  submitted=null;ui=mount(IntakeForm,{onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();
  assert.equal(submitted,null);assert.ok(ui.find(n=>n.props.id==='intake-idea').props.error);
  assert.deepEqual(ui.component('IntakeChecklist').props.groups.map(g=>g.title),['① 아이디어','② 신청자 정보','③ 사업 계획']);ui.unmount();
  // 프로필을 불러오면 신청자 정보는 요약으로 접히고(값은 그대로 들고 간다), 빈 필수 칸이 있으면 접지 않는다.
  const loadedProfile={name:'내 프로필',basic:{applicantType:'individual',ceoName:'대표',birthDate:'1990-01-01',gender:'남성',region:{sido:'서울특별시',sigungu:'강남구'},
    industry:'정보·통신',certs:['벤처기업'],bizNo:'1234567890',companyName:'테스트상사',openedAt:'2024-01-01'},
    capability:{careers:[{type:'경력',title:'개발',period:'2020-01 ~ 2024-01',hasProof:true}],skills:'개발 역량',soloFounder:true,team:[]}};
  ui=mount(IntakeForm,{onSubmit(){}});await ui.flush();
  ui.component('LoadProfileModal').props.onPick(loadedProfile);await ui.flush();
  assert.ok(ui.component('ApplicantSummary'));assert.ok(!ui.nodes().some(n=>n.props?.id==='intake-ceo'));
  assert.ok(ui.component('ApplicantSummary').props.rows.some(([label,value])=>label==='사업자'&&value.includes('1234567890')));
  ui.component('ApplicantSummary').props.onEdit();await ui.flush();
  assert.ok(ui.find(n=>n.props.id==='intake-ceo'));assert.ok(!ui.nodes().some(n=>n.type?.name==='ApplicantSummary'));ui.unmount();
  ui=mount(IntakeForm,{onSubmit(){}});await ui.flush();
  ui.component('LoadProfileModal').props.onPick({...loadedProfile,capability:{...loadedProfile.capability,careers:[]}});await ui.flush();
  assert.ok(!ui.nodes().some(n=>n.type?.name==='ApplicantSummary'));assert.ok(ui.find(n=>n.props.id==='intake-career'));ui.unmount();
  // 예비창업자는 사업비 1 · 2단계가 각 1줄 이상, 일정은 협약기간 내 표가 1줄 이상이어야 넘어간다.
  const preDraft={...draft,applicantType:'preliminary',budgetScale:'1500',budget:[{...draft.budget[0],phase:'1단계'}]};
  submitted=null;ui=mount(IntakeForm,{initialValues:preDraft,onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
  assert.ok(ui.find(n=>n.props.id==='intake-budget').props.error);ui.unmount();
  const preRow={category:'출시',content:'베타 운영',period:'2026.12',detail:'첫 고객 10명'};
  ui=mount(IntakeForm,{initialValues:{...preDraft,budget:[...preDraft.budget,{...draft.budget[0],phase:'2단계'}],schedule:{feasibility:[preRow]}},onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();
  assert.deepEqual(submitted.budget.map(b=>b.phase),['1단계','2단계']);assert.deepEqual(submitted.schedule,{feasibility:[preRow],growth:[]});ui.unmount();
  // 예비창업자는 현물 칸이 없어 앞서 적은 현물이 있어도 0으로 보낸다. 세부 내용은 비워도 된다.
  submitted=null;ui=mount(IntakeForm,{initialValues:{...preDraft,budget:[{...preDraft.budget[0],inKind:'500'},{...draft.budget[0],phase:'2단계'}],schedule:{feasibility:[{...preRow,detail:''}]}},onSubmit:info=>{submitted=info}});await ui.flush();
  ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();
  assert.deepEqual(submitted.budget.map(b=>b.inKind),['0','0']);
  ui.unmount();
  const {budgetAmountFields}=await server.ssrLoadModule('/src/features/workflow/ProjectPlanFields.jsx');
  assert.deepEqual(budgetAmountFields(true).map(f=>f[1]),['정부지원사업비','자기부담금']);
  assert.deepEqual(budgetAmountFields(false).map(f=>f[1]),['정부지원사업비','자기부담 현금','자기부담 현물']);
  // 생성된 HTML은 외부 요청을 막는 CSP를 head 맨 앞에 넣어 연다(head가 없으면 html 뒤, 그것도 없으면 맨 앞).
  const {isolateHtml,SANDBOX_CSP}=await server.ssrLoadModule('/src/features/workflow/ArtifactResult.jsx');
  const csp=`<meta http-equiv="Content-Security-Policy" content="${SANDBOX_CSP}">`;
  assert.equal(isolateHtml('<!doctype html><html lang="ko"><head><script src="https://cdn.x/a.js"></script></head></html>'),
    `<!doctype html><html lang="ko"><head>${csp}<script src="https://cdn.x/a.js"></script></head></html>`);
  assert.equal(isolateHtml('<html><body>x</body></html>'),`<html>${csp}<body>x</body></html>`);
  assert.equal(isolateHtml('<div>x</div>'),`${csp}<div>x</div>`);
  assert.ok(SANDBOX_CSP.includes("default-src 'none'")&&SANDBOX_CSP.includes("connect-src 'none'"));
  // 해당 없음 · 실행 건 환산 만점(백엔드 응답모양변경 10-11 1-2) — 새 칸이 없으면 예전처럼 두 칸을 더한다.
  const {scoresFromResult:sfr}=await server.ssrLoadModule('/src/features/workflow/utils.js');
  const scored=sfr({verdict:{doc_score:50,doc_max_score:60,code_score:8,code_max_score:20,plan_match_score:10,plan_match_max_score:20,artifact_score:18,artifact_max_score:40,total_score:68},
    plan:{score_reasons:[],artifacts:[{score_reasons:[{item_code:'CHECK-HTML-WIRING',score:2,max_score:3},{item_code:'CHECK-HTML-INPUT-LABEL',score:0,max_score:0,applicable:false,reason_text:'해당 없음 — 입력칸 없음'}]}]}});
  assert.deepEqual(scored.artifactLayer,{raw:18,max:40});
  assert.deepEqual(scored.codeCheckItems.map(i=>[i.passed,i.applicable]),[[false,true],[true,false]]);
  assert.equal(sfr({verdict:{code_score:8,code_max_score:15},plan:{score_reasons:[],artifacts:[]}}).artifactLayer,null);
  // 점수 항목 묶음(응답모양변경 10-11 2-1) — tag로 일반현황 · 개요 + 4묶음에 모으고, 이름은 section_code로 찾는다.
  const {taskReasons:tr,bundleScoreOf:bso,planViewFrom:pvf,deliverableNoticesFrom:dnf,prototypeFilesOf:pfo,shortfallFrom:sff}=await server.ssrLoadModule('/src/features/workflow/utils.js');
  // 결과물 화면 미달 항목(deliverable.shortfall_items) — 층별로 나누고 받은 순서 그대로, 계획서 줄은 태그로 묶음 이름, 점수는 소수 한 자리, 없으면 null.
  assert.equal(sff(null),null);assert.equal(sff({shortfall_items:[]}),null);assert.equal(sff({}),null);
  const sf=sff({shortfall_items:[
    {layer:'document',kind:'verifyFail',code:'2.4.1',tag:'1-1',name:'문제 정의',score:1.2,max_score:2.9166666666666665,reason:'근거 부족'},
    {layer:'artifact',kind:'gateFailure',code:'entry',tag:null,name:'진입 파일',score:null,max_score:null,reason:'실행할 진입 파일이 없어 산출물층이 0점입니다.'},
    {layer:'document',kind:'inputError',code:'2.6.2',tag:null,name:'일정',score:0.01,max_score:2.9,reason:'협약기간 초과'},
    {layer:'artifact',kind:'codeCheck',code:'4',tag:null,name:'버튼',score:1.25,max_score:1.875,reason:'부분 점수'}]});
  assert.deepEqual(sf.document.map(r=>[r.bundle,r.name,r.points,r.inputError]),[['문제인식','문제 정의','1.2/2.9점',false],['일반현황 · 개요','일정','0/2.9점',true]]);
  assert.deepEqual(sf.artifact.map(r=>[r.bundle,r.name,r.points]),[[null,'진입 파일',null],[null,'버튼','1.3/1.9점']]);
  assert.equal(sff({shortfall_items:[{layer:'artifact',kind:'codeCheck',code:'4',name:'버튼',score:1.25,max_score:1.875,reason:'1.25/1.88점 — 연결 안 된 버튼'}]}).artifact[0].reason,'연결 안 된 버튼'); // 사유 앞 점수는 뗀다
  // 결과물 화면 '프로토타입' 받기 — 결과의 실행 파일 · 인포그래픽 주소에서 실제 파일 이름을 뽑고, 같은 파일은 한 번만(원페이지형).
  assert.deepEqual(pfo({artifacts:[{executable_path:'/projects/1/artifact-files/r/e/a1/index.html',infographic_path:'/projects/1/artifact-files/r/e/b2/infographic.svg'}]}).map(f=>f.name),['index.html','infographic.svg']);
  assert.deepEqual(pfo({artifacts:[{executable_path:'/p/onepage.svg',infographic_path:'/p/onepage.svg'}]}),[{path:'/p/onepage.svg',name:'onepage.svg'}]);
  assert.deepEqual(pfo({artifacts:[]}),[]);assert.deepEqual(pfo(null),[]);
  // 결과물 화면 고지 — 서버 deliverable(SB-371)의 제출 안내 · 계획서 고지가 있으면 그 문구, 없거나 비면 고정 문구.
  const fixedNotices=dnf(null);
  assert.deepEqual(fixedNotices.map(n=>n.label),['계획서','프로토타입','검증 결과','제출 안내']);
  assert.deepEqual(dnf({submission_notice:null,disclaimer:'  ',user_message:'x'}),fixedNotices);
  const served=dnf({submission_notice:'예비창업패키지는 AI 작성 사실을 밝혀야 합니다.',disclaimer:'AI 초안입니다.',user_message:null});
  assert.deepEqual(served.map(n=>n.text),['AI 초안입니다.',fixedNotices[1].text,fixedNotices[2].text,'예비창업패키지는 AI 작성 사실을 밝혀야 합니다.']);
  const tagged=sfr({verdict:{doc_score:20,doc_max_score:30},plan:{sections:[{section_code:'1.2',tag:null,title:'개요',content_type:'section'},{section_code:'2.4.1',tag:'1-1',title:'문제 정의',content_type:'section'},{section_code:'2.4.2',tag:'1-1',title:'시장',content_type:'section'}],
    score_reasons:[{item_code:'1.2',tag:null,score:4,max_score:5,reason_text:'짧음'},{item_code:'2.4.1',tag:'1-1',score:6,max_score:10,reason_text:'근거 부족'},{item_code:'2.4.2',tag:'1-1',score:5,max_score:5},{item_code:'3.1.1',tag:'3-1',score:5,max_score:10,reason_text:'모호'}],artifacts:[]}});
  assert.deepEqual(tagged.docScore.groups.map(g=>[g.label,g.score,g.max]),[['일반현황 · 개요',4,5],['문제인식',11,15],['성장전략',5,10]]);
  assert.equal(tagged.docScore.items[1].name,'문제 정의');
  assert.deepEqual(tagged.docScore.reasons,['일반현황 · 개요 4/5 — 개요','문제인식 11/15 — 문제 정의','성장전략 5/10 — 3.1.1']);
  const noArtifact={autoCheck:{reasons:[]},crossCheck:{reasons:[]}};
  assert.deepEqual(tr('문제인식',tagged.docScore,noArtifact),['문제 정의 — 근거 부족']);
  assert.deepEqual(bso('문제인식',tagged.docScore),{score:11,max:15,passed:false,lines:['문제 정의 — 근거 부족'],summary:'문제 정의'});
  assert.equal(bso('실현가능성',tagged.docScore),null);
  assert.deepEqual(tr('실현가능성',tagged.docScore,noArtifact),[]);
  // 옛 모양(tag 칸 없음, PSST-1-1)은 묶음 없이 예전처럼 항목별.
  const legacy=sfr({verdict:{doc_score:10},plan:{sections:[{tag:'1-1',title:'문제 인식'}],score_reasons:[{item_code:'PSST-1-1',score:10,max_score:20,reason_text:'부족'}],artifacts:[]}});
  assert.equal(legacy.docScore.groups,null);
  assert.deepEqual(legacy.docScore.reasons,['문제 인식 10/20 — 부족']);
  assert.deepEqual(tr('문제인식',legacy.docScore,noArtifact),['부족']);
  assert.deepEqual(bso('문제인식',legacy.docScore),{score:10,max:20,passed:false,lines:['부족'],summary:'부족'});
  // 묶음 통과는 전체 통과 기준과 같은 비율 — 항목마다 조금씩 깎여도(2.4/2.8 → 86%) 기준 80이면 통과, 깎인 항목 이름은 그대로.
  const nearFull=(threshold)=>sfr({verdict:null,plan:{doc_score:12,doc_max_score:14,threshold,sections:[],score_reasons:[1,2,3,4,5].map(i=>({item_code:`2.4.${i}`,tag:'1-1',score:2.4,max_score:2.8,reason_text:'감점'}))}});
  const near80=bso('문제인식',nearFull(80).docScore);
  assert.deepEqual([near80.passed,near80.summary],[true,'2.4.1, 2.4.2, 2.4.3 외 2개']);
  assert.equal(bso('문제인식',nearFull(90).docScore).passed,false);
  assert.equal(bso('문제인식',{groups:[{label:'문제인식',score:12,max:15,items:[{name:'a',score:12,max:15}]}]}).passed,true); // 기준이 없으면 80%, 경계는 통과
  // 계획서 보기 — 새 모양은 묶음별, 그림 항목(content_type image)은 tag가 '2-1'이어도 본문에서 뺀다. 옛 모양은 legacy.
  const view=pvf({sections:[{section_code:'1.1',tag:null,title:'일반현황',content_type:'section'},{section_code:'2.3.6',tag:'2-1',title:'흐름도',content_type:'image'},{section_code:'2.2.1',tag:'2-1',title:'개발',content_type:'section'},{section_code:'2.3.7',tag:'2-1',title:'일정',content_type:'table'}],
    diagrams:[{diagram_id:'d1',image_url:'/projects/1/artifact-files/a'},{diagram_id:'d2',image_url:null}]});
  assert.deepEqual([view.legacy,view.general.map(s=>s.title),view.bundles.map(b=>[b.tag,b.sections.map(s=>s.title)]),view.diagrams.map(d=>d.diagram_id)],[false,['일반현황'],[['2-1',['개발','일정']]],['d1']]);
  assert.equal(pvf({sections:[{tag:'1-1',title:'a',body:'b'}]}).legacy,true);
  assert.equal(pvf({sections:[]}),null);
  // 검증결과서 PDF — 새 모양은 문서층 칸이 묶음 합계(일반현황 · 개요 + 묶음), 옛 모양은 항목별.
  const {buildVerificationReportHtml:bvr}=await server.ssrLoadModule('/src/features/workflow/verificationReport.js');
  const reportOf=(docScore)=>bvr({projectName:'p',announcementTitle:'a',category:'webdev',docScore,codeCheckItems:[],crossCheck:{raw:0,max:15,reasons:[]},threshold:80});
  const taggedReport=reportOf(tagged.docScore);
  assert.ok(taggedReport.includes('repeat(3, 1fr)')&&taggedReport.includes('<span>일반현황 · 개요</span><b>4 / 5</b>')&&taggedReport.includes('<span>문제 인식</span><b>11 / 15</b>')&&!taggedReport.includes('문제 정의'));
  assert.ok(reportOf(legacy.docScore).includes('<span>문제 인식</span><b>10 / 20</b>'));
  // 새 재작성 묶음(조율 10-12 5번) — 일반현황 · 개요(0-1) · 그림(0-2)은 서버가 그 묶음 기회를 줄 때만 목록에 나온다.
  const {docBundlesFor,bundleOfTag:bot}=await server.ssrLoadModule('/src/features/workflow/data.js');
  assert.deepEqual(docBundlesFor(null),['문제인식','실현가능성','성장전략','팀 구성']);
  assert.deepEqual(docBundlesFor({cap:1,remaining:{'일반현황 · 개요':1,'그림':0,'문제인식':1}}),['일반현황 · 개요','그림','문제인식','실현가능성','성장전략','팀 구성']);
  assert.deepEqual([bot('0-1'),bot('0-2'),bot(null),bot('2-1')],['일반현황 · 개요','그림','일반현황 · 개요','실현가능성']);
  const withDiagram=sfr({verdict:{doc_score:5,doc_max_score:10,notices:['입력 오류 안내']},plan:{sections:[],score_reasons:[{item_code:'2.3.6',tag:'0-2',score:2,max_score:4,reason_text:'노드 부족'},{item_code:'2.1.1',tag:'0-1',score:3,max_score:6}],artifacts:[]}});
  assert.deepEqual(withDiagram.docScore.groups.map(g=>[g.label,g.score,g.max]),[['일반현황 · 개요',3,6],['그림',2,4]]);
  assert.deepEqual(tr('그림',withDiagram.docScore,noArtifact),['2.3.6 — 노드 부족']);
  assert.deepEqual(withDiagram.notices,['입력 오류 안내']);assert.deepEqual(scored.notices,[]);
  // 표 대체 사유(조율 tableFallbacks 10-12) — 항목 번호로 찾는다.
  assert.deepEqual(pvf({sections:[{section_code:'2.6.2',tag:'3-1',title:'일정',content_type:'table'}],table_fallbacks:[{section_code:'2.6.2',tag:'3-1',title:'일정',display_reason:'일정 입력을 확인해 주세요.'}]}).fallbacks,{'2.6.2':'일정 입력을 확인해 주세요.'});
  // 화면 6 — 종합 판정(verdict) 전에는 plan의 문서 점수 · 기준 · 안내로 점수를 만든다(백엔드 BusinessPlanOut). 예전엔 null이라 예시 점수가 보였다.
  const doc6=sfr({verdict:null,plan:{doc_score:42,doc_max_score:60,threshold:75,notices:['입력 확인 필요'],sections:[],score_reasons:[{item_code:'2.4.1',tag:'1-1',score:6,max_score:10,reason_text:'근거 부족'}]}});
  assert.deepEqual([doc6.docScore.raw,doc6.docScore.max,doc6.threshold,doc6.notices,doc6.artifactScore,doc6.total],[42,60,75,['입력 확인 필요'],null,null]);
  assert.deepEqual(doc6.docScore.groups.map(g=>g.label),['문제인식']);
  assert.equal(sfr({verdict:null,plan:{doc_score:null,score_reasons:[]}}),null);assert.equal(sfr(null),null);
  // 재작성 전후 비교 — 새 모양(키 = 항목 번호, tag · title)은 묶음 이름으로, 묶음마다 그 묶음 항목만(보충 10-11).
  const {reworkDiffForLabel}=await server.ssrLoadModule('/src/features/workflow/rework.js');
  const changedNew={sections:{'2.5.1':{before:'b',after:'c',tag:'2-1',title:'개발 방안'},'2.4.2':{before:null,after:'n',tag:'1-1',title:'시장'},'2.4.1':{before:'x',after:'y',tag:'1-1',title:'문제 정의'}}};
  assert.deepEqual(reworkDiffForLabel(changedNew,'문제인식'),{before:'문제 정의 x',after:'문제 정의 y — 문제인식 2개 항목 변경'});
  assert.deepEqual(reworkDiffForLabel(changedNew,'실현가능성'),{before:'개발 방안 b',after:'개발 방안 c — 실현가능성 1개 항목 변경'});
  assert.equal(reworkDiffForLabel(changedNew,'팀 구성'),null);
  assert.deepEqual(reworkDiffForLabel({sections:{'1-1':{before:'a',after:'b'}}},'문제인식'),{before:'문제인식 a',after:'문제인식 b'});
  // 금액 칸이 비어 있거나(0은 된다) 추진 기간에 연도가 없으면 넘어가지 않는다.
  for(const [bad,anchor] of [[{budget:[{...draft.budget[0],cash:''}]},'intake-budget'],[{schedule:{feasibility:[{...draft.schedule.feasibility[0],period:'11월 ~ 1월'}]}},'intake-schedule']]){
    submitted=null;ui=mount(IntakeForm,{initialValues:{...draft,...bad},onSubmit:info=>{submitted=info}});await ui.flush();
    ui.find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await ui.flush();assert.equal(submitted,null);
    assert.ok(ui.find(n=>n.props.id===anchor).props.error);ui.unmount();
  }

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

  let createRequest,createBody;
  globalThis.fetch=async(url,options={})=>{
    const path=new URL(url).pathname;
    if(path==='/auth/me')return response({user_id:1,name:'Tester',role:'user',has_profile:true,notify_enabled:true});
    if(path==='/profile')return response([]);
    if(path==='/auth/logout')return response({});
    if(path==='/projects'&&options.method==='POST'){createBody=JSON.parse(options.body.get('payload'));createRequest=deferred();return createRequest.promise;}
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
  assert.deepEqual(createBody.budget_items,[{phase:null,category:'재료비',execution_plan:'부품 구입',total_amount:1200000,government_amount:1000000,self_cash_amount:200000,self_in_kind_amount:0}]);
  assert.deepEqual(createBody.schedule_items,[{section:'feasibility',category:'개발',content:'시제품',period:'2026.10 ~ 2026.12',detail:'첫 버전'}]);
  assert.equal(createBody.target_customer,'동네 헬스장 운영자'); // 목표 고객 — 앞뒤 공백은 떼고, 비우면 null
  createRequest.resolve(response({detail:'simulated failure'},500));await saving;await ui.flush();
  assert.equal(ui.component('IntakeForm').props.initialValues.item,draft.item);
  // 사업비 · 일정 검증 실패(422)는 원문 JSON 대신 몇째 줄 어느 칸인지 알려 준다.
  const intakeAlerts=[];window.alert=m=>intakeAlerts.push(m);
  saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  createRequest.resolve(response({detail:[{loc:['budget_items',2,'total_amount'],msg:'bad',type:'value_error'}],code:'VALIDATION_ERROR'},422));await saving;await ui.flush();
  assert.equal(intakeAlerts.at(-1),"사업비 3번째 줄의 '총사업비' 칸을 확인해 주세요.");
  // 여러 곳이 한 번에 오면 첫 곳과 나머지 수를, 백엔드의 한국어 사유가 있으면 함께 보인다.
  saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  createRequest.resolve(response({detail:[{loc:['schedule_items',0,'period'],msg:'Value error, 추진기간에 연도가 있어야 해요(예: 2026.05~2026.07)',type:'value_error'},{loc:['budget_items',1,'phase'],msg:'x',type:'value_error'}],code:'VALIDATION_ERROR'},422));await saving;await ui.flush();
  assert.equal(intakeAlerts.at(-1),"추진 일정 1번째 줄의 '추진 기간' 칸을 확인해 주세요. (추진기간에 연도가 있어야 해요(예: 2026.05~2026.07)) 그 밖에 1곳도 확인이 필요해요.");
  // 필수 입력 누락(E-C1-REQUIRED)은 빠진 항목 이름을 보인다.
  saving=ui.component('IntakeForm').props.onSubmit(draft);await ui.flush();
  createRequest.resolve(response({detail:{message:'필수 항목이 비어 있어요',code:'E-C1-REQUIRED',missing:['사업비 집행계획(2단계)']},code:'E-C1-REQUIRED'},422));await saving;await ui.flush();
  assert.equal(intakeAlerts.at(-1),'필수 항목이 비어 있어요: 사업비 집행계획(2단계)');window.alert=()=>{};
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

  // 원페이지 화면 9 — 계획서만 재작성해도 인포그래픽이 함께 다시 만들어지면 변경 내역 · 비교에 넣는다
  window.addEventListener=()=>{};window.removeEventListener=()=>{};
  let onepageReads=0;
  globalThis.fetch=route([
    ['POST /projects/7/retry-task',()=>response({cycle_id:'C9',screen:9,bundles:['문제인식'],collect_until:'2026-10-06T00:00:02Z'})],
    ['GET /projects/7/status',()=>response({stage:'final_review_pending',rework_screen:null})],
    ['GET /projects/7/rework-result',()=>response(++onepageReads<2?{cycle_id:'old',status:'완료',screen:9,bundles:[]}
      :{cycle_id:'C9',status:'완료',screen:9,bundles:['문제인식'],changed:{sections:{'1-1':{before:'옛 문장',after:'새 문장'}},infographic_path:{before:'a/old.svg',after:'a/new.svg'}}})],
  ]);
  ui=mount(FinalVerdict,{...verdictBase,itemInfo:{item:'동네 카페 매장'},artifact:{category:'onepage'},scores:{total:70,threshold:80},onProceed(){}});await ui.flush();
  ui.find(n=>n.type==='input'&&n.props.type==='checkbox').props.onChange();await ui.flush();
  await ui.find(n=>n.type==='button'&&n.props.children==='선택 항목 다시 만들기').props.onClick();await ui.flush();
  const diffToggle=ui.nodes().find(n=>n.type==='button'&&flat(n).includes('항목 변경됨'));
  assert.ok(flat(diffToggle).includes('2개 항목 변경됨'),flat(diffToggle));
  diffToggle.props.onClick();await ui.flush();
  assert.ok(flat(ui.nodes()[0]).includes('계획서와 함께 다시 만들어짐'));ui.unmount();

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

  // ── 받을 수 없는 상태 · 부분 거절(2026-10-06 점검) ─────────────────────────────────────
  // 서버는 받을 수 없는 상태에도 200으로 지금 상태만 준다 — 화면이 넘어가거나 끝없이 기다리면 안 된다.
  // 화면 8: 재작성이 도는 중이면 종합 평가로 넘어가지 않는다(버튼 잠금 + 응답 stage 확인)
  let finalizedAgain=0;
  globalThis.fetch=route([
    ['POST /projects/7/final-review/start',()=>response({stage:'prototype_building',match_status:'in_progress'})],
    ['GET /projects/7/status',()=>response({stage:'artifact_review',rework_screen:null})],
  ]);
  ui=mount(ArtifactResult,{...artifactBase,onFinalize:()=>{finalizedAgain++}});await ui.flush();
  await ui.find(n=>n.type==='button'&&String(n.props.children).includes('종합 평가 확인하기')).props.onClick();await ui.flush();
  assert.equal(finalizedAgain,0);ui.unmount();

  // 화면 9: 검수가 시작되지 않은 응답이면 기다리지 않고 안내(예전엔 끝나지 않는 '검수 진행 중')
  let proceededAgain=0,reviewStatusCalls=0;
  globalThis.fetch=route([
    ['POST /projects/7/review/start',()=>response({stage:'plan_writing',match_status:'in_progress'})],
    ['GET /projects/7/status',()=>{reviewStatusCalls++;return response({stage:'final_review_pending',rework_screen:null})}],
  ]);
  ui=mount(FinalVerdict,{...verdictBase,scores:{total:90,threshold:80},onProceed:async()=>{proceededAgain++}});await ui.flush();
  await ui.find(n=>n.type==='button'&&String(n.props.children).includes('검수하기')).props.onClick();await ui.flush();
  assert.equal(proceededAgain,0);assert.ok(flat(ui.nodes()[0]).includes('지금은 검수를 시작할 수 없어요'));
  const statusCallsAfter=reviewStatusCalls;await wait(2200);assert.equal(reviewStatusCalls,statusCallsAfter);ui.unmount();

  // 화면 6: 묶음 일부만 거절되면 접수된 묶음은 끝까지 추적하고, 끝나면 계획서 미리보기(PDF)를 다시 받는다
  let pdfFetches=0,partialReworked=null;alerts.length=0;
  globalThis.fetch=async(url,opt={})=>{const u=new URL(url);const key=(opt.method||'GET')+' '+u.pathname;
    if(key==='GET /projects/2/plan-document.pdf'){pdfFetches++;return {ok:true,status:200,blob:async()=>new Blob(['pdf'])};}
    if(key==='POST /projects/2/retry-task'){const b=JSON.parse(opt.body);
      return b.bundle_id==='문제인식'?response({cycle_id:'C7',screen:6,bundles:['문제인식'],collect_until:'2026-10-06T00:00:02Z'})
        :response({detail:'이 항목은 다시 만들 수 있는 횟수를 모두 사용했어요.',code:'E-G2-LIMIT'},409);}
    if(key==='GET /projects/2/rework-result')return response({cycle_id:'C7',status:'완료',screen:6,bundles:['문제인식'],changed:{}});
    if(key==='GET /projects/2/status')return response({stage:'plan_review_pending',rework_screen:null});
    return response({detail:'not mocked'},404);};
  ui=mount(PlanForm,{projectId:2,onRework:p=>{partialReworked=p}});await ui.flush();
  const pdfBefore=pdfFetches;
  const boxes=ui.nodes().filter(n=>n.type==='input'&&n.props.type==='checkbox');
  boxes[0].props.onChange();await ui.flush();
  ui.nodes().filter(n=>n.type==='input'&&n.props.type==='checkbox')[2].props.onChange();await ui.flush();
  await ui.find(n=>n.type==='button'&&n.props.children==='선택 항목 재작성').props.onClick();await ui.flush();
  assert.deepEqual(partialReworked,['문제인식']);
  assert.ok(alerts.some(m=>m.includes('성장전략')&&m.includes('횟수를 모두 사용')),alerts.join());
  assert.equal(pdfFetches,pdfBefore+1);ui.unmount();

  // 진행 화면: 시작 요청 뒤에도 사용자대기면 시작되지 않은 것 — 0%에서 끝없이 기다리지 않고 안내
  let stuckPolls=0;
  globalThis.fetch=async(url)=>{stuckPolls++;return response(String(url).endsWith('/start')
    ?{stage:'plan_review_pending',match_status:'user_waiting'}:{stage:'plan_review_pending',match_status:'user_waiting'})};
  ui=mount(GenerationProgress,{kind:'artifact',projectId:5});await ui.flush();
  assert.ok(ui.nodes().some(n=>n.props.role==='alert'&&flat(n).includes('작업을 시작하지 못했어요')));
  const pollsAfter=stuckPolls;await wait(1700);assert.equal(stuckPolls,pollsAfter);ui.unmount();

  // 화면 9 '계획서 보기'는 서버 계획서(plan.sections)를 보인다 — 예전엔 늘 예시 계획서였다
  globalThis.fetch=route([['GET /projects/7/status',()=>response({stage:'final_review_pending',rework_screen:null})]]);
  ui=mount(FinalVerdict,{...verdictBase,scores:{total:90,threshold:80},onProceed(){},
    plan:{sections:[{tag:'1-1',title:'문제 인식',body:'서버가 쓴 문제 인식 본문'},{tag:'2-1',title:'실현 가능성',body:'서버가 쓴 실현 본문'}]}});await ui.flush();
  ui.find(n=>n.type==='button'&&n.props.children==='계획서 보기').props.onClick();await ui.flush();
  const planText=flat(ui.nodes()[0]);
  assert.ok(planText.includes('서버가 쓴 문제 인식 본문')&&planText.includes('서버가 쓴 실현 본문'),planText.slice(0,200));
  assert.ok(!planText.includes('동네 헬스장'));ui.unmount();

  // 알림 이력을 눌러 열면 그 프로젝트의 공고 제목도 같이 넘긴다(번호만 넘겨 화면에 공고 제목이 비던 문제)
  const {NotificationBell}=await server.ssrLoadModule('/src/features/workflow/shared.jsx');
  let opened=null;
  globalThis.fetch=async(url,opt={})=>{const path=new URL(url).pathname;
    if(path==='/projects/notifications')return response([{notification_id:1,project_id:5,kind:'문서평가',read_at:null,created_at:'2026-10-06T01:00:00'}]);
    if(path==='/projects')return response([{project_id:5,description:'B 프로젝트',notice_title:'초기창업패키지',stage:'plan_review_pending',match_status:'user_waiting',display_status:'확인이 필요합니다'}]);
    return response({});};
  ui=mount(NotificationBell,{enabled:true,onToggle(){},onOpenProject:p=>{opened=p},refreshKey:'x'});await ui.flush();
  ui.find(n=>n.type==='button'&&n.props['aria-label']==='알림').props.onClick();await ui.flush();
  ui.find(n=>typeof n.props.onClick==='function'&&flat(n).includes('사업계획서 평가가 끝났어요')).props.onClick();await ui.flush();
  assert.equal(opened.id,5);assert.equal(opened.announcementTitle,'초기창업패키지');ui.unmount();

  console.log('PASS: orchestrator flows — resume screen map, candidates pending · blocked ids, eligibility pending · stale result · 409, gate fields, screen 8 · 9 proceed, onepage infographic rebuild, rework rollback · resume, review progress, not-started guards (screen 8 · 9 · progress), partial rework rejection · plan preview refresh, notification history title, screen 9 server plan');
  console.log('PASS: intake restoration, stale responses, final-stage lock, polling recovery, profile logout race, resume-screen routing, rewrite/generation exclusion');
}finally{globalThis.fetch=originalFetch;await server.close()}
