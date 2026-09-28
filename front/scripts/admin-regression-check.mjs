// Exercise component handlers/effects with controlled API response ordering; no real DB writes.
import assert from 'node:assert/strict';
import React from 'react';
import {createServer} from 'vite';

const server=await createServer({configFile:false,resolve:{preserveSymlinks:true},server:{middlewareMode:true},appType:'custom',plugins:[{
  name:'admin-test-exports',enforce:'pre',
  transform(code,id){if(id.replaceAll('\\','/').endsWith('/features/Admin.jsx'))return code+'\nexport {AnnouncementTab,ProgressTab,AgentsTab,UsersTab,PolicyTab,executionRowFromServer};';},
}]});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const internals=React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;

function mount(Component,props={}){
  const slots=[];let cursor=0,tree,dirty=true,effects=[];
  const dispatcher={
    useState(initial){const i=cursor++;if(!slots[i])slots[i]={value:typeof initial==='function'?initial():initial};return [slots[i].value,v=>{slots[i].value=typeof v==='function'?v(slots[i].value):v;dirty=true}];},
    useRef(initial){const i=cursor++;return (slots[i]??={current:initial});},
    useEffect(fn,deps){const i=cursor++;const old=slots[i];if(!old||!deps||deps.some((d,k)=>!Object.is(d,old.deps[k]))){slots[i]={deps,cleanup:old?.cleanup};effects.push(()=>{slots[i].cleanup?.();slots[i].cleanup=fn()});}},
  };
  const render=()=>{cursor=0;dirty=false;const previous=internals.ReactCurrentDispatcher.current;internals.ReactCurrentDispatcher.current=dispatcher;try{tree=Component(props)}finally{internals.ReactCurrentDispatcher.current=previous}const pending=effects;effects=[];pending.forEach(fn=>fn());};
  const flush=async()=>{for(let i=0;i<5;i++){if(dirty)render();await tick();}};
  const nodes=()=>{const all=[];const visit=x=>{if(Array.isArray(x))x.forEach(visit);else if(x&&typeof x==='object'&&x.props){all.push(x);visit(x.props.children)}};visit(tree);return all;};
  const text=x=>Array.isArray(x)?x.map(text).join(''):x&&typeof x==='object'?text(x.props?.children):String(x??'');
  return {flush,nodes,text:()=>text(tree),find:predicate=>{const node=nodes().find(predicate);assert.ok(node,'Expected control not found');return node;},button:label=>{const node=nodes().find(n=>n.type==='button'&&text(n)===label);assert.ok(node,`Missing button: ${label}`);return node;},unmount:()=>slots.forEach(s=>s?.cleanup?.())};
}

