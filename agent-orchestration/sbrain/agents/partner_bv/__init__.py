"""구현 · 검증-2 담당자 코드(T-B1 · T-B2 · T-V2)와 그 연결 코드.

- engineering_agent/ · verification_agent/ — 담당자 코드를 폴더 이름 그대로 옮긴 것(2026-10-08 받음). 바꾼 곳은 연결부뿐이고
  VENDORED.md에 모두 적었다. 담당자 새 판을 받으면 그 목록으로 비교한다. 두 패키지는 서로 import하지 않는다(만드는 쪽과
  채점하는 쪽 분리 — 담당자 원칙). 우리 연결 코드도 이 분리를 깨지 않는다.
- 바로 아래 파일 — 우리 연결 코드:
  - resources.py: 구현 담당자 자료(글꼴 · 대표 그림 SVG · 인포그래픽 템플릿)를 불러올 때 한 번 읽어 둔 상수
  - tasks.py: 실구현 Task 등록(IMPLEMENTED · IMPLEMENTED_TASKS · IMAGE_TASKS · bind_partner_bv) — 조립(bootstrap.py)만 부른다
- 담당자 tasks.py 두 개(engineering_agent/tasks.py · verification_agent/tasks.py)의 Task 함수(run_tb1 · run_tb2 · run_tv2)는
  지금 계약(파일 참조 FileRef · tools.files)으로 연결부만 고쳤다(VENDORED.md 3 · 4절). 이 파일은 그 둘을 불러오지 않고,
  등록 모듈(tasks.py)이 불러온다.

이 파일은 불러올 때 담당자 모듈을 미리 불러 둔다. 담당자 코드가 함수 안에서 늦게 import하는 모듈(composer의 poster,
artsheet · layout의 composer · showcase, design_kit의 svg_parts · layout, builder_html의 themes, 각 모듈의
sbrain.orchestrator.errors)과 자료 상수(resources)가 Task 실행 중에 처음 불러와지면 그때 디스크를 읽는다 — 미리 불러
두어 실행 중에는 디스크에 닿지 않게 한다(테스트가 디스크 접근을 막고 본다).
"""
from __future__ import annotations

from ...orchestrator import errors as _errors  # noqa: F401 — 담당자 _format_error의 함수 안 import 대상

from . import resources  # noqa: F401 — 자료 상수(가장 먼저: 담당자 모듈이 불러올 때 쓴다)
from .engineering_agent import builder_html, file_writer, gates, html_kit  # noqa: F401
from .engineering_agent.infographic import (  # noqa: F401
    artsheet, compose_guide, composer, content, design, design_kit, fonts, icons, illustrations, layout, poster,
    render, showcase, style, svg_parts, themes,
)
from .verification_agent import feature_match, llm_judge, score  # noqa: F401
from .verification_agent.rules import color, html_parser, items, r4, r4_onepage, wiring  # noqa: F401
from .verification_agent.rules import gates as _verification_gates  # noqa: F401
