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

## 후속 확인 — 원 검토 2번·3번 해결

2026-09-18 · Codex. 위 날짜 수정 확인 이후 Claude가 변경한 `search/app.py`와
`tests/test_match_rules.py`를 재검토했다. 원 검토 2번·3번의 재현 사례는 모두 해결됐다.

- 점수 혼용: 의미 검색 51위 후보를 별도 꼬리로 붙이지 않는다. hybrid score 모드는 모든 후보에 RRF를 사용한다.
  규칙 불일치가 없는 동일 공고 집합에서 order/감점 0 score 모드 모두 `n0001, n0002, n0003`을 반환한다.
  score 모드의 점수도 RRF `0.03279`로 확인했다.
- 후보 미보충: 60건 중 앞 51건이 마감됐을 때 dense/hybrid 및 order/score 네 조합 모두
  두 번 검색 후 `n0052, n0053, n0054`를 반환했다.
- 반복 검색: 600건 중 앞 595건이 마감된 경우 깊이 50→150→450→600, 4회 검색 후 정상 3건 반환.
- 종료 조건: 모든 공고가 마감되면 0건, 유효 공고가 1개뿐이면 1건을 반환하며 색인 끝에서 멈춘다.
- 추가 확인: watermark를 제외한 후보 처리, 표시용 공고 정보가 없는 후보 건너뛰기,
  BM25에만 검색된 후보의 벡터 추가 조회 경로도 확인했다.
- 관련 테스트: `test_gate.py` 18개 + `test_applicant.py` 15개 + `test_match_rules.py` 20개 = **53개 통과**.
  별도 가상 시나리오 **12개 통과**. 이전 지역·설립일·HTTP 날짜 회귀 테스트도 포함한다.
- 실행 환경: 이전과 동일한 번들 Python 3.12.14, 프로젝트 가상환경 패키지, `-B -X utf8`.
  전체 테스트·실제 DB·모델·외부 서버·실데이터 응답시간은 이번 검토에서 확인하지 않았다.

### [P3] 검색시간 표시에서 벡터 추가 조회·순위 결합 시간이 빠진다

- 위치: `search/app.py:330`의 `search_ms = dense_ms + bm25_ms`.
- 조건: BM25가 의미 검색 후보 밖의 공고를 찾아 `_fill_distances()`에서 Chroma `get()`을 호출한다.
- 원인: 새 시간 합산식에는 `col.query()`와 BM25 검색 시간만 포함된다.
  그 사이의 벡터 추가 조회·코사인 계산·RRF 결합 시간은 어느 항목에도 누적되지 않는다.
- 영향: `search_ms`를 사용하는 `web/demo.html`의 검색시간 및 리랭커 제외 응답시간이 실제보다 작게 표시된다.
  후보 보충으로 이 경로를 여러 번 실행하면 누락도 누적된다. 검색 결과 순위 오류는 아니다.
- 재현: 60개 가상 공고에서 Dense 상위 50개 밖의 `n060`을 BM25가 찾도록 구성했다.
  `app.time.time`을 모의 시계로 대체하고 `query()` 10ms, BM25 20ms, `get()` 250ms를 부여했다.
  함수의 모의 경과 시간은 280ms인데 반환 `search_ms`는 30ms였다. 실제 운영 지연을 측정한 수치가 아니다.
- 보완 방향: 검색 반복 전체의 경과 시간을 별도로 재고, dense/BM25 세부 시간은 그대로 유지한다.
  기존 구현처럼 검색 구간의 시작·끝에서 측정하면 추가 조회와 결합 시간이 포함된다.

원 검토 네 건과 날짜 오류는 재현 기준으로 해결 확인했으며, 현재 추가 발견 사항은 위 성능 표시 P3 한 건이다.
검토 문서만 갱신했고 서비스·테스트 코드와 Git 스테이징·커밋·push는 변경하지 않았다.
