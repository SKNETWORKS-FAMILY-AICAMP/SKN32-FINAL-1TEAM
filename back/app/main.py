"""FastAPI 진입점. repo 루트에서 다음처럼 띄운다:

    uvicorn app.main:app --reload --port 8000

Swagger 문서: http://127.0.0.1:8000/docs
(기술스택 선정서 2-3-2 — 6인 팀 인터페이스 합의 비용을 줄이는 용도로 그대로 확인용)

지금은 auth/projects 라우터만 등록돼 있다. admin/faqs 라우터는 아직 만들기 전이라
빼놨다 — 그 라우터들을 만들면, 아래 import 한 줄이랑 include_router 두 줄을
주석 풀어서(또는 새로 추가해서) 다시 등록하면 된다.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import init_sqlite_dev_db
from app.routers import auth, projects
from app.routers.projects import UPLOAD_DIR

# admin/faqs 라우터를 만들면 위 줄을 아래처럼 바꾸고,
# 밑의 app.include_router(...) 두 줄의 주석을 풀면 된다.
# from app.routers import admin, auth, faqs, projects

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
# app.include_router(admin.router)
# app.include_router(faqs.router)


@app.get('/health')
def health():
    return {'status': 'ok'}