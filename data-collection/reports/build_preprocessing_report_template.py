from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from lxml import etree


REFERENCE = Path(r"C:\Users\playdata2\Downloads\[데이터전처리] 데이터전처리결과서.docx")
OUTPUT = Path(r"C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection\reports\데이터_전처리_결과서_양식적용_Codex.docx")
EXPECTED_SHA256 = "264D1F1450AB327DD7C8F55563ACC9D812753D8246BA61038D66A4311C523D04"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def set_text(element, value: str) -> None:
    nodes = element.xpath(".//w:t", namespaces=NS)
    if not nodes:
        paragraphs = element.xpath(".//w:p", namespaces=NS)
        if not paragraphs:
            raise ValueError("Target slot has no paragraph")
        run = etree.SubElement(paragraphs[0], f"{{{W_NS}}}r")
        node = etree.SubElement(run, f"{{{W_NS}}}t")
        nodes = [node]
    nodes[0].text = value
    nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for node in nodes[1:]:
        node.text = ""


def set_table(table, rows: list[list[str]]) -> None:
    xml_rows = table.xpath("./w:tr", namespaces=NS)
    if len(xml_rows) != len(rows):
        raise ValueError(f"Expected {len(rows)} rows, found {len(xml_rows)}")
    for xml_row, values in zip(xml_rows, rows):
        cells = xml_row.xpath("./w:tc", namespaces=NS)
        if len(cells) != len(values):
            raise ValueError(f"Expected {len(values)} cells, found {len(cells)}")
        for cell, value in zip(cells, values):
            set_text(cell, value)


