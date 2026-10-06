"""산출물 파일(구현 Agent가 만든 프로토타입 · 인포그래픽) 저장 위치와 경로 안전 검사 (SB-291).

합의(구현 Agent 답변 2026-10-06):
- 저장 폴더는 워커와 웹이 함께 보는 한 폴더(기본 uploads/artifacts, 환경변수 ARTIFACT_DIR로 바꾼다)
- 구조는 `<저장 폴더>/<project_id>/<시도 ID>/<파일>` — 시도 ID는 구현 Agent가 호출마다 새로 만드는 무작위 값이고, 재작성도 항상 새 시도 폴더에 쓴다
- 파일 이름은 index.html(웹개발 실행 파일) · infographic.svg(웹개발 인포그래픽) · onepage.svg(원페이지 — 프로토타입 본체이자 인포그래픽) 셋뿐이다
- 웹이 내려 주고(로그인한 소유자만, 관리자 제외 — 기획서 6-7), 프로젝트 완전 삭제 · 탈퇴 때 프로젝트 폴더를 지운다

웹은 이 세 이름과 위 구조의 파일만 연다. 사용자가 보낸 값(project_id · 시도 ID · 파일 이름)으로 파일 시스템 경로를 만들기 때문에
여기서 한 번 더 막는다: 허용 이름 · 시도 ID 모양 · 저장 폴더 밖으로 나가는 경로(.. · 심볼릭 링크).
"""
import os
import re
from pathlib import Path

from app.routers import projects

# 파일 이름 → 응답 Content-Type. 이 밖의 이름은 열지 않는다.
ARTIFACT_MEDIA_TYPES = {
    'index.html': 'text/html; charset=utf-8',
    'infographic.svg': 'image/svg+xml',
    'onepage.svg': 'image/svg+xml',
}

# 시도 ID — 구현 Agent는 32자리 16진수를 쓰지만 형식에 기대지 않고 안전한 글자만 받는다(경로 구분자 · 점 불가).
ATTEMPT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# 저장 폴더. 테스트와 배포에서 바꿀 수 있게 호출할 때마다 읽는다(모듈 값 · 환경변수 순).
ARTIFACT_DIR = os.environ.get('ARTIFACT_DIR') or os.path.join(projects.UPLOAD_DIR, 'artifacts')


def artifact_root() -> Path:
    return Path(ARTIFACT_DIR).resolve()


def project_dir(project_id: int) -> Path:
    """그 프로젝트의 산출물 폴더(없을 수 있다). 삭제 · 청소도 이 경로를 쓴다."""
    return artifact_root() / str(int(project_id))


def artifact_file(project_id: int, attempt_id: str, filename: str) -> Path | None:
    """내려 줄 수 있는 파일의 실제 경로, 아니면 None.

    None이 되는 경우: 허용 이름이 아님 · 시도 ID 모양이 아님 · 파일이 없음 · 프로젝트 폴더 밖을 가리킴(심볼릭 링크 포함) · 일반 파일이 아님."""
    if filename not in ARTIFACT_MEDIA_TYPES or not ATTEMPT_ID_RE.match(attempt_id):
        return None
    base = project_dir(project_id)
    path = (base / attempt_id / filename).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return None
    return path
