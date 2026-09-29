# 판정표 지문 신선도 재검수 (2026-09-29)

검수 대상: [요청서](JUDGMENT_FRESHNESS_REVIEW_REQUEST_20260929.md)의 9/29 미커밋 변경. 검수자는 Codex. 코드·DB는 수정하지 않았고, 공용 DB에는 SELECT만 실행했다. 이 문서 외에 기존 문서도 수정하지 않았다.

## 결론

**재검수 보류 — P1 4건, P2 3건.** 현재 기본 `auto` 구성과 데이터에서는 DB 판정 2,525건의 지문이 모두 일치하고 조율 연결 시험도 통과했다. 그러나 원문에서 제거된 첨부와 발췌 밖의 변경을 현재 지문이 반영하지 못하며, `file` 모드는 지문 검사를 우회한다. 구조가 잘못된 JSONL 한 줄은 서버 시작을 멈출 수 있다. 아래 P1을 해결한 뒤 같은 경계 입력으로 다시 검수해야 한다.

## 재현된 문제

### P1-1. 현재 첨부 목록에서 빠진 문서를 여전히 지문에 포함한다

- [스키마](../../../db/mysql_schema.sql)는 `notice_attachments.active`를 **현재 확인된 첨부 목록에서 사용 여부**로 정의한다. [수집 저장](../../../shared/store_mysql.py)은 새 목록을 받으면 기존 첨부를 `active=FALSE`로 바꾼다. 그런데 [load_population()](../../../experiments/sql_semantic/applicant_type_llm.py)은 `at.last_status='ok'`만 보고 `na.active`를 확인하지 않는다(134~140행). 11단계와 서비스 모두 이 함수를 쓰므로 제거된 첨부의 본문과 해시를 계속 재사용한다.
- **현재 DB SELECT 재현:** 비활성인데 성공 추출 본문이 있는 공고 6건 중, 활성 첨부만으로 `atl.prepare()`를 다시 하면 지문이 달라지는 공고가 **5건**이다. 그 5건 중 **1건**은 예비창업자 `not_allowed`/`strong`/`varies=false` 차단 판정이다. 현재 판정표와 서비스 계산 지문은 서로 같으므로 [fresh_only()](../../../search/applicant_types.py)는 이 판정을 신선하다고 선택한다. 그 1건의 실제 신청 가능 여부가 잘못되었다는 것까지 확인한 것은 아니다.
- **영향:** 공고가 첨부를 제거한 경우에도 해당 첨부를 근거로 한 옛 `blocked`가 남을 수 있다. 현재 첨부만 문서와 지문에 포함시키고, 지문이 바뀌는 기존 판정의 재판정 또는 안전한 미사용 경로를 확인해야 한다.

### P1-2. 잘린 원문 변경을 지문으로 감지하지 못한다

- [atl.prepare()](../../../experiments/sql_semantic/applicant_type_llm.py)는 [build_document()](../../../collect/extract_conditions.py)의 최대 6,000자 **발췌**를 해시한다(각각 155~160행, 439~463행). 본문·지원대상 머리는 최대 2,000자만 들어간다. 따라서 지문은 전체 공고 원문의 변경 증명이 아니다.
- **합성 재현:** `body='지원대상: 법인사업자만 신청 가능. ' + 'A'*2100`인 공고의 뒤에 `예비창업자도 신청 가능.`을 추가해도 `atl.prepare()`가 만든 두 `document_sha256`은 같다. 옛 `not_allowed`/`strong` DB 행을 `fresh_only()`에 넣으면 신선한 것으로 채택되고 `pre_founder()`는 `blocked`를 돌려준다.
- **현재 DB SELECT:** 2,525건 중 발췌 한도를 100,000자로 늘렸을 때 입력이 달라지는 공고가 **255건**이며, 그중 **25건**에 강한 차단 판정이 있다. 이는 현재 오판 25건을 뜻하지 않는다. 앞으로 생길 원문 자격 변경이 잘린 영역에 있으면 옛 판정을 차단하지 못한다는 노출 범위다.
- **필요한 확인:** 현재 원문 전체의 변경을 감지하는 별도 지문과 판정에 실제로 사용한 발췌 지문을 구분하고, 변경된 자격 구간이 재판정 입력에 들어오는지도 검증해야 한다. 전체 지문만 바꾸면 옛 판정 사용은 막지만 새 자격 문장을 읽지 못하는 문제는 남는다.

### P1-3. `file` 모드에서 옛 `blocked`가 그대로 활성화된다