def patch_document(document_xml: bytes) -> bytes:
    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(document_xml, parser)
    body = root.find(".//w:body", NS)
    if body is None:
        raise ValueError("Document body not found")

    # Cover title table: retain the source's three-run typography.
    cover_title_nodes = body[1].xpath(".//w:t", namespaces=NS)
    if len(cover_title_nodes) != 3:
        raise ValueError("Unexpected cover title structure")
    for node, value in zip(
        cover_title_nodes,
        ["SK 네트웍스 Family AI 27기 : 1팀", "데이터 전처리", " 결과서"],
    ):
        node.text = value
        node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")

    set_table(
        body[4],
        [
            ["산출물 단계", "데이터 전처리"],
            ["제출 일자", "2026. 9. 16."],
            ["깃허브 경로", "github.com/SKNETWORKS-FAMILY-AICAMP/SKN32-FINAL-1TEAM/tree/main/data-collection"],
            ["작성 팀원", "geunlee00"],
        ],
    )
    set_text(body[8], "데이터 전처리 프로세스 (Data Preprocessing)")

    paragraph_text = {
        9: "전처리 개요",
        10: "전처리 목적 : 창업 지원 공고를 공통 스키마로 정규화하고 검색·학습용 데이터셋 생산",
        11: "전처리 범위 : K Startup·기업마당 API → 정규화 → 첨부 추출 → 임베딩·평가 데이터",
        12: "사용 도구 : Python, requests, BeautifulSoup, pdfplumber, hwp5, sentence-transformers, NumPy",
        13: "원천 데이터 분석",
        14: "    2.1 데이터 출처 및 현황",
        17: "    2.2 품질 이슈 진단",
        20: "     2.3 전처리 파이프라인 흐름도",
        21: "정제·가공·분할 절차 및 후속 활용",
        22: "    3.1 학습 / 검증 / 테스트 분할",
        23: "분할 기준 : qid 또는 scenario_group 단위 그룹 분할, 권장 비율 70:15:15, 고정 seed 사용",
        26: "    3.2 후속 단계 활용 적합성 및 재현성 관리",
        29: "변경 이력 및 적용 전략",
    }
    for index, value in paragraph_text.items():
        set_text(body[index], value)

    set_table(
        body[15],
        [
            ["이슈 유형", "대상 필드", "판정 기준", "처리 방식", "처리량 / 비고"],
            ["수집원", "K Startup", "API 정상 응답", "공통 스키마 변환", "239건 (13.5%)"],
            ["수집원", "기업마당", "API 정상 응답", "공통 스키마 변환", "1,533건 (86.5%)"],
            ["필수값", "notice_id·title", "NULL / 빈 문자열", "거부 큐 기록", "거부 0건"],
            ["중복", "source+source_id", "동일 식별자", "최종 정상 행 유지", "동일 출처 0건"],
            ["기간", "apply_period", "5개 유형 분류", "미해석은 issues 보존", "unknown 54건"],
            ["첨부", "attachment_files", "내용 해시", "형식별 추출·중복 방지", "1,721개 / 650.8 MiB"],
        ],
    )

    set_table(
        body[18],
        [
            ["처리 단계", "입력", "출력", "목적"],
            ["수집 통합", "2개 공개 API", "raw JSON", "원본 보존·재현"],
            ["스키마 정규화", "출처별 필드", "normalized JSON", "공통 필드 통합"],
            ["기간 해석", "원문 접수기간", "5종 period_type", "판단 불가 보존"],
            ["첨부 처리", "링크 2,614개", "파일 1,721개", "해시 중복 방지"],
            ["임베딩·평가", "정제 공고", "vector / qrels", "검색 학습 자산"],
        ],
    )

    set_table(
        body[24],
        [
            ["필드", "타입", "결측 처리", "중복 처리", "이상치 처리", "비고"],
            ["notice_id", "STRING", "필수", "source+source_id", "-", "PK"],
            ["title", "TEXT", "필수", "제목 정제", "빈 문자열 거부", "검색·표시"],
            ["body", "TEXT", "NULL 유지", "내용 해시", "HTML·길이 정제", "임베딩 대상"],
            ["apply_period", "OBJECT", "unknown 보존", "-", "5종 분류", "마감 필터"],
            ["region / subcategory", "ARRAY / TEXT", "NULL 유지", "-", "출처별 범위", "편향 주의"],
        ],
    )

    set_table(
        body[27],
        [
            ["구분", "항목", "기준 / 결과", "설명 및 관리 방안"],
            ["현황", "정규화 공고", "1,772건", "2026-09-16 최신 스냅샷"],
            ["현황", "기간 유형", "fixed 852건", "시작일·종료일 구조화"],
            ["현황", "비정형 기간", "budget 632 / rolling 143", "원문과 유형 동시 보존"],
            ["현황", "기타 기간", "until_filled 91 / unknown 54", "unknown은 issues 기록"],
            ["첨부", "원본 파일", "1,721개 / 650.8 MiB", "PDF 936·HWP 527·HWPX 199"],
            ["벡터", "문서 임베딩", "2,153 × 1,024", "BGE-M3·float32·L2 정규화"],
            ["학습", "평가 질의", "60개", "정상 52·무관 8"],
            ["학습", "후보 쌍 / qrels", "1,657 / 1,317", "Dense·BM25 합집합 후 판정"],
            ["품질", "사람 판정", "143쌍", "최종 성능 검증 우선 집합"],
            ["품질", "LLM 약한 라벨", "1,174쌍", "운영 채택 전 사람 검수"],
            ["재현성", "단위 테스트", "81개 중 68 통과", "외부 의존 13개 건너뜀·실패 0"],
        ],
    )

    set_table(
        body[30],
        [
            ["변경일", "변경자", "변경내용", "영향 받는 항목", "비고"],
            ["2026.09.16", "전체", "data-collection 실제 집계값 반영", "전체", "v2.0"],
            ["2026.09.16", "geunlee00", "지정 양식 적용 및 품질 검증 반영", "t1 ~ t6", "v2.1"],
        ],
    )

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")


def main() -> None:
    if not REFERENCE.exists():
        raise FileNotFoundError(REFERENCE)
    actual = sha256(REFERENCE)
    if actual != EXPECTED_SHA256:
        raise RuntimeError(f"Reference hash changed: {actual}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="preprocessing-template-") as tmp:
        temp_output = Path(tmp) / OUTPUT.name
        with ZipFile(REFERENCE, "r") as source, ZipFile(temp_output, "w", ZIP_DEFLATED) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename == "word/document.xml":
                    payload = patch_document(payload)
                target.writestr(info, payload)
        shutil.copyfile(temp_output, OUTPUT)

    print(OUTPUT)
    print(f"SHA256={sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
