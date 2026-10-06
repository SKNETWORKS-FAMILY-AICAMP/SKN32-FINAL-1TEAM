"""산출물 파일(구현 Agent가 만든 프로토타입 · 인포그래픽) 저장 위치와 경로 안전 검사 (SB-291).

합의(구현 Agent 답변 2026-10-06):
- 저장 폴더는 워커와 웹이 함께 보는 한 폴더(기본 uploads/artifacts, 환경변수 ARTIFACT_DIR로 바꾼다)
- 구조는 `<저장 폴더>/<project_id>/<시도 ID>/<파일>` — 시도 ID는 구현 Agent가 호출마다 새로 만드는 무작위 값이고, 재작성도 항상 새 시도 폴더에 쓴다
- 파일 이름은 index.html(웹개발 실행 파일) · infographic.svg(웹개발 인포그래픽) · onepage.svg(원페이지 — 프로토타입 본체이자 인포그래픽) 셋뿐이다
- 웹이 내려 주고(로그인한 소유자만, 관리자 제외 — 기획서 6-7), 프로젝트 완전 삭제 · 탈퇴 때 프로젝트 폴더를 지운다

웹은 이 세 이름과 위 구조의 파일만 연다. 사용자가 보낸 값(project_id · 시도 ID · 파일 이름)으로 파일 시스템 경로를 만들기 때문에
여기서 한 번 더 막는다: 허용 이름 · 시도 ID 모양 · 저장 폴더 밖으로 나가는 경로(.. · 심볼릭 링크).
"""
import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# projects.py의 UPLOAD_DIR과 같은 계산(app/ 의 위 폴더/uploads) — projects를 가져오면 mapping과 순환하므로 여기서 직접 잡는다.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 파일 이름 → 응답 Content-Type. 이 밖의 이름은 열지 않는다.
ARTIFACT_MEDIA_TYPES = {
    'index.html': 'text/html; charset=utf-8',
    'infographic.svg': 'image/svg+xml',
    'onepage.svg': 'image/svg+xml',
}

# 시도 ID — 구현 Agent는 32자리 16진수를 쓰지만 형식에 기대지 않고 안전한 글자만 받는다(경로 구분자 · 점 불가).
ATTEMPT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

# 저장 폴더. 테스트와 배포에서 바꿀 수 있게 호출할 때마다 읽는다(모듈 값 · 환경변수 순).
ARTIFACT_DIR = os.environ.get('ARTIFACT_DIR') or os.path.join(_BACKEND_ROOT, 'uploads', 'artifacts')


def artifact_root() -> Path:
    return Path(ARTIFACT_DIR).resolve()


def project_dir(project_id: int) -> Path:
    """그 프로젝트의 산출물 폴더(없을 수 있다). 삭제 · 청소도 이 경로를 쓴다."""
    return artifact_root() / str(int(project_id))


def artifact_url(project_id: int, path: str | None) -> str | None:
    """오케스트레이터가 준 산출물 경로 → 웹 주소 `/projects/{project_id}/artifact-files/{시도 ID}/{파일}` (SB-293).

    합의된 상대 경로 `<project_id>/<시도 ID>/<파일>`(저장 폴더 기준)을 바꾼다. 저장 폴더 안을 가리키는 절대 경로도 같은 방식으로 바꾼다
    (조율이 저장 폴더를 넘기기 전에 구현 Agent가 절대 경로로 쓰는 경우를 위해).
    이 프로젝트의 산출물 모양이 아니면(옛 값 · 다른 프로젝트 · 허용 이름이 아님 · `..` 포함 · 이미 주소) 값을 그대로 돌려준다 — 화면이 깨지지 않게 하되
    웹이 내려 줄 수 없는 경로를 주소로 꾸며 내지 않는다."""
    if not path:
        return path
    text = str(path).replace('\\', '/')
    if os.path.isabs(path) or re.match(r'^[A-Za-z]:/', text):
        try:
            parts = Path(os.path.abspath(path)).relative_to(artifact_root()).parts
        except ValueError:
            return path
    else:
        parts = tuple(p for p in text.split('/') if p not in ('', '.'))
    if len(parts) != 3:
        return path
    pid, attempt_id, filename = parts
    if pid != str(project_id) or filename not in ARTIFACT_MEDIA_TYPES or not ATTEMPT_ID_RE.match(attempt_id):
        return path
    return f'/projects/{int(project_id)}/artifact-files/{attempt_id}/{filename}'


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


