# 시스템 구성

S-Brain에서 "공고 데이터 · 매칭 · 자격 판정"을 맡는 부분이다. 정부지원사업 공고를 하루 한 번 모아 팀 공용 DB에 넣고(매일 배치), 신청자 입력에 맞는 공고를 골라 주는 공고 서버(`search/app.py`)를 연다. 사업계획서 작성·프로토타입·검증은 다른 팀원 폴더가 맡고, 이 폴더와는 공고 서버 HTTP 창구와 공용 DB로만 이어진다.

## 구성 요소와 연결

```
 K-Startup API(data.go.kr) ─┐
 기업마당 API ──────────────┼─▶ [매일 배치  collect/]  ──쓰기──▶ [팀 공용 MySQL  s_brain]
 기업마당 첨부 내려받기 ─────┘      │  ▲                          (팀 EC2 43.201.90.238, TLS)
 OpenAI API ◀──── LLM 추출 ────────┘  │                                │  ▲
 HuggingFace(BGE-M3, 첫 실행만) ───────┘                                │  │ SELECT 만
                                                                        │  │
            배치 쪽 data/ (원본 스냅샷·벡터 파일·Chroma·판정 누적 파일·로그)    │  │
                                                                        ▼  │
 [조율 에이전트 (agent-orchestration, 다른 팀원)] ──HTTP──▶ [공고 서버  search/app.py :8000]
 [검증 화면  experiments …viewer :8010] ──HTTP /api/match──▶      │ 켤 때 DB·파일을 메모리에 올림
 [평가 도구  eval/] ── 함수 직접 호출(match·규칙 함수) ───────────────┘
```

| 구성 요소 | 역할 | 의존 방향 |
|---|---|---|
| `collect/` 매일 배치 | 두 API 수집 → 정규화 → 공용 DB 저장 → 첨부 본문 추출 → 임베딩 → LLM 추출 → 판정·가점 올리기 (14단계) | → `shared/`, `search/vecstore`, `experiments/sql_semantic`의 LLM 추출 함수, 공용 DB(쓰기), OpenAI |
| `shared/` | `.env` 읽기, 공용 DB 저장·접속(TLS), 임베딩 입력 정의와 BGE-M3 인코딩, 시·도/시·군·구 어휘 | 바깥 의존 없음 (다른 폴더 import 안 함) |
| `search/` 공고 서버 | 정형 필터 → 하이브리드 검색 → 규칙 재정렬, 자격 판정, 수집 상태, 조율 창구, 가산점 계산 | → `shared/`, `ec2/`(리눅스에서), `collect.extract_bonus`·`collect.extract_conditions`(버전·검산 함수), `experiments/sql_semantic`(판정 해석 함수), 공용 DB(SELECT) |
| `ec2/` | 리눅스(팀 EC2)용 DB 접속. 예전 Chroma 색인 갱신 스크립트(crontab 00:10 UTC, 공고 서버는 더 쓰지 않음) | → 공용 DB(SELECT) |
| `experiments/` | 검증 화면(8010), 별도 로컬 실험 DB 비교, **배치·서버가 쓰는 LLM 추출·업종 그룹 함수** | → `search/`, `shared/`, `collect/`, 로컬 실험 DB(쓰기), 8000(HTTP) |
| `eval/` | 검색 품질 평가셋(질의·판정·qrels)과 지표, 판정 화면(8001) | → `search/`(같은 match·규칙 함수), `shared/` |
| `ml/` | 리랭커(LoRA)·업력 분류기 학습. 제출물이며 서비스 미연결 | → `search/` 일부 |
| `share/` | 검증 화면 결과를 서버 없이 보는 한 장짜리 HTML 생성 | → `experiments/`·`search/` 파일 읽기만 |
| `web/` | 공고 서버가 내려 주는 시험용 화면 HTML | 공고 서버가 파일로 읽음 |
| `db/` | 공용 DB 테이블 생성문과 변경 SQL | 손으로 적용 |

## 어디서 무엇이 도는가

