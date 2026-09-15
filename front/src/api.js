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
