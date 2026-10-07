-- [SB-270, 2026-10-07] 관리자 '코드 기준 자동 검증 항목'을 검증-2(SB-125)의 실제 코드 점검 8항목으로 바꾼다.
--
-- 예전 목록(진입 파일 · README · 비밀값 · html lang 등)은 검증-2가 채점하지 않는 항목이었다. 진입 파일 · 비밀값 · 저장소 API는
-- 항목이 아니라 통과 필수 조건(어기면 산출물층 0점)이다. 이 표는 화면 표시 · 설정용이고 채점에 쓰이지 않는다(점수는 검증-2가 계산).
-- 관리자가 바꾼 가중치 · 사용 여부는 초기화된다. 이 표를 참조하는 외래 키는 없다. 몇 번을 실행해도 결과가 같다.
--
-- 실행: mysql -u <계정> -p <DB 이름> < migrations/003_checklist_items_sb125.sql

DELETE FROM verification_checklist_items;
INSERT INTO verification_checklist_items (item_code, item_no, category, name, method, weight, enabled) VALUES
    ('CHECK-HTML-WIRING', 1, 'html', '동작 연결', '버튼 · 링크 · 입력칸이 화면 동작에 쓰이는지(요소에 직접 붙은 이벤트 · 스크립트가 값을 읽는 입력칸). 비율로 구간 점수(100% 3 · 80% 2 · 50% 1)', 3.00, TRUE),
    ('CHECK-HTML-ALT-TEXT', 2, 'html', 'img·svg 대체 텍스트', '모든 img에 alt, 모든 svg에 title 또는 aria-label. 인포그래픽도 함께 본다(그림이 없으면 해당 없음)', 2.00, TRUE),
    ('CHECK-HTML-INPUT-LABEL', 3, 'html', 'input label 연결', '입력칸마다 label for · aria-label(ledby) · label 안에 넣기 중 하나(입력칸이 없으면 해당 없음)', 2.00, TRUE),
    ('CHECK-HTML-CONTRAST', 4, 'html', '명도 대비 4.5:1', 'color와 background-color를 함께 적은 모든 셀렉터가 4.5:1 이상(투명 배경은 제외)', 2.00, TRUE),
    ('CHECK-HTML-HEADING', 5, 'html', '제목 계층', 'h1이 정확히 1개이고, 내려갈 때 단계를 건너뛰지 않는지', 1.00, TRUE),
    ('CHECK-HTML-WIDTH', 6, 'html', '1440px 폭 안에 들어옴', 'width · min-width에 1440px을 넘는 값이 없는지(max-width는 보지 않음)', 2.00, TRUE),
    ('CHECK-HTML-SCRIPT', 7, 'html', '스크립트 동작 오류 없음', '스크립트가 찾는 id가 전부 문서에 있고, 무시되는 API가 없는지(둘 다 없으면 해당 없음)', 2.00, TRUE),
    ('CHECK-HTML-PLACEHOLDER', 8, 'html', '임시 문구 없음', '보이는 글자에 lorem ipsum · TODO: · FIXME · TBD · "샘플 텍스트" 등이 없는지', 1.00, TRUE),
    ('CHECK-SVG-ALT-TEXT', 1, 'svg', '대체 텍스트', 'title과 desc가 있고 서로 다른 문장이며, desc가 지면의 필수 값 2개 이상을 담는지', 2.00, TRUE),
    ('CHECK-SVG-KEY-INFO', 2, 'svg', '핵심 정보 6항목', '아이템명 · 목표 고객 · 문제 정의 · 해결 방안 · 수익모델 단가 · 추진 일정 기준선이 실재하는지. 개수로 구간 점수', 3.00, TRUE),
    ('CHECK-SVG-CONTRAST', 3, 'svg', '명도 대비 4.5:1', '사각형 위에 놓인 글자가 전부 4.5:1 이상(판정할 글자가 없으면 미충족)', 2.00, TRUE),
    ('CHECK-SVG-INFO-HIERARCHY', 4, 'svg', '정보 계층', '글자 크기가 제목 > 라벨 ≥ 값이고, 크기 단계가 3단 이상인지', 2.00, TRUE),
    ('CHECK-SVG-NO-TRUNCATION', 5, 'svg', '잘림 없음', '표식이 달린 값 중 말줄임표로 끝나는 것이 없는지', 2.00, TRUE),
    ('CHECK-SVG-NO-OVERFLOW', 6, 'svg', '지면 밖 넘침 없음', '글자 시작점이 지면 안에 있는지', 2.00, TRUE),
    ('CHECK-SVG-TEXT-REALNESS', 7, 'svg', '텍스트 실재성', '<text>가 있고, 보이는 그림 면적이 지면의 35% 이하인지', 1.00, TRUE),
    ('CHECK-SVG-MIN-FONT-SIZE', 8, 'svg', '최소 글자 크기', '모든 글자가 12px 이상인지', 1.00, TRUE);
