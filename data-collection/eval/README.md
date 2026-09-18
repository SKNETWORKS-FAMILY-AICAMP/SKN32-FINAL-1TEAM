# 검색 평가셋 (topic-v1)

공고 매칭 검색이 **좋아졌는지 숫자로 증명**하기 위한 평가셋이다.
방향은 [ML_DIRECTION.md](../docs/ML_DIRECTION.md) P0, 데이터 계약은
[ML_CODEX_DESIGN.md](../docs/ML_CODEX_DESIGN.md) 4절을 따른다.

> 판정 화면(`label_app.py`)은 **내부 검토 전용**이다. 서비스 배포 대상이 아니다.

## 한눈에

```
queries.jsonl (60)  ──build_pool──▶  pool.jsonl (Dense@20 ∪ BM25@10, 자르지 않음)
                                        │
                                  judge_llm (A·B 두 번)
                                        ▼
                               llm_judgments.jsonl
                                        │
            사람 ─ label_app ─▶ human_judgments.jsonl   ① 블라인드 150  ② 검수 대기열
                                        │
                                  merge_qrels
                                        ▼
                                  qrels.jsonl ──evaluate──▶ runs/*.json
```

## 검수자가 할 일

```powershell
cd C:\mok_workspace\SKN32-FINAL-1TEAM\data-collection
.\.venv\Scripts\python.exe -X utf8 eval\label_app.py        # http://127.0.0.1:8001
```

1. **질의별 모드로 10질의 파일럿** — 기준이 몸에 붙게 한다. 애매했던 사례는 이유 칸에 적는다.
   판정 기준 자체가 이상하면 여기서 멈추고 기준(`judge_llm.py` SYSTEM, `label.html` 안내)을 고친다.
2. **① 블라인드 150쌍** — LLM 답이 안 보인다. 반드시 ②보다 먼저 한다.
3. `merge_qrels.py` 로 일치율 확인
   - 잠정 기준 통과(정확 일치 ≥0.70 · 가중 카파 ≥0.60 · 0↔2 ≤3%) → ② 로
   - 미달 → 불일치 사례를 보고 프롬프트를 고쳐 `judge_llm.py` 재실행
4. **② 검수** — LLM 답이 흔들린 쌍만 나온다. 이유가 칩으로 붙어 있다.
5. `merge_qrels.py` → `evaluate.py`

판정 기준 요약은 화면 상단 "판정 기준" 을 펼치면 나온다. 핵심 한 줄:
**지역·업력·나이·규모·신청자 형태·마감은 무시하고 지원 내용과 분야만 본다.**

## 명령

```powershell
.\.venv\Scripts\python.exe -X utf8 eval\build_pool.py --plan     # 색인 정합성 · 질의 문장 확인
.\.venv\Scripts\python.exe -X utf8 eval\build_pool.py            # 풀 생성 (기존 쌍 보존, 새 쌍만 추가)
.\.venv\Scripts\python.exe -X utf8 eval\judge_llm.py --plan      # 예상 비용
.\.venv\Scripts\python.exe -X utf8 eval\judge_llm.py             # LLM 판정 (이미 한 것은 건너뜀)
.\.venv\Scripts\python.exe -X utf8 eval\merge_qrels.py           # qrels + 블라인드 일치율
.\.venv\Scripts\python.exe -X utf8 eval\evaluate.py --systems dense bm25 rrf
.\.venv\Scripts\python.exe -X utf8 eval\evaluate.py --judges human   # 사람 판정만 정답으로
```

## 파일

| 파일 | 내용 | git |
|---|---|---|
| `queries.jsonl` | 질의 60 (정상 52 · 무관 8). `MatchRequest` 모양 + `as_of_date` | ✅ |
| `pool.jsonl` | 판정 후보. 순위·점수는 분석용, 화면에는 안 보임 | ✅ |
| `pool_meta.json` | 공고 집합 해시 · 색인 정합성 · 스냅샷 해시 · git 리비전 · seed | ✅ |
| `llm_judgments.jsonl` | LLM 판정 원본 (A/B, 모델, prompt_sha) | ✅ |
| `human_judgments.jsonl` | 사람 판정 원본. 덧붙이기만 한다 | ✅ |
| `qrels.jsonl` | 최종 정답. `judge` = human / llm / llm_unreviewed | ✅ |
| `snapshot/pool_notices.jsonl` | 판정 당시 공고 내용 (약 3MB) | ❌ 보관 정책 미정 |
| `runs/` | 평가 결과 | 선택 |

## 규칙

- `topic_rel` 2 / 1 / 0 / null. **null 과 미판정은 0 이 아니다.** 평가에서 뺀다.
- 무관 질의(`kind: negative`) 도 자동 0 이 아니라 똑같이 판정한다.
- `as_of_date` 로 '창업 N년차' 계산을 고정한다. `search/app.py` 는 고치지 않았다(`common.query_text` 참조).
- 새 검색 방식이 미판정 공고를 상위에 올리면 `build_pool.py` 에 그 방식을 넣어 쌍을 **추가**하고
  같은 `label_version` 으로 판정을 보충한 뒤 모든 시스템을 다시 평가한다.
- 판정 기준을 바꾸면 `LABEL_VERSION` 을 올린다. 섞어 쓰지 않는다.

## 아직 안 한 것 (Codex 설계 대비)

- `eligibility_cases.jsonl` — 자격 판정 정답. 주제 평가가 자리 잡은 뒤
- `splits.json` — 개발/시험 분할. 지금 60질의는 전부 개발용으로 본다
- 풀 밖 무작위 표본으로 풀 편향 점검
- 같은 아이디어를 바꿔 쓴 질의(`scenario_group` 공유) — 현재는 질의마다 그룹이 하나
