"""안내 문서 G-04 — 조율 Agent의 규칙 단계 (기준 문서 시트 2 r21, 시트 5 R-10).

파일을 쓰는 규칙 단계라 run(inp, files) 모양이다 — 엔진이 파일 창구(FileTool)를 둘째 인자로 넘긴다. LLM을 부르지 않는다.

- README.md(text/markdown, UTF-8)를 템플릿으로 만든다. 섹션은 늘 있다 — 슬롯 값이 비면 기본 문구로 채운다(R-10 ①).
  제목(아이템명 · 공고명), 파일 목록(진입 파일 · 자산 · 인포그래픽 · 안내 문서 자신 — 원페이지는 진입 파일과 인포그래픽이 같은
  파일이라 한 번만), 여는 방법(prototype.kind로 갈림 — html은 브라우저로 진입 파일을 열어 실행 · 화면 안 버튼으로 동작 확인,
  svg-onepage는 브라우저로 열람 · 브라우저 인쇄 기능으로 인쇄), AI 생성 고지(기획서 6-8 고정 문구).
- 산출물 내용은 파일 이름만 싣는다(HTML 본문 등은 싣지 않는다). 아이템명 · 공고명은 줄바꿈을 한 칸으로 바꿔 한 줄에 싣는다.
- 자체 검사(readme_check — 담당자 검증-2 README 진단과 같은 기준): 웹개발 · AI API는 '실행' 또는 '열람', 원페이지는 '열람'과
  '인쇄'가 문서 안에 있어야 한다. 불통과면 흐름이 재수행 횟수까지 다시 만들고, 끝내 불통과면 관리자 사건 후 계속한다(점수 밖).
- 문구 · 기본 문구는 잠정이다(PROVISIONAL g04.templateText).
"""
from __future__ import annotations

from ...contracts.tasks import G04In, G04Out
from ...models import CheckResult, FileRef
from ...orchestrator.tools import FileTool

README_FILE = "README.md"
MARKDOWN_TYPE = "text/markdown"
# 기획서 6-8 고정 문구 — 프로토타입 실행 안내의 AI 생성 고지 (T-C4 Deliverable.prototypeNotice도 같은 문구)
PROTOTYPE_NOTICE = "이 프로토타입은 AI가 생성했습니다."

# ── 템플릿 문구 (잠정 — PROVISIONAL g04.templateText) ─────────────────
TITLE_HTML = "실행 · 열람 안내"                    # (잠정)
TITLE_ONEPAGE = "열람 · 인쇄 안내"                 # (잠정)
DEFAULT_ITEM_NAME = "(아이템명 없음)"               # (잠정) 아이템명이 비었을 때
DEFAULT_ANNOUNCEMENT = "(공고명 없음)"              # (잠정) 공고명이 비었을 때
DEFAULT_ENTRY = "진입 파일이 만들어지지 않았습니다."   # (잠정) 진입 파일이 없을 때
LABEL_ENTRY = "진입 파일"                          # (잠정) 파일 목록의 설명
LABEL_ASSET = "함께 받는 파일"                      # (잠정)
LABEL_INFOGRAPHIC = "인포그래픽"                   # (잠정)
LABEL_README = "이 안내 문서"                      # (잠정)
# 여는 방법 — {entry}는 진입 파일 이름(백틱 감쌈) (잠정)
OPEN_HTML = ("1. {entry} 파일을 웹 브라우저(Chrome · Edge 등)로 열면 바로 실행됩니다. 따로 설치할 것은 없습니다.\n"
             "2. 화면 안의 버튼과 입력란을 눌러 주요 기능이 동작하는지 확인합니다.")
OPEN_ONEPAGE = ("1. {entry} 파일을 웹 브라우저(Chrome · Edge 등)로 열어 열람합니다.\n"
                "2. 인쇄하려면 브라우저의 인쇄 기능(Ctrl+P, Mac은 Cmd+P)을 열어 용지 방향과 여백을 확인한 뒤 인쇄합니다. "
                "인쇄 창에서 PDF로 저장할 수도 있습니다.")
