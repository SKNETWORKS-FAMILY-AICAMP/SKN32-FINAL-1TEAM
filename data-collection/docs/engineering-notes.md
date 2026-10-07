# 함정과 비결

## 데이터 신선도

**공고 서버가 새 공고를 모른다.**
- 증상: 배치가 성공했는데 추천·상세에 오늘 공고가 없다. 수집 상태 창구가 `지연`을 준다.
- 원인: 공고 서버는 켤 때 공고·BM25·판정표·가점을 메모리에 올리고 다시 읽지 않는다. 서버가 올린 공고의 저장 시각이 24시간을 넘으면 수집 상태도 `지연`으로 내려간다.
- 대응: 배치 뒤 서버를 다시 켠다. 사용자가 켜 둔 8000·8010은 **끄기 전에 사용자에게 묻는다.**

**PC의 로컬 벡터 파일·Chroma는 멈춰 있다.**
- 증상: PC `data/embeddings_v1.npz`·`data/vecstore/`가 10/2분(2,714건)이다. 이것을 읽는 평가 도구(`eval/build_pool.py`·`chroma_integrity.py` 등)는 그 뒤 공고를 모른다.
- 원인: 매일 배치가 2026-10-02부터 서버(`sbrain-web`)에서 돌아, 6·7단계가 서버의 `data/`만 갱신한다.
- 대응: 공고 서버는 2026-10-07부터 공용 DB 벡터를 직접 읽어 영향이 없다. 평가 도구로 비교할 때는 공용 DB 벡터를 쓰거나(`eval/vector_db_compare.py` 방식) 기준일을 적는다.

**배치 서버 코드는 저장소와 따로 논다.**
- 증상: PC에서 고친 배치 코드가 다음 날 배치에 반영되지 않는다(예: 10/2~10/7에는 14단계 가점 추출이 서버에 없어 새 공고 가산점이 null이었다).
- 원인: 서버 `~/sbrain/data-collection`은 git 체크아웃이 아니라 PC 작업 폴더를 복사한 것이다(마지막 복사 10/7, 코드 폴더 `collect·shared·search·experiments·ec2·db`만 — 이전 코드는 `~/sbrain/_old/code_before_20261007.tgz`).
- 대응: 서버 코드 다시 복사는 사용자 결정 사항이다. 복사할 때는 `experiments/`와 서버가 읽는 `reports/` 결과 파일(업종 final5, 신청자 유형)도 함께 가야 한다. 공용 DB 변경 SQL(007·008) 적용 여부도 함께 확인한다.

**판정표가 옛 공고문 기준이면 쓰지 않는다.**
- 신청자 유형 판정은 지금 공고문의 지문과 같은 행만 쓴다. 지문을 계산하지 못하면 기능 전체가 꺼진다(옛 '불가'로 신청 가능한 공고를 빼는 것보다 안전하다). 가점도 추출 당시 내용 지문·추출기 버전이 다르면 버린다. "판정이 갑자기 0건"이면 `/api/health`의 `applicant_types.error`·`stale`부터 본다.

## 임베딩·벡터

**BGE-M3 리비전이 다르면 공고 전체를 다시 임베딩한다.**
- 원인: 임베딩 설정 지문(모델·리비전·입력 버전·토큰 상한·차원·자료형·정규화 7개)이 하나라도 다르면 옛 벡터와 섞지 않고 전량 재생성한다(전량 약 32분). 지금 지문 `0a803d170f58c36e`.
- 대응: 새 환경에서는 리비전 `5617a9f…`를 고정해 받고, 오프라인(`HF_HUB_OFFLINE=1`)으로 돌린다. 리비전은 `~/.cache/huggingface/hub/models--BAAI--bge-m3/refs/main`에서 읽는다.

**질의 벡터는 `.tolist()`로 넘긴다.**
- 원인: numpy 배열을 `list()`로 감싸면 `np.float32` 스칼라 목록이 되어 Chroma(평가 도구에서 아직 씀)가 거부한다. 메모리 벡터 묶음은 둘 다 받지만 같은 모양을 유지한다.

