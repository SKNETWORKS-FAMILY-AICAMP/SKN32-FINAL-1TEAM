"""Unified KIET-based market crawling pipeline.

Commands:
  init-keywords  Build keyword_list.json from MSS notices.
  crawl-kiet     Crawl KIET SummaryPop texts for all keywords.
  build-report   Build output/results.json from KIET results.
  add-keyword    Add a user keyword, crawl KIET, and rebuild report.
  all            Run init-keywords, crawl-kiet, build-report.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup
from requests import RequestException

ROOT = Path(__file__).parent
OUTPUT_DIR = ROOT / "output"
KEYWORD_LIST = OUTPUT_DIR / "keyword_list.json"
KIET_RESULTS = OUTPUT_DIR / "raw_kiet_results.json"
MARKET_RESEARCH = OUTPUT_DIR / "results.json"
KEYWORD_HISTORY = OUTPUT_DIR / "keyword_history.json"

MSS_PRESS = "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1064518&cbIdx=86&parentSeq=1064518"
MSS_NOTICES = {
    "pre_startup": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1066579&cbIdx=310",
    "restart": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1065552&cbIdx=310",
    "early_general": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1065015&cbIdx=310",
    "early_deeptech": "https://www.mss.go.kr/site/smba/ex/bbs/View.do?bcIdx=1064566&cbIdx=310",
}
MSS_PRE_PDF = "https://www.mss.go.kr/common/board/Download.do?bcIdx=1066579&cbIdx=310&streFileNm=236d517e-fc4d-4607-8ba0-6b2557afeb62.pdf"
DEEPTECH = ["빅데이터·AI", "바이오헬스", "미래모빌리티", "친환경에너지", "로봇"]
PRE_EXAMPLES = ["정보·통신", "전기·전자", "기계·소재(재료)", "바이오·의료(생명·식품)", "에너지·자원(환경·에너지)", "화학(화공·섬유)", "공예·디자인"]

KIET_BASE_URL = "https://www.kiet.re.kr"
KIET_SEARCH_URL = f"{KIET_BASE_URL}/searchAll"
KIET_SUMMARY_URL = f"{KIET_BASE_URL}/getSearchEtt"
KIET_SEARCH_CATEGORIES = {"kiet_research": "연구", "kiet_trends": "동향"}

STOPWORDS = {"기업용", "기업", "서비스", "솔루션", "시스템", "플랫폼", "시장", "산업", "기술", "사업", "제품", "업무", "지원", "관리", "기반", "활용", "관련"}
SYNONYMS = {
    "AI": ["AI", "인공지능", "에이아이"],
    "문서": ["문서"],
    "검색": ["검색", "탐색"],
    "데이터": ["데이터", "빅데이터"],
    "바이오": ["바이오", "의료", "헬스케어"],
    "친환경": ["친환경", "탄소중립", "에너지"],
}
SECTION_LABELS = {
    "marketNeed": "시장 문제와 사업 필요성",
    "marketTrend": "시장 규모 및 최근 동향",
    "competitors": "주요 경쟁사와 대체재",
    "differentiation": "경쟁사 대비 차별성 및 경쟁력",
}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fetch_page_text(url: str, session: requests.Session) -> str:
    response = session.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return BeautifulSoup(response.content, "html.parser").get_text(" ", strip=True)


def fetch_pdf_text(url: str, session: requests.Session) -> str:
    response = session.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    document = fitz.open(stream=response.content, filetype="pdf")
    return " ".join(page.get_text() for page in document)


def build_keyword_list(session: requests.Session | None = None, output: Path = KEYWORD_LIST) -> dict:
    session = session or requests.Session()
    press = fetch_page_text(MSS_PRESS, session)
    normalized = re.sub(r"[^가-힣A-Za-z0-9]", "", html.unescape(press))
    for name in DEEPTECH:
        if re.sub(r"[^가-힣A-Za-z0-9]", "", name) not in normalized:
            raise ValueError(f"중기부 보도자료에서 공식 분야를 확인할 수 없음: {name}")
    titles = {
        "pre_startup": "예비창업패키지",
        "restart": "재도전성공패키지",
        "early_general": "초기창업패키지(일반형)",
        "early_deeptech": "초기창업패키지(딥테크 특화형)",
    }
    for key, url in MSS_NOTICES.items():
        if titles[key] not in fetch_page_text(url, session):
            raise ValueError(f"공고 페이지 제목 확인 실패: {key}")
    pre_pdf = re.sub(r"\s+", "", fetch_pdf_text(MSS_PRE_PDF, session))
    for name in [*PRE_EXAMPLES, "여성", "소셜", "사내", "全기술분야"]:
        if re.sub(r"\s+", "", name) not in pre_pdf:
            raise ValueError(f"예비창업패키지 PDF에서 분류 확인 실패: {name}")
    programs = [
        {"programId": "pre_startup", "programName": "예비창업패키지", "track": "2026 모집공고", "industryRestriction": "all_technology_fields_with_non_exhaustive_examples", "industries": [{"industryId": f"PRE-EXAMPLE-{i:02d}", "industryName": name, "classificationType": "official_non_exhaustive_example", "idOrigin": "internal_generated", "sourceUrl": MSS_PRE_PDF} for i, name in enumerate(PRE_EXAMPLES, 1)], "specializedTracks": ["여성", "소셜벤처", "사내벤처"], "note": "일반분야는 전 기술 분야 지원이며 industries는 공고에 든 예시다. 특화분야 3개는 산업이 아닌 신청 유형이고 사내벤처는 별도 공고 예정이다.", "sourceUrl": MSS_NOTICES["pre_startup"], "classificationSourceUrl": MSS_PRE_PDF},
        {"programId": "restart", "programName": "재도전성공패키지", "track": "2026 모집공고", "industryRestriction": "not_enumerated_in_notice_pdf", "industries": [], "note": "공고 PDF는 예비재창업자 또는 7년 이내 재창업기업을 지원하며 산업별 모집표는 제시하지 않는다. 제외 업종은 공고 PDF 확인.", "sourceUrl": MSS_NOTICES["restart"]},
        {"programId": "early_general", "programName": "초기창업패키지", "track": "일반형", "industryRestriction": "all_fields_subject_to_notice_eligibility", "industries": [], "note": "중기부 2026 창업패키지 유형표에서 일반형은 전 분야 창업기업으로 표기한다. 공고상 제외 업종은 별도 확인.", "sourceUrl": MSS_NOTICES["early_general"], "classificationSourceUrl": MSS_PRESS},
        {"programId": "early_deeptech", "programName": "초기창업패키지", "track": "딥테크 특화형", "industryRestriction": "five_official_fields", "industries": [{"industryId": f"EARLY-DEEPTECH-{i:02d}", "industryName": name, "classificationType": "official_program_field", "idOrigin": "internal_generated", "sourceUrl": MSS_PRESS} for i, name in enumerate(DEEPTECH, 1)], "sourceUrl": MSS_NOTICES["early_deeptech"], "classificationSourceUrl": MSS_PRESS},
    ]
    previous = load_json(Path(output), {})
    data = {"researchYear": 2026, "sourcePublisher": "중소벤처기업부", "dataType": "keyword_list", "scopeNote": "KIET 검색에 사용할 기본 산업 검색어와 사용자 키워드를 저장한다. 사용자 키워드는 공식 지원 분야가 아니다.", "programs": programs, "userKeywords": previous.get("userKeywords", []), "collectedAt": datetime.now(timezone.utc).isoformat()}
    save_json(Path(output), data)
    return data


def keyword_terms(keyword: str) -> list[str]:
    terms = []
    for term in re.findall(r"[A-Za-z]{2,}|[가-힣]{2,}", keyword):
        normalized = term.upper() if term.lower() == "ai" else term
        if normalized in STOPWORDS:
            continue
        if normalized not in terms:
            terms.append(normalized)
    return terms


def query_variants(keyword: str, is_user_keyword: bool) -> list[str]:
    if not is_user_keyword:
        return [keyword]
    terms = keyword_terms(keyword)
    variants = [keyword]
    if len(terms) >= 2:
        variants.append(" ".join(terms[:3]))
        for left in range(len(terms)):
            for right in range(left + 1, len(terms)):
                variants.append(f"{terms[left]} {terms[right]}")
    for term in terms:
        if term in SYNONYMS and len(terms) >= 2:
            for alias in SYNONYMS[term]:
                if alias != term:
                    variants.append(" ".join([alias, *[item for item in terms if item != term][:2]]))
    cleaned = []
    for item in variants:
        item = clean_text(item)
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned[:8]


def matched_terms(text: str, terms: list[str]) -> list[str]:
    matches = []
    for term in terms:
        aliases = SYNONYMS.get(term, [term])
        if any(alias and alias.lower() in text.lower() for alias in aliases):
            matches.append(term)
    return matches


def is_relevant_result(row: dict, required_terms: list[str]) -> tuple[bool, list[str]]:
    if not required_terms:
        return True, []
    text = " ".join(str(row.get(key) or "") for key in ("title", "summaryTitleText", "summaryText"))
    matches = matched_terms(text, required_terms)
    return len(matches) >= (2 if len(required_terms) >= 2 else 1), matches


def keyword_rows(listing: dict) -> list[dict]:
    rows, seen = [], set()
    for program in listing.get("programs", []):
        for field in program.get("industries", []):
            key = (field.get("industryId"), field.get("industryName"))
            if key in seen:
                continue
            seen.add(key)
            rows.append({**field, "programName": program.get("programName"), "track": program.get("track")})
    for index, row in enumerate(listing.get("userKeywords", []), 1):
        keyword = row.get("keyword")
        if keyword:
            rows.append({"industryId": f"USER-KEYWORD-{index:03d}", "industryName": keyword, "classificationType": "user_keyword", "programName": "사용자 키워드", "track": "KIET 검색어"})
    return rows


def parse_meta(text: str) -> dict:
    match = re.search(r"(.+?)\s+([^|]+)\|\s*(\d{4}/\d{2}/\d{2})\s+(.+)", text)
    if not match:
        return {"contentType": None, "author": None, "publishedAt": None, "title": text}
    return {"contentType": clean_text(match.group(1)), "author": clean_text(match.group(2)), "publishedAt": match.group(3).replace("/", "-"), "title": clean_text(match.group(4))}


def parse_open_summary(onclick: str) -> dict | None:
    match = re.search(r"openSummary\('([^']*)',\s*'([^']*)',\s*'([^']*)'\)", onclick or "")
    if not match:
        return None
    return {"menuName": match.group(1), "menuCode": match.group(2), "contentNo": match.group(3)}


def html_text(html_value: str) -> str | None:
    text = clean_text(BeautifulSoup(html_value or "", "html.parser").get_text(" ", strip=True))
    return text or None


def fetch_summary(open_call: dict, session: requests.Session, referer: str) -> dict:
    try:
        response = session.post(KIET_SUMMARY_URL, data={"menu_nm": open_call["menuName"], "menu_cd": open_call["menuCode"], "no": open_call["contentNo"]}, timeout=20, headers={"User-Agent": "Mozilla/5.0", "Referer": referer})
        response.raise_for_status()
        data = response.json()
    except (RequestException, ValueError) as error:
        return {"status": "failed", "error": str(error), "titleText": None, "summaryText": None}
    if not data.get("result"):
        return {"status": "failed", "error": "KIET returned result=false", "titleText": None, "summaryText": None}
    return {"status": "collected", "error": None, "titleText": html_text(data.get("ttl_html")), "summaryText": html_text(data.get("summary_html"))}


def parse_kiet_result(li, keyword: str, source_query: str, search_category: str, search_category_name: str, session: requests.Session, referer: str) -> dict | None:
    anchor = li.select_one("a[href]")
    if not anchor:
        return None
    href = anchor.get("href", "")
    if not href or href.startswith("javascript:"):
        return None
    title_node = anchor.select_one(".title")
    meta = parse_meta(clean_text(title_node.get_text(" ", strip=True))) if title_node else {"title": clean_text(anchor.get_text(" ", strip=True))}
    button = li.select_one("button[onclick*='openSummary']")
    open_call = parse_open_summary(button.get("onclick", "")) if button else None
    if not open_call:
        return None
    summary = fetch_summary(open_call, session, referer)
    if summary["status"] != "collected" or not summary.get("summaryText"):
        return None
    return {"keyword": keyword, "sourceSearchQuery": source_query, "searchCategory": search_category, "searchCategoryName": search_category_name, "title": meta.get("title"), "contentType": meta.get("contentType"), "author": meta.get("author"), "publishedAt": meta.get("publishedAt"), "summaryTitleText": summary.get("titleText"), "summaryText": summary.get("summaryText"), "url": urljoin(KIET_BASE_URL, href), "openSummary": open_call, "sourceName": "산업연구원 KIET", "sourceUrl": KIET_SUMMARY_URL, "verificationStatus": "kiet_summary_pop_collected"}


def crawl_keyword_collection(keyword: str, source_query: str, search_category: str, search_category_name: str, session: requests.Session, limit: int = 10, required_terms: list[str] | None = None) -> dict:
    params = {"query": source_query, "collection": "ALL", "category": search_category, "listCount": str(limit), "startCount": "0", "sort": "DATE"}
    try:
        response = session.get(KIET_SEARCH_URL, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except RequestException as error:
        return {"keyword": keyword, "sourceSearchQuery": source_query, "searchCategory": search_category, "searchCategoryName": search_category_name, "status": "failed", "error": str(error), "results": [], "collectedAt": datetime.now(timezone.utc).isoformat()}
    response.encoding = response.apparent_encoding or response.encoding
    soup = BeautifulSoup(response.text, "html.parser")
    results, seen = [], set()
    for li in soup.select("ul.list_box > li"):
        row = parse_kiet_result(li, keyword, source_query, search_category, search_category_name, session, response.url)
        if not row:
            continue
        relevant, matched = is_relevant_result(row, required_terms or [])
        if not relevant or row["url"] in seen:
            continue
        row["matchedTerms"] = matched
        seen.add(row["url"])
        results.append(row)
        if len(results) >= limit:
            break
    return {"keyword": keyword, "sourceSearchQuery": source_query, "searchCategory": search_category, "searchCategoryName": search_category_name, "status": "collected" if results else "no_relevant_source_found", "error": None, "resultCount": len(results), "results": results, "collectedAt": datetime.now(timezone.utc).isoformat()}


def crawl_keyword(keyword: str, session: requests.Session, limit: int = 10, is_user_keyword: bool = False) -> dict:
    collections, all_results, seen = [], [], set()
    variants = query_variants(keyword, is_user_keyword)
    required = keyword_terms(keyword) if is_user_keyword else []
    for source_query in variants:
        for search_category, search_category_name in KIET_SEARCH_CATEGORIES.items():
            crawl = crawl_keyword_collection(keyword, source_query, search_category, search_category_name, session, limit, required)
            collections.append(crawl)
            for row in crawl.get("results", []):
                if row.get("url") in seen:
                    continue
                seen.add(row.get("url"))
                all_results.append(row)
        if len(all_results) >= limit * len(KIET_SEARCH_CATEGORIES):
            break
    status = "collected" if all_results else "no_relevant_source_found"
    if any(item["status"] == "failed" for item in collections) and not all_results:
        status = "failed"
    return {"keyword": keyword, "status": status, "error": "; ".join(item["error"] for item in collections if item.get("error")) or None, "resultCount": len(all_results), "queryVariants": variants, "requiredTerms": required, "collections": collections, "results": all_results, "collectedAt": datetime.now(timezone.utc).isoformat()}


def crawl_kiet(listing: Path = KEYWORD_LIST, output: Path = KIET_RESULTS, limit: int = 10, session: requests.Session | None = None) -> dict:
    session = session or requests.Session()
    listing_data = load_json(Path(listing))
    categories = []
    for field in keyword_rows(listing_data):
        crawl = crawl_keyword(field["industryName"], session, limit, field.get("classificationType") == "user_keyword")
        categories.append({"industryId": field["industryId"], "industryName": field["industryName"], "classificationType": field.get("classificationType"), "programName": field.get("programName"), "track": field.get("track"), **crawl})
    result = {"researchYear": 2026, "sourceName": "산업연구원 KIET", "sourceUrl": KIET_SEARCH_URL, "limitPerCategory": limit, "categories": categories, "summary": {"categoryCount": len(categories), "collectedCategoryCount": sum(1 for item in categories if item["status"] == "collected"), "totalResultCount": sum(item.get("resultCount", 0) for item in categories)}, "methodNote": "keyword_list.json의 키워드를 KIET 통합검색 query로 전달한다. 사용자 키워드는 핵심 토큰 조합으로 확장하되 최소 2개 핵심 토큰이 SummaryPop 본문에 매칭된 결과만 저장한다.", "collectedAt": datetime.now(timezone.utc).isoformat()}
    save_json(Path(output), result)
    return result


def kiet_by_keyword(kiet_data: dict) -> dict[str, dict]:
    return {item.get("industryName") or item.get("keyword"): item for item in kiet_data.get("categories", [])}


def evidence(row: dict, section: str) -> dict:
    return {"claim": row.get("summaryTitleText") or row.get("title"), "evidenceText": row.get("summaryText"), "source": {"title": row.get("title"), "url": row.get("url"), "type": "kiet_summary_pop", "publisher": "산업연구원 KIET", "publishedAt": row.get("publishedAt"), "contentType": row.get("contentType"), "searchCategory": row.get("searchCategory"), "searchCategoryName": row.get("searchCategoryName"), "sourceSearchQuery": row.get("sourceSearchQuery"), "matchedTerms": row.get("matchedTerms"), "openSummary": row.get("openSummary")}, "verificationStatus": row.get("verificationStatus", "kiet_summary_pop_collected"), "businessPlanUse": section, "analysis": None}


def target_phrase(name: str, field: dict) -> str:
    return f"'{name}' 검색 주제" if field.get("classificationType") == "user_keyword" else f"{name} 분야"


def build_section(name: str, section: str, rows: list[dict], field: dict) -> dict:
    target = target_phrase(name, field)
    is_user = field.get("classificationType") == "user_keyword"
    if section == "marketNeed":
        selected = [row for row in rows if row.get("searchCategoryName") == "연구"][:10]
        prompt = f"{target}의 시장 문제와 사업 필요성은 KIET 연구 자료 중 핵심 토큰이 함께 확인된 SummaryPop 본문을 근거 후보로 검토한다." if selected else (f"{target}와 직접 연결되는 KIET 연구 근거를 찾지 못했다. 더 넓은 산업 키워드나 세부 기술 키워드를 추가해 재검색한다." if is_user else f"{target}의 시장 문제와 사업 필요성은 KIET 연구 자료의 SummaryPop 본문을 근거 후보로 검토한다.")
    elif section == "marketTrend":
        selected = [row for row in rows if row.get("searchCategoryName") == "동향"][:10] or rows[:10]
        prompt = f"{target}의 시장 규모와 최근 동향은 KIET 동향 자료를 우선 검토하고, 부족하면 관련 연구 자료를 보조 근거로 사용한다." if selected else (f"{target}의 직접 동향 근거를 찾지 못했다. 아이템명을 산업 키워드로 확장하거나 유사 기술명을 추가해 재검색한다." if is_user else f"{target}의 시장 규모와 최근 동향은 KIET 동향 자료를 우선 검토하고, 부족하면 연구 자료를 보조 근거로 사용한다.")
    elif section == "competitors":
        selected = []
        prompt = f"{target}의 경쟁사와 대체재는 KIET 산업 요약으로 확정하지 않는다. 제품명, 기업명, 가격 페이지, 고객 사례를 별도 조사한다." if is_user else f"{target}의 경쟁사와 대체재는 KIET 산업 요약만으로 확정하지 말고 기업 공식 홈페이지, 제품 페이지, 고객 사례에서 별도 조사한다."
    else:
        selected = []
        prompt = f"{target}의 차별성과 경쟁력은 사용자가 제시한 기능과 경쟁 제품 비교로 작성한다. KIET 자료는 시장 배경 근거로만 사용한다." if is_user else f"{target}의 차별성과 경쟁력은 사용자의 아이템 기능을 기준으로 경쟁 제품과 비교해 작성한다. KIET 자료는 산업 배경 근거로만 사용한다."
    return {"status": "kiet_summary_pop_collected" if selected else "no_relevant_source_found", "label": SECTION_LABELS[section], "evidence": [evidence(row, section) for row in selected], "promptBrief": prompt}


def build_market_report(listing: Path = KEYWORD_LIST, kiet_results: Path = KIET_RESULTS, output: Path = MARKET_RESEARCH) -> dict:
    listing_data = load_json(Path(listing))
    kiet_data = load_json(Path(kiet_results), {"categories": [], "summary": {}})
    by_keyword = kiet_by_keyword(kiet_data)
    reports = []
    for field in keyword_rows(listing_data):
        name = field["industryName"]
        rows = by_keyword.get(name, {}).get("results", [])
        sections = {section: build_section(name, section, rows, field) for section in SECTION_LABELS}
        reports.append({"industryName": name, "researchYear": 2026, "category": field, "subjectType": "사용자 키워드" if field.get("classificationType") == "user_keyword" else "산업 분야", "sourceKeyword": name, "sourceResultCount": len(rows), "sections": sections, "promptBrief": f"{target_phrase(name, field)} 시장조사는 KIET 통합검색에서 수집한 SummaryPop 본문 {len(rows)}건을 근거 후보로 사용한다. 경쟁사·차별화는 KIET 자료만으로 채우지 않고 제품·기업 공식 자료를 추가 확인한다.", "collectedAt": datetime.now(timezone.utc).isoformat()})
    result = {"researchYear": 2026, "researchMode": "kiet_summary_pop", "source": {"name": "산업연구원 KIET 통합검색", "searchUrl": KIET_SEARCH_URL, "summaryEndpoint": KIET_SUMMARY_URL, "inputPath": str(Path(kiet_results).relative_to(ROOT))}, "reports": reports, "summary": {"reportCount": len(reports), "sourceCategoryCount": kiet_data.get("summary", {}).get("categoryCount", 0), "sourceCollectedCategoryCount": kiet_data.get("summary", {}).get("collectedCategoryCount", 0), "sourceTotalResultCount": kiet_data.get("summary", {}).get("totalResultCount", 0)}, "methodNote": "keyword_list.json의 산업 키워드와 사용자 키워드를 검색어로 사용한다. KIET 연구/동향 더보기 결과의 openSummary 호출값을 /getSearchEtt에 전달해 SummaryPop 본문을 수집한다. 경쟁사와 단가는 별도 수집 파일에서 비교한다.", "collectedAt": datetime.now(timezone.utc).isoformat()}
    save_json(Path(output), result)
    return result


def add_keyword(keyword: str, listing: Path = KEYWORD_LIST, history: Path = KEYWORD_HISTORY) -> dict:
    keyword = keyword.strip()
    if not keyword:
        raise ValueError("keyword is required")
    now = datetime.now(timezone.utc).isoformat()
    listing_data = load_json(Path(listing))
    if not listing_data:
        raise FileNotFoundError("먼저 init-keywords를 실행하세요")
    user_keywords = listing_data.setdefault("userKeywords", [])
    exists = any(row.get("keyword") == keyword for row in user_keywords)
    if not exists:
        user_keywords.append({"keyword": keyword, "classificationType": "user_keyword", "programEligibility": "not_assessed", "addedAt": now})
        save_json(Path(listing), listing_data)

    history_data = load_json(Path(history), {"historyPolicy": "upsert_by_keyword", "searches": []})
    previous_records = [row for row in history_data.get("searches", []) if row.get("keyword") == keyword]
    previous = previous_records[-1] if previous_records else {}

    kiet = crawl_kiet(listing=listing)
    report = build_market_report(listing=listing)
    keyword_row = next((row for row in kiet["categories"] if row.get("industryName") == keyword), None)
    record = {
        "keyword": keyword,
        "wasNewKeyword": not exists,
        "historyPolicy": "upsert_by_keyword",
        "source": "KIET SummaryPop",
        "resultCount": keyword_row.get("resultCount", 0) if keyword_row else 0,
        "status": keyword_row.get("status", "no_relevant_source_found") if keyword_row else "no_relevant_source_found",
        "queryVariants": keyword_row.get("queryVariants", []) if keyword_row else [],
        "requiredTerms": keyword_row.get("requiredTerms", []) if keyword_row else [],
        "results": keyword_row.get("results", []) if keyword_row else [],
        "refreshedFiles": ["output/keyword_list.json", "output/raw_kiet_results.json", "output/results.json"],
        "firstCollectedAt": previous.get("firstCollectedAt") or previous.get("collectedAt") or now,
        "lastCollectedAt": now,
        "searchCount": int(previous.get("searchCount", 0)) + 1,
        "previousCollectedAt": previous.get("lastCollectedAt") or previous.get("collectedAt"),
    }
    history_data["historyPolicy"] = "upsert_by_keyword"
    history_data["description"] = "같은 keyword는 중복 행으로 누적하지 않고 최신 검색 결과로 덮어쓴다. firstCollectedAt/searchCount로 최초 실행일과 실행 횟수를 보존한다."
    history_data["searches"] = [row for row in history_data.get("searches", []) if row.get("keyword") != keyword]
    history_data["searches"].append(record)
    history_data["updatedAt"] = now
    save_json(Path(history), history_data)
    return {"keyword": keyword, "wasNewKeyword": not exists, "resultCount": record["resultCount"], "status": record["status"], "marketReportCount": report["summary"]["reportCount"], "searchCount": record["searchCount"]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified market crawler")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-keywords")
    sub.add_parser("crawl-kiet")
    sub.add_parser("build-report")
    add = sub.add_parser("add-keyword")
    add.add_argument("keyword")
    sub.add_parser("all")
    args = parser.parse_args()

    if args.command == "init-keywords":
        data = build_keyword_list()
        print(json.dumps({"programCount": len(data["programs"]), "keywordFile": str(KEYWORD_LIST)}, ensure_ascii=False))
    elif args.command == "crawl-kiet":
        print(json.dumps(crawl_kiet()["summary"], ensure_ascii=False))
    elif args.command == "build-report":
        print(json.dumps(build_market_report()["summary"], ensure_ascii=False))
    elif args.command == "add-keyword":
        print(json.dumps(add_keyword(args.keyword), ensure_ascii=False))
    elif args.command == "all":
        build_keyword_list()
        kiet = crawl_kiet()
        report = build_market_report()
        print(json.dumps({"kiet": kiet["summary"], "market": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
