# Git Branch Strategy

## main

- 직접 push 금지
- PR을 통해서만 merge
- 최소 1명 승인 필수
- CI 테스트 통과 필수

## 브랜치

```
main
 ├─ feature/{이슈키}-{설명}
 ├─ fix/{이슈키}-{설명}
 └─ refactor/{이슈키}-{설명}
```

## 규칙

- 이슈 1개당 브랜치 1개
- Sub-task는 별도 브랜치를 만들지 않고 동일 브랜치에서 커밋으로 구분
- 기능/수정 완료 즉시 PR
- PR 리뷰 후 merge
- merge 후 브랜치 삭제
- 스프린트 단위로 브랜치를 생성하지 않음
- 스프린트 구분이 필요한 경우 Git tag로 기록

## PR

- PR 제목에 이슈 키 포함
  - 예: `[SB-12] 로그인 기능 구현`
- 최소 1명 승인
- CI 통과 필수
- Squash Merge 권장

## Commit

- 커밋 메시지에 이슈 키 포함
  - 예: `SB-12 로그인 API 구현`

## Sprint

- 브랜치로 구분하지 않음
- 필요 시 main의 특정 커밋에 Git tag 생성
  - 예: `SB-Sprint-1`, `SB-Sprint-2`

## Issue Tracking

- PR/commit에 이슈 키를 일관되게 포함
- Smart Commit 자동화는 사용하는 Jira/Git 연동 규칙에 맞춰 적용
  - GitHub 조직 권한 문제로 앱 연동이 어려운 경우, PR 본문과 Jira 이슈에 서로의
    링크를 수동으로 등록하고 정기적으로 대조 점검하는 방식으로 대체 가능
