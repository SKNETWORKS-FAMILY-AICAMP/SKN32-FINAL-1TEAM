// 백엔드(FastAPI) 호출 공용 헬퍼. 세션은 httpOnly 쿠키라 매 요청에 credentials:'include'가
// 필요하다(back/app/main.py의 CORS allow_credentials=True와 짝). 백엔드 주소는 .env의
// VITE_API_BASE — 세션 쿠키 SameSite 문제 때문에 개발 중엔 프론트도 http://localhost:5174로
// 열어야 한다(127.0.0.1로 열면 로그인 자체는 되는데 그 다음 요청에 쿠키가 안 실린다).
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export class ApiError extends Error{
  constructor(status,detail){super(typeof detail==='string'?detail:JSON.stringify(detail));this.status=status;this.detail=detail}
}

// Access Token(세션 쿠키)은 30분 만료라, 그 사이 401을 받으면 여기서 조용히 POST /auth/refresh로
// 재발급받은 뒤 원래 요청을 한 번 재시도한다(back/app/security.py ACCESS_TOKEN_EXPIRE_MINUTES 참고).
// 같은 순간 여러 요청이 401을 받아도 refresh 호출은 한 번만 나가도록 진행 중인 Promise를 공유한다.
let _refreshInFlight=null;
function refreshAccessToken(){
  if(!_refreshInFlight){
    _refreshInFlight=fetch(API_BASE+'/auth/refresh',{method:'POST',credentials:'include'})
      .finally(()=>{_refreshInFlight=null});
  }
  return _refreshInFlight;
}

// path: '/auth/me' 같은 절대경로. body가 FormData면 그대로, 아니면 JSON으로 감싼다.
export async function apiFetch(path,{method='GET',body,headers,_retried=false}={}){
  const isForm=typeof FormData!=='undefined'&&body instanceof FormData;
  const res=await fetch(API_BASE+path,{
    method,
    credentials:'include',
    headers:isForm?headers:{'Content-Type':'application/json',...headers},
    body:body===undefined?undefined:(isForm?body:JSON.stringify(body)),
  });
  if(res.status===401&&!_retried&&path!=='/auth/refresh'&&path!=='/auth/google'){
    const refreshed=await refreshAccessToken();
    if(refreshed.ok)return apiFetch(path,{method,body,headers,_retried:true});
  }
  const text=await res.text();
  const data=text?JSON.parse(text):null;
  if(!res.ok){throw new ApiError(res.status,data?.detail??data??res.statusText)}
  return data;
}

export const api={
  get:(path)=>apiFetch(path),
  post:(path,body)=>apiFetch(path,{method:'POST',body}),
  put:(path,body)=>apiFetch(path,{method:'PUT',body}),
  delete:(path)=>apiFetch(path,{method:'DELETE'}),
};

// ---------------------------------------------------------------------------
// 프로젝트/워크플로우 관련 호출 (2026-09-15, 팀원이 추가한 백엔드 임시 엔드포인트에 맞춤).
// GET /projects, GET /projects/{id}/match-candidates, POST /projects/{id}/generate,
// GET /projects/{id}/result는 실제 오케스트레이터(Agent 파이프라인)가 아직 없어서
// (app/agents.py 모듈 docstring 참고) seed_dummy_pipeline.py의 더미 로직을 API로 감싼
// 임시 구현이다 — 나중에 실제 오케스트레이터가 붙어도 이 함수들의 계약(요청/응답 모양)은
// 그대로 유지될 예정이라 프론트를 다시 고칠 필요는 없어야 한다.
// ---------------------------------------------------------------------------

// 대시보드 "내 프로젝트" 목록.
export const listProjects=()=>api.get('/projects');

// 대시보드 휴지통 버튼 — 매칭 전이면 실제로 지우고, 매칭 이후면 서버가 보관 처리만
// 한다(back/app/routers/projects.py delete_project 참고). 어느 쪽이든 프론트 입장에선
// 그냥 "내 목록에서 사라진다"만 알면 된다.
export const deleteProject=(projectId)=>api.delete(`/projects/${projectId}`);

// IntakeForm 제출 — multipart/form-data(payload는 JSON 문자열, files는 실제 첨부파일).
export function createProject(payload,files=[]){
  const form=new FormData();
  form.append('payload',JSON.stringify(payload));
  for(const f of files)form.append('files',f);
  return apiFetch('/projects',{method:'POST',body:form});
}

export const getProject=(projectId)=>api.get(`/projects/${projectId}`);
export const getProjectStatus=(projectId)=>api.get(`/projects/${projectId}/status`);
// 계획서·프로토타입 생성 시작 — 바로 응답하고 생성은 서버에서 계속 돈다. 진행률은 getProjectStatus로 본다.
export const startPlanGeneration=(projectId)=>api.post(`/projects/${projectId}/plan/start`);
export const startPrototypeGeneration=(projectId)=>api.post(`/projects/${projectId}/prototype/start`);