# ── 삭제 (SB-294) ─────────────────────────────────────────────────────────────────────
def _remove_tree(path: Path) -> None:
    """폴더 하나를 지운다. 링크(심볼릭 링크 · 정션)는 가리키는 쪽을 건드리지 않고 링크만 뗀다."""
    if path.is_symlink():
        path.unlink()
    elif os.path.isjunction(path):
        os.rmdir(path)
    else:
        shutil.rmtree(path, onexc=_unlink_links)


def _unlink_links(_func, path, exc) -> None:
    """rmtree가 안쪽 정션 앞에서 막히면 링크만 떼고 이어 간다(바깥 파일은 건드리지 않는다). 그 밖의 실패는 그대로 올린다."""
    if os.path.isjunction(path):
        os.rmdir(path)
        return
    raise exc


def delete_project_artifacts(project_id: int) -> bool:
    """그 프로젝트의 산출물 폴더(모든 시도 포함)를 지운다. 지웠으면 True, 폴더가 없거나 지우지 못했으면 False.

    프로젝트 · 계정을 지운 뒤에 부르는 정리 단계라 실패해도 예외를 올리지 않는다 — 남은 폴더는 고아 청소(sweep_orphans)가 치운다."""
    base = project_dir(project_id)
    if not os.path.lexists(base):
        return False
    try:
        _remove_tree(base)
    except OSError:
        logger.warning('산출물 폴더를 지우지 못했습니다: project_id=%s', project_id, exc_info=True)
        return False
    return True


def delete_projects_artifacts(project_ids) -> int:
    """여러 프로젝트의 산출물 폴더를 지운다(탈퇴). 지운 폴더 수."""
    return sum(1 for pid in project_ids if delete_project_artifacts(pid))


def orphan_project_dirs(live_project_ids, min_age_seconds: float = 3600.0) -> list[Path]:
    """저장 폴더 바로 아래에서 주인(프로젝트 행)이 없는 프로젝트 폴더들.

    폴더 이름이 숫자인 것만 본다(다른 이름은 우리 것이 아니라 건드리지 않는다). min_age_seconds보다 최근에 바뀐 폴더는 남긴다 —
    워커가 방금 쓰기 시작했거나, 다른 환경이 같은 저장 폴더를 쓰는 경우를 지나치게 서두르지 않기 위한 여유다."""
    root = artifact_root()
    if not root.is_dir():
        return []
    live = {int(p) for p in live_project_ids}
    now = time.time()
    orphans = []
    for entry in sorted(root.iterdir()):
        if not entry.name.isdigit() or int(entry.name) in live:
            continue
        if not (entry.is_dir() or entry.is_symlink()):
            continue
        if min_age_seconds > 0 and now - entry.lstat().st_mtime < min_age_seconds:
            continue
        orphans.append(entry)
    return orphans


def sweep_orphans(live_project_ids, min_age_seconds: float = 3600.0, dry_run: bool = False) -> list[int]:
    """주인 없는 프로젝트 폴더를 지운다. 지운(dry_run이면 지울) 프로젝트 번호를 돌려준다."""
    swept = []
    for entry in orphan_project_dirs(live_project_ids, min_age_seconds):
        if not dry_run and not delete_project_artifacts(int(entry.name)):
            continue
        swept.append(int(entry.name))
    return swept
