"""추출 상태, 청킹, 저장된 벡터 인덱스를 함께 검증한다."""
import json
import unittest

from pipeline import RAG_DIR, build_rag, chunks, main


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 실제 자료를 다시 처리해 공유용 산출물이 최신인지 확인한다.
        main()

    def test_chunks_keep_text(self):
        values = chunks("첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다.", size=20, overlap=5)
        self.assertGreater(len(values), 1)
        self.assertIn("첫", values[0])
        self.assertIn("셋", values[-1])
        self.assertTrue(all(len(value) <= 20 for value in values))

    def test_failures_are_separate_from_chunks(self):
        records = [
            {"relativePath": "a.pdf", "format": ".pdf", "status": "extracted", "text": "본문입니다."},
            {"relativePath": "b.hwp", "format": ".hwp", "status": "needs_converter", "text": "", "error": "convert"},
        ]
        chunked, failures = build_rag(records)
        self.assertEqual(len(chunked), 1)
        self.assertEqual(failures[0]["relativePath"], "b.hwp")

    def test_real_outputs_include_vector_index(self):
        metadata = json.loads((RAG_DIR / "vector_metadata.json").read_text(encoding="utf-8"))
        chunks = [json.loads(line) for line in (RAG_DIR / "rag_chunks.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue((RAG_DIR / "faiss.index").is_file())
        self.assertTrue((RAG_DIR / "vectorizer.pkl").is_file())
        self.assertEqual(metadata["chunkCount"], len(chunks))
        self.assertTrue(all("sourcePath" not in chunk["metadata"] for chunk in chunks))
        self.assertTrue(all("INSIDabcdef" not in chunk["text"] for chunk in chunks))
        self.assertEqual(json.loads((RAG_DIR / "rag_failures.json").read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()

