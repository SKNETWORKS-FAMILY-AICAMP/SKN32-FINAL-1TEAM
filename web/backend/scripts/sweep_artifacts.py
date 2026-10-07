"""주인 없는 산출물 폴더(고아) 청소 (SB-294).

    python scripts/sweep_artifacts.py --dry-run          # 지울 폴더만 보여 준다
    python scripts/sweep_artifacts.py                    # 지운다
    python scripts/sweep_artifacts.py --min-age-hours 24

프로젝트 완전 삭제 · 탈퇴는 웹 행을 지운 뒤 산출물 폴더를 지우지만, 그 단계가 실패하면(파일 잠김 · 권한 등) 폴더가 남는다.
저장 폴더(`ARTIFACT_DIR`, 기본 uploads/artifacts) 바로 아래의 `<project_id>/` 폴더 가운데 projects 표에 없는 번호를 지운다.
- 이름이 숫자가 아닌 폴더 · 파일은 건드리지 않는다.
- 보관(휴지통) 프로젝트는 행이 남아 있으므로 지우지 않는다.
- `--min-age-hours`(기본 1)보다 최근에 바뀐 폴더는 남긴다 — 방금 쓰기 시작한 폴더를 지나치게 서두르지 않기 위한 여유다.
웹과 같은 DB · 같은 ARTIFACT_DIR 환경 변수로 돌린다(다른 DB로 돌리면 정상 폴더가 고아로 보인다). 주기 실행(cron 등)은 운영에서 정한다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(errors='replace')

from app import artifact_store  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Project  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dry-run', action='store_true', help='지우지 않고 대상만 보여 준다')
    parser.add_argument('--min-age-hours', type=float, default=1.0, help='이보다 최근에 바뀐 폴더는 남긴다(기본 1)')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        live = {pid for (pid,) in db.query(Project.project_id)}
    finally:
        db.close()
    swept = artifact_store.sweep_orphans(live, min_age_seconds=args.min_age_hours * 3600, dry_run=args.dry_run)
    verb = '지울 폴더' if args.dry_run else '지운 폴더'
    print(f'저장 폴더: {artifact_store.artifact_root()}')
    print(f'{verb}: {len(swept)}개' + (f' — project_id {", ".join(map(str, swept))}' if swept else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
