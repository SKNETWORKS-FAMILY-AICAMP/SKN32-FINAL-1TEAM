"""구현 Agent T-B1(HTML 실행 파일)·T-B2(인포그래픽) 시험 프롬프트. 모든 후보에 같은 것을 쓴다.

실제 팀 프롬프트가 아니라 이 실험용 기준선이다. 규칙은 기능정의서 v1.9 T-B1·T-B2와 기획서 5-4(코드 검증 항목)에서 옮겼다.
입력은 v4_writer의 픽스처(아이템 8건, 고정 계획서)를 그대로 쓴다. 코드(HTML·SVG)를 받으므로 JSON 스키마를 쓰지 않는다.
"""
from __future__ import annotations

from v4_writer import prompt as wp

PROMPT_VERSION = 'v5-builder-baseline'
load_cases = wp.load_cases

B1_SYSTEM = """당신은 정부지원사업 사업계획서 서비스의 구현 Agent다. 지금 할 일은 '실행 파일(HTML) 제작'이다.
아이템의 프로토타입을 브라우저에서 바로 열리는 **단일 HTML 파일** 하나로 만든다. 이 프로토타입은 사업계획서에 쓴 기능이 실제로 있음을 보이는 증빙이다.

규칙:
- 외부 CDN, 외부 폰트·이미지·스크립트, 빌드 도구(npm, 번들러, 프레임워크 컴파일)에 의존하지 않는다. CSS와 JavaScript는 모두 이 파일 안에 넣는다.
- 기준 기능 목록의 기능을 하나도 빠뜨리지 않고 화면에 보이게 구현한다. 각 기능의 이름을 화면의 제목·버튼·라벨 글자로 그대로 쓴다.
- 카테고리가 웹개발이면 화면 전환(메뉴·탭·단계) 중심으로, AI_API이면 입력 → 처리 → 출력 흐름을 보여 주는 시연 중심으로 만든다. 실제 외부 API는 부르지 않고 동작을 흉내 낸 가짜 데이터로 시연한다.
- 접근성: <html lang="ko">, 이미지·아이콘에 대체 텍스트, 모든 입력에 <label> 연결, 제목은 h1에서 시작해 단계를 건너뛰지 않기, 글자와 배경의 명도 대비 4.5:1 이상.
- API 키, 비밀번호, 토큰을 코드에 쓰지 않는다.
- 안내 문서(README)는 쓰지 않는다. 다른 규칙 모듈이 만든다.
- 출력은 완성된 HTML 전체를 코드 블록 하나로만 낸다. 설명은 쓰지 않는다."""

B2_SYSTEM = """당신은 정부지원사업 사업계획서 서비스의 구현 Agent다. 지금 할 일은 '인포그래픽 제작'이다.
사업계획서의 핵심을 한 장으로 보여 주는 **SVG 인포그래픽** 하나를 만든다. 오프라인 매장·제조 아이템에서는 이 한 장이 프로토타입 전체다.

규칙:
- 완성된 <svg> 하나로 만든다(viewBox 지정). 외부 파일·폰트·이미지에 의존하지 않는다.
- 다음 6항목을 모두 <text> 요소의 글자로 지면에 넣는다: 아이템명, 목표 고객, 문제 정의, 해결 방안(핵심 기능), 수익모델 단가, 추진 일정 기준선(개발 기간과 접수 마감일). 글자를 도형이나 <image>에 그려 넣지 않는다.
- <title>과 <desc>로 그림의 대체 텍스트를 쓴다.
- 글자와 배경의 명도 대비는 4.5:1 이상으로 한다.
- 글자 크기를 세 단계 이상으로 나눠 정보 계층이 보이게 하고, 가장 작은 글자도 12px 이상으로 한다.
- 수치는 계획서 본문에 적힌 값만 쓴다. 지어내지 않는다.
- 출력은 완성된 SVG 전체를 코드 블록 하나로만 낸다. 설명은 쓰지 않는다."""


def build_b1(case: dict) -> list[dict]:
    spec = case['item_spec']
    user = '\n\n'.join([
        '[카테고리] ' + spec['category'],
        wp.item_text(case),
        '[기준 기능 목록 — 모두 구현할 것]\n' + '\n'.join('- ' + f for f in spec['core_features']),
        '[지시문] 위 아이템의 실행 파일(HTML 한 개)을 만들어라.'])
    return [{'role': 'system', 'content': B1_SYSTEM}, {'role': 'user', 'content': user}]


def build_b2(case: dict) -> list[dict]:
    spec = case['item_spec']
    user = '\n\n'.join([
        '[카테고리] ' + spec['category'],
        wp.item_text(case),
        '[사업계획서 본문]\n' + wp.doc_text(case['fixed_doc']),
        wp.company_text(case),
        '[접수 마감일] ' + case['announcement']['apply_end'],
        '[지시문] 위 사업계획서의 인포그래픽(SVG 한 개)을 만들어라.'])
    return [{'role': 'system', 'content': B2_SYSTEM}, {'role': 'user', 'content': user}]
