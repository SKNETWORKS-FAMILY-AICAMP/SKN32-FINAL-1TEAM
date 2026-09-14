"""[기존 유저] 이어하기 8케이스(기획서 v1.7 4-7절, p.20 표)를 match_results.stage/
progress_percent 컬럼을 추가한 뒤 실제로 구분해낼 수 있는지 재검증한다.

이전 버전(자식 행 존재 여부만으로 판별)에서는 8케이스 중 6개가 3개 그룹으로 뭉쳐
서로 구분이 안 됐다(existing_user_resume_test_report.md). 이번엔 각 케이스가 실제
파이프라인(다른 팀원이 만들 오케스트레이터)에서 남길 stage 값을 직접 채워서 DB
상태를 만들고, app/pipeline_stages.py 상수 기준 신규 판별 함수에 넣어 8개가 전부
구분되는지 확인한다."""
import datetime
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python verify_resume_cases.py`로 실행하는 걸 전제로 한다.
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)
os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

# dev.db가 예전 스키마(컬럼 추가 전)로 이미 만들어져 있으면 SQLAlchemy의
# create_all()은 기존 테이블을 건드리지 않고 그냥 넘어간다 — 그래서 매번 지우고
# 새로 만든다. 같은 dev.db를 다른 용도(실제 로그인 플로우 테스트 등)로 계속
# 쓰고 있었다면, 이 스크립트를 돌릴 때마다 그 데이터는 초기화된다는 점 참고.
_DEV_DB = os.path.join(_REPO_ROOT, 'dev.db')
if os.path.exists(_DEV_DB):
    os.remove(_DEV_DB)

import app.database as appdb  # noqa: E402
from app import pipeline_stages as ps  # noqa: E402
from app.models import Company, EligibilityCheck, MatchResult, Notice, Project, User  # noqa: E402

appdb.init_sqlite_dev_db()
db = appdb.SessionLocal()

user = User(email='resume@example.com', name='이어하기테스트', google_sub='resume-sub', notify_enabled=True)
db.add(user)
db.commit()

company = Company(user_id=user.user_id, start_type='온라인', biz_type='AI 서비스', ceo_name='이어하기테스트')
db.add(company)
db.commit()

notice = Notice(
    notice_id='kstartup:RESUME_TEST', source='kstartup', title='이어하기 테스트용 공고',
    recruitment_status='open', apply_start=datetime.date(2026, 1, 1), apply_end=datetime.date(2026, 12, 31),
)
db.add(notice)
db.commit()


def detect_resume_screen(db, project_id: int):
    """실제 GET /projects/{id}/status 가 하게 될 판별 로직 — match_results.stage를
    app/pipeline_stages.STAGE_TO_SCREEN으로 화면 번호로 바꾼다. match 자체가 없으면
    아직 공고도 안 골랐다는 뜻이라 NO_MATCH_SCREEN(3)으로 돌려보낸다."""
    match = (
        db.query(MatchResult).filter(MatchResult.project_id == project_id)
        .order_by(MatchResult.match_id.desc()).first()
    )
    if match is None:
        return ps.NO_MATCH_SCREEN, None
    if match.stage is None:
        return None, None  # 마이그레이션 이전 데이터 등 — 화면을 못 정한다
    return ps.STAGE_TO_SCREEN.get(match.stage), match.progress_percent


def make_project(desc: str) -> int:
    p = Project(company_id=company.company_id, description=desc, notify_region='서울', notify_industry='IT')
    db.add(p)
    db.commit()
    return p.project_id


def base_match(project_id: int, stage: str, progress_percent: int | None = None) -> MatchResult:
    m = MatchResult(
        project_id=project_id, notice_id=notice.notice_id, status='in_progress',
        stage=stage, progress_percent=progress_percent,
    )
    db.add(m)
    db.commit()
    db.add(EligibilityCheck(match_id=m.match_id, passed=True))
    db.commit()
    return m


CASES = [
    # (표기, 기대 화면, DB 상태 구성 함수)
    ('① 공고 선택 전', 3, lambda: make_project('①: 공고 선택 전')),
    ('② 자격요건 통과 후 작성 전', 5, lambda: base_match(
        make_project('②: 작성 전'), ps.STAGE_PLAN_WRITING, progress_percent=0,
    ).project_id),
    ('③ 계획서 작성 중 (진행률 이어받기)', 5, lambda: base_match(
        make_project('③: 작성 중'), ps.STAGE_PLAN_WRITING, progress_percent=45,
    ).project_id),
    ('④ 문서 평가 판단 대기', 6, lambda: base_match(
        make_project('④: 문서 평가 판단 대기'), ps.STAGE_PLAN_REVIEW_PENDING,
    ).project_id),
    ('⑤ 프로토타입 제작 중', 7, lambda: base_match(
        make_project('⑤: 프로토타입 제작 중'), ps.STAGE_PROTOTYPE_BUILDING, progress_percent=60,
    ).project_id),
    ('⑥ 산출물 확인 중', 8, lambda: base_match(
        make_project('⑥: 산출물 확인 중'), ps.STAGE_ARTIFACT_REVIEW,
    ).project_id),
    ('⑦ 종합 평가 판단 대기', 9, lambda: base_match(
        make_project('⑦: 종합 평가 판단 대기'), ps.STAGE_FINAL_REVIEW_PENDING,
    ).project_id),
    ('⑧ 검수 이후', 11, lambda: base_match(
        make_project('⑧: 검수 이후'), ps.STAGE_DONE,
    ).project_id),
]

print('=== 이어하기 8케이스 재검증 (stage 컬럼 반영 후) ===')
all_ok = True
for label, expected_screen, build_fn in CASES:
    project_id = build_fn()
    screen, progress = detect_resume_screen(db, project_id)
    ok = screen == expected_screen
    all_ok = all_ok and ok
    mark = 'OK' if ok else 'FAIL'
    progress_note = f', progress_percent={progress}' if progress is not None else ''
    print(f'[{mark}] {label:32s} -> 화면 {screen} (기대: {expected_screen}){progress_note}')

print()
if all_ok:
    print('결과: 8케이스 전부 기획서 표 19가 정한 화면으로 정확히 돌아감 (이전 6/8 뭉침 문제 해소).')
    print('②·③번은 원래 표에서도 둘 다 화면 5로 같이 가게 돼 있고(계획서 작성 화면 하나에서 '
          '시작 전/진행 중을 같이 다룸), progress_percent로 ③번이 요구하는 "진행률 이어받기"까지 '
          '별도로 복원 가능한 걸 확인했다.')
else:
    print('결과: 기대한 화면과 다르게 나온 케이스가 있음 — 위 FAIL 항목 확인.')

db.close()
assert all_ok, '이어하기 화면 판별에 실패한 케이스가 있다'