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
  const {useWorkflowStore:store}=await server.ssrLoadModule('/src/store/useWorkflowStore.js');
  const file=new Blob(['attachment']);
  const draft={applicantType:'individual',ceoName:'대표',birthDate:'1990-01-01',gender:'남성',foundedAt:'2024-01-01',
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
  ui=mount(GenerationProgress,{kind:'plan',projectId:1});await ui.flush();await wait(1600);await ui.flush();
  assert.ok(ui.nodes().some(n=>n.props.role==='alert'));
  await wait(1600);await ui.flush();assert.equal(ui.component('Preparation').props.progress,100);
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
    if(path==='/projects/2/status')return response({stage:'done'});
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
  cache.set('sbrain-last-view:2','review');
  await ui.component('Dashboard').props.onOpenProject({id:2,matched:true,announcementTitle:'B notice'},'plan-form');await ui.flush();
  assert.ok(ui.component('ReviewScreen'));assert.equal(cache.get('sbrain-last-view:2'),'review');
  createRequest.resolve(response({project_id:99}));await saving;await ui.flush();
  assert.equal(store.getState().projectId,2);assert.equal(store.getState().itemInfo.item,'B project');ui.unmount();
  console.log('PASS: intake restoration, founding date validation/type switch, stale eligibility/create responses, final-stage lock, automatic/manual polling recovery');
}finally{globalThis.fetch=originalFetch;await server.close()}