**첫 질의가 약 20초 걸린다.**
- 원인: 모델 첫 호출 준비. 대응: `boot()`가 워밍업 인코딩을 한다. 워밍업이 실패하면 그동안 BM25 단독으로 답한다. 서버 시작은 약 22초, 메모리 약 2GB.

**벡터가 없는 공고는 의미 검색에서 빠진다.**
- 증상: 오늘 새로 들어온 공고가 추천(하이브리드)에 나오지 않는다(배치 6~8단계가 벡터를 올리기 전에 서버를 켠 경우). `BM25단독` 대체 경로에서만 나온다.
- 원인: `boot()`가 올린 벡터 ID만 의미 검색에 넘기고, 하이브리드는 단어 검색으로만 찾은 공고라도 벡터(유사도)가 없으면 결과에서 뺀다.
- 대응: 배치가 벡터를 올린 뒤(한국 09:03쯤) 서버를 다시 켠다 — 시험 서버는 09:20 재시작. 확인은 `/api/health`의 `indexed`와 `notices` 비교.

**Chroma와 메모리 계산은 순서가 조금 다르다.**
- 증상: 같은 벡터인데 Chroma로 찾은 상위 10과 순서가 가끔 다르다(10/7 비교: 상위 10 순서 같음 63/66, 1위는 66/66 같음).
- 원인: Chroma는 근사 검색(HNSW)이고, 메모리 묶음은 전부 비교한다. 메모리 쪽이 정확하다.
- 대응: 옛 평가 결과와 새 결과가 조금 다르면 이 차이를 먼저 의심한다. 같은 벡터로 다시 재려면 `.\.venv\Scripts\python.exe -X utf8 -m eval.vector_db_compare`.

**리눅스면 EC2로 판단한다.**
- 증상: 리눅스 서버·컨테이너에서 공고 서버를 켜면 DB를 `ec2/.env`로 붙고(`ec2/ec2_vecstore.connect`), BGE-M3를 직접 올리고, `0.0.0.0`에 연다.
- 원인: `ON_EC2 = sys.platform.startswith('linux')`. 대응: 리눅스에 올릴 때는 `ec2/.env`에 DB 설정을 두고 외부 접근을 보안그룹으로 막는다.

## 수집

**인증키는 디코딩 원본이어야 한다.** data.go.kr의 "인코딩된 인증키"(`%2B` 등)를 넣으면 이중 인코딩으로 인증 실패. `shared/config`가 경고를 찍는다.

**연휴에는 새 공고 0건이 정상이다.** 기업마당은 평일에만 새 공고가 올라오고, 전날 공고가 다음 날 API에 잡힌다. 10/3~10/5 연휴·9/24~27 추석에 0건이었다. "수집이 멈췄다"는 보고를 받으면 서버 `run.log`의 `exit=0`과 `import_runs` 저장 시각, 기업마당 원본 등록일(`creatPnttm`) 최신값부터 본다.

**K-Startup 목록이 덜 오면 모집 종료 처리를 건너뛴다.** 로그에 "목록을 오늘 빠짐없이 받지 못해 모집 종료 처리를 건너뛴다"가 남는다. 장애가 아니다.

**배치 로그 시각은 배치 PC 현지 시각이다.** `collect_log.jsonl`의 `run_at`은 한국 시간으로, `import_runs.imported_at`은 UTC로 읽는다.

**`docker compose run`이 표준입력을 삼킨다.** `run_batch.sh`의 `< /dev/null`을 지우면 cron에서 스크립트 나머지 줄이 실행되지 않는다.

**서버 시간대는 UTC다.** cron에 한국 시각을 적으면 9시간 밀린다. 한국 09:00 = `0 0 * * *`, 팀 EC2 색인 갱신 09:10 = `10 0 * * *`.

## 원격 작업

