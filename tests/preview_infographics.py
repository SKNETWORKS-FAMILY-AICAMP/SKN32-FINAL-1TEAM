"""Generate a reproducible design gallery without an API call.

Run from the repository root: python -m tests.preview_infographics
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from engineering_agent.infographic.render import render_infographic
from engineering_agent.infographic.svg_parts import esc


SAMPLES = [
    ("원페이지", {
        "item_name": "AI 스포츠 데이터 분석 에이전시",
        "item_summary": "선수 영입 · 훈련 · 전술 의사결정을 돕는 데이터 분석 플랫폼",
        "target_users": "프로팀 · 에이전트 · 선수",
        "problem": "선수 영입 실패와 비효율적인 훈련을 줄여야 한다",
        "solution": "경기·훈련 데이터를 분석해 선수 평가와 전술 결정을 돕는다",
        "features": ["선수 평가", "스카우팅", "훈련 분석", "전술 분석", "위험 예측", "리포트", "기록 관리"],
        "feature_details": ["경기 기록 기반 선수 종합 평가", "팀에 필요한 선수를 탐색", "선수별 훈련 결과 비교", "경기 상황별 전술 검토", "부상 위험 근거 확인", "분석 결과 보고서 제공", "경기·훈련 기록 통합"],
        "revenue_unit_price": "팀당 월 150만원 SaaS 구독",
        "timeline_baseline": "2026년 11월 기반 구축, 2027년 3월 시장 검증, 2027년 9월 확장",
        "key_metrics": [{"value": "50팀", "label": "24개월 계약 목표"},
                        {"value": "30억원", "label": "24개월 연매출 목표"},
                        {"value": "25%", "label": "목표 영업이익률"}],
        "solution_steps": ["경기·훈련 기록 수집", "선수별 데이터 분석", "평가·전술 리포트", "팀 의사결정 지원"],
    }),
    ("원페이지", {
        "item_name": "반찬온", "item_summary": "동네 반찬가게의 예약 주문과 생산 계획을 연결합니다",
        "target_users": "예약 주문을 받는 동네 반찬가게",
        "problem": "수요를 알기 어려워 당일 만든 반찬이 남는다",
        "solution": "예약 수량을 모아 다음 날 생산량을 정한다",
        "features": ["예약 주문", "생산량 집계", "픽업 안내"],
        "feature_details": ["고객이 메뉴와 수령일을 선택한다", "메뉴별 예약 수량을 모아 보여준다", "준비가 끝나면 수령 시간을 알린다"],
        "revenue_unit_price": "매장당 월 29,000원 구독",
        "timeline_baseline": "2026년 12월 시범 운영, 2027년 3월 정식 출시",
        "key_metrics": [{"value": "18%", "label": "시범 매장 폐기율"}, {"value": "10곳", "label": "시범 운영 목표"}],
        "solution_steps": ["고객 예약 접수", "메뉴별 수량 집계", "매장 생산 준비", "고객 픽업"],
    }),
    ("원페이지", {
        "item_name": "순환상자", "item_summary": "사용한 배송 상자를 회수해 다시 공급합니다",
        "target_users": "정기 배송을 운영하는 지역 판매자",
        "problem": "배송할 때마다 일회용 상자를 구매하고 버린다",
        "solution": "다회용 상자를 회수·세척해 다음 배송에 쓴다",
        "features": ["상자 대여", "회수 신청", "상태 관리"],
        "feature_details": ["배송 일정에 맞춰 상자를 공급한다", "사용한 상자의 회수 날짜를 정한다", "세척과 재사용 상태를 기록한다"],
        "revenue_unit_price": "상자당 회당 1,500원",
        "timeline_baseline": "2026년 11월 회수 실험, 2027년 2월 지역 공급",
        "solution_steps": ["판매자에 공급", "배송 후 회수", "세척 및 검수", "다음 배송에 공급"],
    }),
    ("웹개발", {
        "item_name": "작업실 예약", "item_summary": "빈 작업실을 찾아 시간 단위로 예약합니다",
        "target_users": "공유 작업실을 이용하는 창작자",
        "features": ["공간 탐색", "시간 예약", "예약 조회"],
        "feature_details": ["위치와 장비로 공간을 좁힌다", "빈 시간과 이용 시간을 선택한다", "확정된 예약 내용을 확인한다"],
        "flow_steps": ["공간 검색", "장비 확인", "시간 선택", "예약 확정"],
    }),
    ("AI_API", {
        "item_name": "설비 점검 노트", "item_summary": "현장 점검 기록을 정리하고 확인할 항목을 제시합니다",
        "target_users": "설비 점검을 담당하는 현장 관리자",
        "features": ["기록 입력", "이상 항목 분류", "점검 결과 확인"],
        "feature_details": ["설비 상태와 작업 기록을 입력한다", "점검 기록에서 이상 항목을 구분한다", "관리자가 항목별 근거를 확인한다"],
        "pipeline": {"input": "설비 상태와 현장 점검 기록", "process": "기록 분류 및 이상 항목 추출", "output": "확인이 필요한 항목과 근거"},
    }),
]


def main() -> None:
    gallery = Path(__file__).resolve().parents[1] / "engineering_agent" / "output" / f"design-kit-{uuid4().hex[:8]}"
    gallery.mkdir(parents=True)
    cards = []
    for index, (category, data) in enumerate(SAMPLES):
        result = render_infographic(category, data)
        filename = f"sample-{index + 1}.svg"
        (gallery / filename).write_text(result["source_text"], encoding="utf-8")
        cards.append(f'<article><h2>{esc(data["item_name"])}</h2><p>{esc(category)} '
                     f'· <a href="{filename}">새 구성 원본</a> · '
                     '</p>'
                     f'<img src="{filename}" alt="{esc(result["alt_text"])}"></article>')
    html = '''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>S-Brain 인포그래픽 디자인 키트</title><style>
body{margin:0;background:#eeeef0;color:#20252b;font-family:'Malgun Gothic',sans-serif}
main{max-width:1480px;margin:48px auto;padding:0 32px}h1{font-size:30px}
.gallery{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:32px}
article{min-width:0}article>p{color:#555}img{display:block;width:100%;background:white}
@media(max-width:900px){.gallery{grid-template-columns:1fr}}
</style><main><h1>S-Brain 인포그래픽 디자인 키트</h1>
<p>디자인 확인용 가상 데이터입니다. 실제 사업 실적이나 목표를 의미하지 않습니다.</p>
<div class="gallery">''' + "".join(cards) + "</div></main></html>"
    (gallery / "index.html").write_text(html, encoding="utf-8")
    print(gallery.resolve())


if __name__ == "__main__":
    main()
