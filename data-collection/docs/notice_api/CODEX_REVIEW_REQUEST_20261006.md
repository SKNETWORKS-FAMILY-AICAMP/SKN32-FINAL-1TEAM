# 검수 요청 — 공고 서버 API 01~03 (조율 에이전트 창구 · 가산점) (2026-10-06)

작성: Claude · 결정: 사용자(이근준) · 검수: Codex · 브랜치 `feature/SB-189-data-collection`(기준 커밋 `99a0bc9`, **미커밋**)

결과는 같은 폴더 `CODEX_REVIEW_20261006.md`에 P1(틀림·위험) / P2(고칠 것) / P3(제안)로 쓴다. 코드·DB·Git 스테이징은 고치지 않고 지적만 한다. **공용 DB는 조회만 한다.** 유료 API(OpenAI)는 부르지 않는다.

## 0. 배경 (한 문단)

조율 담당(4nchez)이 공고 서버를 HTTP로 부르기로 하고 요청서를 보냈다(SB-87 브랜치 `agent-orchestration/docs/공고서버_API요청_공고팀전달.md`). 조율 쪽 연결 코드는 `agent-orchestration/sbrain/agents/notice/`(`client.py`·`convert.py`·`g01.py`·`tc2.py`)에 있다. 우리 쪽은 그 약속대로 창구를 열었다. 작업별 기록은 이 폴더의 [01](01_status_match/README.md) · [02](02_detail_eligibility/README.md) · [03](03_bonus/README.md)에 있다. **먼저 세 README를 읽으면** 무엇을 왜 했는지 알 수 있다.

## 1. 바뀐 것

| 작업 | 파일 | 내용 |
|---|---|---|
| 01 | `search/notice_api.py`(새) | `GET /api/collection_status` — DB 판정 + **서버가 올린 공고 저장 시각이 24시간 넘으면 정상→지연**(`served_status`). DB를 못 읽으면 503 |
| 01 | `search/content_version.py`(새) | 공고 내용 지문 `cv1-…` — 원문 칸 + 첨부 파일 바이트 SHA-256. 수집 시각·LLM 값 제외. 하루 비교 명령 `--save`·`--compare` |
| 01 | `search/app.py` | `include_router(notice_api.build_router(STATE, lambda: _connect()))`, boot에서 저장 시각·지문 읽기, 추천 결과에 `content_version` |
| 02 | `search/eligibility.py`(새) | app.py 의 화면용 자격 판정 본문을 **그대로 옮김**(`today`·판정표를 인자로) |
| 02 | `search/notice_api.py` | `GET /api/notices/{notice_id:path}`, `POST /api/notices/{notice_id:path}/eligibility`, 404 + `{"code":"NOTICE_NOT_FOUND"}`, 422 검사, `allowed_types()`·`notice_detail()`·`judge()`, 지원 금액 `load_amounts()` |
| 03 | `collect/extract_bonus.py`(새) | 공고 가점 LLM 추출(`gpt-5.6-luna` medium, 프롬프트 v3). 근거 대조 `find_quote()`(단어가 같은 순서로 가까이), 점수 검사 `_points_in()`, 상태 `none·found·unverified·no_mention`, `--all`·`run_batch()` |
| 03 | `db/mysql_migration_007_notice_bonus.sql`(새) | `notice_bonus` 표. **10/6 사용자 승인으로 공용 DB에 생성·적재함**(2,057행) |
| 03 | `search/bonus.py`(새) | 신청자별 가산점 `item_hit()`(해당·해당 아님·모름)·`score()`(0/null 구분, 합계 한도, 중복 제거) |
| 03 | `search/app.py` | boot에서 `STATE['bonus']`, 추천 결과 `bonus_score`·`bonus_items`, `Weights.bonus`(순위 반영 세기)·`bonus_boost()` |
| 03 | `collect/daily_pipeline.py` | **14단계 '가점 추출'**(하루 300건, `--skip-bonus`·`--bonus-limit`, `--skip-upload`도 따름) |
| 03 | `eval/bonus_rank_eval.py`(새) | 순위 반영 세기 비교(가상 신청자 3종 × 세기 4개) |
| 시험 | `tests/test_notice_api.py`(새)·`test_extract_bonus.py`(새)·`test_bonus.py`(새)·`test_match_deh.py` | |

## 2. 검증 (Claude 실행)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

- 전체 시험 통과(마지막 실행 수는 03 README·WORKLOG 참고).
- 02: 실제 `boot()` 후 공고 2,765건 × 신청자 5가지 = 13,825회에서 **새 자격 판정과 추천 정형 필터의 결론이 다른 경우 0건**. 옛 app.py(`99a0bc9`)와 화면용 판정 16,590회 비교 **다름 0건**. 공고 상세 2,765건 형식 오류 0.
- 01: 실제 DB 지문 2,765건 재계산 동일·충돌 0. 하루 뒤 비교는 아직(10/7 배치 뒤 `python -m search.content_version --compare data/notice_api/content_version_20261006.json`).
- 03: 표본 30건 v1·v2 비교, 전량 667건 LLM(실패 0, 약 $1.05), 가상 신청자 점검(무작위 15·20건 근거 대조 — AI 참고). 순위 반영 측정은 아래 4절.

## 3. 봐 줄 것

