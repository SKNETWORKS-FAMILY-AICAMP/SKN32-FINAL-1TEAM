# 작업 인계 — 2026-09-14

이 문서 하나로 현재 상태를 파악할 수 있게 썼다. 커밋하지 않은 작업이 많아
`git log` 만으로는 알 수 없다.

담당 범위: `data-collection/` — 공고 수집·검색·자격요건 데이터 파이프라인

---

## 1. 한 장으로 보는 구조

```
작업 PC  매일 09:00 · 작업 스케줄러 S-Brain-DailyCollection · 약 5분
   1  collect/fetch.py               K-Startup 오픈API
   2  collect/fetch_bizinfo.py       기업마당 오픈API
   3  collect/normalize.py           두 출처를 공통 스키마로
   4  shared/store_mysql.py         MySQL 저장 (notices·notice_attachments·import_runs)
   5  attachment_pipeline    첨부 다운로드 → 본문 추출 → attachment_texts
   6  shared/embed.py               BGE-M3 벡터 → data/embeddings_v1.npz
   7  search/vecstore.py            로컬 Chroma 색인
   8  collect/upload_vectors.py      벡터 → EC2 MySQL notices.embedding            ← 신규
   9  collect/upload_attachments.py  첨부 원본 → EC2 MySQL attachment_files         ← 신규
  10  collect/extract_conditions.py  공고문에서 자격요건 추출(LLM) → notice_conditions ← 신규

EC2  43.201.90.238 · t3.medium 4GB · 스왑 2GB · 탄력적 IP
   MySQL s_brain                    공고·첨부·본문·벡터·자격요건
   ~/s-brain/data/vecstore/chroma   벡터 DB
   ~/s-brain/attachments            첨부 원본 612MB (2026-09-09부터 있었음)
   crontab 00:10 UTC (= 09:10 KST) ec2/ec2_vecstore.py  MySQL 벡터 → Chroma      ← 신규
```

**5~10단계는 모두 바뀐 것만 처리한다.** 두 번째 실행하면 전부 0건이 나온다.

2026-09-14 실측 — 신규 공고 30건이 들어온 실행에서 전 단계가 연쇄 동작했다.

```
정규화 1,794건 · 첨부 ok 32 · 임베딩 35 · 벡터 업로드 35
첨부파일 33개 12.5MB · 자격요건 32건(금액 7 · 형태 11) · 298.7초
```

---

## 2. 반드시 지켜야 할 제약

### 공고 검색은 벡터 DB(Chroma)를 거친다

MySQL 의 `notices.embedding` 을 직접 읽어 numpy 로 계산하는 경로를 **쓰지 않는다.**
성능만 보면 numpy 가 빠르지만(0.0ms vs 9ms), 요구사항은 성능이 아니라 아키텍처다.
벡터 DB 가 다른 앱이 붙어 쓰는 서비스여야 한다.

두 경로 결과가 같은 것은 실측으로 확인했다 — 상위 5건 순위·점수가 소수점 4자리까지
동일, 오차 3.58e-07. 그래도 Chroma 경로를 쓴다.

### 판정은 3단이다. `확인 필요` 를 뭉개지 않는다

`search/gate.py` 가 이 원칙으로 짜여 있다.

```
True   조건 충족          통과
False  조건 미달          탈락
None   확인할 수 없음      후보로 남기되 "확인 필요" 로 표기
```

`None` 을 `False` 로 뭉개면 기업마당 1,700여 건이 전건 탈락한다(업력·마감일 필드가
없다). `None` 을 조용히 `True` 로 처리하면 사용자가 자격을 확인받은 것으로 읽는다.
**못 찾은 것과 조건이 없는 것은 다르다.**

### 추출값은 근거 문장과 함께만 신뢰한다

LLM 추출은 `source_quote`(근거 원문)를 반드시 같이 저장한다. 근거가 없으면 값을
버린다. 근거 없이 숫자만 저장하면 틀렸는지 확인할 방법이 없다. 실제로 이 원칙
덕분에 금액 10배 오류와 나이·업력 혼동을 찾아냈다.