- 서버로 여러 줄 명령을 보낼 때는 Git Bash에서 `ssh.exe … 'bash -s' <<'EOF'`를 쓴다. PowerShell 파이프는 BOM·CRLF가 섞여 깨진다. cmd.exe에서는 `>`·`>=`·중첩 따옴표·heredoc이 깨지므로 파일로 올려 실행한다.
- 팀 EC2 22번 포트는 사용자 IP로 제한돼 있다. "3306은 되는데 22만 타임아웃"이면 사용자 IP가 바뀐 것이다.

## LLM 추출

- 가점 추출(`collect/extract_bonus`)은 `--plan`으로 대상·예상 비용을 먼저 본다. `--sample`·`--ids`는 DB에 쓰지 않고 `reports/`에 남긴다. `--all`만 공용 DB에 쓴다(유료·DB 쓰기 → 사용자 승인).
- 하루 상한 기록(`data/bonus_daily_calls.json`)을 읽지 못하면(깨짐) 그날은 가점 추출을 부르지 않는다(결과 `daily_record_unreadable`, 종료 코드 4). 파일이 없으면 0부터 센다. 깨진 파일은 사람이 확인해 고치거나 지운다 — 지우면 그날 이미 부른 수를 모른 채 다시 300건까지 부를 수 있다.
- 업종·신청자 유형 추출은 결과를 파일(`data/applicant_types/`·`data/industries/`)에만 쓰고, 13단계가 바뀐 행만 공용 DB로 올린다. 파일이 크게 줄면 경고만 내고 올리기는 막지 않는다.

## 시험 작성

- 배치 모듈의 기본 경로는 **함수를 정의할 때 묶인다**(`attachment_pipeline.done_already(path=RESULTS)`·`append`, `upload_vectors.load_local(path=NPZ)`, `upload_attachments.local_files(root=ATTACH)`). 시험에서 모듈 상수만 바꾸면 실제 `data/`를 읽고 쓴다(10/7 `data/attachment_results.jsonl`에 가짜 기록이 생긴 적 있음). 시험은 함수 자체를 임시 경로로 감싸서 바꾼다(`tests/test_attachment_pipeline.py`·`test_upload_vectors.py`·`test_upload_attachments.py`).
- 커버리지는 `.venv`에 `coverage`를 설치해 잰다(의존성 목록에는 없음). 범위·측정 스크립트는 `reports/unit_test_20261007T021113Z/`의 `run_unit.py`·`cov_summary.py`.

## 확인 순서 (반복 작업)

**10/7 이후 첫 배치 뒤 내용 지문 점검**
1. `.\.venv\Scripts\python.exe -X utf8 -m search.content_version --compare data/notice_api/content_version_20261006_cv2.json`
2. 새 공고가 들어왔는지, 바뀐 공고의 `by_field`가 특정 칸에 몰렸는지 본다.
3. 날마다 바뀌는 칸이 몰려 있으면 그 칸을 지문에서 빼고 접두어를 `cv3-`로 올린다. 확인: 다음 날 다시 비교해 원문이 그대로인 공고의 지문이 같은지 본다.

**조율 쪽 계약 시험 다시 돌리기**
1. 조율 브랜치 코드를 작업 폴더 **밖** 임시 폴더에 푼다: `git archive origin/feature/SB-87-init-supervisor-integration agent-orchestration/sbrain | tar -x -C <임시 폴더>`
2. 8000 서버가 지금 코드로 켜져 있는지 확인한다.
3. `.\.venv\Scripts\python.exe -X utf8 -m experiments.notice_api_contract --sbrain <임시 폴더>\agent-orchestration --all`
4. 확인: 16개 확인 통과, 모든 공고 G-01 형식 오류 0. 조율 쪽 코드는 우리 `.venv`로 불러진다(pydantic 같은 버전).

**배치 첫 실행·전환 뒤 점검**
1. 서버 `~/sbrain/data-collection/data/run.log` 마지막 `exit=` 값.
2. 공용 DB `import_runs` 최신 `imported_at`(UTC)과 `notice_count`.
3. 출처별 건수가 전날과 비슷한지(절반 미만이면 교체가 막혔을 것).
4. 확인: `/api/collection_status`가 `정상`(서버를 다시 켠 뒤).
