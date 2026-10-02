"""기존 전략·작성 함수의 OpenAI Responses 실행 연결.

각 함수의 F번호는 strategy_writing_agent.html의 계약표와 동일하게 유지한다.
공개 함수의 이름과 인자를 유지한다. 실제 사용 모델은 반환값에 기록한다.
"""
from __future__ import annotations
from typing import Any
from agent_strategy.runtime.llm_runtime import CONTRACT, request_json


def _pending(function_name: str, **payload: Any) -> dict[str, Any]:
    fid = next(fid for fid, config in CONTRACT['functions'].items() if config['name'] == function_name)
    return request_json(fid, payload)

# F02 analyze_item()
def analyze_item(item_input: dict, research_data: dict) -> dict: return _pending("analyze_item", item_input=item_input, research_data=research_data)
# F03 analyze_market()
def analyze_market(item: dict, market_data: dict, analysis_type: str) -> dict: return _pending("analyze_market", item=item, market_data=market_data, analysis_type=analysis_type)
# F04 analyze_competitors()
def analyze_competitors(item: dict, market_data: dict, competitor_data: dict) -> dict: return _pending("analyze_competitors", item=item, market_data=market_data, competitor_data=competitor_data)
# F05 analyze_team_capability()
def analyze_team_capability(team_data: dict, item_requirements: list) -> dict: return _pending("analyze_team_capability", team_data=team_data, item_requirements=item_requirements)
# F06 define_development_goal()
def define_development_goal(item_spec: dict, duration: int, target_field: str) -> dict: return _pending("define_development_goal", item_spec=item_spec, duration=duration, target_field=target_field)
# F07 define_development_method()
def define_development_method(core_technologies: list, constraints: dict) -> dict: return _pending("define_development_method", core_technologies=core_technologies, constraints=constraints)
# F08 create_development_plan()
def create_development_plan(goals: dict, duration: int, phases: list) -> dict: return _pending("create_development_plan", goals=goals, duration=duration, phases=phases)
# F09 create_production_plan()
def create_production_plan(product: dict, development_plan: dict, phases: list) -> dict: return _pending("create_production_plan", product=product, development_plan=development_plan, phases=phases)
# F10 create_marketing_strategy()
def create_marketing_strategy(item: dict, market: dict, target_customer: str, stage: str) -> dict: return _pending("create_marketing_strategy", item=item, market=market, target_customer=target_customer, stage=stage)
# F11 create_business_model()
def create_business_model(item: dict, market: dict, customer: str, strategy: dict) -> dict: return _pending("create_business_model", item=item, market=market, customer=customer, strategy=strategy)
# F12 create_growth_strategy()
def create_growth_strategy(market: dict, competitors: dict, bm: dict, investment: dict, social_value: dict) -> dict: return _pending("create_growth_strategy", market=market, competitors=competitors, bm=bm, investment=investment, social_value=social_value)
# F13 create_resource_plan()
def create_resource_plan(item: dict, required_capabilities: list, team: dict, resource_type: list) -> dict: return _pending("create_resource_plan", item=item, required_capabilities=required_capabilities, team=team, resource_type=resource_type)
# F16 generate_section()
def generate_section(section_spec: dict, source_data: dict, writing_rules: dict) -> dict: return _pending("generate_section", section_spec=section_spec, source_data=source_data, writing_rules=writing_rules)
# F18 generate_image_spec()
def generate_image_spec(item: dict, architecture: dict, flow_type: str) -> dict: return _pending("generate_image_spec", item=item, architecture=architecture, flow_type=flow_type)