### 업력은 LLM 값을 판정에 쓰지 않는다

`notice_conditions.age_years_max` 는 컬럼만 두고 참고용이다. LLM 출력의 61%가
오답이었다(사람 나이·근속연수·개월을 업력으로 읽음). 업력 판정은 K-Startup 이
정형으로 주는 `notices.age_condition_raw` 를 쓴다 — `search/gate.py` 가 그렇게 한다.

---

## 3. 현재 데이터 (EC2 s_brain)

```
notices             2,084행   10.0MB   벡터 2,084건 (NULL 0)
notice_attachments  2,973행    1.8MB
attachment_texts    1,736행   28.6MB   ok 1,575 · image_only 157 · parse_error 4
attachment_files    1,679개  631.7MB   해시 전량 재검증 일치
notice_conditions   1,573행    0.5MB   아래 5절
import_runs            12행

로컬  data/attachments 637MB · Chroma 색인 2,084건
```

### 스키마 변경 (전부 적용 완료)

| 마이그레이션 | 내용 |
|---|---|
| `002_embedding.sql` | `notices` +5컬럼 — `embedding`(MEDIUMBLOB) `embedding_dim` `embedding_input_sha256` `embedding_fingerprint` `embedding_updated_at` + 색인 |
| `003_attachment_files.sql` | `attachment_files` — `content_sha256` PK · `bytes` LONGBLOB |
| `004_notice_conditions.sql` | `notice_conditions` 18컬럼 |
| `005_amount_rejected.sql` | `notice_conditions` +`amount_rejected` — 004 에서 `age_rejected` 만 만들고 대칭을 놓쳤다 |

기존 컬럼을 수정·삭제한 것은 없다. 추가만 했다. `notices` 33 → 38컬럼.

---

## 4. 실측 숫자 (추측 아님)

### 벡터 검색

```
문서 벡터      2,084건 × 1024차원 float32 = 8.1MB
질의 인코딩    258~390ms (EC2) · 200ms (PC) · 첫 질의는 20.8초
Chroma 검색    9ms
Chroma 색인    15MB · MySQL 벡터로 3초에 재생성 가능
EC2 메모리     BGE-M3 피크 2,731MB · 4GB 에서 MySQL 과 공존 확인
```

### 유사도 점수를 0~100 으로 바꾸지 말 것

```
"제조업 스마트공장 구축 보조금"   0.6728 0.6566 0.6458
"청년 창업 초기기업 자금 지원"    0.6416 0.6390 0.6371
"반려견 산책 도우미 매칭 플랫폼"   0.5402 0.5000 0.4899
상위 3건 전체 범위               0.49 ~ 0.67

무관한 질의 "오늘 날씨가 좋네요 점심 뭐 먹을까"  →  0.4329 0.4278 0.4231
```

**무관한 질의도 0.43 이 나온다.** ×100 하면 43점이 되고 사용자는 "좀 맞나" 로 읽는다.
목업의 `적합도 92/81/68` 은 실제 분포와 맞지 않는다. `search/app.py` 는 원값 + 3단 라벨
(`매우 적합`≥0.62 / `적합`≥0.55 / `참고`)로 표시한다.

### 자격요건 판정 가능 범위 (정형 데이터 기준)

| 항목 | 판정 가능 | 근거 |
|---|---|---|
| 접수기간 | **100%** | `apply_end` + `apply_period_type`(예산소진·상시·선착순·미정) |
| 업력 | 20% | `age_condition_raw` 350건(K-Startup만) + 정규식 60건 |
| 지원대상 유형 | — | `target_category` 는 "중소기업·소상공인" 같은 규모 분류라 개인/법인 구분 불가 |

