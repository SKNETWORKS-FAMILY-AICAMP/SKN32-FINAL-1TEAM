"""Curated web-development knowledge for a coding agent, with source URLs.

Run this file to regenerate the JSON and Markdown artifacts. The short entries are
editorial summaries of the linked primary/official documentation, not quotations.
"""
import json
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import requests
from bs4 import BeautifulSoup

CATEGORIES = {
    "development_process": "개발 방법론 및 개발 프로세스",
    "design_architecture": "소프트웨어 설계·아키텍처",
    "practice_quality": "개발 실무 및 품질 관리",
    "career_competencies": "개발자 연차별 역량",
}

# name | definition | when | implementation | benefit | caution | source URL | career level
ROWS = {
"development_process": '''
워터폴|요구·설계·구현·검증을 순차 단계로 계획하는 방식|범위와 승인 단계가 명확한 프로젝트|요구사항과 단계별 산출물·검수 기준을 먼저 정하고 변경 절차를 둔다|일정과 승인 기준이 명료하다|변경이 잦으면 후기 수정 비용이 커진다|https://www.atlassian.com/agile/project-management/waterfall-methodology|
애자일|작은 가치 단위를 자주 전달하고 피드백으로 계획을 조정하는 원칙|요구가 변하거나 사용자 검증이 필요한 제품|작은 기능을 우선순위화하고 작동하는 결과를 주기적으로 보여준다|변화에 빨리 대응한다|계획·문서가 불필요하다는 뜻은 아니다|https://agilemanifesto.org/principles|
스크럼|제품 목표·스프린트·검토·회고를 사용하는 경험적 프레임워크|팀이 짧은 주기로 제품 가치를 전달할 때|제품 백로그를 정렬하고 스프린트 목표와 완료 정의를 합의한다|목표와 피드백 주기가 선명하다|이벤트만 흉내 내고 완료 가능한 증가분이 없으면 효과가 약하다|https://scrumguides.org/scrum-guide.html|
칸반|작업 흐름을 시각화하고 진행 중 작업을 관리하는 풀 방식|지원·유지보수처럼 일이 계속 유입될 때|시작·진행·완료 흐름을 정의하고 병목·흐름 지표를 점검한다|과부하와 병목을 볼 수 있다|보드만 만들고 흐름 정책을 운영하지 않으면 개선되지 않는다|https://kanbanguides.org/the-kanban-guide/2020.12/|
테스트 주도 개발 TDD|실패하는 테스트·최소 구현·리팩터링을 반복하는 개발 방식|규칙이 명확한 로직을 안전하게 만들 때|작은 동작의 실패 테스트를 작성하고 통과시킨 뒤 중복을 정리한다|빠른 회귀 피드백을 얻는다|구현 세부사항만 테스트하면 변경에 취약하다|https://martinfowler.com/bliki/TestDrivenDevelopment.html|
행동 주도 개발 BDD|업무·개발·테스트 담당자가 구체적 사례로 기대 행동을 합의하는 방식|요구 해석 차이가 잦은 기능|사용자 예시를 발견·표현하고 중요한 시나리오를 자동화한다|공통 이해와 실행 가능한 명세를 만든다|Given/When/Then 문법만 쓰는 것은 BDD가 아니다|https://cucumber.io/docs/bdd/|
도메인 주도 설계 DDD|도메인 모델과 공통 언어로 복잡한 업무 규칙을 설계하는 접근|업무 규칙이 복잡하고 팀 간 의미가 다른 경우|도메인 전문가와 용어를 맞추고 경계별 모델·규칙을 분리한다|업무 의미를 코드에 반영한다|단순 CRUD에 모든 패턴을 적용하면 과설계가 된다|https://www.domainlanguage.com/ddd/reference/|
MVP|핵심 가설을 검증할 수 있는 최소한의 제품 버전|제품 가치와 고객 수요가 불확실할 때|검증할 가설·대상 사용자를 정하고 최소 기능을 출시해 학습한다|투자 전에 가정을 검증한다|최소 기능을 저품질과 혼동하지 않는다|https://martinfowler.com/articles/lean-inception/|
프로토타이핑|구현 전 핵심 사용 흐름이나 기술 가정을 빠르게 시험하는 시제품 활동|사용성·기술 가능성이 불확실할 때|가설 하나를 정해 화면 또는 기술 시제품을 만들고 관찰 결과를 기록한다|큰 구현 전에 위험을 드러낸다|시제품을 검증 없이 운영 코드로 승격하지 않는다|https://www.ibm.com/training/enterprise-design-thinking/framework|
반복 개발|짧은 개발 반복마다 실행 가능한 결과와 학습을 쌓는 방식|초기 요구를 모두 확정하기 어려울 때|기능을 세로로 작게 나누고 반복마다 통합·평가·재계획한다|초기에 오류와 요구 오해를 찾는다|반복 계획 없이 기능만 추가하면 범위가 흔들린다|https://martinfowler.com/articles/newMethodology.html|
''',
"design_architecture": '''
SOLID|객체 설계에서 책임·확장·대체 가능성·인터페이스 분리·의존성 역전을 다루는 원칙|변경이 잦고 객체 간 결합이 높을 때|변경 이유별로 책임을 분리하고 핵심이 구현 세부사항에 의존하지 않게 한다|변경 영향을 줄인다|모든 클래스에 추상화를 추가하는 규칙으로 쓰지 않는다|https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/architectural-principles|
DRY|같은 지식이나 규칙이 여러 곳에 중복되지 않게 하는 원칙|동일 업무 규칙이 여러 곳에서 수정될 때|중복 규칙의 단일 소유 위치를 만들고 호출 측에서 재사용한다|수정 불일치를 줄인다|겉모양만 비슷한 코드를 성급히 합치지 않는다|https://martinfowler.com/bliki/BeckDesignRules.html|
단순 설계 KISS|현재 요구를 만족하는 이해하기 쉬운 구조를 우선하는 원칙|새 기능의 구조를 선택할 때|테스트를 통과하는 가장 단순한 설계를 택하고 실제 변경 압력이 생길 때 확장한다|이해·유지 비용을 낮춘다|단순함을 필수 요구 누락의 핑계로 삼지 않는다|https://martinfowler.com/bliki/BeckDesignRules.html|
MVC|모델·뷰·컨트롤러의 책임을 분리하는 UI 구조|서버 렌더링 웹 앱이나 요청 처리 계층을 설계할 때|컨트롤러는 입력을 조정하고 모델은 규칙을, 뷰는 표시를 담당하게 한다|화면과 규칙의 결합을 줄인다|컨트롤러에 모든 업무 로직을 몰아넣지 않는다|https://learn.microsoft.com/en-us/aspnet/core/mvc/overview|
클린 아키텍처|업무 핵심을 중심에 두고 인프라가 핵심에 의존하게 하는 구조|외부 DB·UI 교체나 복잡한 업무 규칙이 예상될 때|핵심 모델·인터페이스를 안쪽에 두고 DB·HTTP 구현을 바깥에 둔다|기술 교체와 핵심 테스트가 쉬워진다|작은 앱에 계층·프로젝트를 과도하게 늘리지 않는다|https://learn.microsoft.com/en-us/dotnet/architecture/modern-web-apps-azure/common-web-application-architectures|
레이어드 아키텍처|UI·업무·데이터 접근 등 책임을 계층으로 나누는 구조|전형적인 업무 웹 앱의 변경 경계를 정할 때|계층별 인터페이스와 호출 방향을 정하고 순환 의존을 피한다|책임과 변경 범위를 명확히 한다|단순 전달 계층만 늘면 복잡도만 증가한다|https://learn.microsoft.com/en-us/azure/architecture/guide/architecture-styles/n-tier|
REST 자원 설계|HTTP의 자원·메서드·상태 코드를 일관되게 활용하는 API 설계|외부 또는 프런트엔드용 HTTP API를 만들 때|자원 URI를 정하고 GET·POST·PUT·DELETE와 상태 코드를 의미에 맞게 사용한다|클라이언트 계약을 이해하기 쉽다|모든 동작을 CRUD에 억지로 맞추지 않는다|https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods|
데이터베이스 제약과 트랜잭션|스키마 제약과 원자적 작업으로 데이터 일관성을 지키는 설계|여러 테이블을 갱신하거나 중복·누락을 막을 때|기본키·외래키·유니크 제약을 두고 함께 성공해야 할 변경을 트랜잭션으로 묶는다|데이터 무결성을 높인다|긴 트랜잭션과 불필요한 잠금을 피한다|https://www.postgresql.org/docs/current/tutorial-transactions.html|
디자인 패턴|반복되는 설계 문제에 검증된 구조적 해법을 적용하는 방식|객체 생성·상태·구성의 문제가 반복될 때|문제를 먼저 설명하고 적합한 패턴을 작은 범위에 적용한다|공통 설계 어휘를 제공한다|패턴 이름을 목표로 과설계하지 않는다|https://refactoring.guru/design-patterns|
의존성 주입|필요한 구현을 내부 생성 대신 외부에서 제공받는 구성 방식|테스트 대역이나 구현 교체가 필요한 서비스|핵심 코드는 인터페이스에 의존하고 시작 지점에서 실제 구현을 연결한다|결합을 낮추고 테스트를 쉽게 한다|단순 객체까지 모두 주입하면 구성이 난해해진다|https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection/overview|
''',
"practice_quality": '''
Git 브랜치와 통합 전략|변경을 분리하고 공통 브랜치에 안전하게 합치는 작업 방식|여러 개발자가 같은 저장소에서 일할 때|작은 브랜치를 만들고 자주 동기화하며 검토·검사를 통과한 뒤 병합한다|협업 변경을 추적할 수 있다|오래 살아 있는 브랜치는 통합 충돌을 키운다|https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches|
코드 리뷰|병합 전 변경의 정확성·가독성·위험을 동료가 검토하는 절차|공유 코드나 운영 영향이 있는 변경|작은 PR에 의도·검증 결과를 적고 구체적인 리뷰 의견을 주고받는다|결함 발견과 지식 공유에 도움 된다|리뷰를 개인 평가나 단순 승인 절차로 만들지 않는다|https://docs.github.com/en/pull-requests/reference/pull-request-reviews|
단위 테스트|작은 함수·모듈의 동작을 격리해 검증하는 테스트|업무 규칙과 경계 조건을 빠르게 확인할 때|입력·기대 출력을 명시하고 정상·오류·경계 사례를 자동화한다|빠른 회귀 피드백을 준다|내부 구현만 고정하는 테스트를 피한다|https://docs.pytest.org/en/stable/getting-started.html|
통합 테스트|여러 구성 요소의 실제 연결과 계약을 검증하는 테스트|DB·API·서비스 사이 오류가 걱정될 때|실제 또는 통제된 의존성을 연결해 주요 성공·실패 흐름을 실행한다|경계 연결의 오류를 찾는다|모든 사례를 느린 통합 테스트로만 검증하지 않는다|https://learn.microsoft.com/en-us/aspnet/core/test/integration-tests|
E2E 테스트|사용자 관점에서 앱의 전체 흐름을 실행하는 테스트|로그인·결제 등 핵심 경로를 출시 전 확인할 때|브라우저로 시작부터 결과까지 실행하고 안정적인 사용자 선택자를 사용한다|시스템 전체의 깨진 흐름을 잡는다|모든 세부 경우를 E2E로 검증하면 느리고 불안정하다|https://playwright.dev/docs/intro|
CI|변경을 자주 통합하고 자동 빌드·검사를 실행하는 실무|팀 변경의 통합 결함을 일찍 찾을 때|PR과 기본 브랜치에서 빌드·린트·테스트를 자동 실행한다|통합 문제를 일찍 발견한다|CI가 느리거나 자주 실패하면 신뢰가 떨어진다|https://docs.github.com/en/actions/get-started/continuous-integration|
CD|검증된 변경을 자동 배포 파이프라인으로 전달하는 실무|반복 배포와 롤백을 안정화할 때|빌드·테스트 뒤 환경별 배포와 승인·비밀 관리·복구 경로를 설정한다|반복 작업과 배포 오류를 줄인다|자동화 전에 배포 실패 시 복구 방법을 정한다|https://docs.github.com/en/actions/get-started/continuous-deployment|
디버깅|재현·관찰·가설 검증으로 오류 원인을 찾는 활동|증상만 있고 원인이 불명확할 때|오류를 재현하고 로그·브라우저 개발 도구·중단점으로 원인을 좁힌다|추측성 수정을 줄인다|민감 정보를 로그에 남기지 않는다|https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Scripting/Debugging_JavaScript|
웹 보안 점검|주요 웹 취약점에 맞춰 설계·구현·검증을 수행하는 활동|인증·입력·권한을 다루는 웹 서비스|OWASP 위험 목록을 점검표로 쓰고 접근 통제·입력 처리·의존성을 검토한다|흔한 보안 실패를 예방한다|Top 10만으로 모든 위협을 포괄하지 않는다|https://owasp.org/www-project-top-ten/|
성능 측정과 최적화|실제 지표를 측정한 뒤 병목을 개선하는 실무|페이지 응답이 느리거나 사용자 경험이 나쁠 때|실사용 지표와 프로파일을 확인하고 큰 리소스·긴 작업부터 줄인다|체감 성능을 개선한다|측정 없이 미세 최적화부터 시작하지 않는다|https://web.dev/articles/vitals|
''',
"career_competencies": '''
주니어 · 웹 언어 기초|HTML·CSS·JavaScript의 구조·표현·동작을 이해하는 역량|작은 화면과 기능을 독립 구현할 때|시맨틱 HTML과 CSS 레이아웃·JS 이벤트를 직접 구현하고 설명한다|프레임워크 문제를 기초 수준에서 진단한다|프레임워크 문법만 암기하지 않는다|https://developer.mozilla.org/en-US/docs/Learn_web_development|junior
주니어 · 프레임워크 활용|선택한 웹 프레임워크의 컴포넌트·상태·라우팅을 사용하는 역량|팀 표준 스택으로 기능을 만들 때|공식 가이드대로 작은 화면을 만들고 데이터 흐름을 추적한다|기능 구현 속도를 높인다|기초 웹 플랫폼을 건너뛰지 않는다|https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Frameworks_libraries|junior
주니어 · 디버깅과 오류 보고|재현 조건과 관찰 결과를 기록하며 오류를 좁히는 역량|버그 수정 작업을 맡았을 때|재현 단계·기대/실제 결과를 적고 개발 도구로 실패 지점을 찾는다|수정과 협업의 출발점을 명확히 한다|증상만 보고 코드를 무작위로 바꾸지 않는다|https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Scripting/Debugging_JavaScript|junior
주니어 · Git 기본 협업|브랜치·커밋·PR로 작은 변경을 공유하는 역량|팀 저장소에 처음 기여할 때|작은 브랜치에서 의미 있는 커밋을 만들고 PR을 제출한다|변경 이력을 추적할 수 있다|공유 브랜치에 무심코 강제 푸시하지 않는다|https://github.com/skills/introduction-to-github|junior
미드레벨 · 기능 분해와 설계|요구를 구현 가능한 단위와 인터페이스로 나누는 역량|중간 크기 기능을 단독 책임질 때|입출력·오류·데이터 변경을 설계하고 작은 PR로 분할한다|기능 변경의 범위를 통제한다|구현 전에 불필요한 범용 구조를 만들지 않는다|https://sfia-online.org/en/sfia-9/skills/programming-software-development|mid
미드레벨 · 테스트 전략|위험에 따라 단위·통합·E2E 범위를 선택하는 역량|여러 계층을 지나는 기능을 출시할 때|규칙은 단위 테스트, 경계는 통합, 핵심 사용자 흐름은 E2E로 검증한다|검사 비용과 위험을 균형 있게 관리한다|테스트 수 자체를 품질 목표로 삼지 않는다|https://sfia-online.org/en/sfia-9/skills/functional-testing|mid
미드레벨 · 코드 리뷰와 피드백|변경의 의도·정확성·유지보수성을 검토하는 역량|동료 변경을 승인할 때|재현 가능한 문제와 개선 근거를 구체적으로 남긴다|팀 지식과 품질을 높인다|취향을 필수 수정 사항처럼 강요하지 않는다|https://docs.github.com/en/pull-requests/reference/pull-request-reviews|mid
시니어 · 아키텍처 판단|비기능 요구와 제약을 고려해 시스템 경계를 정하는 역량|성장·변경·운영 비용을 함께 판단할 때|대안·근거·트레이드오프를 기록하고 작은 검증으로 위험을 줄인다|장기 변경 비용을 관리한다|패턴 유행을 근거로 구조를 선택하지 않는다|https://sfia-online.org/en/sfia-9/skills/solution-architecture|senior
시니어 · 기술 의사결정|기술 선택의 위험·비용·운영 영향을 설명하고 책임지는 역량|팀 전체에 영향을 주는 기술을 선택할 때|결정 기록에 목표·대안·검증 결과·되돌리기 조건을 남긴다|결정의 맥락과 책임이 남는다|개인 선호를 팀 표준으로 고정하지 않는다|https://sfia-online.org/en/sfia-9/skills/programming-software-development|senior
시니어 · 멘토링과 역량 전파|동료의 자율성과 기술 성장을 돕는 역량|팀 내 지식 편중과 반복 실수가 있을 때|설계 리뷰·페어링·문서로 판단 과정을 공유하고 위임한다|팀의 독립 실행 능력을 높인다|모든 결정을 시니어에게 집중시키지 않는다|https://sfia-online.org/en/about-sfia/how-sfia-works|senior
'''
}


