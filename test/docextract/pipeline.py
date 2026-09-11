"""Extract local planning files, record failures, and build a compact FAISS RAG index."""
from __future__ import annotations

import html
import hashlib
import json
import pickle
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import faiss
import fitz
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = ROOT / "docs" / "공유자료" / "사업계획서 자료" / "# 필수"
RESULTS_DIR = Path(__file__).parent / "results"
RAG_DIR = RESULTS_DIR / "rag"
SUFFIXES = (".pdf", ".docx", ".hwpx", ".hwp")

# 일부 정부 PDF의 선택 딕셔너리 키가 깨져 있어도 본문은 읽힙니다.
# 배치 실행 시 MuPDF 진단 메시지만 숨기고 추출 실패는 status로 남깁니다.
fitz.TOOLS.mupdf_display_errors(False)


@dataclass(frozen=True)
class Result:
    path: Path
    format: str
    status: str
    text: str
    error: str | None = None
    details: dict[str, int | str] | None = None


def clean(text: str) -> str:
    """HWPX 내부 제어 문자열을 제거하고 공백을 정리한다."""
    text = html.unescape(text)
    text = re.sub(r"\bHWPHYPERLINK_[A-Z_]+\b", "", text)
    # 일부 PDF가 반복 삽입하는 내부 식별자와 페이지 번호를 제거한다.
    text = re.sub(r"INSID[A-Za-z]+_:MS_\d+MS_\d+\s*-\s*\d+\s*-\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def xml_text(raw: str) -> str:
    """패키지 메타데이터를 제외하고 문단 순서대로 본문만 읽는다."""
    root = ElementTree.fromstring(raw)
    paragraphs = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "p":
            value = clean(" ".join(part for part in element.itertext() if part.strip()))
            if value:
                paragraphs.append(value)
    return "\n".join(paragraphs)


def archive_text(path: Path, members: list[str]) -> str:
    with zipfile.ZipFile(path) as archive:
        return "\n".join(xml_text(archive.read(name).decode("utf-8", errors="replace")) for name in members).strip()


def extract(path: Path) -> Result:
    """원문 하나를 추출하고, 실패는 RAG에 넣지 않고 상태로 기록한다."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            with fitz.open(path) as document:
                pages = [page.get_text().strip() for page in document]
            text = clean("\n".join(page for page in pages if page))
            status = "extracted" if text else "needs_ocr"
            return Result(path, suffix, status, text, None if text else "No embedded text; OCR required", {"pageCount": len(pages), "textCharacterCount": len(text)})
        if suffix == ".docx":
            text = archive_text(path, ["word/document.xml"])
            return Result(path, suffix, "extracted" if text else "failed", text, None if text else "DOCX body has no text", {"textCharacterCount": len(text)})
        if suffix == ".hwpx":
            with zipfile.ZipFile(path) as archive:
                members = sorted(name for name in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", name))
            text = archive_text(path, members)
            return Result(path, suffix, "extracted" if text else "failed", text, None if text else "No HWPX section text found", {"sectionCount": len(members), "textCharacterCount": len(text)})
        if suffix == ".hwp":
            command = shutil.which("hwp5txt")
            if not command:
                return Result(path, suffix, "needs_converter", "", "Convert HWP to HWPX/PDF or install hwp5txt", {"textCharacterCount": 0})
            completed = subprocess.run([command, str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            text = clean(completed.stdout)
            return Result(path, suffix, "extracted" if text else "failed", text, completed.stderr.strip() or None, {"textCharacterCount": len(text)})
        return Result(path, suffix, "unsupported", "", "Unsupported file format")
    except Exception as error:
        return Result(path, suffix, "failed", "", str(error))


def save_result(result: Result) -> dict:
    relative = result.path.relative_to(SOURCE_DIR)
    # 공유하는 결과물에 개발자 PC의 절대 경로를 남기지 않는다.
    payload = {"relativePath": str(relative), "format": result.format, "status": result.status, "text": result.text, "error": result.error, "details": result.details or {}}
    output = RESULTS_DIR / relative.parent / f"{relative.name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def chunks(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    """문단·문장 경계를 우선 지키며 오버랩이 있는 검색 단위를 만든다."""
    pieces = [piece.strip() for piece in re.split(r"(?<=[.!?])\s+|\n+", text) if piece.strip()]
    output, current = [], ""
    for piece in pieces:
        # 표나 조항은 긴 한 줄로 들어올 수 있어 제한 길이에서 강제로 나눈다.
        while len(piece) > size:
            if current:
                output.append(current)
                current = ""
            output.append(piece[:size])
            piece = piece[size - overlap:]
        if current and len(current) + len(piece) + 1 > size:
            output.append(current)
            tail = current[-overlap:].strip()
            # 오버랩을 넣어도 제한 길이를 넘지 않을 때만 유지한다.
            current = f"{tail} {piece}".strip() if len(tail) + len(piece) + 1 <= size else piece
        else:
            current = f"{current} {piece}".strip()
    return output + ([current] if current else [])


def build_rag(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """출처를 추적할 청크와 변환·OCR 대기 목록을 분리한다."""
    prepared, failures = [], []
    for record in records:
        if record["status"] != "extracted" or not record["text"]:
            failures.append({key: record.get(key) for key in ("relativePath", "format", "status", "error")})
            continue
        document_id = hashlib.sha256(record["relativePath"].encode("utf-8")).hexdigest()[:16]
        document_chunks = chunks(record["text"])
        for index, text in enumerate(document_chunks):
            prepared.append({"chunkId": f"{document_id}-{index:04d}", "documentId": document_id, "text": text, "metadata": {"relativePath": record["relativePath"], "documentTitle": Path(record["relativePath"]).name, "format": record["format"], "chunkIndex": index, "documentChunkCount": len(document_chunks), "isDocumentStart": index == 0, "isDocumentEnd": index == len(document_chunks) - 1}})
    return prepared, failures


def write_index(prepared: list[dict], failures: list[dict]) -> None:
    """모델 서버 없이 저메모리 한국어 어휘 벡터와 FAISS 인덱스를 만든다."""
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    (RAG_DIR / "rag_chunks.jsonl").write_text("".join(json.dumps(chunk, ensure_ascii=False) + "\n" for chunk in prepared), encoding="utf-8")
    (RAG_DIR / "rag_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    documents = [chunk for chunk in prepared if chunk["metadata"]["isDocumentStart"]]
    guide = ["# RAG 문서별 청크 안내", "", "`rag_chunks.jsonl`은 기계용 JSON Lines 파일입니다. 아래 목록에서 원문별 청크 범위를 확인합니다.", ""]
    for chunk in documents:
        meta = chunk["metadata"]
        guide.extend([f"## {meta['documentTitle']}", f"- 원본 경로: `{meta['relativePath']}`", f"- 형식: `{meta['format']}`", f"- 청크: `{chunk['chunkId']}` ~ `{chunk['documentId']}-{meta['documentChunkCount'] - 1:04d}` ({meta['documentChunkCount']}개)", ""])
    (RAG_DIR / "rag_documents.md").write_text("\n".join(guide), encoding="utf-8")
    if not prepared:
        return
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=4096, dtype=np.float32, norm="l2")
    vectors = vectorizer.fit_transform([chunk["text"] for chunk in prepared]).toarray().astype("float32")
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(RAG_DIR / "faiss.index"))
    with (RAG_DIR / "vectorizer.pkl").open("wb") as file:
        pickle.dump(vectorizer, file)
    (RAG_DIR / "vector_metadata.json").write_text(json.dumps({"embeddingMethod": "TF-IDF Korean character n-grams", "metric": "cosine", "chunkCount": len(prepared), "dimension": vectors.shape[1], "chunks": prepared}, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    records = [save_result(extract(path)) for suffix in SUFFIXES for path in sorted(SOURCE_DIR.rglob(f"*{suffix}"))]
    prepared, failures = build_rag(records)
    write_index(prepared, failures)
    print(f"Indexed {len(prepared)} chunks; queued {len(failures)} documents for conversion or OCR.")


if __name__ == "__main__":
    main()
