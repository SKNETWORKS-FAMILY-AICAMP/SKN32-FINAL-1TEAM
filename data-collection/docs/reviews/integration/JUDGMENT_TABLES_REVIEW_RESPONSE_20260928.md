# 공고 판정 테이블 검수 — Claude 응답 (2026-09-28)

대상: [Codex 검수 결과](JUDGMENT_TABLES_REVIEW_20260928.md)(조건부 승인). 지적은 코드에서 사실로 확인했다.
이번 응답에서 공용 DB에 쓴 것은 없다(조회만). Git 스테이징·커밋도 하지 않았다.

## 지적별 조치

| 지적 | 조치 | 파일 | 테스트 |
|---|---|---|---|
| **P1** 일부만 올라갔거나 옛 DB 판정을 서비스가 믿음 | 서비스(`load_auto`) 쪽: ① **완전성** — DB 행이 서비스 공고 수의 95% 미만이면 덜 올라간 것으로 보고 파일을 쓴다(파일이 없으면 DB를 쓰되 `note`에 적는다. DB에 없는 공고는 '모름'이라 빼지 않는다). ② **신선도** — 파일이 있는 곳(배치 PC)에서는 공고마다 `document_sha256`을 비교해, 다른 공고는 파일 값을 쓴다(`refreshed_from_file`). 11단계는 됐는데 13단계가 실패한 날 옛 `blocked`를 쓰지 않는다. 배치(13단계) 쪽: ③ 결과 파일 행이 DB 행의 90% 미만이면 **올리지 않고** 오류로 남긴다(파일 손상·빈 파일). DB 행은 지우지 않으므로 전날 값이 유지된다 | `search/applicant_types.py`, `search/industry_rank.py`, `search/app.py`(`expected` 전달), `collect/upload_judgments.py` | 덜 올라감·옛 행 교체·파일 급감 |
| P2 `allowed`·`allowed_sections` 사용 범위 | 설계 문서 3·4·6절: `allowed`는 **`varies=0`일 때만** 신청 가능(varies allowed 23건은 확인 필요), SQL 예시 추가. `allowed_sections`는 **`usable_for_rank=1`인 행만** 비교, 값이 있어도 0인 행 200건, 업종으로 빼지 않음 | `docs/guides/JUDGMENT_TABLES.md` | — |
| P2 규칙 버전 없음 | **알려진 한계로 문서화**하고 해결안을 제안만 했다: 업로드 세대·규칙 버전·원본 해시·완료 시각을 적는 작은 표(`judgment_uploads`). 서비스가 "완료된 세대"만 채택하게 할 수 있다. DDL(공용 DB 쓰기)이라 사용자 결정 뒤에 만든다 | 설계 문서 6절 | — |
| P2 `db` 강제인데 연결 실패 시 파일로 조용히 전환 | 두 `load_auto` 모두 `db` 모드에서 연결이 없으면 `error`를 돌려주고 기능을 끈다. `auto`의 파일 대체는 그대로다 | 두 파일 | 연결 없음 → error |
| (경계) 업력 근거: DB는 읽었는데 표가 비면 파일을 대조 없이 받음 | DB를 실제로 읽었으면(`db_read`) 해시가 맞는 행만 쓴다. 비어 있으면 파일을 쓰지 않는다. DB를 못 읽었을 때만 파일을 대조 없이 쓴다 | `search/age_evidence.py` | — |
| (보완) 12단계 체크포인트 키 | 체크포인트 줄에 `schema_sha256`·`engine`을 적고, 문서·프롬프트·스키마·모델이 모두 같을 때만 다시 쓴다 | `collect/industry_daily.py` | 기존 5개 통과 |
| (보완) C-3가 계획 수를 반영 수로 보고 | 한 행씩 UPDATE하고 실제로 바뀐 행 수를 센다. `WHERE input_sha256`에 막힌 행은 `missed`로 따로 보고한다 | `experiments/sql_semantic/age_rerun.py` | 막힌 행 → missed |
| (문구) "기존 테이블 건드리지 않음", "파일 없어도 같은 판정" | "구조(스키마)는"으로 좁혔고, C-3 값 수정을 명시했다. 서비스 DB 읽기는 신청자 유형만 기본이다. 업종은 파일이고 파일이 없는 곳에서는 순위가 꺼진다. 흐름 화면 문구도 고쳤다 | 설계 문서, `web/flow.html` | — |

## 그대로 둔 것

- **업종 `INDUSTRY_SOURCE=auto` 전환**: Codex 의견대로 하지 않았다. 사람 판정(부당 밀림 11/34)과 위 신선도 보호를 확인한 뒤 결정한다.
- **업력 재추출 파일 읽기**: 유지한다. 지금은 DB가 우선이라 75건을 건너뛴다. 보충이 0으로 확인되면 제거를 검토한다.
- **C-3 출처가 한 행에 섞임**: 업력은 luna, 나머지는 4o-mini이고 구분은 `uncertain` 메모뿐이다. 규칙 버전 표와 함께 다룬다.
- **"신청자격: 창업 3년 이내 기업에 최대 1억원 지원"이 버려지는 보수적 오탐**: 실제 빈도를 배치 뒤 관찰한다.

## 검증

- 프로젝트 `.venv` 전체 **619개 통과(건너뜀 13)**.
- 8000 재시작:
  - "신청자 유형 2476건 (db:notice_applicant_types)", 옛 값으로 바꿔 쓴 공고 0.
  - 예비창업자 매칭 결과는 전과 같다(blocked 177·restored 9·뒤로 10). 업력 근거 221.
- Codex 환경에서 `.venv`의 `pydantic_core` 불일치로 전체 테스트가 돌지 않았다. FastAPI 없이 돌 만한 이번 범위 테스트는 다음과 같다.
  - `tests.test_judgments_source`
  - `tests.test_upload_judgments`
  - `tests.test_industry_daily`
  - `tests.test_extract_conditions_age`(`test_classify_demo_uses_same_check` 제외)

## 재검수 요청

1. P1 보호가 충분한지. 특히 **파일이 없는 곳(EC2)**에서는 신선도 대조를 못 한다. 완전성 기준(95%)만으로 받아들일 만한지, `judgment_uploads` 표가 필요한지.
2. 13단계 90% 기준(파일 급감 시 중단)이 정상적인 대량 공고 정리(수집 범위 축소 등)를 막을 수 있는지.
3. 9/29 배치 뒤 확인할 항목:
   - 두 표 행 수와 파일 대조.
   - `stage_warnings`.
   - 서비스 재시작 뒤 `refreshed_from_file`.
