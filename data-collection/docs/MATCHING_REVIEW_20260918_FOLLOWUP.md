# 공고 매칭 수정 재검토 — 2026-09-18

검토자: Codex. 대상: Claude의 '검토 지적 4번·1번 수정(자격 판정·규칙 우선순위)'.
원 검토는 [MATCHING_REVIEW_20260918.md](MATCHING_REVIEW_20260918.md)를 참조한다.
수정 범위는 `search/gate.py`, `search/app.py`, 신규 `tests/test_match_rules.py`다.
이번 재검토에서는 서비스·테스트 코드를 수정하지 않았다.

## 발견 사항

### [P2] 달력상 유효하지 않은 설립일은 여전히 HTTP 500을 일으킨다

- 위치: `search/gate.py:87-89`, 호출되는 `parse_ymd()`의 `99-102`행.
- 입력: 법인사업자, `founded_at='2026-02-30'`.
- 실제: `business_age_months()`가 `parse_ymd()`를 호출하면 `date.fromisoformat()`에서
  `ValueError: day is out of range for month`가 발생한다. `/api/match`와 `/api/eligibility`가 모두 HTTP 500을 반환한다.
- 같은 결과: `20260230`, `2026-13-01`, 윤년이 아닌 해의 `2025-02-29`.
- 원인: 수정은 `parse_ymd()`가 None을 반환하는 경우만 처리한다. 날짜 형식에 맞는 문자열은
  Python 날짜 생성까지 들어가므로 실제 날짜가 유효하지 않으면 예외가 발생하고 None 검사에 도달하지 못한다.
- 기대: 현재 구현 의도대로 설립일 미상·판단 불가로 처리하거나 API 입력 오류로 4xx를 반환해야 한다.
  잘못된 설립일 하나로 전체 검색·자격 확인이 서버 오류로 끝나면 안 된다.
- 수정 방향: 날짜 변환의 `ValueError`를 처리하고, 회귀 테스트에 형식 오류 외에 존재하지 않는 날짜도 추가한다.
  기존의 `test_broken_founded_date_is_also_unknown`은 '설립일'이라는 문자열만 사용해 이 경우를 검증하지 못한다.

이 문제는 이번 수정으로 새로 생긴 회귀가 아니라, 이번에 추가한 날짜 오류 방어에서 빠진 경우다.

## 해결 확인

| 기존 문제 | 재검토 결과 |
|---|---|
| 1번: 시군구 규칙이 시도 순위를 뒤집음 | 해결 확인. 동일 후보에 경기 수원 신청 시 **수원 → 성남 → 서울**. dense와 hybrid 모두 확인 |
| 4번: 설립일 누락 사업자를 예비창업자로 취급 | 빈 값·'설립일' 문자열은 **설립일 미상 / 판단 불가**로 처리. 정상 날짜·예비창업자의 기존 판정도 테스트 통과 |
| 2번: score 모드 RRF·코사인 점수 혼용 | 수정 범위 밖. 후보 51위가 1위로 올라가는 기존 재현 유지 |
| 3번: 마감 제외 후 후보 미보충 | 수정 범위 밖. 접수 중 9건이 있어도 결과 0건인 기존 재현 유지 |

현재 재정렬 키는 시도 불일치 → 시군구 불일치 → 집단 근거 없음 → 기존 순서다.
규칙의 우선순위를 한 번의 정렬에 모아 기존 덮어쓰기 문제를 해결한 것을 확인했다.

## 검증

- `test_gate.py` 18개 + `test_applicant.py` 15개 + `test_match_rules.py` 9개 = **42개 통과**, 건너뜀 없음.
- 별도 가상 데이터: 지역 순서를 dense/hybrid 각각 확인하고, 이전 2번·3번의 미해결 동작도 재확인.
- FastAPI `TestClient(raise_server_exceptions=False)`로 날짜 입력 7종 × API 2개 = **14개 응답 확인**.
  빈 문자열, '설립일', `2025-01-01`은 두 API 모두 200.
  위 네 종류의 존재하지 않는 날짜는 두 API 모두 500.
