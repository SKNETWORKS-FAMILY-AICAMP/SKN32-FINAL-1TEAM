import {createServer} from 'vite';
import React from 'react';
import {renderToString} from 'react-dom/server';
const server=await createServer({configFile:false,resolve:{preserveSymlinks:true},server:{middlewareMode:true},appType:'custom'});
const checks=[];
try{
 const {default:Landing}=await server.ssrLoadModule('/src/components/Landing.jsx');
 const {WorkspaceShell,Dashboard}=await server.ssrLoadModule('/src/components/Workspace.jsx');
 const flow=await server.ssrLoadModule('/src/features/Workflow.jsx');
 const noop=()=>{};
 const info={item:'동네 헬스장 예약 서비스',ceoName:'김창업',foundedAt:'2025-01-10',applicantType:'startup',files:[],team:[],pricing:[]};
 const shared={announcement:flow.ANNOUNCEMENTS[0],itemInfo:info,onBack:noop,onSubmit:noop,onProceed:noop,onLeave:noop,onGenerate:noop,onFinalize:noop,onGoDashboard:noop,onCheckEligibility:noop,onComplete:noop,disabledTitles:[],docOutcome:'fail',artifactOutcome:'fail',setDocOutcome:noop,setArtifactOutcome:noop};
 const cases=[['Landing',Landing,{onStart:noop}],['WorkspaceShell',WorkspaceShell,{view:'dashboard',notifyEnabled:true,onHome:noop,onDashboard:noop,onNewProject:noop,onToggleNotify:noop}],['Dashboard',Dashboard,{onNewProject:noop,onOpenProject:noop,isNewUser:false,onToggleNewUser:noop}],['EmptyDashboard',Dashboard,{onNewProject:noop,onOpenProject:noop,isNewUser:true,onToggleNewUser:noop}],...['IntakeForm','MatchProgress','MatchResults','EligibilityGate','PlanForm','ArtifactResult','FinalVerdict','ReviewScreen'].map(name=>[name,flow[name],shared])];
 for(const [name,Component,props] of cases){const result=renderToString(React.createElement(Component,props));if(result.length<50)throw new Error(name+' rendered no content');checks.push(name);}
 console.log('PASS: '+checks.join(', '));
}finally{await server.close()}