1. **조율 쪽 계약과 맞는가.** 요청서 2.1~2.5·3.1·3.2와 조율 코드 `convert.py`(`req_*`·`opt_*` 검사)·`g01.py`(`to_announcement`·`to_gate`)·`tc2.py`가 우리 응답을 형식 오류 없이 받는가. 특히 "있어야 함" 키가 늘 있는가, 정수·참거짓 형식, `fallback_mode`·`band` 값, 404 본문이 최상위 `code`인가, 경로가 없을 때의 404와 구분되는가.
2. **수집 상태의 "서버 데이터 나이" 규칙**(`served_status`)이 요청서·기준 문서(R-3 ②) 취지에 맞는가. `loaded_store_at`을 공고보다 먼저 읽는 순서가 맞는가. DB 실패 503이 맞는 선택인가.
3. **내용 지문**에 날마다 바뀌는 값이 섞일 위험(예: `url`·`apply_url`에 세션 값, `apply_period_raw` JSON 표기, 첨부 `content_sha256`이 재다운로드마다 바뀌는지).
4. **판정 옮기기**가 정말 동작을 바꾸지 않았는가(`types_table` 인자: 화면용은 `STATE.get(...) or {}`, 조율용은 `active`일 때만). `allowed_types()`의 정의(예비창업자=판정 불통과면 제외, 사업자=업력 칸 '예비창업자'만이면 제외)가 판정과 모순되지 않는가.
5. **가점 추출의 코드 검사.** `find_quote()`의 완화("같은 순서·근거 길이×2+60자 안")가 지어낸 근거를 통과시킬 수 있는가. `_points_in()`이 표의 번호(연번)를 점수로 오인할 수 있는가. `no_mention`(첨부에 '가점·가산점' 말이 없음 → 0점)이 '우대'만 적힌 공고를 0으로 만드는 문제가 있는가.
6. **가산점 계산 규칙**(`search/bonus.py`)이 너무 후하거나 엄격한 곳. 인증 목록을 "고르지 않으면 없음"으로 보는 가정(조율 쪽이 인증을 안 물었을 때 `[]`를 보내면 모두 '해당 아님'이 된다 — 0 과 null 구분에 영향). 합계 한도로 마지막 항목 점수를 줄이고 이름에 "(합계 한도 N점 적용)"을 붙이는 방식.
7. **가점 표본 점검(AI 참고 정답 요청).** `reports/bonus_full_20261006T013520Z/results.jsonl`에서 `status=found` 20건을 무작위(시드 자유, 적어 줄 것)로 골라, 공고문 원문(공용 DB `attachment_texts.extracted_text`, 조회만)과 대조해 항목별로 ① 실제 가점인가 ② 점수가 맞는가 ③ 종류(kind)가 맞는가를 판정해 달라. `status=none` 10건은 정말 가점이 없는지 봐 달라.
8. **순위 반영**(`bonus_boost`, `Weights.bonus`) — 규칙 묶음을 넘지 않는가, 세기 0에서 순서가 정확히 같은가, 4절 측정 해석이 맞는가.
9. **매일 배치 14단계** — 실패·키 없음이 수집 상태를 막지 않는가, 하루 상한, 서버 복사본에서 돌 때 필요한 것(`notice_bonus` 표는 이미 있음, `.env`의 `OPENAI_API_KEY`).
10. 개인정보: 요청 본문(신청자 정보)을 로그에 남기는 곳이 없는가(요청서 5절).

## 4. 순위 반영 측정 (3-4)

`eval/bonus_rank_eval.py` → `reports/bonus_rank_eval_20261006T015155Z/summary.md`. 기준일 9/15 말뭉치 2,084건(가점 행 1,576) · 정상 질의 58 · 상위 10 · qrels 1,617쌍 · 가상 신청자 3종(평가 질의에 성별·인증·지역이 없어 덧붙임) · 세기 0/0.1/0.2/0.3.

| 가상 신청자 | 상위 10 중 가산점 공고(평균) | 세기 0.3 자리 바뀐 수 | 지표(신청 불가@10 · P@3 하한 · nDCG@10 · 쓸모@10 하한) |
|---|---|---|---|
| 여성 · 서울 | 0.02 | 0.00 | 모두 변화 0 |
| 여성기업 · 벤처 · 경기 | 0.21 | 0.31 | 모두 변화 0 |
| 남성 · 장애인기업 · 이노비즈 · 전남광주 | 0.03 | 0.00 | 모두 변화 0 |

- Claude 해석: 밀어내는 해는 측정되지 않았지만 효과가 작게 잡혔다(가점 공고가 상위에 드묾 — 닫힌 공고는 추출 안 함). 정답이 가산점을 모르므로 "좋은 순위인가"는 재지 못한다. 그래서 **기본 세기 0.2**(가운데)를 골랐다. **이 선택이 근거에 비해 과한지·약한지 봐 달라.**
- 가산점이 있는 후보가 없으면 다시 정렬하지 않는다(`bonus_boost`가 빈 사전). 실제 데이터에서 속성 없는 신청자의 세기 0과 0.2 순서가 같음을 확인했다.

## 5. 알려진 한계 (지적하지 않아도 되는 것 — 이미 답변서에 적을 예정)

- K-Startup 공고(열린 221건)는 첨부 공고문을 수집하지 않아 가산점이 늘 `null`.
- 사업자 신청자는 "지원대상 유형"이 늘 확인 필요(개인·법인 자동 판정 안 함, 9/28 결정).
- `support_amount_text`는 `null`.
- 생년월일을 받지 않아 청년 가점은 모름.
