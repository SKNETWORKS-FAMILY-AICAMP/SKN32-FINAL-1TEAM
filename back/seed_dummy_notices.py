"""로컬 SQLite 개발 DB(dev.db)에 더미 공고를 몇 개 넣어준다.

DB_BACKEND=sqlite 일 때만 동작한다 — 실수로 팀 공유 AWS MySQL에 가짜 공고를
넣는 사고를 막으려고, mysql 모드일 때는 아무 것도 안 하고 바로 종료한다.
notices 테이블은 원래 공고 수집 파이프라인(이근준님 repo)이 채워주는 테이블이라
백엔드가 직접 쓸 일이 없지만, 로컬 개발 중 매칭/공고 조회 로직을 테스트해보려면
행이 몇 개는 있어야 해서 만든 용도다.

embedding_status/embedding_updated_at/embedding_fail_reason 값도 같이 넣는다.
이 3개는 실제 AWS MySQL엔 아직 없는 컬럼이라 models.py의 Notice에도 SQLite 모드일
때만 존재한다(app/models.py의 `if IS_SQLITE:` 블록 참고) — 이 스크립트 자체가
DB_BACKEND=sqlite 가 아니면 아예 실행을 거부하니, 여기서 이 필드들을 채워도
실제 DB와 어긋날 걱정 없이 항상 안전하다.

실행:
    python seed_dummy_notices.py
여러 번 실행해도 안전하다 — notice_id가 이미 있으면 건너뛴다.
"""
import datetime
import sys

from app.database import IS_SQLITE, SessionLocal, init_sqlite_dev_db
from app.models import Notice

DUMMY_NOTICES = [
    # K-Startup 공고 — organizer만 채워짐 (supervising_org/executing_org는 K-Startup에 없음)
    dict(
        notice_id='kstartup:PBLN_0001',
        source='kstartup',
        title='2026년 예비창업패키지(일반분야) 창업지원사업 모집공고',
        target_text='예비창업자, 사업자등록 이력이 없는 자',
        category='예비창업',
        organizer='중소벤처기업부',
        supervising_org=None,
        executing_org=None,
        apply_start=datetime.date(2026, 9, 1),
        apply_end=datetime.date(2026, 10, 31),
        recruitment_status='open',
        url='https://www.k-startup.go.kr/example/PBLN_0001',
        embedding_status='completed',
        embedding_updated_at=datetime.datetime(2026, 9, 2, 10, 0, 0),
        embedding_fail_reason=None,
    ),
    dict(
        notice_id='kstartup:PBLN_0002',
        source='kstartup',
        title='2026년 초기창업패키지 지원사업 통합공고',
        target_text='창업 3년 이내 기업',
        category='초기창업',
        organizer='창업진흥원',
        supervising_org=None,
        executing_org=None,
        apply_start=datetime.date(2026, 8, 1),
        apply_end=datetime.date(2026, 9, 30),
        recruitment_status='open',
        url='https://www.k-startup.go.kr/example/PBLN_0002',
        embedding_status='pending',
        embedding_updated_at=None,
        embedding_fail_reason=None,
    ),
    dict(
        notice_id='kstartup:PBLN_0003',
        source='kstartup',
        title='2026년 K-Startup 청년창업사관학교 모집(마감)',
        target_text='만 39세 이하 예비창업자',
        category='예비창업',
        organizer='중소벤처기업진흥공단',
        supervising_org=None,
        executing_org=None,
        apply_start=datetime.date(2026, 3, 1),
        apply_end=datetime.date(2026, 4, 30),
        recruitment_status='closed',
        url='https://www.k-startup.go.kr/example/PBLN_0003',
        embedding_status='completed',
        embedding_updated_at=datetime.datetime(2026, 3, 2, 9, 0, 0),
        embedding_fail_reason=None,
    ),
    # 기업마당 공고 — supervising_org/executing_org 중 있는 값만 채워짐 (organizer는 없음)
    dict(
        notice_id='bizinfo:PBLN_1001',
        source='bizinfo',
        title='2026년 소상공인 디지털 전환 지원사업',
        target_text='소상공인, 1인 자영업자',
        category='디지털전환',
        organizer=None,
        supervising_org='중소벤처기업부',
        executing_org='소상공인시장진흥공단',
        apply_start=datetime.date(2026, 9, 5),
        apply_end=datetime.date(2026, 11, 15),
        recruitment_status='open',
        url='https://www.bizinfo.go.kr/example/PBLN_1001',
        embedding_status='completed',
        embedding_updated_at=datetime.datetime(2026, 9, 6, 11, 30, 0),
        embedding_fail_reason=None,
    ),
    dict(
        notice_id='bizinfo:PBLN_1002',
        source='bizinfo',
        title='2026년 중소기업 수출바우처 지원사업',
        target_text='수출 실적 보유 중소기업',
        category='수출지원',
        organizer=None,
        supervising_org='산업통상자원부',
        executing_org=None,
        apply_start=datetime.date(2026, 7, 1),
        apply_end=datetime.date(2026, 9, 20),
        recruitment_status='open',
        url='https://www.bizinfo.go.kr/example/PBLN_1002',
        embedding_status='failed',
        embedding_updated_at=datetime.datetime(2026, 7, 2, 8, 0, 0),
        embedding_fail_reason='임베딩 API 타임아웃',
    ),
    dict(
        notice_id='bizinfo:PBLN_1003',
        source='bizinfo',
        title='2026년 지역특화산업 육성사업(마감)',
        target_text='비수도권 소재 중소기업',
        category='지역산업',
        organizer=None,
        supervising_org=None,
        executing_org='한국산업기술진흥원',
        apply_start=datetime.date(2026, 2, 1),
        apply_end=datetime.date(2026, 3, 31),
        recruitment_status='closed',
        url='https://www.bizinfo.go.kr/example/PBLN_1003',
        embedding_status='pending',
        embedding_updated_at=None,
        embedding_fail_reason=None,
    ),
]


def main() -> None:
    if not IS_SQLITE:
        print(
            '[seed_dummy_notices] DB_BACKEND가 sqlite가 아니다 — 팀 공유 AWS MySQL로 보인다.\n'
            '                     여기에 더미 공고를 넣으면 안 되니 중단한다.\n'
            '                     .env에 DB_BACKEND=sqlite 를 설정하고 다시 실행하세요.',
            file=sys.stderr,
        )
        raise SystemExit(1)

    init_sqlite_dev_db()  # 테이블이 아직 없으면 만든다 (이미 있으면 아무 일도 안 함)

    db = SessionLocal()
    try:
        inserted, skipped = 0, 0
        for row in DUMMY_NOTICES:
            exists = db.query(Notice).filter(Notice.notice_id == row['notice_id']).one_or_none()
            if exists is not None:
                skipped += 1
                continue
            db.add(Notice(**row))
            inserted += 1
        db.commit()
        print(f'[seed_dummy_notices] 완료 — 새로 추가 {inserted}건, 이미 있어서 건너뜀 {skipped}건 '
              f'(전체 {len(DUMMY_NOTICES)}건 중)')
    finally:
        db.close()


if __name__ == '__main__':
    main()