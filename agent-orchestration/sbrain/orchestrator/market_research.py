"""실행별 KIET 조사 연결 — 벤더 크롤러를 쓰되 공유 자료 파일은 수정하지 않는다."""
from __future__ import annotations

import hashlib
import time
from typing import Any

import requests

from ..agents.partner_sw.agent_strategy.runtime import market_crawler

MAX_SEARCH_SECONDS = 25.0
MAX_RESULTS = 4
MAX_TEXT_CHARS = 1_200


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
    """KIET 검색 결과를 메모리에서만 반환한다. add_keyword()와 달리 JSON 파일을 쓰지 않는다."""
    keyword = " ".join(str(keyword or "").split())[:120]
    if not keyword:
        return {"status": "skipped", "keyword": "", "sources": [], "resultCount": 0}

    budget = max(0.1, min(float(timeout_sec), MAX_SEARCH_SECONDS))
    session = _DeadlineSession(time.monotonic() + budget)
    try:
        result = market_crawler.crawl_keyword(keyword, session, limit=MAX_RESULTS, is_user_keyword=True)
    except requests.RequestException as exc:
        return {"status": "failed", "keyword": keyword, "errorType": type(exc).__name__,
                "sources": [], "resultCount": 0}
    finally:
        session.close()

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
    return {"status": status, "keyword": keyword, "sources": sources,
            "resultCount": len(sources), "errorType": "RequestException" if status == "failed" else None}


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
