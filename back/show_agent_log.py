"""project_id의 agent_executions 로그(관리자 대시보드 "에이전트 테스크" 탭 대응)를
터미널에 표로 보여준다. seed_dummy_pipeline.py를 돌린 뒤 14단계(+재시도) 로그가
실제로 잘 쌓였는지 확인할 때 쓴다. 아직 이 로그를 보여주는 API가 없어서(관리자
라우터 미구현) DB를 직접 조회한다.

project_id를 생략하면 가장 최근에 매칭이 생긴 프로젝트를 보여준다.

실행:
    python show_agent_log.py 3
    python show_agent_log.py       # 가장 최근 프로젝트
"""
import argparse
import os
import sys

# 이 스크립트는 repo 루트(back/, app/ 패키지가 바로 옆에 있는 위치)에서
# `python show_agent_log.py [project_id]`로 실행하는 걸 전제로 한다.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

from app.database import SessionLocal  # noqa: E402
from app.models import AgentExecution, MatchResult  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project_id', type=int, nargs='?', default=None, help='생략하면 가장 최근 프로젝트')
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = db.query(MatchResult).order_by(MatchResult.match_id.desc())
        if args.project_id is not None:
            query = query.filter(MatchResult.project_id == args.project_id)
        match = query.first()

        if match is None:
            if args.project_id is not None:
                print(f'project_id={args.project_id}에 매칭 결과가 없다 — seed_dummy_pipeline.py를 먼저 돌렸는지 확인.', file=sys.stderr)
            else:
                print('match_results가 비어 있다 — seed_dummy_pipeline.py를 먼저 돌렸는지 확인.', file=sys.stderr)
            raise SystemExit(1)

        execs = (
            db.query(AgentExecution)
            .filter(AgentExecution.match_id == match.match_id)
            .order_by(AgentExecution.execution_id)
            .all()
        )

        print(f'project_id={match.project_id}  match_id={match.match_id}  '
              f'status={match.status}  stage={match.stage}')
        print()
        if not execs:
            print('agent_executions에 로그가 없다 — seed_dummy_pipeline.py를 --no-agent-log 없이 돌렸는지 확인.')
            return

        print(f'agent_executions 로그 ({len(execs)}건):')
        print(f'  {"task_key":<24} {"agent_name":<8} {"attempt":<8} {"status":<8} {"model_used":<14} {"token":<6} started_at')
        print(f'  {"-"*24} {"-"*8} {"-"*8} {"-"*8} {"-"*14} {"-"*6} {"-"*19}')
        for e in execs:
            task_key = e.task_key or '(없음)'
            print(f'  {task_key:<24} {e.agent_name:<8} {e.attempt_no:<8} {e.status:<8} '
                  f'{e.model_used:<14} {e.token_usage:<6} {e.started_at}')
    finally:
        db.close()


if __name__ == '__main__':
    main()