try{
  const admin=await server.ssrLoadModule('/src/features/Admin.jsx');
  const {api}=await server.ssrLoadModule('/src/api.js');
  assert.equal(admin.executionRowFromServer({status:'success',token_usage:1}).statusTone,'ok');

  const noticeRequests=[];
  api.get=url=>url.startsWith('/admin/notices')?(()=>{const req=deferred();noticeRequests.push(req);return req.promise})():Promise.resolve({sources:[],recent_runs:[]});
  let ui=mount(admin.AnnouncementTab);await ui.flush();await wait(330);
  ui.find(n=>n.type==='input').props.onChange({target:{value:'new'}});await ui.flush();await wait(330);
  noticeRequests[1].resolve([{notice_id:'new',title:'NEW RESULT',source:'bizinfo'}]);await ui.flush();
  noticeRequests[0].resolve([{notice_id:'old',title:'OLD RESULT',source:'bizinfo'}]);await ui.flush();
  assert.ok(ui.text().includes('NEW RESULT'));assert.ok(!ui.text().includes('OLD RESULT'));ui.unmount();

  const histories=[];
  api.get=url=>url==='/admin/items'?Promise.resolve([{project_id:1,description:'A'},{project_id:2,description:'B'}]):(()=>{const req=deferred();histories.push(req);return req.promise})();
  ui=mount(admin.ProgressTab);await ui.flush();
  const historyButtons=()=>ui.nodes().filter(n=>n.type==='button'&&n.props.children==='이력보기');
  historyButtons()[0].props.onClick();await ui.flush();
  ui.find(n=>n.props.title==='A 점수 이력').props.onClose();await ui.flush();
  historyButtons()[1].props.onClick();await ui.flush();
  histories[1].resolve({doc:[{score:62,scored_at:'2026-09-21'}],code:[],plan:[]});await ui.flush();
  histories[0].resolve({doc:[{score:13,scored_at:'2026-09-20'}],code:[],plan:[]});await ui.flush();
  assert.ok(ui.text().includes('62점'));assert.ok(!ui.text().includes('13점'));
  ui.find(n=>n.props.title==='B 점수 이력').props.onClose();await ui.flush();
  historyButtons()[0].props.onClick();await ui.flush();histories[2].reject(new Error('offline'));await ui.flush();
  assert.ok(ui.text().includes('점수 이력을 불러오지 못했어요'));assert.ok(!ui.text().includes('누적된 이력이 없습니다'));ui.unmount();

  let taskCalls=0,execCalls=0;
  api.get=url=>url==='/admin/agent-tasks'?(++taskCalls===1?Promise.reject(new Error('offline')):Promise.resolve([])):url.startsWith('/admin/agent-executions')?(++execCalls===1?Promise.reject(new Error('offline')):Promise.resolve([])):Promise.resolve({});
  ui=mount(admin.AgentsTab);await ui.flush();assert.ok(ui.text().includes('Task 현황을 불러오지 못했어요'));
  ui.button('Execution별 보기').props.onClick();await ui.flush();assert.ok(ui.text().includes('실행 세션을 불러오지 못했어요'));
  ui.button('Task별 보기').props.onClick();await ui.flush();assert.ok(!ui.text().includes('Task 현황을 불러오지 못했어요'));
  ui.button('Execution별 보기').props.onClick();await ui.flush();assert.ok(ui.text().includes('실행 로그가 아직 없어요'));ui.unmount();

  let updates=[];
  api.get=url=>Promise.resolve(url==='/admin/users'?[]:[{faq_id:1,question:'Q',answer:'old',is_visible:false}]);
  api.put=(url,body)=>{const req=deferred();updates.push({body,...req});return req.promise};
  ui=mount(admin.UsersTab,{pushToast:()=>{}});await ui.flush();ui.button('답변').props.onClick();await ui.flush();
  ui.find(n=>n.type==='textarea').props.onChange({target:{value:'new'}});await ui.flush();
  const save=ui.button('답변 저장'),toggle=ui.button('노출로 전환');
  const saving=save.props.onClick();await toggle.props.onClick();assert.equal(updates.length,1);
  updates[0].resolve({answer:'new',is_visible:false});await saving;await ui.flush();
  const toggling=ui.button('노출로 전환').props.onClick();assert.equal(updates[1].body.answer,'new');
  updates[1].resolve({answer:'new',is_visible:true});await toggling;await ui.flush();ui.unmount();

  let writes=0;
  api.get=url=>Promise.resolve(url==='/admin/policy'?{doc_weight:70,code_weight:15,plan_weight:15,pass_threshold:80,rerun_cap:3,token_retry_cap:2,deviation_cap:5}:[]);
  api.put=async()=>{writes++};
  ui=mount(admin.PolicyTab,{pushToast:()=>{}});await ui.flush();
  ui.nodes().filter(n=>n.type==='input'&&n.props.type==='number')[3].props.onChange({target:{value:''}});await ui.flush();
  await ui.button('판정 기준 저장').props.onClick();assert.equal(writes,0);ui.unmount();
  console.log('PASS: success status, search/history races, history errors, agent retry recovery, FAQ write serialization, blank policy rejection');
}finally{await server.close()}
