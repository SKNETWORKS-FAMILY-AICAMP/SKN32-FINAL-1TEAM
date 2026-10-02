#!/usr/bin/env bash
# 매일 수집 배치를 서버에서 돌린다. data-collection/run_daily.bat 의 리눅스판.
# 시작·종료 줄과 출력 전체를 data-collection/data/run.log 에 남긴다(PC 와 같은 파일).
#
#   bash deploy/run_batch.sh                 # 실제 실행
#   bash deploy/run_batch.sh --dry-run       # 인자는 collect.daily_pipeline 에 그대로 넘어간다
#
# 예약(crontab, 서버는 UTC):  0 0 * * *  /home/ubuntu/sbrain/deploy/run_batch.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
LOG="$HERE/../data-collection/data/run.log"
mkdir -p "$(dirname "$LOG")"

stamp() { TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(stamp)] start (server) $*" >> "$LOG"
cd "$HERE"
# < /dev/null: docker 가 표준입력을 읽어 부른 쪽 스크립트의 나머지 줄을 삼키지 않게 한다
docker compose --profile batch run --rm -T batch python -m collect.daily_pipeline "$@" < /dev/null >> "$LOG" 2>&1
code=$?
echo "[$(stamp)] exit=$code" >> "$LOG"

# 0 성공 / 1 실패 / 2 부분 실패 / 3 이미 실행 중 / 4 수집은 성공, 후처리 경고
exit "$code"
