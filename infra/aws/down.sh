#!/usr/bin/env bash
# S-Brain 원버튼 삭제 — up.sh 가 만든 것을 전부 지운다. 되돌릴 수 없다.
#
#   bash infra/aws/down.sh                  # aws configure 의 기본 계정
#   bash infra/aws/down.sh --profile team   # 다른 계정(프로필)
#
# 지우는 것: VPC · NAT · 고정 IP · EC2 2대(디스크 포함) · RDS · S3 버킷과 안의 파일 · 비밀값 · SSH 키 페어
# 남기는 것: RDS 마지막 스냅샷(데이터 보관용, 끝에 이름과 지우는 명령을 알려 줌), 이 PC 의 SSH 키 파일
set -euo pipefail
# shellcheck source=infra/aws/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

usage() {
  cat <<'EOF'
사용법: bash infra/aws/down.sh [옵션]
  --profile 이름   다른 AWS 계정의 스택을 지울 때
  --region 리전    리전 (기본: settings.env 의 REGION)
  --stack 이름     스택 이름 (기본: sbrain)
  --yes            스택 이름 입력 확인 없이 바로 지운다
EOF
}

parse_common_args "$@"
[ ${#EXTRA_ARGS[@]} -eq 0 ] || { usage >&2; die "모르는 옵션: ${EXTRA_ARGS[0]}"; }
load_settings
require_cli

step "1/3 어느 계정에서 지우는지 확인"
show_identity
STATUS="$(stack_status)"
if [ -z "$STATUS" ]; then
  echo "  → 이 계정·리전에 '$STACK_NAME' 스택이 없습니다. 지울 것이 없습니다."
  exit 0
fi
case "$STATUS" in
  DELETE_IN_PROGRESS) echo "  → 이미 지우는 중입니다. 끝날 때까지 기다립니다." ;;
  *_IN_PROGRESS)      die "스택에 다른 작업이 진행 중입니다($STATUS). 끝난 뒤 다시 실행하세요." ;;
  *)                  echo "  → 상태: $STATUS" ;;
esac

load_outputs || true
BUCKET="${OUT_DeployBucketName:-}"
DB_ID="$(awsq cloudformation describe-stack-resources --stack-name "$STACK_NAME" --logical-resource-id DbInstance \
  --query 'StackResources[0].PhysicalResourceId' 2>/dev/null || true)"
[ "$DB_ID" = None ] && DB_ID=""

echo
echo "  지울 것: VPC · NAT · 고정 IP · EC2 2대(디스크 포함) · RDS · S3 버킷과 안의 파일 · 비밀값 · SSH 키 페어"
echo "  남는 것: RDS 마지막 스냅샷(데이터 보관용)"
if [ "$ASSUME_YES" != 1 ] && [ "$STATUS" != DELETE_IN_PROGRESS ]; then
  ans=""
  read -r -p "  정말 지우려면 스택 이름($STACK_NAME)을 그대로 입력하세요: " ans || true
  [ "$ans" = "$STACK_NAME" ] || die "입력이 달라 취소했습니다."
fi

step "2/3 지우기 — RDS 때문에 10~20분 걸립니다"
if [ "$STATUS" != DELETE_IN_PROGRESS ]; then
  # 파일이 남은 버킷은 AWS 가 지우지 못한다. 먼저 비운다.
  if [ -n "$BUCKET" ] && aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
    echo "  S3 버킷 비우는 중: $BUCKET"
    aws s3 rm "s3://$BUCKET" --recursive --only-show-errors
  fi
  aws cloudformation delete-stack --stack-name "$STACK_NAME"
fi
if ! aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"; then
  show_failed_events
  die "지우기가 끝나지 않았습니다. 위 원인을 확인한 뒤 down.sh 를 다시 실행하세요."
fi
rm -rf "$REL/.out/$STACK_NAME-$REGION"
echo "  → 스택을 모두 지웠습니다."

step "3/3 남은 것"
if [ -n "$DB_ID" ]; then
  SNAPS="$(awsq rds describe-db-snapshots --db-instance-identifier "$DB_ID" --snapshot-type manual \
    --query 'DBSnapshots[].DBSnapshotIdentifier' 2>/dev/null | tr '\t' '\n' | sed -e '/^$/d' -e '/^None$/d' || true)"
  if [ -n "$SNAPS" ]; then
    echo "  RDS 마지막 스냅샷 (보관 요금이 조금 나갑니다. 필요 없으면 아래 명령으로 지우세요):"
    for s in $SNAPS; do
      echo "    aws rds delete-db-snapshot --region $REGION --db-snapshot-identifier $s"
    done
  fi
fi
[ -f "$KEY_FILE" ] && echo "  이 PC 의 SSH 키 파일: $KEY_FILE (이제 쓸 곳이 없으니 지워도 됩니다)"
echo "  끝."