| 위치 | 도는 것 | 비고 |
|---|---|---|
| 개인 AWS EC2 `sbrain-web` (13.125.40.88, Ubuntu, Docker) | 매일 배치. crontab `0 0 * * *`(UTC 00:00 = 한국 09:00) → 저장소 루트 `deploy/run_batch.sh` → `batch` 컨테이너에서 `python -m collect.daily_pipeline` | 코드는 git 체크아웃이 아니라 `~/sbrain/data-collection`에 **복사한 폴더**다. `data/`·`.env`(배치 키 8개)도 그 폴더에 있다 |
| 팀 EC2 (43.201.90.238) | 공용 MySQL `s_brain`. **공고 시험 서버** `http://43.201.90.238:8000` — systemd `notice-server`로 상시 실행, 매일 00:20 UTC(한국 09:20) 재시작(`/etc/cron.d/notice-server-restart`). 코드는 `~/notice-server/data-collection/`(이 PC 작업 폴더에서 **복사**, git 아님), 파이썬 환경은 `~/s-brain/.venv`. 예전 Chroma 색인 갱신 cron(00:10 UTC)도 남아 있다 | 시간대 UTC. 8000은 시험 기간만 전체 공개 |
| 사용자 PC (Windows) | 개발용 공고 서버 8000(127.0.0.1, 손으로 켤 때만), 검증 화면 8010, 평가·학습·실험 | PC 작업 스케줄러 `S-Brain-DailyCollection`은 **사용 안 함**(지우지 않음, 되돌리기용). PC의 `data/` 벡터 색인은 2026-10-02 이후 갱신되지 않는다 |

공고 서버는 실행 환경을 운영체제로 판단한다. **리눅스면 EC2로 본다** — `ec2/ec2_vecstore`로 DB에 붙고, BGE-M3를 직접 올리고, `0.0.0.0`에 연다. 윈도우면 `shared/store_mysql`·`search/vecstore`를 쓰고 `127.0.0.1`에 연다.

## 대표 흐름 1 — 매일 배치 (한 번 실행)

```
1  K-Startup 수집 (collect/daily_job)   모집 중 목록 전체, 100건씩. 실패 시 3번 재시도 후 어제 data/notices.json 유지
2  기업마당 수집 (collect/fetch_bizinfo)  한 번에 전량. 실패하면 직전 data/raw/bizinfo_*.json 재사용
3  정규화 (collect/normalize)           두 출처를 schema_version=1 공통 형식으로 → data/normalized/notices_*.json
4  공용 DB 저장 (shared/store_mysql)     한 트랜잭션: notices·notice_attachments upsert + import_runs 1행
                                       + 오늘 목록에서 빠진 K-Startup open 공고를 closed 로 (조건부)
5  첨부 받기·본문 추출                    기업마당 공고문 첨부만. data/attachments/ 해시 이름 → attachment_texts
6  임베딩 (shared/embed)                입력 해시가 바뀐 공고만 BGE-M3 → data/embeddings_v1.npz
7  벡터 색인 (search/vecstore)           바뀐 공고만 로컬 Chroma(data/vecstore/chroma)에 반영
8  벡터 올리기 (collect/upload_vectors)  npz 와 DB 를 대조해 못 올린 벡터를 notices 임베딩 칸으로
9  첨부 원본 올리기                        해시 기준 새 파일만 attachment_files 로
10 자격요건 추출 (LLM)                    지원 금액·업력 근거 → notice_conditions
11 신청자 유형 추출 (LLM)                 → data/applicant_types/results.jsonl (파일만)
12 업종 추출 (LLM)                        → data/industries/ (파일만)
13 판정 올리기                            11·12 결과 중 바뀐 행 → notice_applicant_types·notice_industries
14 가점 추출 (LLM)                        가점·우대 말이 있는 열린 공고 → notice_bonus
```

- 4단계가 끝나야 5~14단계가 돈다(`stored`). 5단계 이후 실패는 앞 단계 결과를 되돌리지 않는다.
- 공용 DB로 쓰는 단계: 4·8·9·10·13·14. `--skip-upload`이면 8·13·14를 건너뛴다.
- 배치 PC/서버에만 남는 것: 원본·정규화 스냅샷(출처별 14개), 첨부 원본, npz, 로컬 Chroma, 11·12단계 누적 파일, `collect_log.jsonl`(실행마다 한 줄), `run.log`(시작·종료 줄).
- 결과는 종료 코드로 요약된다: 0 성공 · 1 실패 · 2 부분 실패(출처 하나 이상 실패) · 3 이미 실행 중 · 4 수집은 성공, 10~14단계 경고.

## 대표 흐름 2 — 공고 추천 한 번 (`POST /api/match`)

```
신청자 입력(유형·설립일·아이디어·지역·업종·인증 …)
 → build_query: 아이디어 + 수익모델 + 유형/업력 문구 + 팀 경력 + 업종·인증·채용계획을 한 문장으로
 → ① 정형 필터: 메모리의 모든 공고에 gate.prefilter(+ 예비창업자면 공고 본문 신청자 유형 판정)
 → ② 필터 통과 공고 안에서만 검색
       의미 검색: 질의 BGE-M3 벡터 → 메모리 벡터 묶음에서 통과 공고 전부와 코사인(근사 없음)
       단어 검색: 메모리 BM25 (allowed=통과 공고)
       RRF(k=60)로 합침, 각 검색에서 최대 50건
 → ③ 규칙 재정렬: 다른 시·도 → 다른 시·군·구 → 예비창업자 불가 추정 → 업종 목록 밖(기본 꺼짐) → 대상 집단 근거 없음 순으로 뒤로
 → ④ 결과마다 내용 지문·가산점·규칙 표시를 붙여 top(기본 10)건 반환
```