// 매칭 후보 {candidates:[...batch 1|2], rematch_used} — 처음 부를 때 10건을 뽑아 서버에 저장하고
// 이후엔 같은 목록을 돌려준다. 사용자가 고른 뒤 generatePipeline 호출.
export const getMatchCandidates=(projectId)=>api.get(`/projects/${projectId}/match-candidates`);
// 공고 다시 찾기 — 프로젝트당 1회(서버가 409로 막음). 이전 후보는 유지하고 10건을 더한다.
export const rematchCandidates=(projectId)=>api.post(`/projects/${projectId}/match-candidates/rematch`);

// 선택한 공고로 매칭~최종판정까지 한 번에 생성(더미). noticeId 생략하면 서버가 아무 공고나 고른다.
export const generatePipeline=(projectId,noticeId)=>api.post(`/projects/${projectId}/generate`,{notice_id:noticeId||null});

// 이미 generatePipeline으로 만들어둔 결과를 재생성 없이 다시 불러온다("이어서 보기").
export const getProjectResult=(projectId)=>api.get(`/projects/${projectId}/result`);

// 개별 작업 재시도 — task_key: 'strategy'|'writing'|'verify1_rubric'|'verify1_evidence'|
// 'implement_prototype'|'implement_infographic'|'verify2_static'|'verify2_crosscheck'|
// 'review_expression'|'review_token_check' (app/schemas.py RetryTaskRequest 참고).
export const retryTask=(projectId,taskKey)=>api.post(`/projects/${projectId}/retry-task`,{task_key:taskKey});

// [2026-09-15] 응답이 JSON이 아니라 실제 파일 바이너리인 다운로드 공용 헬퍼 — apiFetch(항상
// JSON 파싱)를 못 쓰는 GET /projects/{id}/plan-document.docx 가 쓴다.
// 파일 바이너리를 Blob으로 받아온다(401이면 한 번 갱신 후 재시도) — 받아서 저장하는
// downloadFile과, 화면에 띄우는 fetchPlanDocumentPdf가 같이 쓴다.
async function fetchBlob(path){
  let res=await fetch(`${API_BASE}${path}`,{credentials:'include'});
  if(res.status===401){
    const refreshed=await refreshAccessToken();
    if(refreshed.ok)res=await fetch(`${API_BASE}${path}`,{credentials:'include'});
  }
  if(!res.ok){
    const text=await res.text();
    // 에러 본문이 JSON이 아닐 수도 있다(프록시가 낸 HTML 오류 페이지 등) — 그땐 본문/상태 문구를 쓴다.
    let data=null;
    try{data=text?JSON.parse(text):null}catch(e){data=text||null}
    throw new ApiError(res.status,data?.detail??data??res.statusText);
  }
  return res.blob();
}

async function downloadFile(path,filename){
  const blob=await fetchBlob(path);
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download=filename;
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// GET /projects/{id}/plan-document.docx 에서 초기창업패키지(일반형)/예비창업패키지 공식
// 양식(별첨1) 구조로 채운 진짜 docx를 내려준다(app/plan_document_export.py) — ReviewScreen의
// 더미(dummyDeliverables.js) 대신 이 함수를 쓰면 실제 양식이 반영된 파일을 받는다.
export const downloadPlanDocument=(projectId,filename='사업계획서.docx')=>downloadFile(`/projects/${projectId}/plan-document.docx`,filename);

// GET /projects/{id}/plan-document.pdf — 위 docx를 서버가 LibreOffice로 변환한 PDF(app/pdf_export.py).
// 화면(PlanForm 우측 뷰어)에 띄우려고 Blob으로 받는다 — iframe src에 엔드포인트를 그대로 걸면
// 401 재발급 처리가 안 되고, 변환 실패(503) 사유도 브라우저 기본 화면에 묻혀 안 보인다.
export const fetchPlanDocumentPdf=(projectId)=>fetchBlob(`/projects/${projectId}/plan-document.pdf`);

// 마이페이지 사업자등록번호 조회 — 서버가 국세청 상태조회 API를 대신 호출한다
// (back/app/routers/biz_check.py). 응답: {valid, b_stt_cd, label, tax_type, tax_type_cd, message}
// profileId를 주면 그 결과를 해당 정보 슬롯(user_profiles)에 서버가 같이 저장한다 — 아직
// 서버에 저장된 적 없는 슬롯(profileId 없음)이면 조회 결과만 화면에 보여주고 저장은
// 건너뛴다(back/app/routers/biz_check.py — profile_id 없으면 아무 슬롯도 안 건드림).
export const checkBizNo=(bNo,profileId)=>api.post('/biz-check',{b_no:bNo,profile_id:profileId??null});

// ---------------------------------------------------------------------------
// 마이페이지 프로필 (SB-59 v2, 계정당 최대 3슬롯) — back/app/routers/profile.py
// ---------------------------------------------------------------------------
export const listProfiles=()=>api.get('/profile');
export const createProfile=(body)=>api.post('/profile',body);
export const updateProfile=(profileId,body)=>api.put(`/profile/${profileId}`,body);
export const deleteProfile=(profileId)=>api.delete(`/profile/${profileId}`);