- DB·임베딩 모델은 mock으로 대체했다. 외부 네트워크나 실제 서버·DB·모델은 호출하지 않았다.
- 실행기: 번들 Python 3.12.14. 현재 프로세스의 `PYTHONPATH`에 기존 `.venv/Lib/site-packages`를 연결하고 `-B -X utf8` 사용.
  환경 파일 변경·패키지 설치 없음. 전체 테스트와 실제 검색 품질 평가는 이번 범위에서 실행하지 않았다.

실행기 경로: `C:\Users\playdata2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
테스트는 `unittest.defaultTestLoader.discover('tests', pattern=...)`로 위 세 파일을 한 suite로 구성해 실행했다.

문제 재현 예시(작업 디렉터리 `data-collection`, 기존 프로젝트 패키지를 사용할 수 있는 Python에서 실행):

```python
import sys
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0, 'tests')
from test_match_rules import notice, state
from search import app

rows = {'n001': notice('n001')}
with patch.dict(app.STATE, state(rows), clear=True):
    with TestClient(app.app, raise_server_exceptions=False) as client:
        for route, extra in (
            ('/api/match', {'idea': '창업 지원'}),
            ('/api/eligibility', {'notice_id': 'n001'}),
        ):
            response = client.post(route, json={
                'applicant_type': '법인사업자',
                'founded_at': '2026-02-30',
                **extra,
            })
            print(route, response.status_code)  # 현재 두 경로 모두 500
```

이 입력은 질의 인코딩 전에 실패하므로 위 최소 재현은 실제 임베딩 모델을 로드하지 않는다.
이번 검토는 새 날짜 오류 한 건을 보고하고, 기존 1번·4번 수정의 기본 동작을 확인한 것으로 종료했다.

## 후속 확인 — 무효 날짜 오류 해결

2026-09-18 · Codex. 위 본문은 오류 발견 당시 기록이며 아래는 Claude의 추가 수정 후 확인이다.

`parse_ymd()`가 날짜 생성 과정의 `ValueError`를 잡아 None으로 처리하도록 바뀌었다.
지난번 지적한 무효 날짜가 이제 '설립일 미상 / 판단 불가'로 연결된다.
이번 수정 범위에서 추가로 발견한 문제는 없다.

- 관련 테스트: `test_gate.py` 18개, `test_applicant.py` 15개, `test_match_rules.py` 12개, **총 45개 통과**.
- 별도 TestClient 확인: 아래 11종을 `/api/match`와 `/api/eligibility`에 각각 전송해 **22건 모두 HTTP 200**.
  DB·모델은 기존 가상 색인과 `_encode` mock으로 대체했다.
  - 무효·빈 값 8종: 빈 문자열, '설립일', `2026-02-30`, `20260230`, `2026-13-01`, `2025-02-29`, `2026-00-10`, `0000-01-01`.
  - 정상 날짜 3종: `2024-02-29`, `20240229`, `2025-01-01`.
- 응답 내용: 무효 입력의 업력 판정은 None이고 내 값은 '설립일 미상'. 정상 입력은 공고 '7년미만' 조건을 충족.
  매칭 API는 가상 공고 1건을 정상 반환했다.
- 추가 확인: 윤년 정상 날짜의 두 표기에서 같은 업력이 계산되며, 공고의 `apply_start` 또는 `apply_end`가
  `2026-02-30`일 때도 `gate.judge()`가 날짜 파싱 예외를 내지 않았다.
- 실행 환경: 이전 재검토와 동일한 번들 Python 3.12.14 + 기존 `.venv/Lib/site-packages`, `-B -X utf8`.
  전체 테스트·실제 DB·모델·외부 서버는 실행하지 않았다.

기존 2번(score 모드 점수 혼용)과 3번(마감 제외 후 후보 미보충)은 이번 변경에 포함되지 않았고 미해결 상태다.
서비스·테스트 코드는 수정하지 않았으며 Git 스테이징·커밋·push도 실행하지 않았다.
