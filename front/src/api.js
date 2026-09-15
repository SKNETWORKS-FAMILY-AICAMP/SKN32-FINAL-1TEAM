// 백엔드(FastAPI) 호출 공용 헬퍼. 세션은 httpOnly 쿠키라 매 요청에 credentials:'include'가
// 필요하다(back/app/main.py의 CORS allow_credentials=True와 짝). 백엔드 주소는 .env의
// VITE_API_BASE — 세션 쿠키 SameSite 문제 때문에 개발 중엔 프론트도 http://localhost:5174로
// 열어야 한다(127.0.0.1로 열면 로그인 자체는 되는데 그 다음 요청에 쿠키가 안 실린다).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export class ApiError extends Error{
  constructor(status,detail){super(typeof detail==='string'?detail:JSON.stringify(detail));this.status=status;this.detail=detail}
}

// path: '/auth/me' 같은 절대경로. body가 FormData면 그대로, 아니면 JSON으로 감싼다.
export async function apiFetch(path,{method='GET',body,headers}={}){
  const isForm=typeof FormData!=='undefined'&&body instanceof FormData;
  const res=await fetch(API_BASE+path,{
    method,
    credentials:'include',
    headers:isForm?headers:{'Content-Type':'application/json',...headers},
    body:body===undefined?undefined:(isForm?body:JSON.stringify(body)),
  });
  const text=await res.text();
  const data=text?JSON.parse(text):null;
  if(!res.ok){throw new ApiError(res.status,data?.detail??data??res.statusText)}
  return data;
}

export const api={
  get:(path)=>apiFetch(path),
  post:(path,body)=>apiFetch(path,{method:'POST',body}),
  put:(path,body)=>apiFetch(path,{method:'PUT',body}),
};

// ---------------------------------------------------------------------------
// 프로젝트/워크플로우 관련 호출 (2026-09-15, 하정원님이 추가한 백엔드 임시 엔드포인트에 맞춤).
// GET /projects, GET /projects/{id}/match-candidates, POST /projects/{id}/generate,
// GET /projects/{id}/result는 실제 오케스트레이터(Agent 파이프라인)가 아직 없어서
// (app/agents.py 모듈 docstring 참고) seed_dummy_pipeline.py의 더미 로직을 API로 감싼
// 임시 구현이다 — 나중에 실제 오케스트레이터가 붙어도 이 함수들의 계약(요청/응답 모양)은
// 그대로 유지될 예정이라 프론트를 다시 고칠 필요는 없어야 한다.
// ---------------------------------------------------------------------------

// 대시보드 "내 프로젝트" 목록.
export const listProjects=()=>api.get('/projects');

// IntakeForm 제출 — multipart/form-data(payload는 JSON 문자열, files는 실제 첨부파일).
export function createProject(payload,files=[]){
  const form=new FormData();
  form.append('payload',JSON.stringify(payload));
  for(const f of files)form.append('files',f);
  return apiFetch('/projects',{method:'POST',body:form});
}

export const getProject=(projectId)=>api.get(`/projects/${projectId}`);
export const getProjectStatus=(projectId)=>api.get(`/projects/${projectId}/status`);

// 매칭 후보(최대 3건) — 아직 아무것도 저장 안 됨, 사용자가 고른 뒤 generatePipeline 호출.
export const getMatchCandidates=(projectId)=>api.get(`/projects/${projectId}/match-candidates`);

// 선택한 공고로 매칭~최종판정까지 한 번에 생성(더미). noticeId 생략하면 서버가 아무 공고나 고른다.
export const generatePipeline=(projectId,noticeId)=>api.post(`/projects/${projectId}/generate`,{notice_id:noticeId||null});

// 이미 generatePipeline으로 만들어둔 결과를 재생성 없이 다시 불러온다("이어서 보기").
export const getProjectResult=(projectId)=>api.get(`/projects/${projectId}/result`);

// 개별 작업 재시도 — task_key: 'strategy'|'writing'|'verify1_rubric'|'verify1_evidence'|
// 'implement_prototype'|'implement_infographic'|'verify2_static'|'verify2_crosscheck'|
// 'review_expression'|'review_token_check' (app/schemas.py RetryTaskRequest 참고).
export const retryTask=(projectId,taskKey)=>api.post(`/projects/${projectId}/retry-task`,{task_key:taskKey});

// [2026-09-15] 사업계획서.docx 다운로드 — 응답이 JSON이 아니라 실제 .docx 바이너리라
// apiFetch(항상 JSON 파싱)를 못 쓰고 별도 함수로 뺐다. 서버가
// GET /projects/{id}/plan-document.docx 에서 초기창업패키지(일반형) 공식 양식(별첨1)
// 구조로 채운 진짜 docx를 내려준다(app/plan_document_export.py) — ReviewScreen의
// 더미(dummyDeliverables.js) 대신 이 함수를 쓰면 실제 양식이 반영된 파일을 받는다.
export async function downloadPlanDocument(projectId,filename='사업계획서.docx'){
  const res=await fetch(`${API_BASE}/projects/${projectId}/plan-document.docx`,{credentials:'include'});
  if(!res.ok){
    const text=await res.text();
    const data=text?JSON.parse(text):null;
    throw new ApiError(res.status,data?.detail??data??res.statusText);
  }
  const blob=await res.blob();
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download=filename;
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
