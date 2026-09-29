"""FastAPI 진입점. repo 루트에서 다음처럼 띄운다:

    uvicorn app.main:app --reload --port 8000

Swagger 문서: http://127.0.0.1:8000/docs
(기술스택 선정서 2-3-2 — 6인 팀 인터페이스 합의 비용을 줄이는 용도로 그대로 확인용)

auth/projects/admin/faqs/biz_check/profile 라우터가 전부 등록돼 있다. faqs 라우터(로그인한
유저가 새 질문을 직접 올리는 공개용 `POST /faqs`, 공개 FAQ 목록 `GET /faqs`)는 2026-09-14에
추가됐다 — FaqCreateRequest 스키마는 이전부터 있었지만 그걸 쓰는 라우터가 없던
갭이었다(설계 문서 3.3절에서 지적).

biz_check 라우터(`POST /biz-check`)는 마이페이지 사업자등록번호 입력칸의 자동 판정용이다.
국세청 상태조회 API(공공데이터포털)를 서버가 대신 호출해 영업상태·과세유형만 돌려준다 —
업종·개업일은 이 API 응답에 없어서(진위확인 입력값이지 조회 결과가 아님) 계속 사용자
직접 입력으로 남는다.

profile 라우터(`GET`/`POST /profile`, `PUT`/`DELETE /profile/{profile_id}`, 2026-09-17
추가·2026-09-18 v2로 슬롯형 개편, SB-59)는 마이페이지 입력값을 계정별로 서버(user_profiles)
에 저장/조회한다 — 그동안 브라우저(localStorage)에만 남아 다른 기기에서 로그인하면 안
보이던 문제를 고친다. 계정당 최대 3개 슬롯(schemas.MAX_PROFILES)을 둘 수 있다. biz_check가
조회 성공 시 요청이 지정한 슬롯(profile_id)에 결과를 upsert한다(app/routers/biz_check.py).
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_sqlite_dev_db
from app.request_logging import RequestLoggingMiddleware
from app.routers import admin, auth, biz_check, faqs, profile, projects, uploads
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

# [2026-09-23, 팀 로깅 정책 "웹서비스" 담당분] 요청마다 시작/끝을 back/logs/에 파일로
# 남긴다(DB엔 안 남김) — CORS보다 나중에 추가해서 미들웨어 스택 바깥쪽을 차지하게 했다
# (Starlette는 add_middleware 호출 역순으로 스택을 쌓아서, 나중에 추가한 게 가장 바깥쪽 —
# 즉 요청이 CORS를 타기도 전에 로그가 먼저 찍힌다). app/request_logging.py 참고.
app.add_middleware(RequestLoggingMiddleware)

# projects.py 의 POST /projects 가 로컬 디스크(/uploads)에 저장한 첨부파일을
# 기존 URL을 유지하면서 uploads 라우터에서 인증·소유권을 확인한다.
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.include_router(uploads.router)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(admin.router)
app.include_router(faqs.router)
app.include_router(biz_check.router)
app.include_router(profile.router)


# [2026-09-22] 계획서/프로토타입 생성 진행(match_results.stage)을 다시 살리는 백그라운드
# 루프 — 서버가 재시작되면서 끊긴 작업을 이어받는다(app/routers/projects.py
# _generation_recovery_loop 참고. Redis 등 별도 브로커 없이 DB 클레임 컬럼만으로 동작).
@app.on_event('startup')
def _resume_pending_generations() -> None:
    projects.start_generation_recovery_loop()


from fastapi import Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Notice

@app.get('/test-db')
def test_db(db: Session = Depends(get_db)):
    notice = db.query(Notice).filter(Notice.id == 1).first()
    # for col in notice.table.columns:
    #     value = getattr(notice, col.name)
    #     print(col.name, col.type, type(value), repr(value)[:50])
    print(notice.title)
    return {"ok": True}
@app.get('/health')
def health():
    return {'status': 'ok'}