`recruitment_status` 로 필터하면 안 된다 — 기업마당이 전부 `unknown` 이라 `open` 만
남기면 83%가 사라진다. 날짜(`apply_end`) 기준을 쓴다.

---

## 5. LLM 자격요건 추출 — 완료

### 결과

```
최초 전량    1,542건 · 실패 0 · 약 40분
현재         1,573건 (매일 신규분이 추가되고 있다)
누적 토큰     입력 6,424,658 · 출력 165,810
누적 비용     약 $1.06   (gpt-4o-mini 1M당 입력 $0.15 / 출력 $0.60 기준)
```

| 항목 | 건수 | 비율 | 판정에 사용 |
|---|---|---|---|
| 지원금액 `amount_max_won` | 664 | 42% | ✅ |
| 예비창업 가능여부 `pre_startup_allowed` | 853 | 54% | ✅ |
| 사업자 형태 `business_type` | 595 | 38% | ✅ |
| 업력 `age_years_max/min` | 128 | 8% | ❌ **참고용** |

금액대 분포: 1천만원 미만 321 · 1천만~1억 224 · 1억~10억 112

### 검산이 걸러낸 것

```
업력 폐기   200건   근거가 사람 나이·근속연수·개월 단위
금액 폐기    45건   근거에 금액 없음 · 후보와 불일치 · 10억 이상
금액 교정    50건   근거와 대조해 단위 자리수(10·100배) 보정
```

**업력은 LLM 출력의 61%가 오답이었다.** 검산 없이 저장했다면 200건의 잘못된
자격 판정이 들어갔다.

실제 오답 유형:

```
"만 19세 ~ 만 45세"        → 업력 45년           사람 나이
"장기재직(3년 이상)"        → 업력 3년            근로자 근속
"3개월 이상 영업 중"        → 업력 3년            개월을 년으로
"보증한도 1억 원 이내"      → 1,000,000,000원    억 단위 10배
"1억 5천만원 ~ 3억원 한도"  → 3,000,000,000원    억 단위 10배
"최고 보증지원 한도 4,000억원/건"  → 400,000,000,000원   사업 총 보증한도
"지원규모 : 500억원"        → 50,000,000,000원   사업 전체 예산
"매출액 200억원 이하 중소기업" → 20,000,000,000원   자격 기준을 지원금으로
```

### 금액 상한 — `AMOUNT_SANITY_MAX = 10 ** 9`

10억 이상은 근거와 숫자가 일치해도 버린다. 그 구간은 **숫자는 맞고 의미가 틀린**
경우(사업 총예산·전체 융자 규모·매출 기준)가 대부분이라 정규식으로 가릴 수 없다.
최초 전량 실행에서 38건이 이에 해당해 `NULL` 로 정리했다(695 → 657건).

조정하려면 `collect/extract_conditions.py` 의 상수를 고치고 `--redo` 로 재추출한다.
`/review` 화면에서 구간별로 근거를 보며 판단할 수 있다.

### 매일 드는 비용 (실측)

```
신규 32건    입력 129,767 · 출력 3,490 토큰  →  약 $0.021
한 달 환산                                    약 $0.63
```

문서 해시(`input_sha256`)가 같으면 LLM 을 부르지 않는다. 실행 직후 다시 돌리면
호출 0회다(확인함).

### 안전장치

```
--skip-conditions       LLM 을 끄고 배치를 돌린다
--conditions-limit N    이번 실행 상한 (비용 폭주 방지)
API 키 없음             건너뛰고 나머지 단계는 정상 진행
한 건 실패              멈추지 않고 실패 건수만 보고. 다음 실행이 재시도
```

---

## 6. 화면

### 시험용 매칭 화면 — `/`

```
.\.venv\Scripts\python.exe -X utf8 -m search.app   →  http://127.0.0.1:8000
```

리눅스에서 실행하면 `0.0.0.0:8000` 으로 뜬다(EC2 배포 대비). 준비에 약 20초
(모델 로딩 + 워밍업). 로그인·알림·포인트는 넣지 않았다.

