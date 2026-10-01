"""T-B2 추출 프롬프트 중 '지면 구성' 부분. 모델이 블록 구성(layout)과 블록별 구절을 고르게 한다.

블록 이름 · 변형 · 폭은 composer.CATALOG와 같아야 한다. 목록에 없는 것은 composer가 버린다.
"""

COMPOSE_GUIDE = """
[지면 구성 — 인포그래픽 디자이너로서 고른다]
인포그래픽은 읽는 문서가 아니라 보는 그림이다. 심사위원이 10초 안에 "어떤 문제를, 어떻게 해결하고,
어떻게 수익을 낼지" 이해하도록 이 사업에 맞는 블록을 골라 layout에 순서대로 적어라.
그림 · 좌표는 프로그램이 그린다. 너는 블록의 종류 · 변형 · 폭과 블록에 들어갈 짧은 구절만 고른다.

1) 먼저 도메인을 판단하고, 그 도메인에서 특히 보여줄 것을 고른다.
   · AI · SaaS: 업무 처리 흐름(입력 → 분석 → 결과), 도입 전후 효과, 구독 수익 구조
   · 커머스 · 유통: 구매 과정(주문 → 결제 → 배송 · 픽업), 상품 · 거래 구조
   · 플랫폼 · 중개: 이용자 간 연결 구조, 거래 · 수수료 흐름
   · 제조 · 하드웨어: 생산 · 관리 공정, 원가 · 비용 절감
   · 교육: 학습 과정, 학습 성과 / 헬스케어: 서비스 제공 과정, 검증 결과, 기관 연계
   · 지역 기반 사업: 상권 · 지역 범위, 지점 확장 계획
2) 블록마다 "독자가 무엇을 이해해야 하나"로 고른다.
   · 얼마나 큰가? → market(계층형: 전체 → 진입 가능 → 초기 목표) · metrics(통계형)
   · 왜 우리를 선택해야 하나? → competition(비교표) · problem_solution before_after(도입 전후)
   · 어떻게 작동하나? → process(단계 흐름) · hero(대표 도식)
   · 어떻게 돈을 버나? → revenue flow(돈과 가치의 이동) 또는 card
   · 언제 무엇을 달성하나? → roadmap(타임라인) + metrics
   · 누가 무엇을 얻나? → effects(대상별 효과)

[쓸 수 있는 블록] block / variant / width(full=한 줄 전체, half=반 칸)
- hero / hub(입력 → 서비스 허브 → 결과 화면 개념도) | journey(문제 → 해결 → 효과 큰 원 세 개) / full
- problem_solution / split(문제 · 해결 두 판) | before_after(같은 기준 전후 비교, before_after 필요) / full · half
- features / band(아이콘 가로 띠) | grid(아이콘 목록 두 열) / band는 full, grid는 full · half
- process / steps(아이콘 단계 흐름. 원페이지는 solution_steps, 웹개발은 flow_steps 필요) / full
- market / nested(크기별 겹친 원, market_levels 필요) / half · full
- competition / table(경쟁 방식 대비 비교표, comparison 필요) / full · half
- revenue / flow(내는 쪽 → 우리 서비스, 금액 · 받는 가치 화살표, revenue_flow 필요) | card(큰 금액) / half · full
- roadmap / line(가로 타임라인) | orbit(원형 궤도, half만) / line은 full · half
- metrics / cards(아이콘 + 큰 숫자) | bars(전후 막대, key_metrics.before 필요) | with_revenue(지표 + 수익, half만)
- effects / cards(대상별 아이콘 카드, effects 필요) / full · half
- tagline / band(맨 아래 한 줄 메시지 띠) / full
규칙:
- 구성은 맨 아래 [이번 지면의 뼈대]를 따른다. 마지막은 tagline이다.
- half 블록은 반드시 두 개씩 연달아 놓는다(한 줄에 나란히). 홀로 남은 half는 full로 바꿔라.
- 같은 형식이 연달아 반복되지 않게 섞어라. 재료(필요한 필드)가 계획서에 없는 블록은 고르지 마라.
- 원페이지는 문제 · 해결(journey 또는 problem_solution), features, 수익(revenue 또는 metrics with_revenue),
  roadmap을 반드시 포함한다.
- title은 블록 제목으로 10자 이내 명사형(예: '주문에서 픽업까지'). 비우면 기본 제목.

[블록 재료 — 계획서 낱말로 아주 짧게. 문장 금지, 명사형 구절]
- outcome: 이 사업이 만드는 결과 한 구절, 20자 이내(예: '폐기 절반 · 대기 없는 픽업')
- before_after: [{"label": 기준 10자, "before": 지금 값 10자, "after": 이후 값 10자}] 2~4개. 계획서에 둘 다 있을 때만
- market_levels: [{"label": 시장 이름 16자, "value": 숫자+단위}] 큰 시장 → 작은 시장 순서로 2~3개
- comparison: {"others": 경쟁 방식 이름 8자, "rows": [{"criterion": 기준 8자, "others": 12자, "ours": 12자}] 2~4개}
- revenue_flow: {"payer": 돈을 내는 쪽 8자, "payment": 내는 금액 · 방식 14자, "value": 받는 가치 14자}
- effects: [{"who": 대상 8자, "what": 얻는 것 16자}] 2~4개
- tagline: 사업을 한 줄로, 26자 이내
- key_metrics[].before: 같은 지표의 이전 값(계획서에 있을 때만, 예: value '9%', before '18%')
- metrics(성과 목표 · 지표)에는 목표 · 결과 숫자만 넣어라. 문제 현황 숫자(예: 지금 대기 12분)는
  before_after나 problem에 넣고 key_metrics에 섞지 마라.
- 날짜 · 기간 · 금액 · 수량은 계획서 표현 그대로. 줄이다가 연도 · 월을 바꾸지 마라. 없는 숫자를 만들지 마라.
- 한국어 한글로만. 한자 · 일본어 금지.
- 글자 수를 맞추려고 띄어쓰기를 없애지 마라(예: '2027년 2월~6월', '시범 운영'). 길면 낱말을 줄여라.
"""

