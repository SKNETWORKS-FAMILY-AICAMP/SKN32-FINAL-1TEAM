// 프로젝트/워크플로우 관련 백엔드 호출 모음. Login.jsx에도 같은 API_BASE 상수가 따로 있는데
// (로그인은 이미 검증된 상태라 안 건드림), 여기는 IntakeForm 이후 화면들(대시보드/매칭/
// 자격판정/계획서~검수)이 쓰는 호출을 한곳에 모아둔 것 — backend_decisions.md #4 확정값과
// 동일하게 기본값은 http://localhost:8000, front/.env의 VITE_API_BASE로 덮어쓸 수 있다.
const API_BASE=import.meta.env.VITE_API_BASE||'http://localhost:8000';

// [2026-09-15, 프론트 통합 임시 구현] 아래 함수들이 부르는 GET /projects, GET /projects/{id}/
// match-candidates, POST /projects/{id}/generate, GET /projects/{id}/result 는 전부 이번에
// 새로 추가한 임시 백엔드 엔드포인트다 — 실제 오케스트레이터(Agent 파이프라인)가 아직 없어서
// (app/agents.py 모듈 docstring 참고) seed_dummy_pipeline.py의 더미 로직을 API로 감싼 것.
// 나중에 실제 오케스트레이터가 붙으면 백엔드 구현만 바뀌고 이 함수들의 계약(요청/응답 모양)은
// 그대로 유지될 예정이라, 프론트 쪽을 다시 고칠 필요는 없어야 한다.

async function apiFetch(path,options={}){
  const res=await fetch(`${API_BASE}${path}`,{credentials:'include',...options});
  if(!res.ok){
    const body=await res.json().catch(()=>({}));
    throw new Error(body.detail?(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail)):`요청이 실패했어요 (${res.status})`);
  }
  if(res.status===204)return null;
  return res.json();
}

// 대시보드 "내 프로젝트" 목록.
export function listProjects(){
  return apiFetch('/projects');
}

// IntakeForm 제출 — multipart/form-data(payload는 JSON 문자열, files는 실제 첨부파일).
export function createProject(payload,files=[]){
  const form=new FormData();
  form.append('payload',JSON.stringify(payload));
  for(const f of files)form.append('files',f);
  return apiFetch('/projects',{method:'POST',body:form});
}

export function getProject(projectId){
  return apiFetch(`/projects/${projectId}`);
}

export function getProjectStatus(projectId){
  return apiFetch(`/projects/${projectId}/status`);
}

// 매칭 후보(최대 3건) — 아직 아무것도 저장 안 됨, 사용자가 고른 뒤 generatePipeline 호출.
export function getMatchCandidates(projectId){
  return apiFetch(`/projects/${projectId}/match-candidates`);
}

// 선택한 공고로 매칭~최종판정까지 한 번에 생성(더미). noticeId 생략하면 서버가 아무 공고나 고른다.
export function generatePipeline(projectId,noticeId){
  return apiFetch(`/projects/${projectId}/generate`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({notice_id:noticeId||null}),
  });
}

// 이미 generatePipeline으로 만들어둔 결과를 재생성 없이 다시 불러온다("이어서 보기").
export function getProjectResult(projectId){
  return apiFetch(`/projects/${projectId}/result`);
}

// 개별 작업 재시도 — task_key: 'strategy'|'writing'|'verify1_rubric'|'verify1_evidence'|
// 'implement_prototype'|'implement_infographic'|'verify2_static'|'verify2_crosscheck'|
// 'review_expression'|'review_token_check' (app/schemas.py RetryTaskRequest 참고).
export function retryTask(projectId,taskKey){
  return apiFetch(`/projects/${projectId}/retry-task`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task_key:taskKey}),
  });
}