def knowledge():
    result = []
    seen = set()
    for category, raw in ROWS.items():
        for rank, line in enumerate(raw.strip().splitlines(), 1):
            name, definition, when, how, benefit, caution, url, level = line.split("|")
            if name in seen:
                raise ValueError("duplicate knowledge: " + name)
            seen.add(name)
            result.append({"id": f"DK-{list(CATEGORIES).index(category)+1:02d}-{rank:02d}",
                           "category": category, "categoryName": CATEGORIES[category], "rank": rank,
                           "knowledgeName": name, "definition": definition, "whenToUse": when,
                           "howToApply": how, "benefits": benefit, "cautions": caution,
                           "careerLevel": level or None,
                           "source": {"url": url, "type": "official_or_primary_technical_reference"},
                           "agentPromptHint": f"{when} {how} 주의: {caution}"})
    if len(result) != 40:
        raise ValueError(f"expected 40 entries, got {len(result)}")
    return result


def crawl_sources(items, output, workers=6):
    """Download each distinct source once and keep the extracted original text."""
    urls = list(dict.fromkeys(x["source"]["url"] for x in items))
    raw = output / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    def fetch(url):
        record = {"url": url, "checkedAt": datetime.now(timezone.utc).isoformat()}
        try:
            response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (research archive)"})
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("HTML 원문이 아님")
            soup = BeautifulSoup(response.content, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
            if len(body) < 100:
                raise ValueError("본문이 너무 짧음")
            digest = hashlib.sha256(response.content).hexdigest()
            filename = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + ".txt"
            (raw / filename).write_text(body, encoding="utf-8")
            record.update(status="collected", finalUrl=response.url, title=title,
                          sha256=digest, textLength=len(body), localPath=f"raw/{filename}")
        except (requests.RequestException, ValueError) as exc:
            record.update(status="failed", reason=str(exc))
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        manifest = list(pool.map(fetch, urls))
    by_url = {x["url"]: x for x in manifest}
    for item in items:
        record = by_url[item["source"]["url"]]
        item["source"]["collectionStatus"] = record["status"]
        item["source"]["archivePath"] = record.get("localPath")
    (output / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def write(output=None, crawl=False):
    output = Path(output) if output else Path(__file__).parent / "output"
    output.mkdir(parents=True, exist_ok=True)
    items = knowledge()
    if crawl:
        crawl_sources(items, output)
    (output / "development_knowledge.json").write_text(
        json.dumps({"title": "웹 개발 Agent 지식 TOP 40", "rankingNote": "실무 활용도 기준 편집 순서이며 통계적 인기 순위가 아님",
                    "categories": CATEGORIES, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 웹 개발 Agent 지식 TOP 40", "", "각 분류 10개. 순위는 실무 활용도를 기준으로 한 편집 순서입니다.", ""]
    for category, title in CATEGORIES.items():
        lines += [f"## {title}", ""]
        for item in (x for x in items if x["category"] == category):
            lines += [f"### {item['rank']}. {item['knowledgeName']}", "",
                      f"- 개념: {item['definition']}", f"- 언제: {item['whenToUse']}",
                      f"- 적용: {item['howToApply']}", f"- 장점: {item['benefits']}",
                      f"- 주의: {item['cautions']}", f"- 출처: {item['source']['url']}", ""]
    (output / "development_knowledge.md").write_text("\n".join(lines), encoding="utf-8")
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--crawl", action="store_true", help="공식 원문을 내려받아 raw/와 수집 로그 저장")
    args = parser.parse_args()
    write(args.output, args.crawl)
