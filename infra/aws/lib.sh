# shellcheck shell=bash
# shellcheck disable=SC2034  # TEMPLATE · BUILD_DIR · OUT_DIR · KEY_FILE 은 up.sh · down.sh 가 쓴다
# up.sh · down.sh 가 함께 쓰는 설정과 도우미. 직접 실행하지 않는다.
#
# 윈도우 Git Bash · macOS · 리눅스 · AWS CloudShell 어디서나 돌도록 쓴다.
# (macOS 기본 bash 3.2 에 없는 문법은 쓰지 않는다)

# Git Bash 는 / 로 시작하는 인자를 C:/Program Files/Git/... 로 바꿔 aws.exe 에 넘긴다.
# /aws/service/..., /ec2/keypair/... 같은 이름이 깨지지 않도록 끈다.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'
# aws CLI 2 가 결과를 less 로 넘겨 멈추지 않게 한다.
export AWS_PAGER=""

AWS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$AWS_DIR/../.." && pwd)"
# aws.exe 에 넘기는 파일 경로는 모두 저장소 루트 기준 상대 경로로 쓴다.
# 윈도우 aws.exe 는 /c/... 같은 Git Bash 경로를 읽지 못한다.
cd "$REPO_ROOT" || exit 1
REL=infra/aws
TEMPLATE="$REL/sbrain-stack.yml"
BUILD_DIR="$REL/.build"

ASSUME_YES=0
STACK_ARG=""
REGION_ARG=""
EXTRA_ARGS=()

die()  { printf '\n[오류] %s\n' "$*" >&2; exit 1; }
warn() { printf '[주의] %s\n' "$*" >&2; }
step() { printf '\n==> %s\n' "$*"; }

# aws 결과를 글자로 받는다. 윈도우 aws.exe 가 줄 끝에 붙이는 \r 을 지운다.
awsq() { aws "$@" --output text | tr -d '\r'; }

# 공통 옵션을 읽고, 나머지는 EXTRA_ARGS 에 담는다. 부르기 전에 usage 를 정의해 둔다.
parse_common_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --profile) [ $# -ge 2 ] || die "--profile 뒤에 프로필 이름을 적으세요."; export AWS_PROFILE="$2"; shift 2 ;;
      --region)  [ $# -ge 2 ] || die "--region 뒤에 리전을 적으세요."; REGION_ARG="$2"; shift 2 ;;
      --stack)   [ $# -ge 2 ] || die "--stack 뒤에 스택 이름을 적으세요."; STACK_ARG="$2"; shift 2 ;;
      -y|--yes)  ASSUME_YES=1; shift ;;
      -h|--help) usage; exit 0 ;;
      *)         EXTRA_ARGS+=("$1"); shift ;;
    esac
  done
}

# settings.env → settings.env.local → 명령 옵션 순으로 덮어쓴다.
load_settings() {
  local f
  for f in "$REL/settings.env" "$REL/settings.env.local"; do
    [ -f "$f" ] || continue
    # 윈도우 줄바꿈(\r)이 값에 섞이지 않게 지우고 읽는다.
    eval "$(tr -d '\r' < "$f")"
  done
  STACK_NAME="${STACK_ARG:-${STACK_NAME:-sbrain}}"
  REGION="${REGION_ARG:-${REGION:-ap-northeast-2}}"
  WEB_INSTANCE_TYPE="${WEB_INSTANCE_TYPE:-c7i-flex.large}"
  NOTICE_INSTANCE_TYPE="${NOTICE_INSTANCE_TYPE:-m7i-flex.large}"
  DB_INSTANCE_CLASS="${DB_INSTANCE_CLASS:-db.t4g.micro}"
  DB_ENGINE_VERSION="${DB_ENGINE_VERSION:-8.4}"
  DB_STORAGE_GB="${DB_STORAGE_GB:-20}"
  DB_NAME="${DB_NAME:-s_brain}"
  NOTICE_PRIVATE_IP="${NOTICE_PRIVATE_IP:-10.20.11.10}"
  ADMIN_CIDR="${ADMIN_CIDR:-}"

  [[ "$STACK_NAME" =~ ^[A-Za-z][A-Za-z0-9-]{0,31}$ ]] \
    || die "스택 이름은 영문으로 시작하고 영문·숫자·- 만 쓸 수 있습니다(32자 이하): $STACK_NAME"
  [[ "$DB_NAME" =~ ^[A-Za-z0-9_]{1,64}$ ]] || die "DB_NAME 은 영문·숫자·_ 만 쓸 수 있습니다: $DB_NAME"

  # 모든 aws 명령이 같은 리전을 쓰게 한다.
  export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
  OUT_DIR="$REL/.out/$STACK_NAME-$REGION"
  KEY_FILE="$HOME/.ssh/$STACK_NAME-$REGION.pem"
}

require_cli() {
  command -v aws >/dev/null 2>&1 \
    || die "AWS CLI 가 없습니다. 설치 안내: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  case "$(aws --version 2>&1)" in
    aws-cli/2.*) ;;
    *) warn "AWS CLI 2 버전을 권장합니다. 지금: $(aws --version 2>&1)" ;;
  esac
}

# 어느 계정·리전에 작업하는지 보여 준다. 다른 계정에 잘못 만드는 일을 막기 위해 늘 먼저 부른다.
show_identity() {
  local ident
  ident="$(awsq sts get-caller-identity --query '[Account,Arn]' 2>/dev/null)" \
    || die "AWS 로그인 정보가 없습니다. 'aws configure' 로 키를 넣거나 --profile 로 프로필을 고르세요."
  ACCOUNT_ID="$(printf '%s' "$ident" | cut -f1)"
  printf '  계정      : %s\n' "$ACCOUNT_ID"
  printf '  로그인    : %s\n' "$(printf '%s' "$ident" | cut -f2)"
  printf '  프로필    : %s\n' "${AWS_PROFILE:-기본값}"
  printf '  리전      : %s\n' "$REGION"
  printf '  스택 이름 : %s\n' "$STACK_NAME"
}

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  local ans=""
  read -r -p "$1 [y/N] " ans || true
  case "$ans" in
    y|Y|yes|YES) ;;
    *) die "취소했습니다." ;;
  esac
}

# 스택 상태. 없으면 빈 글자.
stack_status() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null | tr -d '\r' || true
}

# 스택 결과(Outputs)를 OUT_<이름> 변수에 담는다.
load_outputs() {
  local rows k v
  rows="$(awsq cloudformation describe-stacks --stack-name "$STACK_NAME" \
    --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]')" || return 1
  while IFS=$'\t' read -r k v; do
    if [ -n "$k" ] && [ "$k" != None ]; then
      printf -v "OUT_$k" '%s' "$v"
    fi
  done <<< "$rows"
}

show_failed_events() {
  echo "최근 실패 기록 (AWS 원문):" >&2
  aws cloudformation describe-stack-events --stack-name "$STACK_NAME" \
    --query "StackEvents[?contains(ResourceStatus, 'FAILED')].[LogicalResourceId, ResourceStatusReason] | [0:15]" \
    --output table 2>/dev/null | tr -d '\r' >&2 || true
}
