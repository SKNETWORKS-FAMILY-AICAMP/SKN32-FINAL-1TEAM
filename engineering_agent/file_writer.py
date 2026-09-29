"""LLM 코드블록을 파싱하고 변경 불가능한 시도별 경로에 저장한다."""
import re
from pathlib import Path

# builder_html._ENTRY_FILENAME과 같은 값. 저장 화이트리스트를 여기에 두는 이유는
# LLM이 지어낸 다른 파일명이 디스크에 닿지 않게 막는 것이 이 모듈의 몫이기 때문이다.
_ENTRY_FILENAME = "index.html"

# ```lang:filename\n(내용)\n``` 형식. lang 토큰은 html/markdown/js 등 임의 문자열이고,
# 실제로 파일을 가리키는 건 콜론 뒤 filename뿐이라 lang 값 자체는 파싱에 쓰지 않는다.
_CODE_BLOCK_RE = re.compile(
    r'```[ \t]*[\w.+-]*:([^\n`]+)\n(.*?)```',
    re.DOTALL,
)


def parse_code_blocks(llm_output: str) -> dict[str, str]:
    """```lang:filename 코드블록들을 {파일명: 내용} dict로 추출한다."""
    files: dict[str, str] = {}
    for match in _CODE_BLOCK_RE.finditer(llm_output):
        filename = match.group(1).strip()
        content = match.group(2)
        # 닫는 ``` 바로 앞 줄바꿈 하나는 마크다운 포맷용이라 파일 내용에서는 제거한다.
        if content.endswith('\n'):
            content = content[:-1]
        files[filename] = content
    return files


def save_files(files: dict[str, str], run_id: str, output_root: Path | None = None) -> dict[str, str]:
    """기존 시도 파일을 덮어쓰지 않고 허용된 산출물만 저장한다."""
    base = output_root if output_root is not None else Path(__file__).parent / "output"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("시도 ID는 영문/숫자/_/-만 허용합니다")
    run_dir = base / run_id
    if not files or set(files) != {_ENTRY_FILENAME}:
        raise ValueError(f"{_ENTRY_FILENAME} 한 파일만 저장할 수 있습니다")
    run_dir.mkdir(parents=True, exist_ok=False)

    saved: dict[str, str] = {}
    for filename, content in files.items():
        file_path = run_dir / filename
        with file_path.open("x", encoding="utf-8") as target:
            target.write(content)
        saved[filename] = str(file_path.resolve())
    return saved
