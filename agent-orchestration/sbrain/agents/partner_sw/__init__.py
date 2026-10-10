"""전략 · 작성 · 검증-1 담당자 코드(F01 ~ F19)와 그 연결 코드 (spec 4.1).

- agent_strategy/ · agent_validation_1/ — 담당자 코드를 폴더 이름 그대로 옮긴 것(2026-10-08 받음). 바꾼 곳은 연결부뿐이고
  VENDORED.md에 모두 적었다. 담당자 새 판을 받으면 그 목록으로 비교한다.
- 바로 아래 파일 — 우리 연결 코드:
  - purposes.py: 호출 목적 이름(F번호) 상수
  - calls.py: 담당자 LLM 호출의 호출 수단(tools · 지시문) 전달과 메시지 모양(spec 4.4)
  - resources.py: 담당자 자료 파일(JSON · MD)을 불러올 때 한 번 읽어 둔 상수 — Task 실행 중 파일을 열지 않는다
  - contract.py: 담당자 실행 계약 · 채점 정책 · 항목 기준(양식 묶음 form_defaults가 읽는다)

이 파일은 아무것도 불러오지 않는다 — contract만 쓰는 곳(양식 묶음)이 담당자 자료 전체를 읽지 않게.
"""
