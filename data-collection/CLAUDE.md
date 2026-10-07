# data-collection — 공고 데이터·매칭·자격 판정

S-Brain(정부지원사업 사업계획서·프로토타입 생성 서비스, SK네트웍스 Family AI 32기 1팀)에서 **공고를 모으고, 신청자에게 맞는 공고를 고르고, 자격을 판정하는** 부분이다. 담당은 이근준 한 명이고, 공고 약 2,700건·하루 한 번 배치·Python(FastAPI·MySQL·BGE-M3)의 작은 규모다. 결과는 조율 에이전트(다른 팀원)가 HTTP로 부르고, 팀원은 공용 DB를 읽는다. 최종 발표 2026-10-26, 배포 완료 10/25.

## 폴더 지도

```
data-collection/
├── AGENTS.md · CLAUDE.md          ← 지금 이 안내(두 파일 내용 같음)
├── docs/
│   ├── architecture.md            ← 구성 요소·어디서 무엇이 도는지·배치/추천/서버 기동 흐름·공용 DB 테이블
│   ├── business-rules.md          ← 판정 원칙: 모르면 빼지 않음, 정형 필터, 순위 규칙, 자격 판정, 수집·수집 상태, 내용 지문, 가산점
│   ├── security.md                ← 보호 대상, 누가 무엇을 해도 되는지, DB 접속·비밀값·비용·수집 예절
│   ├── standards.md               ← 어기면 깨지는 규칙(Git, 실행, 폴더 경계, 배치 단계, 버전 값, DB 변경, 검증, 기록)
│   ├── engineering-notes.md       ← 함정(증상 → 원인 → 대응)과 반복 점검 순서
│   ├── operations.md              ← 설치·자주 쓰는 명령·환경 변수·서버 배치 운영·되돌리기
│   ├── contracts.md               ← 조율 에이전트용 HTTP 창구 4개와 팀원용 DB 테이블 약속
│   ├── tracking/
│   │   ├── status.md              ← 맡은 범위 대비 끝난 것·남은 일·막힌 것
│   │   ├── decisions/index.md     ← 결정 기록 목록(0001~0012)
│   │   └── findings.md            ← 아직 못 푼 문제
│   ├── STATUS.md · WORKLOG.md     ← 진행 일지(세션마다 갱신, 맨 위가 최신)
│   ├── NEXT_SESSION_HANDOFF_*.md  ← 최신 인계서(새 세션 시작점)
│   ├── FLOW.md                    ← 배치 단계별로 파일이 주고받는 것(자세한 설명)
│   └── README.md                  ← 문서 지도(reviews·specs·guides·archive 등 하위 폴더)
├── collect/AGENTS.md              ← 매일 배치 14단계
├── search/AGENTS.md               ← 공고 서버: 필터·검색·순위·자격 판정·조율 창구·가산점
├── shared/AGENTS.md               ← 설정·DB 저장·임베딩 입력·지역 어휘
├── ec2/AGENTS.md                  ← 팀 EC2 색인 갱신·리눅스 접속
├── db/AGENTS.md                   ← 테이블 생성문·변경 SQL
├── eval/AGENTS.md                 ← 검색 평가셋·지표·판정 화면
├── experiments/AGENTS.md          ← 검증 화면(8010)·실험 DB·배치/서버가 쓰는 LLM 추출 함수
├── ml/AGENTS.md                   ← 리랭커·업력 분류기(제출물, 서비스 미연결)
├── web/AGENTS.md                  ← 공고 서버가 내려 주는 시험 화면
└── share/AGENTS.md                ← 서버 없이 보는 공유 HTML
```

## 꼭 지킬 것