- [load_auto()](../../../search/applicant_types.py)의 `mode='file'` 분기는 `current`가 없으면 파일 판정을 그대로 돌려준다(227~231행). 실제 [app.boot()](../../../search/app.py)는 `current`를 전달하지 않는다(158행). `active=True`이면 매칭이 `pre_founder()` 판정을 사용한다(390~401행).
- **임시 JSONL 재현:** `notice_id='n1'`, 옛 `document_sha256='old'`, `pre_founder={status:'not_allowed',strength:'strong'}` 한 줄을 넣고 `APPLICANT_TYPES_SOURCE=file`로 `load_auto(None, path=임시파일)`을 호출했다. 결과는 `active=True`, `pre_founder('n1')='blocked'`였다. 현재 문서 지문이 달라도 확인하지 않는다.
- 이 모드는 [설계 문서](../../guides/JUDGMENT_TABLES.md)에서 개발용이라고 명시한다. 그래도 환경 변수만으로 실제 서버가 같은 경로를 타므로, 모든 모드에서 옛 판정으로 공고를 빼지 않는다는 보장은 성립하지 않는다. 파일 전용 모드의 사용 범위를 강제하거나 서비스에서도 현재 지문을 필수로 확인해야 한다.

### P1-4. 구조가 잘못된 JSONL 한 줄이 서버 시작으로 예외를 전파한다

- [load()](../../../search/applicant_types.py)의 행 파싱은 예외를 잡지만, `out['notices'][notice_id] = info`는 해당 `try` 밖에 있다(105~115행). `notice_id`가 배열이나 객체이면 `TypeError: unhashable type: 'list'`가 난다. [app.boot()](../../../search/app.py)의 호출에는 `finally`만 있고 `except`가 없다(153~161행).
- **임시 JSONL 재현:** `{"notice_id":["n1"],"llm":{"pre_founder":{"status":"not_allowed","strength":"strong"}}}` 한 줄을 넣었다. 정상 DB 판정 2건과 현재 지문을 제공한 `auto` 모드에서도 `load_auto()`가 `TypeError`로 끝났다. 단위 테스트가 다루는 깨진 JSON 문법은 건너뛰지만, 이 구조 오류는 건너뛰지 못한다.
- `notice_id` 형식을 검사하고 사전 삽입까지 행 단위 예외 처리 안에 두어야 한다. 부팅 진입점에서도 신청자 유형 로더의 예상 밖 예외가 서버 전체로 번지지 않는지 확인해야 한다.

### P2-1. 같은 길이의 첨부가 있으면 지문이 비결정적이다

- [첨부 조회](../../../experiments/sql_semantic/applicant_type_llm.py)는 `ORDER BY n.notice_id, at.text_chars DESC`까지만 지정한다(134~138행). 길이가 같은 서로 다른 첨부 둘의 반환 순서를 합성 입력에서 뒤집자 문서와 SHA가 달라졌다. 원문이 그대로여도 판정을 오래된 것으로 버려 기능이 줄 수 있다.
- 현재 DB SELECT에서 같은 공고의 해당 길이 동률 그룹은 **0건**이었다. 첨부의 안정적인 식별자를 정렬의 마지막 기준으로 추가하는 것이 필요하다.

### P2-2. 13단계의 오류와 90% 경고가 동시에 나면 경고가 상태 화면에서 사라진다

- [daily_pipeline.py](../../../collect/daily_pipeline.py)는 두 표의 `error`와 `warning`을 모두 `judgments_result`에 모으지만(390~393행), `stage_warnings_of()`는 `if/elif`로 한 종류만 내보낸다(448~452행).
- **가짜 결과 재현:** `stage_warnings_of({'judgments_upload': {'error':'types: duplicate', 'warning':'industries: coverage low'}})`의 결과에는 오류만 있었다. 이 조합은 한 표의 중복과 다른 표의 90% 미만 경고에서 가능하다. `collect_log.jsonl`의 원시 `judgments_upload`에는 두 값이 남지만, `stage_warnings`와 [상태 화면](../../../web/collection_status.html)의 후처리 경고에서는 뒤의 경고를 볼 수 없다. 종료 코드 4 자체는 오류 항목 때문에 유지된다.

### P2-3. 판정표가 정상적으로 비어 있어도 기능 중단 이유가 `boot_errors`에 없다

- DB와 파일 판정이 모두 빈 경우 `load_auto()`는 `active=False, error=None`을 돌려줄 수 있다(260~269행). [app.boot()](../../../search/app.py)는 `error`가 있을 때만 `boot_errors['applicant_types']`를 기록한다(162~164행). 현재 데이터에서는 재현되지 않지만, 빈 표로 기능이 꺼진 상황에서 `/api/health`의 `active=false` 외에는 이유가 나타나지 않는다. 요청서의 “기능이 꺼지면 boot_errors” 설명과도 다르다. 정상적인 빈 표를 허용할지, 공고가 있는데 판정이 0건이면 경고할지 운영 기준을 정해야 한다.

