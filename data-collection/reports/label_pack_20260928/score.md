# Codex 판정 대조 — label_pack_20260928

판정은 **AI 참고 정답**(Codex)이다. 사람 정답이 아니다.

- 판정 수: 신청자 유형 93 · 업종 34

| 확인 | 결과 | 쓰임 |
|---|---|---|
| 예비 불가 strong → 판정도 불가 | 30/30 (100%) | 게이트 필터 사용 여부 |
| └ 판정은 "가능"(신청 가능한 공고를 뺄 오류) | 없음 | 0이어야 한다 |
| B: API 불가·본문 가능 → 판정 가능 | 9/9 (100%) | 본문을 API 보다 우선 |
| 예비 불가 weak → 판정 불가 | 13/17 (76%) | 약한 근거 사용 여부 |
| 개인사업자 불가 strong → 판정 불가 | 7/7 (100%) | 개인/법인 게이트 |
| 법인 불가 strong → 판정 불가 | 8/8 (100%) | 개인/법인 게이트 |
| 예비 불가 추정 → 판정 불가·추정 | 23/23 (100%) | 순위 신호 사용 여부 |
| └ 판정은 "가능" | 없음 | |
| F: LLM 모두 언급 없음인데 판정 불가 | P084, P085, P089 | 놓침 |

유형별 전체 일치: pre_founder 74/93 (80%) · sole_proprietor 88/93 (95%) · corporation 89/93 (96%)

업종 (공고×신청자 대분류): eligible 32 · ineligible 101 · unclear 2
잘못 밀림(eligible): bizinfo:PBLN_000000000126456(C), bizinfo:PBLN_000000000126456(F), bizinfo:PBLN_000000000126456(G), bizinfo:PBLN_000000000126456(I), bizinfo:PBLN_000000000126456(J), bizinfo:PBLN_000000000122625(A), bizinfo:PBLN_000000000122625(C), bizinfo:PBLN_000000000122625(F), bizinfo:PBLN_000000000122625(G), bizinfo:PBLN_000000000122625(I), bizinfo:PBLN_000000000122625(J), bizinfo:PBLN_000000000126466(J), bizinfo:PBLN_000000000126512(J), bizinfo:PBLN_000000000126235(A), bizinfo:PBLN_000000000126235(C), bizinfo:PBLN_000000000126235(F), bizinfo:PBLN_000000000126235(G), bizinfo:PBLN_000000000126235(J), bizinfo:PBLN_000000000126547(C), bizinfo:PBLN_000000000126547(G), kstartup:179286(A), kstartup:179286(C), kstartup:179286(F), kstartup:179286(G), bizinfo:PBLN_000000000121098(J), bizinfo:PBLN_000000000121103(A), bizinfo:PBLN_000000000121103(F), bizinfo:PBLN_000000000121103(I), bizinfo:PBLN_000000000121103(J), bizinfo:PBLN_000000000123900(C), bizinfo:PBLN_000000000123900(F), bizinfo:PBLN_000000000126501(G)
