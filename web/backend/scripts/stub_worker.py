"""전략 · 작성 · 검증-1을 스텁으로 둔 워커 — 따로 띄운 워커가 필요한 E2E(e2e_worker_flow · e2e_concurrent_abort · e2e_business_applicant)를
실제 OpenAI 호출 없이 돌릴 때 `python -m sbrain.worker` 대신 쓴다 (SB-343).

    $env:SBRAIN_DB_URL = '<로컬 e2e DB URL>'; $env:SBRAIN_ARTIFACT_ROOT = '<절대 경로 폴더>'; python scripts/stub_worker.py

조율 T-C1 · T-C3는 그대로 실제 LLM이라 agent-orchestration/.env의 OPENAI_API_KEY가 필요하다(호출 몇 번). 나머지는 sbrain.worker와 같다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_worker_flow import use_stub_partner_agents  # noqa: E402

use_stub_partner_agents()

from sbrain.worker import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
