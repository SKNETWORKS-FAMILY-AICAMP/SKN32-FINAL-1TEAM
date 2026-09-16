# 웹 개발 Agent 지식 TOP 40 수집 데이터 보고서

## 1. 수집 데이터 개요

| **데이터명** | **수집 대상** | **수집 목적** | **사용 예정 기능** | **출처 / 저작권** |
| -------- | --------- | --------- | ------------ | ------------ |
| 웹 개발 Agent 지식 TOP 40 | 개발 방법론, 설계·아키텍처, 개발 실무·품질, 개발자 연차별 역량 | 개발 Agent가 프롬프트 작성, 설계 판단, 구현·검증 기준 설정에 참고할 구조화 지식 확보 | 개발 Agent 지식 검색, 프롬프트 컨텍스트 주입, 설계·품질 체크리스트 생성 | 공식 문서와 공개 기술 자료 URL 기반 요약. 원문 저작권은 각 출처에 귀속되며 본 데이터는 요약·메타데이터 형태 |

## 2. 수집 방법 및 자동화 절차

웹 크롤링 방식으로 공식 문서와 신뢰 가능한 기술 자료 URL을 수집하고, 원문 접근 가능 여부와 제목·해시를 `source_manifest.json`에 기록했다. 수집 후 4개 분류별 TOP 10 지식을 사람이 검토 가능한 JSON과 Markdown 형태로 구조화했다.

## 2.2 수집 방식

| **사용 언어 / 라이브러리** |
| -------------------- |
| Python, requests, BeautifulSoup, hashlib, json |
| **자동화 여부 및 주기** |
| 수동 실행 기반 자동화. 필요 시 `crawler.py`를 다시 실행해 최신 출처를 재수집 |
| **오류 발생 시 예외 처리 전략** |
| URL별 수집 성공·실패를 `source_manifest.json`에 기록하고, 원문 수집 실패 출처는 고품질 데이터에서 제외 |

## 4. 예시 스크립트 또는 흐름도 첨부

```text
출처 URL 목록 정의
→ 원문 HTML 요청
→ 제목·본문·SHA-256 기록
→ 개발 지식 항목 구조화
→ development_knowledge.json 저장
→ development_knowledge.md 및 collection_report.md 생성
```

```powershell
cd test/crawling/development_knowledge
python -B crawler.py
```

## 5. 파일 및 필드 설명

| **파일명 / 테이블명** | **필드명** | **데이터 타입** | **설명** | **예시** |
| -------------- | ------- | ---------- | ------ | ------ |
| `development_knowledge.json` | `categories` | array | 4개 지식 분류 목록 | 개발 방법론 및 개발 프로세스 |
| `development_knowledge.json` | `items` | array | 분류별 지식 항목 | SOLID |
| `development_knowledge.json` | `definition` | string | 개념 및 정의 | 변경 이유별 책임 분리 |
| `development_knowledge.json` | `whenToUse` | string | 사용 시점 | 변경이 잦고 결합이 높을 때 |
| `development_knowledge.json` | `howToApply` | string | 실제 적용 방법 | 책임 분리, 인터페이스 의존 |
| `development_knowledge.json` | `cautions` | string | 주의점 | 과도한 추상화 주의 |
| `development_knowledge.json` | `sources` | array | 참고 출처 URL | https://scrumguides.org/ |
| `source_manifest.json` | `url` | string | 수집 원문 URL | https://developer.mozilla.org/ |
| `source_manifest.json` | `sha256` | string | 원문 식별용 해시 | 64자 해시 |
| `development_knowledge.md` | 문서 본문 | markdown | 사람이 읽는 지식 목록 | TOP 40 표 |

## 6. 데이터 양

| **전체 수집 데이터 건수** |
| ----------------------------- |
| 40개 지식 항목, 참조 URL 36개 |
| **추출된 고품질 데이터 건수 (필터링 후 기준)** |
| 40개 지식 항목, 원문 수집 성공 URL 36개 |

