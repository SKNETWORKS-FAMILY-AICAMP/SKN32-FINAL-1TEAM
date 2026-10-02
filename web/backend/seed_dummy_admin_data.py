"""관리자 대시보드(app/routers/admin.py)가 기대하는 초기 데이터를 채운다.

admin.py를 연결해보니 `verification_checklist_items`/`faqs` 두 테이블이 둘 다 비어
있어서, 라우터를 붙여도 `GET /admin/checklist`/`GET /admin/faqs`가 빈 배열만
돌려준다 — 이 둘은 seed_dummy_pipeline.py(프로젝트 하나짜리 파이프라인 결과)와
성격이 달라서(프로젝트에 안 딸린 전역 설정값 / 유저 질문) 별도 스크립트로 뺐다.

DB_BACKEND=sqlite 일 때만 동작한다 — seed_dummy_notices.py 등과 같은 이유로, 팀 공유
AWS MySQL에 가짜 FAQ 질문 같은 걸 실수로 쌓는 사고를 막기 위해서다.

[2026-09-22 구조 교체, 프론트 전달사항 10번] 예전엔 팀이 확정한 실제 목록이 없어서
(기능명세엔 예시 한 개뿐) "이런 모양일 것이다"로 채운 5항목/100점 자리표시 값이었다.
이제 기획서 v1.8 5-4 기준(산출물 카테고리별 8항목, 합계 15점)이 확정돼서 그대로 옮겼다
— html(웹개발·AI API)/svg(원페이지) 두 세트, 세트마다 8항목·15점(models.py
VerificationChecklistItem 참고). 실제 항목/가중치는 여전히 관리자 화면
(PUT /admin/checklist)으로 바꿀 수 있다 — 다만 저장 검증은 이제 "카테고리별 합계 15점"
기준이다(admin.py save_checklist).

실행:
    python seed_dummy_admin_data.py
여러 번 실행해도 안전하다 — item_code/질문이 이미 있으면 건너뛴다.
"""
import datetime
import sys

from app.database import IS_SQLITE, SessionLocal, init_sqlite_dev_db
from app.models import Faq, User, VerificationChecklistItem, VerificationPolicy

# (item_code, item_no, category, name, method, weight, enabled) — 카테고리(html/svg)별로
# enabled 항목 가중치 합계가 15가 되도록 맞춰둠. app_schema.sql의 INSERT와 같은 데이터.
CHECKLIST_ITEMS = (
    # 웹개발·AI API(HTML) — 8항목, 합계 15점
    ('CHECK-HTML-ENTRY-FILE', 1, 'html', '진입 파일 존재 여부', '산출물 루트에 지정된 진입 파일(index.html 등)이 실제로 있는지 확인', 3.00, True),
    ('CHECK-HTML-ALT-TEXT', 2, 'html', 'img·svg 대체 텍스트', 'img/svg 요소에 alt(또는 대체 텍스트 접근법)가 있는지 파싱', 2.00, True),
    ('CHECK-HTML-INPUT-LABEL', 3, 'html', 'input label 연결', 'input 요소가 label(for/aria-label 등)로 연결돼 있는지 파싱', 2.00, True),
    ('CHECK-HTML-LANG-ATTR', 4, 'html', 'html lang 속성', '<html> 태그에 lang 속성이 있는지 확인', 1.00, True),
    ('CHECK-HTML-CONTRAST', 5, 'html', '명도 대비 4.5:1', '주요 텍스트·배경 색상 조합의 명도 대비가 4.5:1 이상인지 계산', 2.00, True),
    ('CHECK-HTML-HEADING', 6, 'html', '제목 계층', 'h1~h6 제목 태그가 순서를 건너뛰지 않고 계층적으로 쓰였는지 확인', 2.00, True),
    ('CHECK-HTML-README', 7, 'html', '실행·열람 안내 문서', '실행 방법을 설명하는 안내 문서(README 등)가 있는지 확인', 1.00, True),
    ('CHECK-HTML-SECRET', 8, 'html', '하드코딩된 비밀값', 'API 키·비밀번호 등이 코드에 하드코딩돼 있는지 패턴 스캔', 2.00, True),
    # 원페이지(SVG) — 8항목, 합계 15점
    ('CHECK-SVG-ENTRY-FILE', 1, 'svg', '진입 파일 존재 여부', '산출물 루트에 지정된 진입 파일(svg 등)이 실제로 있는지 확인', 3.00, True),
    ('CHECK-SVG-ALT-TEXT', 2, 'svg', '대체 텍스트', '이미지·아이콘 요소에 대체 텍스트가 있는지 파싱', 2.00, True),
    ('CHECK-SVG-KEY-INFO', 3, 'svg', '핵심 정보 항목 포함', '계획서가 요구하는 핵심 정보 항목이 실제로 담겨 있는지 확인', 2.00, True),
    ('CHECK-SVG-CONTRAST', 4, 'svg', '명도 대비 4.5:1', '주요 텍스트·배경 색상 조합의 명도 대비가 4.5:1 이상인지 계산', 2.00, True),
    ('CHECK-SVG-INFO-HIERARCHY', 5, 'svg', '정보 계층', '정보가 중요도 순으로 시각적 계층을 이루는지 확인', 2.00, True),
    ('CHECK-SVG-TEXT-REALNESS', 6, 'svg', '텍스트 실재성', '텍스트가 이미지가 아니라 실제 선택 가능한 텍스트 요소인지 확인', 2.00, True),
    ('CHECK-SVG-MIN-FONT-SIZE', 7, 'svg', '최소 글자 크기', '본문 텍스트가 정책상 최소 글자 크기 이상인지 확인', 1.00, True),
    ('CHECK-SVG-README', 8, 'svg', '열람 안내 문서', '결과물 열람 방법을 설명하는 안내 문서가 있는지 확인', 1.00, True),
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

        # [2026-09-22] name은 이제 카테고리(html/svg)를 넘나들며 겹친다(둘 다 "진입 파일
        # 존재 여부" 등) — item_code(카테고리+항목까지 포함해 고유)로 중복을 가른다.
        existing_codes = {i.item_code for i in db.query(VerificationChecklistItem).all()}
        added_items = 0
        for item_code, item_no, category, name, method, weight, enabled in CHECKLIST_ITEMS:
            if item_code in existing_codes:
                continue
            db.add(VerificationChecklistItem(
                item_code=item_code, item_no=item_no, category=category,
                name=name, method=method, weight=weight, enabled=enabled,
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
