"""v1.10 기획서 6-7절 데이터 보관 정책 대응 — "실행 로그(점수 이력, Task 상태, 시도
횟수, 재시도·재개 기록, 오류 종류)"는 "실행 중" 동안 보관하다가, 완료 후 12개월이
지나면 "식별자를 분리해 통계로만 보존"하도록 되어 있다.

agent_executions 한 행이 어떤 프로젝트/계정 것인지 식별 가능한 건 match_id(및 그 안에
자유 텍스트가 들어가는 error_reason, 산출물 원본 행을 가리키는 output_ref)뿐이다.
task_key/agent_name/attempt_no/rerun_type/model_used/token_usage/status/error_kind는
전부 범주형·통계용 값이라 식별자가 아니다 — 그래서 이 스크립트는 오래된 행에서
match_id/error_reason/output_ref 세 개만 NULL로 비우고 나머지는 그대로 남긴다(통계
집계는 계속 가능, 어느 프로젝트/계정 것이었는지는 더 이상 복원 불가).

주의: "점수 이력"(fit_score, match_score_reasons)은 match_results 쪽에 있는데,
projects/match_results 테이블 통합 작업이 진행 중이라 이번 스크립트 범위에서는 뺐다 —
통합이 끝나면 같은 방식(오래된 행의 fit_score/reason 등을 분리)으로 확장해야 한다.

이 프로젝트엔 별도 스케줄러(celery/APScheduler 등)가 없어서, catch_up_local_schema.sql
과 마찬가지로 필요할 때 사람이 직접 돌리거나 OS 스케줄러(cron/작업 스케줄러)에 등록해서
쓰는 걸 전제로 한다. 티켓 없음, 안 급함(2026-09-28 기준) — 공유 DB에 바로 --apply로
돌리지 말고 먼저 --dry-run 결과를 같이 확인한 뒤 실행할 것.

실행:
    python anonymize_execution_logs.py              # dry-run, 대상 건수만 보여줌
    python anonymize_execution_logs.py --apply       # 실제로 NULL 처리
    python anonymize_execution_logs.py --months 6    # 보관 기간을 바꿔서 확인하고 싶을 때
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 콘솔 기본 코드페이지(cp949)로는 em-dash 등 일부 문자를 못 찍어서 죽는다 —
# 콘솔 출력을 UTF-8로 강제한다.
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

os.environ.setdefault('DB_BACKEND', 'sqlite')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'ci-dummy-client-id')
os.environ.setdefault('JWT_SECRET', 'ci-dummy-secret-not-for-production')

from app.database import SessionLocal  # noqa: E402
from app.models import AgentExecution  # noqa: E402

DAYS_PER_MONTH = 30  # 달력 월 경계가 아니라 근사치 — 이 정책은 "약 12개월" 수준의 정밀도면 충분


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--months', type=int, default=12, help='보관 기간(개월). 기본 12 — v1.10 6-7절 기준')
    parser.add_argument('--apply', action='store_true', help='지정하지 않으면 대상 건수만 보여주고 아무것도 바꾸지 않는다(dry-run)')
    args = parser.parse_args()

    cutoff = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(days=args.months * DAYS_PER_MONTH)

    db = SessionLocal()
    try:
        query = db.query(AgentExecution).filter(
            AgentExecution.started_at < cutoff,
            AgentExecution.match_id.isnot(None),
        )
        targets = query.all()

        if not targets:
            print(f'{cutoff.isoformat()} 이전 실행 로그 중 아직 식별자가 남아있는 행이 없다.')
            return

        print(f'{cutoff.isoformat()} 이전, 식별자(match_id)가 아직 남아있는 실행 로그: {len(targets)}건')
        if not args.apply:
            print('dry-run — 아무것도 바꾸지 않았다. 실제로 처리하려면 --apply를 붙여서 다시 실행할 것.')
            return

        for row in targets:
            row.match_id = None
            row.error_reason = None
            row.output_ref = None
        db.commit()
        print(f'{len(targets)}건에서 match_id/error_reason/output_ref를 비웠다(task_key/status/error_kind/시도 횟수 등 통계용 값은 유지).')
    finally:
        db.close()


if __name__ == '__main__':
    main()
