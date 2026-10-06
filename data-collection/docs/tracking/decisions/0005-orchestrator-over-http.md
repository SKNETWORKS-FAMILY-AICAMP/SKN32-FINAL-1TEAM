# 0005. 조율 에이전트는 공고 서버를 HTTP로 부른다

- 날짜: 2026-10-03(조율 담당 결정), 2026-10-06 구현 · 2026-09-29 결정을 대체

## 배경
9/29에는 조율 쪽 프로세스가 `search.app.boot()`를 한 번 부르고 `app.match()`를 직접 import하는 방식이었다(설명서 `docs/guides/ORCHESTRATION_HANDOFF.md`). boot 약 22초·메모리 약 2.1GB를 조율 프로세스가 떠안고, 우리 함수 모양이 바뀌면 조율 쪽 코드가 깨졌다. 10/3 조율 담당이 HTTP 호출로 바꾸고 새 창구 3개와 추천 결과 키 3개를 요청했다.

## 결정
공고 서버(`search/app.py`)에 `GET /api/collection_status`, `GET /api/notices/{id}`, `POST /api/notices/{id}/eligibility`를 열고, `/api/match` 결과에 `content_version`·`bonus_score`·`bonus_items`를 더한다. 판정 코드는 화면용과 조율용이 한 곳(`search/eligibility.py`)을 쓴다.

## 대안
- 직접 import 유지: 메모리·기동 시간을 조율 쪽이 떠안고, 두 코드가 같은 저장소 버전에 묶인다.
- 조율 쪽 어댑터를 우리 폴더에 두기: "우리는 코드를 연결하지 않고 전달하는 입장"이라는 사용자 판단으로 하지 않았다.

## 결과
- 응답 키·값이 계약이 된다. 바꾸기 전에 조율 담당에게 알릴 문서를 먼저 고친다.
- 공고 서버를 따로 배포해야 한다(위치·인증 미정). 서버 데이터가 켠 시점 기준이라 수집 상태에 "서버가 올린 공고의 나이"를 넣었다.
- 9/29 설명서(`ORCHESTRATION_HANDOFF.md`)는 지난 방식 기록이다.
