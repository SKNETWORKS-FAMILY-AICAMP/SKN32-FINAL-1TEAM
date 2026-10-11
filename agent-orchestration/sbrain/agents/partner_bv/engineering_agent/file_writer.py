"""LLM 코드블록을 파싱하고 변경 불가능한 시도별 경로에 저장한다.

[S-Brain] 코드블록 꺼내기(parse_code_blocks)만 남겼다. 저장 함수 save_files · 저장 화이트리스트 _ENTRY_FILENAME ·
pathlib import를 지웠다 — 파일은 연결 코드가 tools.files.put으로 넣는다(VENDORED.md).
"""
import re

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


# [S-Brain] save_files(시도 폴더 만들기 · 파일 쓰기) 삭제 — 연결 코드가 tools.files.put으로 넣는다