```
입력(신청자 유형·대표자명·설립일자·아이디어·팀원·수익모델)
  → POST /api/match        벡터 검색 3건
  → 카드 클릭
  → POST /api/eligibility  search/gate.py 판정 4항목
```

### 추출 검토 화면 — `/review`

LLM 추출 결과를 **근거 문장과 나란히** 본다. 탭 9개로 구간별 확인:
금액 전체 · 1천만 미만 · 1천만~1억 · 1억~10억 · 10억 이상 · 검산 교정분 ·
사업자 형태 · 업력 남은 것 · 업력 폐기분.

조회 API: `GET /api/conditions?kind=amount|type|age_kept|age_rejected|corrected&band=&limit=`

---

## 7. 오늘 고친 버그

실제로 배치를 죽이고 있던 것들이다.

| 증상 | 원인 | 조치 |
|---|---|---|
| 작업 스케줄러 종료 코드 1 | `run_daily.bat` 이 LF 줄바꿈. cmd.exe 는 `.bat` 에 CRLF 필수 → `REM` 주석이 명령으로 실행됨 | CRLF 변환 |
| `schedule-task.ps1` 파싱 실패 | BOM 없는 UTF-8 → PowerShell 5.1 이 ANSI 로 읽어 한글 깨짐 → 따옴표 안 토큰 파괴 | BOM 추가 + CRLF |
| `ec2/ec2_vecstore.py` 접속 실패 | `.env` 를 읽는 코드가 없었음(환경변수만 봄) | `.env` 파서 + 빈 값 검사 |
| EC2 crontab 미등록 | `set -e` 에서 `crontab -l` 실패가 서브셸을 죽임 | `\|\| true` |
| LLM 추출 효과 절반 과소평가 | `GROUP_CONCAT` 이 1024바이트에서 자름(한글 340자). 19,563자 공고문이 앞 340자만 넘어감 | 첨부를 행별로 받아 파이썬에서 합침 |
| Chroma 가 질의 벡터 거부 | `list(numpy배열)` 이 `np.float32` 스칼라 목록을 만듦 | `.tolist()` |

`.gitattributes` 로 `*.bat`·`*.ps1` = CRLF, `*.sh`·`*.py` = LF 를 고정해 재발을 막았다.

---

## 8. 백업

```
data/backup_20260914T160825.sql   46.9MB
  import_runs 11 · notices 2,050 · notice_attachments 2,908 · attachment_texts 1,701
```

행수가 DB 와 일치하는 것을 검산했다. `mysqldump` 가 없어 `collect/backup_db.py` 를 만들었다.
표준 SQL 이라 어떤 클라이언트로도 복원된다.

```
mysql -h <host> -u <user> -p s_brain < data/backup_20260914T160825.sql
```

`attachment_files`(631MB)는 **일부러 제외** — 로컬 `data/attachments/` 로
`collect/upload_attachments.py` 가 재생성한다. 포함하려면 `--include-files`.

**이 백업은 자격요건 추출 전 시점이다.** `notice_conditions` 가 없다. 새로 뜨려면
`python -m collect.backup_db` 를 다시 돌린다(테이블 목록에 `notice_conditions` 를 추가해야 한다
— `CORE_TABLES` 상수).

---

## 9. 파일 목록

### 신규