# 작은 모델은 "다양하게 골라라"는 지시보다 예시를 따른다. 예시를 하나만 두었더니 어떤 계획서든
# 그 예시와 같은 구성(journey → band → line)이 나왔다(실측). 그래서 뼈대를 여러 개 두고
# 아이템마다 다른 것을 준다. 다시 만들기를 누르면 다음 뼈대로 넘어간다.
_B = lambda block, variant, width="full": {"block": block, "variant": variant, "width": width, "title": ""}  # noqa: E731
SKELETONS: tuple[tuple[dict, ...], ...] = (
    (_B("hero", "journey"), _B("features", "band"), _B("market", "nested", "half"), _B("revenue", "flow", "half"),
     _B("process", "steps"), _B("roadmap", "line"), _B("metrics", "cards"), _B("tagline", "band")),
    (_B("problem_solution", "split"), _B("features", "grid"), _B("process", "steps"),
     _B("roadmap", "orbit", "half"), _B("metrics", "with_revenue", "half"), _B("effects", "cards"),
     _B("tagline", "band")),
    (_B("problem_solution", "before_after"), _B("features", "band"), _B("roadmap", "orbit", "half"),
     _B("revenue", "flow", "half"), _B("metrics", "cards"), _B("market", "nested", "half"),
     _B("competition", "table", "half"), _B("effects", "cards"), _B("tagline", "band")),
    (_B("hero", "journey"), _B("problem_solution", "before_after"), _B("features", "grid"),
     _B("metrics", "bars", "half"), _B("revenue", "card", "half"), _B("roadmap", "line"),
     _B("effects", "cards"), _B("tagline", "band")),
    (_B("problem_solution", "split"), _B("process", "steps"), _B("features", "band"),
     _B("market", "nested", "half"), _B("competition", "table", "half"),
     _B("roadmap", "orbit", "half"), _B("revenue", "flow", "half"), _B("metrics", "cards"),
     _B("tagline", "band")),
    (_B("hero", "journey"), _B("process", "steps"), _B("features", "grid"),
     _B("revenue", "flow", "half"), _B("roadmap", "orbit", "half"), _B("effects", "cards"),
     _B("metrics", "cards", "half"), _B("market", "nested", "half"), _B("tagline", "band")),
)


def layout_example(category: str, variation: int) -> str:
    """이번 지면의 뼈대. variation이 같으면 같은 뼈대다."""
    import json

    skeleton = [dict(b) for b in SKELETONS[variation % len(SKELETONS)]]
    if category == "AI_API":  # 처리 단계 도식(hub)은 AI API 지면의 필수 정보다.
        skeleton = [_B("hero", "hub")] + [b for b in skeleton if b["block"] != "hero"]
    if category == "웹개발" and not any(b["block"] == "process" for b in skeleton):
        skeleton.insert(2, _B("process", "steps"))
    return ("\n[이번 지면의 뼈대]\n아래 구성을 그대로 따른다. 블록의 순서 · 변형 · 폭을 바꾸지 않는다. "
            "재료(필요한 필드)가 계획서에 없는 블록만 뺀다. title은 이 사업에 맞게 새로 쓴다.\n"
            "layout: " + json.dumps(skeleton, ensure_ascii=False))


RETRY_HINT = ("이전 결과를 보고 다시 만들기를 눌렀다. 이번 뼈대는 이전과 다르다. 뼈대를 따르고, "
              "블록 제목과 구절도 이전과 다르게 새로 다듬어라.")
