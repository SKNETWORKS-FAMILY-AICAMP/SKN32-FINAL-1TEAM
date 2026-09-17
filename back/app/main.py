"""FastAPI 진입점. repo 루트에서 다음처럼 띄운다:

    uvicorn app.main:app --reload --port 8000

Swagger 문서: http://127.0.0.1:8000/docs
(기술스택 선정서 2-3-2 — 6인 팀 인터페이스 합의 비용을 줄이는 용도로 그대로 확인용)

auth/projects/admin/faqs/biz_check 라우터가 전부 등록돼 있다. faqs 라우터(로그인한 유저가
새 질문을 직접 올리는 공개용 `POST /faqs`, 공개 FAQ 목록 `GET /faqs`)는 2026-09-14에
추가됐다 — FaqCreateRequest 스키마는 이전부터 있었지만 그걸 쓰는 라우터가 없던
갭이었다(설계 문서 3.3절에서 지적).

biz_check 라우터(`POST /biz-check`)는 마이페이지 사업자등록번호 입력칸의 자동 판정용이다.
국세청 상태조회 API(공공데이터포털)를 서버가 대신 호출해 영업상태·과세유형만 돌려준다 —
업종·개업일은 이 API 응답에 없어서(진위확인 입력값이지 조회 결과가 아님) 계속 사용자
직접 입력으로 남는다.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_sqlite_dev_db
from app.routers import admin, auth, biz_check, faqs, projects
from app.routers.projects import UPLOAD_DIR

app = FastAPI(title='S-Brain API', version='0.1.0')

# DB_BACKEND=sqlite(.env, 개인 로컬 개발용)일 때만 실제로 테이블을 만든다.
# DB_BACKEND=mysql(팀 공유 AWS, 기본값)일 때는 아무 일도 안 한다 — 그쪽은 app_schema.sql로 직접 적용.
init_sqlite_dev_db()

# 프론트(Vite dev server) 에서 호출하므로 CORS 허용. 포트/오리진은 backend_decisions.md
# #4로 확정: 프론트 http://127.0.0.1:5174. allow_credentials=True 는 httpOnly 쿠키
# 세션(#1 확정)을 쓰려면 필수 — 프론트도 fetch/axios에 credentials: 'include' 필요.
# localhost:5174도 같이 열어둔 건, 쿠키 SameSite 문제(security.py의 set_session_cookie
# 주석 참고) 때문에 개발할 땐 프론트를 127.0.0.1 대신 localhost로 띄우는 걸 권장해서다.
# 배포 시 allow_origins 는 실제 도메인으로 좁힌다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://127.0.0.1:5174', 'http://localhost:5174'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# projects.py 의 POST /projects 가 로컬 디스크(/uploads)에 저장한 첨부파일을
# 그대로 URL로 접근 가능하게 정적 서빙한다 (backend_decisions.md #6).
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount('/uploads', StaticFiles(directory=UPLOAD_DIR), name='uploads')

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(admin.router)
app.include_router(faqs.router)
app.include_router(biz_check.router)


@app.get('/health')
def health():
    return {'status': 'ok'}