| 파일 | 하는 일 |
|---|---|
| `collect/upload_vectors.py` | 벡터 → EC2 MySQL. 증분. `--plan` `--limit` |
| `collect/upload_attachments.py` | 첨부 파일 → EC2 MySQL. 증분. `--plan` `--limit` `--verify` |
| `collect/extract_conditions.py` | LLM 자격요건 추출 + 검산. `--sample` `--save-db` `--redo` · 배치는 `run_batch()` |
| `search/gate.py` `tests/test_gate.py` | 자격 판정. `finak_mok/poc` 에서 가져옴. 테스트 18개 |
| `search/app.py` `web/app.html` `web/review.html` | 시험용 화면 + 검토 화면 |
| `collect/backup_db.py` | DB 백업. `--include-files` |
| `search/search_local.py` | PC 검색 시험. ⚠ 기본 엔진이 `mysql` — 2절 제약과 어긋나므로 `chroma` 로 바꿔야 함 |
| `ec2/ec2_vecstore.py` | **EC2 실행.** MySQL 벡터 → Chroma. `--plan` `--rebuild` `--stat` |
| `ec2/ec2_search.py` | **EC2 실행.** 대화형 벡터 검색 |
| `ec2/ec2_check_model.py` | **EC2 실행.** BGE-M3 메모리·속도 측정 |
| `ec2_setup.sh` | **EC2 실행.** venv·의존성·색인·crontab 한 번에 |
| `mysql_migration_00{2,3,4,5}_*.sql` | 스키마 변경 이력 |
| `TEAM_DATA.md` | **팀원용.** 공고·첨부·벡터를 개발에 쓰는 법 |
| `HANDOFF.md` | 이 문서 |
| `.gitattributes` | 줄바꿈 고정 |

### 수정

```
collect/daily_pipeline.py    8·9·10단계 편입 · --skip-upload --skip-files --skip-conditions
                     --conditions-limit · 요약줄 3줄 추가
run_daily.bat        CRLF 변환 (배치가 죽던 원인)
schedule-task.ps1    BOM 추가 + CRLF (파싱 실패 원인)
README.md FLOW.md    8·9단계 문서화 (10단계는 아직 반영 안 됨)
.gitignore           산출물 패턴 추가 (npz·vecstore·backup·표본 JSON)
```

### 커밋 상태

**전부 커밋하지 않았다.** 작업 트리에만 있다. 브랜치 `feature/SB-46-data-collection`.
코덱스와 같은 폴더를 보며 작업하기로 해서 커밋을 미뤘다.

---

## 10. 접속 정보와 환경

```
EC2        43.201.90.238  ubuntu@ip-172-31-16-208  t3.medium 4GB + 스왑 2GB
SSH 키     C:\Users\playdata2\.ssh\skn32-1team.pem   (SKN32-1Team.ppk 변환본)
보안그룹    22 → 작업자 IP 만 · 3306 → 개방
MySQL      s_brain / s_brain_team · require_secure_transport=ON
로컬 venv   data-collection/.venv
EC2 venv    ~/s-brain/.venv
```

`.env` 에 `KSTARTUP_KEY` `BIZINFO_KEY` `OPENAI_API_KEY` `MYSQL_*` 가 있다.
EC2 쪽 `.env` 는 `MYSQL_HOST=127.0.0.1` + `MYSQL_SSL=1` 이고 API 키는 넣지 않았다.

### 걸려 넘어질 것들

**`.ppk` 는 OpenSSH 가 못 읽는다.** `ssh -i` 에는 변환한 `.pem` 을 쓴다. PuTTY 의
명령줄 변환(`puttygen.exe ... -O private-openssh`)이 이 환경에서 조용히 실패(exit 1)
했다. 파이썬으로 직접 변환했다.

**cmd.exe 에서 ssh 명령을 줄 때** `>` `>=` `<` `|` `&` 중첩 따옴표 heredoc 이 전부
깨진다. `pip install 'x>=3.0'` 이 `=3.0` 파일로 리다이렉션되며 실패한다. 복잡한 것은
파일로 올려서 실행한다.

**22번이 타임아웃이고 3306 은 되면** IP 가 바뀐 것이다. 보안그룹 22번 소스를
`내 IP` 로 다시 선택한다.

**`GROUP_CONCAT` 을 긴 텍스트에 쓰지 말 것.** `group_concat_max_len` 기본값 1024바이트
= 한글 340자에서 잘린다. 조용히 잘려서 알아채기 어렵다.

