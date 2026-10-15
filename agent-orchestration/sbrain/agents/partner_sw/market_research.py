"""실행별 KIET 시장 조사 연결 (SB-360) — 담당자 크롤러(crawl_keyword)를 쓰되 공유 자료 파일은 수정하지 않는다.

- 위치: 연결 코드라 담당자 코드 곁(agents/partner_sw)에 둔다. 엔진(orchestrator/)은 담당자 코드 · requests를 모른다.
- 스위치(기본 꺼짐): 워커 프로세스 값 하나(_kiet_search). bootstrap.build_app이 SBRAIN_KIET_SEARCH(환경 변수 → .env)를 읽어
  set_kiet_search로 넘긴다. Task 함수 · 담당자 코드는 환경 변수를 읽지 않고 kiet_search_enabled()만 본다.
  꺼져 있으면 T-S1은 KIET 검색 호출을 아예 하지 않는다(호출 기록도 없음).
- 호출: T-S1이 tools.search("KIET 시장 조사", …, retries=KIET_RETRIES)로만 부른다 — 시간 한도 · 재시도 · 호출 기록은 엔진이 한다.
- 실패: 크롤러 값의 status가 "failed"이거나 크롤러 밖으로 예외가 나오면 KietSearchFailed(ConnectionError — 엔진이 기록하고
  재시도하는 호출 실패)로 바꿔 올린다. 메시지 · 기록에는 고정 문구와 오류 종류 이름만 싣는다 — 검색어 · 응답 내용 · 크롤러
  값의 error 글(검색 주소 · 검색어가 들어 있음)은 넣지 않는다. 결과 0건("no_relevant_source_found")과 일부 검색만 실패하고
  결과가 있는 경우(크롤러 값 "collected")는 실패가 아니다.
- 재시도를 다 쓰면(ToolCallExhausted) T-S1이 받아 있는 자료로 계속한다(필수 규칙 2의 예외 — T-S1의 KIET 검색 호출만).
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import requests

from .agent_strategy.runtime import market_crawler

MAX_SEARCH_SECONDS = 25.0
MAX_RESULTS = 4
MAX_TEXT_CHARS = 1_200
KIET_RETRIES = 2   # (잠정) KIET 검색 호출만의 재시도 횟수 — 처음 포함 최대 3번. 다른 호출은 설정 retry.retryCount
SEARCH_FAILED = "KIET 검색 실패"   # 예외 메시지의 고정 문구 (검색어 · 응답 내용 없음)

_kiet_search = False   # 실행별 KIET 검색 스위치 — 워커 프로세스 값, 기본 꺼짐


def set_kiet_search(on: bool) -> None:
    """실행별 KIET 검색을 켜거나 끈다 (워커 조립 build_app이 부른다)."""
    global _kiet_search
    _kiet_search = bool(on)


def kiet_search_enabled() -> bool:
    """실행별 KIET 검색이 켜져 있는가 — T-S1이 검색 전에 본다."""
    return _kiet_search


class KietSearchFailed(ConnectionError):
    """KIET 검색 실패 — 엔진(tools._call)이 '호출실패'로 기록하고 재시도한다. 메시지는 고정 문구 + 오류 종류 이름뿐이다."""


class _DeadlineSession(requests.Session):
    """requests.Session에 검색 전체의 절대 시간 제한을 적용한다."""

    def __init__(self, deadline: float) -> None:
        super().__init__()
        self._deadline = deadline

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout("KIET 검색 전체 시간 제한 초과")
        configured = kwargs.get("timeout") or 20
        if isinstance(configured, tuple):
            kwargs["timeout"] = tuple(min(float(value or remaining), remaining) for value in configured)
        else:
            kwargs["timeout"] = min(float(configured), remaining)
        return super().request(method, url, **kwargs)


def search_keyword(keyword: str, timeout_sec: float) -> dict[str, Any]:
    """KIET 검색 결과를 메모리에서만 반환한다. add_keyword()와 달리 JSON 파일을 쓰지 않는다.

    실패(크롤러 값 status "failed" · 크롤러 밖으로 나온 예외)는 KietSearchFailed로 올린다 — tools.search가 재시도한다."""
    keyword = " ".join(str(keyword or "").split())[:120]
    if not keyword:
        return {"status": "skipped", "keyword": "", "sources": [], "resultCount": 0}

    budget = max(0.1, min(float(timeout_sec), MAX_SEARCH_SECONDS))
    session = _DeadlineSession(time.monotonic() + budget)
    try:
        result = market_crawler.crawl_keyword(keyword, session, limit=MAX_RESULTS, is_user_keyword=True)
        if result.get("status") == "failed":   # 크롤러가 안에서 잡은 네트워크 오류 · 시간 초과 — error 글은 싣지 않는다
            raise KietSearchFailed(SEARCH_FAILED) from None
        return _normalize(keyword, result)
    except KietSearchFailed:
        raise
    except Exception as exc:   # 요청 오류 · 시간 초과 · 사이트 모양 변화 등 — 원래 예외(검색어 · 주소가 들 수 있음)를 잇지 않는다
        raise KietSearchFailed(f"{SEARCH_FAILED} — {type(exc).__name__}") from None
    finally:
        session.close()


def _normalize(keyword: str, result: dict[str, Any]) -> dict[str, Any]:
    """크롤러 값을 실행별 시장 근거 모양으로 바꾼다 (실패가 아닌 값만 온다)."""
    sources = []
    for row in result.get("results", [])[:MAX_RESULTS]:
        url = str(row.get("url") or "")
        title = str(row.get("summaryTitleText") or row.get("title") or "KIET 자료")
        summary = str(row.get("summaryText") or "").strip()
        text = (title + (" — " + summary if summary else ""))[:MAX_TEXT_CHARS]
        if not text.strip():
            continue
        ref_seed = url or (keyword + "\n" + title + "\n" + text)
        ref = "kiet:run:" + hashlib.sha256(ref_seed.encode("utf-8")).hexdigest()[:16]
        sources.append({
            "domain": "market", "sourceRef": ref, "title": title, "url": url or None,
            "publishedAt": row.get("publishedAt"), "text": text,
            "matchedTerms": list(row.get("matchedTerms") or []),
            "publisher": "산업연구원 KIET", "retrievalMethod": "per-run KIET search",
        })
    status = "collected" if sources else str(result.get("status") or "no_relevant_source_found")
    return {"status": status, "keyword": keyword, "sources": sources, "resultCount": len(sources), "errorType": None}


def merge_market_evidence(local: dict[str, Any], fresh: dict[str, Any], *, char_budget: int = 5_500) -> dict[str, Any]:
    """새 KIET 근거와 기존 로컬 근거를 합쳐 retrieve()와 같은 형태로 돌려준다."""
    local_sources = list(local.get("sources") or [])
    fresh_sources = list(fresh.get("sources") or [])
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    used = 0
    for row in fresh_sources + local_sources:
        ref = str(row.get("sourceRef") or "")
        if ref in seen:
            continue
        size = len(str(row.get("text") or "")) + len(str(row.get("title") or ""))
        if used + size > char_budget:
            continue
        selected.append(row)
        seen.add(ref)
        used += size
        if len(selected) >= MAX_RESULTS:
            break
    result = dict(local)
    result.update({
        "sources": selected,
        "contextChars": used,
        "issues": [] if selected else list(local.get("issues") or []),
        "status": "retrieved" if selected else local.get("status", "no_relevant_evidence"),
        "kietSearch": {key: fresh.get(key) for key in ("status", "keyword", "resultCount", "errorType")},
    })
    return result