## 7. 저장 위치 및 포맷

| **저장 경로** |
| --------- |
| `test/crawling/development_knowledge/output/development_knowledge.json` |
| **저장 포맷** |
| JSON, Markdown |
| **인코딩** |
| UTF-8 |

## 8. 법적·윤리적 검토

| **개인정보 포함 여부** |
| -------------------- |
| 없음 |
| **포함된 경우 필드** |
| 해당 없음 |
| **비식별화 조치 여부** |
| 해당 없음 |
| **출처 및 사용권 — 공개 여부** |
| 공개 웹 문서 URL 기반. 원문은 복제하지 않고 요약과 링크를 저장 |
| **라이선스 / 약관 검토 여부** |
| 출처 URL 보존. 실제 배포·상업 활용 전 각 출처 약관 재확인 필요 |
| **검토자** |
| 박상희 |
| **검토 일자** |
| 2026-09-14 |

## 9. 데이터 품질 및 정합성 관리 방안

| **중복 제거 기준** |
| -------------------- |
| 동일 지식명, 동일 출처 URL, 동일 개념 범위 기준으로 중복 제거 |
| **정합성 검증 방법** |
| 원문 URL 접근 성공 여부, 제목·SHA-256 기록, 분류별 10개 항목 수 검증 |
| **Null 처리 및 결측치 전략** |
| 필수 필드가 비어 있으면 항목에서 제외하거나 보완 후 저장 |
| **표준화 전략** |
| 지식명, 개념, 사용 시점, 적용 방법, 장점, 주의점, 출처 URL 형식 통일 |

## 10. 변경 이력 및 보완 내역

| **변경일** | **변경자** | **변경 내용** | **비고** |
| ------- | ------- | --------- | ------ |
| 2026-09-14 | 박상희 | 개발 지식 TOP 40 수집 데이터 생성 | 최초 산출 |
| 2026-09-14 | 박상희 | 지정 보고서 양식 추가 | 기존 상세 본문 유지 |

## 기존 상세 보고서

- 보고서 생성일: 2026-09-14
- 수집 항목: 40개, 4개 분류에 각 10개
- 참조 URL: 36개; 원문 수집 성공: 36/36개
- 원본: [구조화 데이터](development_knowledge.json), [읽기용 목록](development_knowledge.md), [출처 수집 기록](source_manifest.json)

## 조사 목적과 해석 범위

개발 Agent가 요구사항 분석, 설계, 구현, 검증, 협업 단계에서 참고할 실무 지식을 정리했다. 각 항목에는 개념, 사용 시점, 적용 방법, 장점, 주의점, 출처 URL과 프롬프트 힌트가 있다. TOP 40의 순서는 사용 빈도나 성과에 대한 통계 순위가 아니라 실무 활용도를 기준으로 편집한 순서다. 연차별 역량은 수행 책임의 예시이며 근속 연수나 SFIA 등급과 일대일로 대응하지 않는다.

## 핵심 결과

| 분류 | 항목 수 | Agent 활용 지점 |
| --- | ---: | --- |
| 개발 방법론 및 개발 프로세스 | 10 | 과제의 불확실성·변경 빈도에 맞춰 진행 방식을 선택 |
| 소프트웨어 설계·아키텍처 | 10 | 경계, 의존성, 데이터 정합성, 인터페이스를 설계 |
| 개발 실무 및 품질 관리 | 10 | 브랜치·리뷰·테스트·배포·보안·성능의 완료 기준 설정 |
| 개발자 연차별 역량 | 10 | 역할과 책임에 맞게 작업 분해 및 리뷰 수준 조정 |

개발 Agent에는 전체 40개를 매번 주입하기보다 작업 유형에 맞는 항목을 선택하는 편이 좋다. 예를 들어 신규 API 구현은 REST 자원 설계·데이터베이스 제약과 트랜잭션·단위/통합 테스트를, 기존 서비스 수정은 Git 통합 전략·코드 리뷰·디버깅을 함께 참조한다. 이 조합은 보고서 작성자의 활용 제안이며 수집 출처가 검증한 성능 비교 결과는 아니다.