1. **git commit·push·`git add`는 사용자만 한다.** 남이 해 둔 수정·스테이징은 되돌리거나 덮지 않는다.
2. **모르면 빼지 않는다.** 확실한 미달만 후보에서 빼고 불합격으로 낸다. 판정할 수 없음을 미달로도, "제한 없음"으로도 바꾸지 않는다. 지역·업종은 걸러내지 않고 순위에만 쓴다.
3. **사용자 요청 없이 하지 않는다**: 공용 DB 쓰기·변경 SQL 적용, 배포·서버 코드 복사·AWS 변경, 켜져 있는 8000·8010 서버 끄기, 약 $5 이상 드는 LLM 실행.
4. **조율 쪽과 맞춘 창구 응답(키·값·오류 코드)을 말없이 바꾸지 않는다.** 바꾸려면 조율 담당에게 보낼 문서를 먼저 고친다.
5. K-Startup 첨부는 자동으로 내려받지 않는다(robots.txt 금지). 키·비밀번호·신청자 개인정보를 문서·결과·로그에 쓰지 않는다.

## 작업 전에 읽을 것

- 항상: `docs/standards.md`, `docs/engineering-notes.md`, 고칠 폴더의 `AGENTS.md`, 진행 일지 `docs/STATUS.md` 맨 위 항목과 `docs/WORKLOG.md` 최근 항목. 새 세션이면 최신 `docs/NEXT_SESSION_HANDOFF_*.md`.
- 판정·필터·순위를 고치기 전: `docs/business-rules.md`의 2~5절과 결정 0001·0002·0003. 정형 필터와 자격 판정이 같은 결론을 내는지 시험으로 확인할 방법을 먼저 정한다.
- 조율 창구·추천 응답을 고치기 전: `docs/contracts.md` 전체와 결정 0005·0008.
- 매일 배치 단계를 더하거나 고치기 전: `docs/standards.md`의 "매일 배치 단계"·"버전 값", `docs/engineering-notes.md`의 "배치 서버 코드는 저장소와 따로 논다", `collect/AGENTS.md`.
- DB 테이블을 바꾸기 전: `db/AGENTS.md`, `docs/security.md`의 접근 표.
- 내용 지문·가점 추출기·임베딩 설정을 바꾸기 전: `docs/standards.md`의 "버전 값" — 바꾸면 전량 무효화·재계산이 따라온다.
- 검색 비교·평가를 하기 전: `docs/standards.md`의 "결과·평가 기록", `eval/AGENTS.md`.
- 서버·배포 작업 전: `docs/operations.md` 4~6절, `docs/security.md`의 "공고 서버 접근 정책".

## 문제를 만나면

곧바로 사용자에게 알릴 것(작업을 멈추고):
- 공용 DB의 공고·판정 데이터가 지워지거나 잘못 덮였을 가능성(잘못된 UPSERT, 의도치 않은 변경 SQL, 실험 테이블이 공용 DB에 생김).
- 정형 필터·자격 판정이 신청 가능한 공고를 빼거나 불합격으로 내는 결함(특히 판정 불가를 미달로 바꾸는 변경).
- 매일 배치가 연속으로 실패하거나(`exit=1`·`2`), 수집 상태가 `실패`.
- 키·비밀번호·신청자 개인정보가 저장소·문서·로그·응답에 노출됨.
- LLM 비용이 하루 상한을 넘어 계속 호출되는 상황.
- 조율 쪽과 맞춘 응답 형식이 깨진 것(계약 시험 실패).

그 밖에 지금 풀 수 없는 문제는 `docs/tracking/findings.md`에 증상·영향·지금 못 푸는 이유·가능한 방법으로 적는다.

## 새 대화를 시작할 때

저장소 루트에서 시작하면 이 안내를 자동으로 못 읽을 수 있다. 그럴 때는 이렇게 시작한다.

> data-collection/AGENTS.md를 읽고, docs/STATUS.md 맨 위와 최근 WORKLOG.md, 최신 인계서를 확인한 뒤 작업해줘. 커밋과 push는 내가 직접 한다.

사용자와의 대화는 한국어로, 비유를 먼저 들고 쉬운 말로 한다. 사용자 터미널은 PowerShell 5.1이다.