## 통과한 경로와 실행 근거

| 검사 | 결과 |
|---|---|
| 전체 단위 테스트 | 번들 Python 3.12에 `.venv/Lib/site-packages`를 추가해 `unittest.defaultTestLoader.discover('tests')` 실행: **637개 통과, 13개 건너뜀**. 테스트 통과만으로 위 경계 입력은 보장되지 않는다. |
| 지문 대조 | 공용 DB **SELECT만**: 현재 공고 2,525건, 신청자 유형 판정 2,525행, 지문 일치 2,525건·불일치 0건·누락 0건. `legacy` 값은 조회하지만 `build_document()`와 해시에 들어가지 않는다. |
| 13단계 계획 | `python -X utf8 -m collect.upload_judgments --plan`(번들 Python 사용): 신청자 유형·업종 각 **2,525건 동일**, 새로 0·변경 0·공고 없음 0. 업로드하지 않았다. 현재 11·12단계 누적 파일도 각 2,525줄/고유 ID 2,525개다. 두 단계는 ID를 키로 누적한 뒤 원자적으로 다시 써서 정상 재시도만으로 중복 줄을 만들지 않는다. |
| 업로드 가드 | 중복 ID가 있으면 해당 표를 업로드하지 않는다. 90%는 현재 `notices`에 있는 **고유 ID** 기준 경고이며, 다른 유효 행은 업로드한다. 공고 삭제는 파일·DB 양쪽 분모에서 빠지고 12단계 하루 상한 300건은 누적 파일을 줄이지 않으므로, 이 두 상황만으로 경고가 생기지는 않는다. 관련 단위 테스트 18개 통과. |
| 모드·고장 처리 | 기존 `tests.test_judgments_source` 19개 통과: `auto`/`db`의 낡은 DB 판정 배제, 신선한 파일 대체, 연결 없음·지문 계산 실패 시 기능 중단, DB 읽기 실패+신선한 파일 사용 등을 확인했다. `file` 모드의 `current` 미전달 예외는 위 P1-3이다. |
| 반환 모양 사용처 | `load_auto()` 직접 호출은 서비스 부팅과 테스트에서 확인했다. 매칭·자격 확인·`eval/filter_first_eval.py`는 `app.STATE['applicant_types']`의 `active`/`notices`를 사용하며 전체 테스트와 조율 프로브에서 반환 모양 때문에 깨진 경로는 없었다. 8010의 `/api/applicant-types` 화면은 별도 보고서 파일을 읽으므로 이 반환값에 의존하지 않는다. 브라우저 화면 자체는 별도 실행하지 않았다. |
| 조율 연결 | `python -X utf8 -m experiments.orchestration_probe --sbrain ..\agent-orchestration`(번들 Python, 공용 DB SELECT): D 빠른 시작·A T-C2·B G-01·C 흐름 모두 통과. G-01은 공고 **2,525건 × 신청자 5가지**에서 매칭 1단계와 차이 0건. 시험용 더 보기 실패 주입도 실패로 감지했다. |
| 기능 꺼짐의 G-01 | 설명서의 `eligibility_of()`를 `app.STATE['applicant_types']={'active':False,'notices':{}}` 및 가짜 공고 한 건으로 별도 실행: 예외 없이 신청자 유형 세 가지 허용·`eligibility_parsed=False` 반환. 즉 빈 판정표 자체는 G-01을 멈추지 않는다. |

## 검증 범위와 남은 확인

- Linux/EC2에서의 실제 부팅과 2026-09-30 09:00 배치의 13단계 경고 경로는 실행하지 않았다. 이번 검수는 Windows, 공용 DB SELECT, 임시 합성 입력과 기존 단위 테스트에 근거한다.
- 90% 미만은 의도대로 **경고 후 부분 업로드**다. 형식은 정상이나 내용이 틀린 행까지 의미적으로 검증하지는 않는다. 서비스의 문서 지문 대조도 동일 지문을 단 오판정의 진위는 판별하지 못한다. 업종 순위 기능의 판정 정확도는 이번 범위 밖이다.
- 첨부 추가·재추출로 `last_status`가 바뀌면 입력 지문이 달라져 해당 판정이 사용되지 않을 수 있다. 현재 DB에는 성공 본문이 남았지만 `last_status!='ok'`여서 제외되는 공고가 0건이었다. 비활성 첨부 문제는 P1-1에 별도로 적었다.
- 코드·DB·STATUS·WORKLOG·문서 지도는 사용자 지시대로 수정하지 않았다. Git 스테이징·커밋도 하지 않았다.