## 전체 항목과 적용 지침

### 개발 방법론 및 개발 프로세스

| 순위 | 지식 | 사용 시점 | 실제 적용 방법 | 주의점 | 출처 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 워터폴 | 범위와 승인 단계가 명확한 프로젝트 | 요구사항과 단계별 산출물·검수 기준을 먼저 정하고 변경 절차를 둔다 | 변경이 잦으면 후기 수정 비용이 커진다 | [원문](https://www.atlassian.com/agile/project-management/waterfall-methodology) |
| 2 | 애자일 | 요구가 변하거나 사용자 검증이 필요한 제품 | 작은 기능을 우선순위화하고 작동하는 결과를 주기적으로 보여준다 | 계획·문서가 불필요하다는 뜻은 아니다 | [원문](https://agilemanifesto.org/principles) |
| 3 | 스크럼 | 팀이 짧은 주기로 제품 가치를 전달할 때 | 제품 백로그를 정렬하고 스프린트 목표와 완료 정의를 합의한다 | 이벤트만 흉내 내고 완료 가능한 증가분이 없으면 효과가 약하다 | [원문](https://scrumguides.org/scrum-guide.html) |
| 4 | 칸반 | 지원·유지보수처럼 일이 계속 유입될 때 | 시작·진행·완료 흐름을 정의하고 병목·흐름 지표를 점검한다 | 보드만 만들고 흐름 정책을 운영하지 않으면 개선되지 않는다 | [원문](https://kanbanguides.org/the-kanban-guide/2020.12/) |
| 5 | 테스트 주도 개발 TDD | 규칙이 명확한 로직을 안전하게 만들 때 | 작은 동작의 실패 테스트를 작성하고 통과시킨 뒤 중복을 정리한다 | 구현 세부사항만 테스트하면 변경에 취약하다 | [원문](https://martinfowler.com/bliki/TestDrivenDevelopment.html) |
| 6 | 행동 주도 개발 BDD | 요구 해석 차이가 잦은 기능 | 사용자 예시를 발견·표현하고 중요한 시나리오를 자동화한다 | Given/When/Then 문법만 쓰는 것은 BDD가 아니다 | [원문](https://cucumber.io/docs/bdd/) |
| 7 | 도메인 주도 설계 DDD | 업무 규칙이 복잡하고 팀 간 의미가 다른 경우 | 도메인 전문가와 용어를 맞추고 경계별 모델·규칙을 분리한다 | 단순 CRUD에 모든 패턴을 적용하면 과설계가 된다 | [원문](https://www.domainlanguage.com/ddd/reference/) |
| 8 | MVP | 제품 가치와 고객 수요가 불확실할 때 | 검증할 가설·대상 사용자를 정하고 최소 기능을 출시해 학습한다 | 최소 기능을 저품질과 혼동하지 않는다 | [원문](https://martinfowler.com/articles/lean-inception/) |
| 9 | 프로토타이핑 | 사용성·기술 가능성이 불확실할 때 | 가설 하나를 정해 화면 또는 기술 시제품을 만들고 관찰 결과를 기록한다 | 시제품을 검증 없이 운영 코드로 승격하지 않는다 | [원문](https://www.ibm.com/training/enterprise-design-thinking/framework) |
| 10 | 반복 개발 | 초기 요구를 모두 확정하기 어려울 때 | 기능을 세로로 작게 나누고 반복마다 통합·평가·재계획한다 | 반복 계획 없이 기능만 추가하면 범위가 흔들린다 | [원문](https://martinfowler.com/articles/newMethodology.html) |

### 소프트웨어 설계·아키텍처

| 순위 | 지식 | 사용 시점 | 실제 적용 방법 | 주의점 | 출처 |
| ---: | --- | --- | --- | --- | --- |
| 1 | SOLID | 변경이 잦고 객체 간 결합이 높을 때 | 변경 이유별로 책임을 분리하고 핵심이 구현 세부사항에 의존하지 않게 한다 | 모든 클래스에 추상화를 추가하는 규칙으로 쓰지 않는다 | [원문](https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/architectural-principles) |
| 2 | DRY | 동일 업무 규칙이 여러 곳에서 수정될 때 | 중복 규칙의 단일 소유 위치를 만들고 호출 측에서 재사용한다 | 겉모양만 비슷한 코드를 성급히 합치지 않는다 | [원문](https://martinfowler.com/bliki/BeckDesignRules.html) |
| 3 | 단순 설계 KISS | 새 기능의 구조를 선택할 때 | 테스트를 통과하는 가장 단순한 설계를 택하고 실제 변경 압력이 생길 때 확장한다 | 단순함을 필수 요구 누락의 핑계로 삼지 않는다 | [원문](https://martinfowler.com/bliki/BeckDesignRules.html) |
| 4 | MVC | 서버 렌더링 웹 앱이나 요청 처리 계층을 설계할 때 | 컨트롤러는 입력을 조정하고 모델은 규칙을, 뷰는 표시를 담당하게 한다 | 컨트롤러에 모든 업무 로직을 몰아넣지 않는다 | [원문](https://learn.microsoft.com/en-us/aspnet/core/mvc/overview) |
| 5 | 클린 아키텍처 | 외부 DB·UI 교체나 복잡한 업무 규칙이 예상될 때 | 핵심 모델·인터페이스를 안쪽에 두고 DB·HTTP 구현을 바깥에 둔다 | 작은 앱에 계층·프로젝트를 과도하게 늘리지 않는다 | [원문](https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/common-web-application-architectures) |
| 6 | 레이어드 아키텍처 | 전형적인 업무 웹 앱의 변경 경계를 정할 때 | 계층별 인터페이스와 호출 방향을 정하고 순환 의존을 피한다 | 단순 전달 계층만 늘면 복잡도만 증가한다 | [원문](https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/n-tier) |
| 7 | REST 자원 설계 | 외부 또는 프런트엔드용 HTTP API를 만들 때 | 자원 URI를 정하고 GET·POST·PUT·DELETE와 상태 코드를 의미에 맞게 사용한다 | 모든 동작을 CRUD에 억지로 맞추지 않는다 | [원문](https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods) |
| 8 | 데이터베이스 제약과 트랜잭션 | 여러 테이블을 갱신하거나 중복·누락을 막을 때 | 기본키·외래키·유니크 제약을 두고 함께 성공해야 할 변경을 트랜잭션으로 묶는다 | 긴 트랜잭션과 불필요한 잠금을 피한다 | [원문](https://www.postgresql.org/docs/current/tutorial-transactions.html) |
| 9 | 디자인 패턴 | 객체 생성·상태·구성의 문제가 반복될 때 | 문제를 먼저 설명하고 적합한 패턴을 작은 범위에 적용한다 | 패턴 이름을 목표로 과설계하지 않는다 | [원문](https://refactoring.guru/design-patterns) |
| 10 | 의존성 주입 | 테스트 대역이나 구현 교체가 필요한 서비스 | 핵심 코드는 인터페이스에 의존하고 시작 지점에서 실제 구현을 연결한다 | 단순 객체까지 모두 주입하면 구성이 난해해진다 | [원문](https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection/overview) |

### 개발 실무 및 품질 관리

| 순위 | 지식 | 사용 시점 | 실제 적용 방법 | 주의점 | 출처 |
| ---: | --- | --- | --- | --- | --- |
| 1 | Git 브랜치와 통합 전략 | 여러 개발자가 같은 저장소에서 일할 때 | 작은 브랜치를 만들고 자주 동기화하며 검토·검사를 통과한 뒤 병합한다 | 오래 살아 있는 브랜치는 통합 충돌을 키운다 | [원문](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches) |
| 2 | 코드 리뷰 | 공유 코드나 운영 영향이 있는 변경 | 작은 PR에 의도·검증 결과를 적고 구체적인 리뷰 의견을 주고받는다 | 리뷰를 개인 평가나 단순 승인 절차로 만들지 않는다 | [원문](https://docs.github.com/en/pull-requests/reference/pull-request-reviews) |
| 3 | 단위 테스트 | 업무 규칙과 경계 조건을 빠르게 확인할 때 | 입력·기대 출력을 명시하고 정상·오류·경계 사례를 자동화한다 | 내부 구현만 고정하는 테스트를 피한다 | [원문](https://docs.pytest.org/en/stable/getting-started.html) |
| 4 | 통합 테스트 | DB·API·서비스 사이 오류가 걱정될 때 | 실제 또는 통제된 의존성을 연결해 주요 성공·실패 흐름을 실행한다 | 모든 사례를 느린 통합 테스트로만 검증하지 않는다 | [원문](https://learn.microsoft.com/en-us/aspnet/core/test/integration-tests) |
| 5 | E2E 테스트 | 로그인·결제 등 핵심 경로를 출시 전 확인할 때 | 브라우저로 시작부터 결과까지 실행하고 안정적인 사용자 선택자를 사용한다 | 모든 세부 경우를 E2E로 검증하면 느리고 불안정하다 | [원문](https://playwright.dev/docs/intro) |
| 6 | CI | 팀 변경의 통합 결함을 일찍 찾을 때 | PR과 기본 브랜치에서 빌드·린트·테스트를 자동 실행한다 | CI가 느리거나 자주 실패하면 신뢰가 떨어진다 | [원문](https://docs.github.com/en/actions/get-started/continuous-integration) |
| 7 | CD | 반복 배포와 롤백을 안정화할 때 | 빌드·테스트 뒤 환경별 배포와 승인·비밀 관리·복구 경로를 설정한다 | 자동화 전에 배포 실패 시 복구 방법을 정한다 | [원문](https://docs.github.com/en/actions/get-started/continuous-deployment) |
| 8 | 디버깅 | 증상만 있고 원인이 불명확할 때 | 오류를 재현하고 로그·브라우저 개발 도구·중단점으로 원인을 좁힌다 | 민감 정보를 로그에 남기지 않는다 | [원문](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Scripting/Debugging_JavaScript) |
| 9 | 웹 보안 점검 | 인증·입력·권한을 다루는 웹 서비스 | OWASP 위험 목록을 점검표로 쓰고 접근 통제·입력 처리·의존성을 검토한다 | Top 10만으로 모든 위협을 포괄하지 않는다 | [원문](https://owasp.org/www-project-top-ten/) |
| 10 | 성능 측정과 최적화 | 페이지 응답이 느리거나 사용자 경험이 나쁠 때 | 실사용 지표와 프로파일을 확인하고 큰 리소스·긴 작업부터 줄인다 | 측정 없이 미세 최적화부터 시작하지 않는다 | [원문](https://web.dev/articles/vitals) |

### 개발자 연차별 역량

| 순위 | 지식 | 사용 시점 | 실제 적용 방법 | 주의점 | 출처 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 주니어 · 웹 언어 기초 | 작은 화면과 기능을 독립 구현할 때 | 시맨틱 HTML과 CSS 레이아웃·JS 이벤트를 직접 구현하고 설명한다 | 프레임워크 문법만 암기하지 않는다 | [원문](https://developer.mozilla.org/en-US/docs/Learn_web_development) |
| 2 | 주니어 · 프레임워크 활용 | 팀 표준 스택으로 기능을 만들 때 | 공식 가이드대로 작은 화면을 만들고 데이터 흐름을 추적한다 | 기초 웹 플랫폼을 건너뛰지 않는다 | [원문](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Frameworks_libraries) |
| 3 | 주니어 · 디버깅과 오류 보고 | 버그 수정 작업을 맡았을 때 | 재현 단계·기대/실제 결과를 적고 개발 도구로 실패 지점을 찾는다 | 증상만 보고 코드를 무작위로 바꾸지 않는다 | [원문](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Scripting/Debugging_JavaScript) |
| 4 | 주니어 · Git 기본 협업 | 팀 저장소에 처음 기여할 때 | 작은 브랜치에서 의미 있는 커밋을 만들고 PR을 제출한다 | 공유 브랜치에 무심코 강제 푸시하지 않는다 | [원문](https://github.com/skills/introduction-to-github) |
| 5 | 미드레벨 · 기능 분해와 설계 | 중간 크기 기능을 단독 책임질 때 | 입출력·오류·데이터 변경을 설계하고 작은 PR로 분할한다 | 구현 전에 불필요한 범용 구조를 만들지 않는다 | [원문](https://sfia-online.org/en/sfia-9/skills/programming-software-development) |
| 6 | 미드레벨 · 테스트 전략 | 여러 계층을 지나는 기능을 출시할 때 | 규칙은 단위 테스트, 경계는 통합, 핵심 사용자 흐름은 E2E로 검증한다 | 테스트 수 자체를 품질 목표로 삼지 않는다 | [원문](https://sfia-online.org/en/sfia-9/skills/functional-testing) |
| 7 | 미드레벨 · 코드 리뷰와 피드백 | 동료 변경을 승인할 때 | 재현 가능한 문제와 개선 근거를 구체적으로 남긴다 | 취향을 필수 수정 사항처럼 강요하지 않는다 | [원문](https://docs.github.com/en/pull-requests/reference/pull-request-reviews) |
| 8 | 시니어 · 아키텍처 판단 | 성장·변경·운영 비용을 함께 판단할 때 | 대안·근거·트레이드오프를 기록하고 작은 검증으로 위험을 줄인다 | 패턴 유행을 근거로 구조를 선택하지 않는다 | [원문](https://sfia-online.org/en/sfia-9/skills/solution-architecture) |
| 9 | 시니어 · 기술 의사결정 | 팀 전체에 영향을 주는 기술을 선택할 때 | 결정 기록에 목표·대안·검증 결과·되돌리기 조건을 남긴다 | 개인 선호를 팀 표준으로 고정하지 않는다 | [원문](https://sfia-online.org/en/sfia-9/skills/programming-software-development) |
| 10 | 시니어 · 멘토링과 역량 전파 | 팀 내 지식 편중과 반복 실수가 있을 때 | 설계 리뷰·페어링·문서로 판단 과정을 공유하고 위임한다 | 모든 결정을 시니어에게 집중시키지 않는다 | [원문](https://sfia-online.org/en/about-sfia/how-sfia-works) |

## Agent 적용 지침

1. 작업의 목표와 제약을 먼저 적고, 위 표에서 해당하는 지식 2~4개를 선택한다.
2. 선택한 항목의 `whenToUse`와 `cautions`를 프롬프트의 적용 조건과 금지 조건으로 옮긴다.
3. 구현 중에는 `howToApply`를 체크리스트로 쓰고, 테스트·리뷰 결과를 별도 기록한다.
4. 설계 원칙이 서로 충돌하면 현재 요구와 위험을 기준으로 판단하고 근거를 남긴다.

## 출처 및 품질 한계

원본은 36개 URL을 참조한다. 수집 기록상 36개가 원문 수집에 성공했으며, 각 URL의 수집 시각·제목·SHA-256이 `source_manifest.json`에 있다. 항목 문장은 원문을 그대로 인용한 것이 아니라 한국어로 편집한 실무 요약이다. 출처가 개정되면 적용 전 현재 버전을 다시 확인해야 한다. 특정 방법론의 우월성이나 연차별 생산성은 이 데이터에서 측정하지 않았다.