질의 인코딩·의미 검색·BM25 오류는 따로 잡아 대체 경로(`임베딩단독`·`BM25단독`·`마감임박순`)로 답한다. 어떤 경로에서도 정형 필터는 생략하지 않는다.

## 대표 흐름 3 — 공고 서버 켜기 (`boot`)

서버는 켤 때 한 번 아래를 메모리(`STATE`)에 올리고, 요청 처리 중에는 공고 데이터를 다시 읽지 않는다. **매일 배치 뒤 서버를 다시 켜야 새 공고가 반영된다.**

| 올리는 것 | 출처 | 실패하면 |
|---|---|---|
| 공고 벡터 | 공용 DB `notices.embedding`(1,024차원 float32만) → 메모리(`search/memvec.py`, 약 11MB). 설정 지문이 질의 인코더와 다르면 `vector_fingerprint` 경고 | DB 오류·0건이면 의미 검색 없이 연다(BM25 단독) |
| 올린 공고의 저장 시각 | `import_runs` 최신 행 (공고보다 먼저 읽음) | null → 수집 상태가 '지연'으로 나간다 |
| 공고 정보 | `notices` 전체 | **서버가 멈춘다** |
| 공고 내용 지문 | `notices` + 지금 달린 첨부 파일 해시 | 지문 null, 가점도 쓰지 않음 |
| 지원 금액 | `notice_conditions`(버린 값 제외) | 금액 모두 null |
| 공고 가점 | `notice_bonus`(지문·추출기 버전이 지금과 같은 행만) | 가산점 모두 null |
| BM25 색인 | `notices`를 임베딩과 같은 입력으로 | **서버가 멈춘다** |
| 업종 판정 | 기본 파일 `reports/industry_llm_full_luna_20260928_final5/results.jsonl` (`INDUSTRY_SOURCE`·`INDUSTRY_RESULTS`) | 업종 규칙 꺼짐 |
| 신청자 유형 판정 | 기본 auto: 공용 DB `notice_applicant_types` → 배치 쪽 파일, 지금 공고문 지문과 같은 판정만 | 기능 꺼짐(예비창업자 본문 판정 없이 동작) |
| 업력 근거 | DB + 파일 | 화면 설명만 빠짐 |
| 임베딩 모델 | PC: `search/vecstore`, 리눅스: BGE-M3 직접 | BM25 단독 |

켤 때의 실패는 `boot_errors`에 모아 `/api/health`로 보인다.

## 경계 — 무엇이 넘나드는가

- **공고 서버 ↔ 공용 DB**: SELECT만 한다. 서버는 DB에 쓰지 않는다.
- **조율 에이전트 ↔ 공고 서버**: HTTP 4개 창구(수집 상태·추천·공고 상세·자격 판정)만. 조율 쪽은 이 폴더 코드를 import하지 않는다. 조율 쪽 연결은 `SBRAIN_NOTICE_API_URL`을 넣어야 켜지며 아직 꺼져 있다.
- **팀원 ↔ 공용 DB**: 공고·첨부 원본·벡터·판정표를 SQL로 읽는다. 로컬 Chroma·npz·11·12단계 파일은 공유되지 않는다.
- **실험 DB**: `experiments/sql_semantic`만 쓰고, 공용 DB와 섞이지 않는다(로컬 호스트만 허용).
- **수집 범위 밖**: 대형 국가 R&D(IRIS·NTIS), K-Startup 첨부 공고문(robots.txt 금지).

## 공용 DB 테이블

| 테이블 | 쓰는 단계 | 내용 |
|---|---|---|
| `import_runs` | 4 | 저장 성공 1회당 1행. `imported_at`(UTC)이 수집 상태 판정의 기준, `report`에 입력 파일·모집 종료 처리 ID |
| `notices` | 4, 8 | 공고 1건 1행. `notice_id = 출처:원본ID`. 임베딩 칸 5개(8단계) |
| `notice_attachments` | 4 | 공고별 첨부 링크(`active`로 지금 달린 것 표시) |
| `attachment_texts` | 5 | 첨부 추출 본문·파일 바이트 SHA-256·시도 상태 |
| `attachment_files` | 9 | 첨부 원본 바이트(해시 기준 한 벌) |
| `notice_conditions` | 10 | LLM 자격요건(지원 금액 상한·근거 문장·버림 표시 등) |
| `notice_applicant_types` · `notice_industries` | 13 | 신청자 유형·업종 판정 |
| `notice_bonus` | 14 | 공고 가점(상태·항목·합계 한도·추출 당시 내용 지문·추출기 버전) |
