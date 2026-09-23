# 웹 개발 Agent 지식 수집

개발 Agent가 프롬프트와 구현 작업에 재사용할 수 있는 실무 지식 40개를 네 분류에
10개씩 정리합니다. `TOP 10`은 인기도 통계가 아니라 실무 활용도를 기준으로 한
편집 순서입니다. 연차별 역량은 근속 연수가 아니라 수행 책임의 예시이며, SFIA의
공식 레벨과 정확히 일대일로 대응한다고 주장하지 않습니다.

```powershell
python -B crawler.py --crawl
python -B -m unittest test_crawler
```

- `output/development_knowledge.json`: ID, 분류, 순위, 개념, 사용 시점, 적용 방법,
  장점, 주의점, 출처, Agent 프롬프트 힌트
- `output/development_knowledge.md`: 사람이 읽는 동일 목록
- `output/source_manifest.json`: 출처 URL별 수집 시각, 원문 제목, SHA-256, 성공·실패 상태
- `output/raw/*.txt`: 출처별 HTML 본문을 추출한 원문 아카이브
- `output/collection_report.md`: TOP 40 전체 목록, 적용 지침, 출처·품질 한계를 정리한 산출물 보고서

두 수집 데이터의 산출물 보고서는 저장된 JSON에서 `python -B test/collection_reports/generate_reports.py`로 재생성합니다(저장소 루트에서 실행).

2026-09-14 실행에서 서로 다른 36개 출처의 원문을 모두 수집했습니다. 각 항목은
원문을 그대로 옮긴 인용문이 아니라 링크한 자료에 근거한 짧은 한국어 요약입니다.
코드의 수동 요약을 수정한 뒤 재실행하면 결과를 재생성할 수 있습니다. 원문을 다시
다운로드하려면 `--crawl`을 지정합니다. 문서 내용은 이후 개정될 수 있으므로
에이전트가 실제 구현에 적용할 때는 해당 출처의 현재 버전을 확인해야 합니다.
