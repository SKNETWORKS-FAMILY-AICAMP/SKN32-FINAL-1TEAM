# S-Brain 워크플로우

Git 브랜치 전략, Jira 연동 규칙, CI 체크리스트, 실전 명령어를 정리한 팀 참고 문서입니다.

**스택**: Python 3.12 · FastAPI · React + Vite · GitHub Actions · Jira
**구조**: `web/backend` (FastAPI) / `web/frontend` (React, Vite) 모노레포

---

## 0. 개요

### main 브랜치
- 직접 push 금지
- PR을 통해서만 merge
- 최소 1명 승인 필수
- CI 테스트 통과 필수

### 이슈 ↔ 브랜치 ↔ PR
- 이슈 1개당 브랜치 1개
- Sub-task는 같은 브랜치의 커밋으로 구분 (별도 브랜치 X)
- 기능/수정 완료 즉시 PR 오픈
- merge 후 브랜치 삭제

---

## 1. 브랜치 전략

스프린트 단위로 브랜치를 만들지 않습니다. 스프린트 구분이 필요하면 main의 특정 커밋에 git tag를 남깁니다.

```
main
 ├─ feature/{이슈키}-{설명}
 ├─ fix/{이슈키}-{설명}
 └─ refactor/{이슈키}-{설명}
```

| 타입 | 패턴 | 용도 |
|---|---|---|
| `feature` | `feature/{이슈키}-{설명}` | 신규 기능, 초기 구성 등 |
| `fix` | `fix/{이슈키}-{설명}` | 버그 수정 |
| `refactor` | `refactor/{이슈키}-{설명}` | 동작 변경 없는 구조 개선 |

각 브랜치는 이슈 1개에 대응하며, main으로는 PR + 리뷰 승인 + CI 통과를 거쳐야만 들어갑니다.

---

## 2. 작업 흐름

1. **Jira에 이슈 생성** — 이슈 키(예: `SB-63`)가 발급됩니다. 이후 모든 브랜치명·커밋·PR 제목에 이 키를 붙입니다.
2. **main 기준으로 브랜치 생성** — `feature/` · `fix/` · `refactor/` 중 성격에 맞는 접두사를 고릅니다.
3. **이슈 키를 포함해 커밋** — Sub-task가 있어도 새 브랜치를 만들지 않고, 같은 브랜치에서 커밋으로 나눕니다.
4. **push 후 PR 오픈** — 기능/수정이 끝나는 즉시 PR을 엽니다. 제목에 이슈 키 포함, 본문에 Jira 링크를 답니다.
5. **CI 통과 + 리뷰 승인 대기** — `pr-title` · `backend` · `frontend` 체크가 모두 초록불이어야 하고, 팀원 1명 이상의 Approve가 필요합니다.
6. **Squash and merge** — 커밋 히스토리를 하나로 정리해 main에 합칩니다.
7. **브랜치 정리** — merge 후 원격/로컬 브랜치를 모두 삭제합니다.

---

## 3. 명령어 치트시트

이슈 키만 바꿔서 그대로 복사해 쓰면 됩니다. 예시는 `SB-63`, 설명은 `init-scaffold` 기준입니다.

**1) 브랜치 생성**
```bash
git checkout main
git pull
git checkout -b feature/SB-63-init-scaffold
```

**2) 커밋 (이슈 키 포함)**
```bash
git add web
git commit -m "SB-63 FastAPI/React 초기 스캐폴딩 추가"
```

**3) Push (최초 1회)**
```bash
git push -u origin feature/SB-63-init-scaffold
```
이후 같은 브랜치에 커밋을 추가할 땐 `git push`만 하면 됩니다.

**4) PR 오픈 (웹)**
GitHub 저장소 페이지의 **Compare & pull request** 버튼 → 제목 `[SB-63] FastAPI/React 초기 스캐폴딩 추가` → 본문에 Jira 링크 → **Create pull request**.

**5) merge 후 브랜치 정리**
```bash
git checkout main
git pull
git branch -d feature/SB-63-init-scaffold
```
원격 브랜치는 보통 PR 머지 화면의 **Delete branch** 버튼으로 지웁니다. 직접 지우려면:
```bash
git push origin --delete feature/SB-63-init-scaffold
```

---

## 4. PR · 커밋 규칙

**PR**
- 제목에 이슈 키 포함 — 예: `[SB-12] 로그인 기능 구현`
- 최소 1명 승인
- CI 통과 필수
- Squash Merge 권장

**Commit**
- 메시지에 이슈 키 포함 — 예: `SB-12 로그인 API 구현`

**이슈 트래킹**
- PR / commit에 이슈 키 일관 포함
- Smart Commit 연동이 되면 그 규칙을 따름
- 앱 연동이 어려우면 PR 본문 ↔ Jira에 서로 링크를 수동 등록하고 정기적으로 대조

---

## 5. CI 체크

`.github/workflows/ci.yml` — `main`으로의 push와 PR에서 실행됩니다.

| 체크 이름 | 확인 내용 | 비고 |
|---|---|---|
| `PR Title Convention` | PR 제목이 `[이슈키] 설명` 형식인지 정규식 검사 | pull_request에서만 실행 |
| `Backend (Python 3.12)` | pip install → `ruff check` → `pytest` | `web/backend/requirements.txt` 없으면 스킵 |
| `Frontend (React/Vite)` | npm ci → lint → `vitest` → `vite build` | `web/frontend/package.json` 없으면 스킵 |

---

## 6. 저장소 설정 (Rulesets)

Settings → Rules → Rulesets → `main` 대상 ruleset. 새 저장소를 세팅할 때 아래 순서를 그대로 따라가면 됩니다.

1. **Target branches 지정** — Add target → Include default branch (또는 패턴 `main`). **이걸 빼먹으면 아래 규칙이 전부 있어도 아무 브랜치에도 적용되지 않습니다.**
2. **Require a pull request before merging** — Required approvals: **1**
3. **Require status checks to pass** — 워크플로우가 저장소에서 한 번 이상 실행된 뒤에만 검색에 나타납니다. `PR Title Convention`, `Backend (Python 3.12)`, `Frontend (React/Vite)` 세 개를 추가 — job id(`backend` 등)가 아니라 job의 **표시 이름**으로 등록됩니다.
4. **Bypass list는 비워두기** — admin 역할이 여기 들어가면 승인·체크를 우회할 수 있습니다. 특별한 이유가 없으면 비워둡니다.

---

## 7. 트러블슈팅

**push가 "refusing to allow a Personal Access Token ... without workflow scope"로 거부됨**
`.github/workflows/*.yml`을 포함한 push는 PAT에 `workflow` 스코프가 있어야 합니다.
→ 해결: `gh auth refresh -h github.com -s workflow` (gh CLI) — 또는 github.com/settings/tokens에서 토큰에 workflow 스코프 추가 후 자격 증명 갱신 — 또는 SSH 원격으로 전환.

**Squash and merge 옵션 자체가 안 보임**
→ 해결: PR 머지 버튼 옆 ▾ 화살표에서 방식 선택 가능.

---

## 8. 스프린트 태그

스프린트는 브랜치로 나누지 않습니다. 구분이 필요하면 main의 특정 커밋에 태그만 남깁니다.

```bash
git checkout main
git pull
git tag SB-Sprint-1
git push origin SB-Sprint-1
```

태그는 그 시점의 main 커밋을 가리킬 뿐, 별도 브랜치를 만들지 않습니다. 다음 스프린트는 `SB-Sprint-2`로 이어서 붙입니다.
