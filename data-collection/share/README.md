# 공유 페이지 (share/)

검증 화면(8010)의 결과를 **서버 없이** 볼 수 있게 옮긴 한 장짜리 HTML 페이지들이다. 데이터가 파일 안에 들어 있어서, 파일을 브라우저로 열기만 하면 된다. 글꼴만 Google Fonts에서 불러오므로 인터넷이 없으면 기본 글꼴로 보인다.
같은 페이지를 claude.ai에도 올려 두었다(비공개 — 공유는 각 페이지의 Share 메뉴에서 소유자가 한다).

| 페이지 | 원래 화면 | 게시 링크 | 데이터 | 다시 만들기 |
|---|---|---|---|---|
| [매칭방식비교.html](매칭방식비교.html) | `/filter-first-eval` | [공고 매칭 방식 비교](https://claude.ai/artifact/UT4MmaFiorn5GYZnaaFXDJ) | `reports/filter_first_eval_20260928T104212Z` | `build_filter_first.py` + `filter_first.template.html` |
| [전체흐름.html](전체흐름.html) | `/flow` | [공고 데이터 전체 흐름](https://claude.ai/artifact/MWB72kbMUNmz5ku73StqFS) | 코드·STATUS·WORKLOG (2026-09-29 기준으로 새로 씀) | 손으로 쓴 페이지 — 직접 고친다 |
| [업종추출결과.html](업종추출결과.html) | `/industry-results` | [업종 추출 결과](https://claude.ai/artifact/CTumyNQb6KUoVB3tps8jaN) | `reports/industry_llm_full_luna_20260928_final5`(+ final6 비교, `label_pack_20260928`) | `build_industry.py` (페이지 안 `/*DATA*/…/*END*/`만 다시 채운다) |
| [Jev채점시험.html](Jev채점시험.html) | `/jev-probe` | [Jev 채점 시험](https://claude.ai/artifact/K2WJfq5XcxoZz8nrn68myc) | `reports/jev_judge_probe_20260928T110603Z` | `build_jev.py` + `jev_template.html` |
| [신청자유형.html](신청자유형.html) | `/applicant-types` | [신청자 유형 판정](https://claude.ai/artifact/SwEHA6bDVei9PPVFe1KrUp) | `reports/applicant_type_llm_full_20260928T023916Z` | `build_applicant_types.py` + `applicant_types.template.html` |
| [테이블구조.html](테이블구조.html) | 없음 (2026-09-30 새로 만듦) | [공고 DB 테이블 구조](https://claude.ai/artifact/5iu7oSKGHENt3hdbcgtiLL) | 공용 DB `information_schema`·행 수(9/30 SELECT), 9/30 `data/run.log` | 손으로 쓴 페이지 — 칸 목록만 9/30 DB 주석에서 뽑아 넣었다. 직접 고친다 |

## 다시 만들기 (data-collection 에서)

```powershell
.\.venv\Scripts\python.exe -X utf8 share\build_filter_first.py      # 인자로 다른 결과 폴더 이름을 줄 수 있다
.\.venv\Scripts\python.exe -X utf8 share\build_industry.py
.\.venv\Scripts\python.exe -X utf8 share\build_jev.py
.\.venv\Scripts\python.exe -X utf8 share\build_applicant_types.py
```

- 모두 **파일만 읽는다**(DB·모델·유료 API 호출 없음). 스크립트는 자기 위치의 한 단계 위를 data-collection으로 본다.
- 2026-09-29 확인: 네 스크립트로 다시 만든 페이지가 게시본과 같았다(업종·Jev·신청자 유형은 바이트까지 같고, 매칭 방식 비교는 데이터 안 항목 순서 하나만 다르다). 그 뒤 저장소 판에만 첫 줄 charset 선언을 더했다.
- 다시 만든 뒤 claude.ai 게시본도 바꾸려면 Claude에게 "share/○○.html 을 이 링크로 다시 게시해 줘"라고 링크와 함께 요청한다. 링크는 그대로 유지된다.

## 알아 둘 것

- **결과는 자동으로 바뀌지 않는다.** 저장된 실행 결과를 넣은 것이라, 새 실험·새 배치 결과는 다시 만들어야 반영된다. 예: 신청자 유형은 9/28 실행(2,476건) 기준이고, 9/29 공용 DB는 2,525건이다.
- 페이지 디자인(색·글꼴·다크 모드)은 여섯 장이 같다(테이블구조는 9/30 추가). 새 페이지를 만들면 `filter_first.template.html` 의 `<style>` 을 재사용한다.
- **보는 법: HTML 파일을 더블클릭해 브라우저로 열면 된다.** 서버·설치가 필요 없다. 맨 첫 줄 `<meta charset="utf-8">` 덕분에 한글이 깨지지 않는다(2026-09-29 추가 — 틀 파일에도 넣어 다시 만들어도 유지된다).
- 페이지 파일에는 `<!doctype>`·`<html>`·`<body>` 태그가 없다. claude.ai 게시가 이 틀을 씌우며, 첫 줄의 charset 선언은 게시본에서 영향이 없다.
- 비밀번호·API 키·서버 주소는 넣지 않는다.