**작업 스케줄러가 `Interactive` 로 등록돼 있다.** `S4U` 등록이 권한 부족으로 거부됐다.
**로그오프 상태에서는 배치가 돌지 않는다.** 관리자 권한 PowerShell 에서
`-Mode Uninstall` 후 `-Mode Install` 하면 `S4U` 로 바뀐다.

**EC2 는 UTC 다.** crontab 시각을 한국시간으로 적으면 9시간 밀린다. 처음에 `10 9` 로
등록해 18:10 KST 에 돌았다. 09:10 KST 는 `10 0 * * *` 이다(2026-09-15 수정).

**`MYSQL_SSL_CA` 를 비우고 평문으로 붙으면 거부된다.** 루프백이라도
`require_secure_transport=ON` 이 적용된다. EC2 안에서는 `MYSQL_SSL=1` 을 쓴다.

---

## 11. 열려 있는 결정

| 항목 | 상태 |
|---|---|
| 매칭 화면에 금액·형태 연결 | ❌ `/api/match` 가 `notice_conditions` 를 조인하지 않는다. 목업의 "최대 1억원" 이 아직 안 나온다 |
| `search/gate.py` 의 `지원대상 유형` 판정 | ❌ 무조건 `확인 필요`. `business_type`·`pre_startup_allowed` 를 쓰면 판정 가능 (`search/app.py` 의 `eligibility()` 참조) |
| `attachment_files` 중복 | EC2 파일시스템에 612MB 가 이미 있었다(9/9부터). MySQL 631MB 는 중복. 지우면 DB 672 → 41MB. 9단계를 rsync 로 바꾸는 선택지 |
| `search/search_local.py` 기본 엔진 | `mysql` → `chroma` 로 바꿔야 함 |
| `AMOUNT_SANITY_MAX` 값 | 10억. `/review` 로 확인하고 조정 |
| 업력 폐기 기준 | `"1년 이상 운영 중"` 처럼 실제 업력인데 버린 사례가 있다. `운영 중`·`사업 중` 을 인정 목록에 추가할지 |
| AI 요약 한 줄 | 목업에 있으나 미구현. LLM 필요. 매칭 3건만이라 저렴 |
| 모집 상태 행 | `search/gate.py` 가 검사한다. 화면 요구는 3항목이라 뺄지 결정 |
| `search/app.py` EC2 배포 | 지금은 PC 전용. 포트 8000 개방 + systemd 필요 |
| Chroma 서버 모드 | 팀원이 벡터 DB 에 직접 붙으려면 `chroma run` + 포트 + 인증 필요 |
| `collect/backup_db.py` 대상 | `notice_conditions` 가 `CORE_TABLES` 에 없다 |
| README·FLOW 10단계 | 8·9단계만 반영돼 있다 |
| 커밋 | 미수행 |

---

## 12. 재현 절차

```powershell
# 로컬
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline --dry-run          # 수집만. DB 안 건드림
.\.venv\Scripts\python.exe -X utf8 -m collect.daily_pipeline --skip-conditions  # LLM 없이 전체
.\.venv\Scripts\python.exe -X utf8 -m search.app                               # 화면 + /review
.\.venv\Scripts\python.exe -X utf8 -m collect.extract_conditions --sample 30    # 표본만. DB 안 씀
.\.venv\Scripts\python.exe -X utf8 -m collect.backup_db
```

```bash
# EC2
ssh -i "C:/Users/playdata2/.ssh/skn32-1team.pem" ubuntu@43.201.90.238
cd ~/s-brain && .venv/bin/python -m ec2.ec2_vecstore --stat    # 색인 상태
cd ~/s-brain && .venv/bin/python -m ec2.ec2_search             # 대화형 검색
crontab -l                                                 # 09:10 갱신 확인
```

테스트 81개 통과(기존 63 + gate 18). MySQL 통합 13개는 `MYSQL_INTEGRATION_TEST=1`
없으면 건너뛴다.
