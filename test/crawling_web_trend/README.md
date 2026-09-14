# 2026 웹디자인 트렌드 TOP 30

2026년 디자인 리포트에서 직접 확인한 근거 문구를 포함한 웹디자인·UI/UX 트렌드 30개를 생성합니다. 크롤링, URL 접근 로그, 성공률, RAG, 통계 보고서는 만들지 않습니다.

```powershell
python -B crawler.py
python -B -m unittest test_crawler
```

- `output/web_design_trends_2026.json`: 구조화된 30개 목록
- `output/web_design_trends_2026.md`: 동일 내용의 읽기용 목록

모든 항목은 `rank`, `trendId`, `trendName`, `description`, `webApplicationExample`, `secondBrainApplication`, `keywords`, `evidence`를 포함합니다. `evidence.supportingText`는 출처에서 직접 확인한 문구입니다.
