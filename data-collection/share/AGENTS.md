# share/ — 서버 없이 보는 공유 HTML

## 맡는 것
- 검증 화면(8010)의 결과를 데이터까지 한 파일에 넣은 HTML 6장: `매칭방식비교.html`, `전체흐름.html`, `업종추출결과.html`, `Jev채점시험.html`, `신청자유형.html`, `테이블구조.html`. 같은 페이지를 claude.ai에 비공개로 올려 두었다(공유는 소유자가 각 페이지에서).
- 생성 스크립트: `build_filter_first.py`(+ `filter_first.template.html`), `build_industry.py`, `build_jev.py`(+ `jev_template.html`), `build_applicant_types.py`(+ `applicant_types.template.html`).

## 맡지 않는 것
- 결과 계산. 스크립트는 `reports/`의 정해진 결과 폴더와 `experiments/`·`search/`의 표시 함수를 **읽기만** 한다(DB·모델·유료 API 호출 없음).
- `전체흐름.html`·`테이블구조.html`은 손으로 쓴 페이지다. 스크립트로 만들지 않는다.

## 항상 지켜야 할 것
- 생성 스크립트는 자기 위치의 한 단계 위를 data-collection으로 본다. 파일 경로로 실행한다: `.\.venv\Scripts\python.exe -X utf8 share\build_<이름>.py`.
- `build_industry.py`는 페이지 안 `/*DATA*/ … /*END*/` 구간만 다시 채운다. 그 표시를 지우지 않는다.
- 다시 만든 페이지가 게시본과 같아야 한다(2026-09-29 확인: 업종·Jev·신청자 유형은 바이트까지 같음). 데이터 원본 폴더를 바꾸면 이 폴더 README 표도 고친다.
- 페이지에 키·접속 정보·실제 신청자 정보를 넣지 않는다. AI 판정은 "AI 참고 정답"으로 표시한다.
- 글꼴만 외부(Google Fonts)에서 불러온다. 다른 외부 스크립트를 넣지 않는다(파일만 열어 보여야 한다).

## 이 폴더의 방식
- 템플릿 + 데이터 JSON 삽입. 첫 줄에 charset 선언을 둔다.

## 시험
- 자동 시험은 없다. 다시 만든 뒤 브라우저로 열어 보고, 게시본과 비교한다.
