# Chroma 실제 벡터 검증 — 불일치

- 실행: 2026-09-21T03:19:27+00:00 → 2026-09-21T03:19:31+00:00
- 명령: `python -X utf8 eval/chroma_integrity.py`
- 판정: **불일치** · chroma_content_verified = False
- 읽은 것: DB(SELECT 만), `data/embeddings_v1.npz`, `data/vecstore/chroma` (원본을 임시 폴더로 복사해 사본을 열었다)
- 쓰기: 이 보고서 폴더뿐. DB·NPZ·Chroma 는 고치지 않았다.

## ① DB ↔ NPZ (입력 해시)

- 판정: 통과 · DB 공고 2328건

## ② NPZ ↔ Chroma (실제 벡터 원소 단위)

- 판정: 불일치
- NPZ 2328건 · Chroma 2328건 · 비교 2328건
- 허용 오차 이내: 바이트 일치 1775건 · 재정규화 일치 552건 · 그 외 0건
  (재정규화 일치 = NPZ 벡터를 길이 1로 다시 나누면 Chroma 값과 같다. 코사인 색인이 저장할 때 다시 정규화한다)
- 최대 절대 차이 0.0193024 · 불일치 공고를 뺀 최대 1.49012e-08 (허용 1e-06, float32)
- 허용 오차 근거: float32 → .tolist() → Chroma float32 왕복. 코사인 색인의 재정규화로 마지막 자리가 바뀔 수 있다 (관측 최대 1.5e-8). 1e-6 은 그보다 크고 서로 다른 벡터의 차이(1e-3 이상)보다 훨씬 작다.
- 벡터 값이 허용 오차(1e-06)를 넘게 다른 공고 1건
  - `kstartup:179193` 최대 차이 0.0193024 · 코사인 0.9866

## ③ 메타데이터 (Chroma · NPZ · 현재 설정)

- 판정: 통과

| 칸 | Chroma | NPZ | 현재 | 같음 |
|---|---|---|---|---|
| model | BAAI/bge-m3 | BAAI/bge-m3 | BAAI/bge-m3 | 예 |
| revision | 5617a9f61b028005a4858fdac845db406aefb181 | 5617a9f61b028005a4858fdac845db406aefb181 | 5617a9f61b028005a4858fdac845db406aefb181 | 예 |
| input_version | v1:title+body+target_text+target_category+category+subcategory | v1:title+body+target_text+target_category+category+subcategory | v1:title+body+target_text+target_category+category+subcategory | 예 |
| max_tokens | 512 | 512 | 512 | 예 |
| dim | 1024 | 1024 | 1024 | 예 |
| dtype | float32 | float32 | float32 | 예 |
| normalized | True | True | True | 예 |
| byte_order | little | little | little | 예 |

## 검사 중 변경 감지

- 변경 없음
- 방법: NPZ 는 파일 sha256, Chroma 는 원본 폴더 전체 파일의 크기·sha256, DB 는 공고 입력 해시 집합의 sha256 을 검사 전후에 비교한다. 검사 도중 잠깐 바뀌었다가 되돌아간 경우는 잡지 못한다.

## 식별 해시

- DB 입력 해시 집합: `e77a852f2122e849a5c6e2e6e43568aafe76df8b0a8aaa8e0b91f7a5ea1c7ce5`
- NPZ 파일: `3def67cf6598f06f66ff9949adc02ccb60ad4298a6d76bd844ebac563c262ccb`
- NPZ 벡터 집합: `438ed2ad0ceb5518022e5f300fe376529861d43d2f40b1dcb18b228a3f979da0`
- Chroma 조회 벡터 집합: `499d812abc3c0e8449d7cb90dcc0cfb8b23d794e0e956291428b44f6c866009f`
- 벡터 집합 해시 계산: ID 정렬 → `ID(utf-8) + 0x00 + float32 리틀엔디언` 을 이어 sha256. 바이트 일치용이며 허용 오차 기반 일치와 다르다.

## 한계

- 이번 검사는 **지금 시점**의 정합성이다. 과거 `search_comparison_20260918T054314Z` 실행 당시의 정합성 증명이 아니다.
- 검색 품질을 증명하지 않는다. 사람 관련성 판정은 여전히 없다.
- 불일치가 있어도 색인·벡터를 자동으로 고치지 않았다. 고치는 것은 별도 작업이다.