OPEN_NO_ENTRY_HTML = "진입 파일이 만들어지지 않아 실행할 파일이 없습니다."      # (잠정)
OPEN_NO_ENTRY_ONEPAGE = "진입 파일이 만들어지지 않아 열람 · 인쇄할 파일이 없습니다."  # (잠정)

# 자체 검사 낱말 (구현 · 검증-2 담당 합의 2026-09-30 — 검증-2 README 진단과 같은 기준)
CHECK_ANY_HTML = ("실행", "열람")       # 웹개발 · AI API — 둘 중 하나
CHECK_ALL_ONEPAGE = ("열람", "인쇄")    # 원페이지 — 둘 다


def _one_line(text: str | None) -> str:
    return " ".join((text or "").split())


def _code(name: str) -> str:
    return f"`{name}`"


def build_readme(inp: G04In) -> str:
    """템플릿에 슬롯을 채운 마크다운 글. 파일 이름 외의 산출물 내용은 싣지 않는다."""
    proto, info = inp.prototype, inp.infographic
    onepage = proto.kind == "svg-onepage"
    item = _one_line(inp.item_spec.item_name) or DEFAULT_ITEM_NAME
    announcement = _one_line(inp.announcement.title) or DEFAULT_ANNOUNCEMENT
    entry: FileRef | None = proto.entry_file

    files: list[str] = []
    files.append(f"- {LABEL_ENTRY}: {_code(entry.name)}" if entry is not None else f"- {LABEL_ENTRY}: {DEFAULT_ENTRY}")
    files += [f"- {LABEL_ASSET}: {_code(f.name)}" for f in proto.asset_files]
    if entry is None or info.image_file.key != entry.key:   # 원페이지는 진입 파일 = 인포그래픽 그림 — 한 번만
        files.append(f"- {LABEL_INFOGRAPHIC}: {_code(info.image_file.name)}")
    files.append(f"- {LABEL_README}: {_code(README_FILE)}")

    if entry is None:
        how = OPEN_NO_ENTRY_ONEPAGE if onepage else OPEN_NO_ENTRY_HTML
    else:
        how = (OPEN_ONEPAGE if onepage else OPEN_HTML).format(entry=_code(entry.name))
    title = TITLE_ONEPAGE if onepage else TITLE_HTML
    return (f"# {title} — {item}\n\n"
            f"- 아이템: {item}\n"
            f"- 공고: {announcement}\n\n"
            f"## 파일 목록\n\n" + "\n".join(files) + "\n\n"
            f"## 여는 방법\n\n{how}\n\n"
            f"## AI 생성 고지\n\n{PROTOTYPE_NOTICE}\n")


def readme_check(text: str, kind: str) -> CheckResult:
    """자체 검사 — 웹개발 · AI API는 '실행' 또는 '열람', 원페이지는 '열람'과 '인쇄'. 실패 문구에 문서 내용을 넣지 않는다."""
    if kind == "svg-onepage":
        missing = [w for w in CHECK_ALL_ONEPAGE if w not in text]
        failures = [f"안내 문서에 '{w}' 안내가 없음" for w in missing]
    else:
        failures = [] if any(w in text for w in CHECK_ANY_HTML) else ["안내 문서에 '실행' 또는 '열람' 안내가 없음"]
    return CheckResult(passed=not failures, failures=failures)


def run(inp: G04In, files: FileTool) -> G04Out:
    """README.md를 만들어 파일 창구로 넣고 참조와 자체 검사 결과를 돌려준다."""
    text = build_readme(inp)
    ref = files.put(README_FILE, text.encode("utf-8"), MARKDOWN_TYPE)
    return G04Out(readme_file=ref, check=readme_check(text, inp.prototype.kind))


__all__ = ["MARKDOWN_TYPE", "PROTOTYPE_NOTICE", "README_FILE", "build_readme", "readme_check", "run"]
