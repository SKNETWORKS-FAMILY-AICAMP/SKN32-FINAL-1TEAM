"""관리자 대시보드(app/routers/admin.py)가 기대하는 초기 데이터를 채운다.

admin.py를 연결해보니 `verification_checklist_items`/`faqs` 두 테이블이 둘 다 비어
있어서, 라우터를 붙여도 `GET /admin/checklist`/`GET /admin/faqs`가 빈 배열만
돌려준다 — 이 둘은 seed_dummy_pipeline.py(프로젝트 하나짜리 파이프라인 결과)와
성격이 달라서(프로젝트에 안 딸린 전역 설정값 / 유저 질문) 별도 스크립트로 뺐다.

DB_BACKEND=sqlite 일 때만 동작한다 — seed_dummy_notices.py 등과 같은 이유로, 팀 공유
AWS MySQL에 가짜 FAQ 질문 같은 걸 실수로 쌓는 사고를 막기 위해서다.

체크리스트 8항목(R-4 "코드 8항목 자동 검증")은 팀이 확정한 실제 목록이 아직 없어서
(기능명세엔 "진입 파일 존재 여부" 같은 예시 한 개만 있음), 지금은 "이런 모양일
것이다"로 채운 자리표시 값이다 — 실제 항목/가중치는 나중에 관리자 화면
(PUT /admin/checklist)으로 얼마든지 바꿀 수 있고, enabled 항목 가중치 합은
지금도 100으로 맞춰뒀다(admin.py의 저장 검증과 동일한 규칙).

실행:
    python seed_dummy_admin_data.py
여러 번 실행해도 안전하다 — 이름/질문이 이미 있으면 건너뛴다.
"""
import datetime
import sys

from app.database import IS_SQLITE, SessionLocal, init_sqlite_dev_db
from app.models import Faq, User, VerificationChecklistItem, VerificationPolicy

# (name, method, category, weight, enabled) — enabled 항목 가중치 합계가 100이 되도록 맞춰둠
CHECKLIST_ITEMS = (
    ('진입 파일 존재 확인', '산출물 루트에 지정된 진입 파일(index.html 등)이 실제로 있는지 파일 존재 여부만 확인', '정적분석', 15, True),
    ('실행 파일 정상 로드', '헤드리스 브라우저로 진입 파일을 열어 5xx/파싱 에러 없이 렌더링되는지 확인', '실행검증', 15, True),
    ('콘솔 에러 없음', '위 렌더링 중 브라우저 콘솔에 찍힌 에러 로그가 있는지 스캔', '실행검증', 10, True),
    ('반응형 레이아웃 구현', 'viewport meta 태그와 CSS media query 존재 여부 파싱', '정적분석', 10, True),
    ('접근성 기본 준수', 'img alt 속성, 시맨틱 태그(header/main/nav 등) 사용 여부 파싱', '정적분석', 10, True),
    ('계획서 대비 기능 누락 확인', '계획서 featureList와 산출물 코드에 등장하는 기능명을 대조해 빠진 게 없는지 확인', '기능대조', 20, True),
    ('인포그래픽 포함 여부', '산출물 폴더에 이미지/SVG 파일이 실제로 존재하는지 확인', '정적분석', 10, True),
    ('빌드 산출물 크기 상한', '전체 산출물 용량이 정책상 상한(예: 50MB)을 넘지 않는지 확인', '정적분석', 10, True),
)

# (question, answer, is_visible) — answer가 None이면 미답변(관리자 답변 대기 상태) 그대로 둬서
# PUT /admin/faqs/{id}(답변 저장) 플로우를 테스트해볼 수 있게 한다.
FAQ_SEEDS = (
    ('프로토타입 재시도는 몇 번까지 가능한가요?',
     '기본 3회까지 가능하며, 관리자 화면의 재시도 상한(rerun_cap) 설정을 따릅니다.', True),
    ('사업계획서 다운로드는 어떤 형식으로 제공되나요?',
     'PDF와 원본 텍스트 두 가지 형식으로 다운로드하실 수 있습니다.', True),
    ('공고 매칭 기준은 어떻게 되나요?', None, False),
)


def main() -> None:
    if not IS_SQLITE:
        print(
            '[seed_dummy_admin_data] DB_BACKEND가 sqlite가 아니다 — 팀 공유 AWS MySQL로 보인다.\n'
            '                        더미 FAQ 질문 등을 실수로 쌓을 수 있어 중단한다.\n'
            '                        .env에 DB_BACKEND=sqlite 를 설정하고 다시 실행하세요.',
            file=sys.stderr,
        )
        raise SystemExit(1)

    init_sqlite_dev_db()  # 테이블이 아직 없으면 만든다 (이미 있으면 아무 일도 안 함)

    db = SessionLocal()
    try:
        if db.query(VerificationPolicy).order_by(VerificationPolicy.policy_id).first() is None:
            db.add(VerificationPolicy())
            print('[seed_dummy_admin_data] verification_policies 초기 행 생성(기본값 — pass_threshold=80)')

        existing_names = {i.name for i in db.query(VerificationChecklistItem).all()}
        added_items = 0
        for name, method, category, weight, enabled in CHECKLIST_ITEMS:
            if name in existing_names:
                continue
            db.add(VerificationChecklistItem(
                name=name, method=method, category=category, weight=weight, enabled=enabled,
            ))
            added_items += 1
        print(f'[seed_dummy_admin_data] verification_checklist_items {added_items}개 추가'
              f'(이미 있던 항목은 건너뜀, 전체 {len(CHECKLIST_ITEMS)}개 중)')

        # FAQ는 users.user_id NOT NULL FK라 유저가 하나는 있어야 한다 — 구글 로그인을
        # 한 번도 안 해본 완전 빈 DB에서 이 스크립트만 먼저 돌리는 경우까지 대비.
        user = db.query(User).order_by(User.user_id).first()
        if user is None:
            user = User(
                google_sub='dummy-admin-seed-user', email='dummy-faq-user@example.com',
                name='더미유저(FAQ용)', role='user', status='active',
            )
            db.add(user)
            db.flush()  # user.user_id 확보
            print('[seed_dummy_admin_data] FAQ를 달 유저가 하나도 없어 더미 유저를 하나 만듦')

        existing_questions = {f.question for f in db.query(Faq).all()}
        added_faqs = 0
        for question, answer, is_visible in FAQ_SEEDS:
            if question in existing_questions:
                continue
            db.add(Faq(
                user_id=user.user_id, question=question, answer=answer, is_visible=is_visible,
                answered_at=datetime.datetime.utcnow() if answer else None,
            ))
            added_faqs += 1
        print(f'[seed_dummy_admin_data] faqs {added_faqs}개 추가'
              f'(이미 있던 질문은 건너뜀, 전체 {len(FAQ_SEEDS)}개 중)')

        db.commit()
    finally:
        db.close()

    print('[seed_dummy_admin_data] 완료 — GET /admin/checklist, GET /admin/faqs 로 확인 가능')


if __name__ == '__main__':
    main()
