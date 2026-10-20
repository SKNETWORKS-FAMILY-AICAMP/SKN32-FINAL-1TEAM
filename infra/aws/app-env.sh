#!/usr/bin/env bash
# shellcheck disable=SC2154  # OUT_* 변수는 load_outputs 가 printf -v 로 채운다
# S-Brain 앱 설정 넣기 — 비밀 값을 AWS SSM Parameter Store 에 두고, 웹 서버에 env 파일 둘을 만든다
#
#   bash infra/aws/app-env.sh                          # 빠진 값만 묻고, 웹 서버의 env 파일을 다시 만든다
#   bash infra/aws/app-env.sh --reset OPENAI_API_KEY   # 그 값을 다시 넣는다(여러 번 줄 수 있다)
#   bash infra/aws/app-env.sh --remove                 # 넣어 둔 값을 모두 지운다(down.sh 는 이 값을 지우지 않는다)
#   공통 옵션: --profile 이름 · --region 리전 · --stack 이름 · --yes (up.sh 와 같다)
#
# 넣는 값 — SSM Parameter Store, SecureString(기본 키 aws/ssm), 이름 /<스택>/app/<이름>
#   OPENAI_API_KEY         워커                — 필수
#   GOOGLE_CLIENT_ID       웹 백엔드 · 프론트 빌드 — 필수
#   JWT_SECRET             웹 백엔드            — 필수. 비워 두고 Enter 를 누르면 무작위 값을 만든다
#   NTS_SERVICE_KEY        웹 백엔드            — 선택(국세청 사업자 조회 — 디코딩 키). 없으면 그 기능만 꺼진다
#   SBRAIN_NOTICE_API_URL  워커                — 선택(공고 서버 주소 http://<내부 주소>:8000). 없으면 공고 매칭 · 자격 확인이 스텁
# 웹 서버에 쓰는 파일(root 만 읽음): /etc/sbrain/worker.env · /etc/sbrain/web.env — infra/aws/app/write-app-env.sh 가 만든다.
# 값은 화면 · 명령줄 · 원격 실행 기록에 나오지 않는다(입력할 때도 보이지 않는다). AWS 키는 넣지 않는다 — 서버는 IAM 역할로 읽는다.
#
# 먼저: up.sh 를 이 스택에 한 번 이상 실행해 둔다(서버 · /etc/sbrain/db.env · 이 값을 읽는 서버 권한).
set -euo pipefail
# shellcheck source=infra/aws/lib-app.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-app.sh"

usage() {
  cat <<'EOF'
사용법: bash infra/aws/app-env.sh [옵션]
  --reset 이름     그 값을 다시 넣는다 (OPENAI_API_KEY · GOOGLE_CLIENT_ID · JWT_SECRET · NTS_SERVICE_KEY · SBRAIN_NOTICE_API_URL)
  --remove         넣어 둔 값을 모두 지운다 (웹 서버의 env 파일은 그대로 둔다)
  --profile 이름   다른 AWS 계정(프로필)
  --region 리전    리전 (기본: settings.env 의 REGION)
  --stack 이름     스택 이름 (기본: sbrain)
  --yes            확인 질문 없이 진행 (값 입력은 그래도 묻는다)
EOF
}

NAMES="OPENAI_API_KEY GOOGLE_CLIENT_ID JWT_SECRET NTS_SERVICE_KEY SBRAIN_NOTICE_API_URL"
REQUIRED="OPENAI_API_KEY GOOGLE_CLIENT_ID JWT_SECRET"
is_word_in() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

parse_common_args "$@"
RESETS=""
REMOVE=0
set -- ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
while [ $# -gt 0 ]; do
  case "$1" in
    --reset)
      [ $# -ge 2 ] || die "--reset 뒤에 이름을 적으세요."
      is_word_in "$2" "$NAMES" || die "모르는 이름입니다: $2 (쓸 수 있는 이름: $NAMES)"
      RESETS="$RESETS $2"
      shift 2 ;;
    --remove) REMOVE=1; shift ;;
    *) usage >&2; die "모르는 옵션: $1" ;;
  esac
done

load_settings
require_cli
PREFIX="/$STACK_NAME/app"
mkdir -p "$BUILD_DIR"
PARAM_FILE="$BUILD_DIR/app-param.json"
trap 'rm -f "$PARAM_FILE"' EXIT

step "1/3 어느 계정의 값을 다루는지 확인"
show_identity
echo "  값 이름    : $PREFIX/<이름>"

EXISTING="$(awsq ssm get-parameters-by-path --path "$PREFIX" --query 'Parameters[].Name' | tr '\t' '\n' | sed -e '/^$/d' -e '/^None$/d')" \
  || die "Parameter Store 를 읽지 못했습니다. 로그인 정보 · 권한을 확인하세요."
has_param() { printf '%s\n' "$EXISTING" | grep -qx "$PREFIX/$1"; }

if [ "$REMOVE" = 1 ]; then
  [ -n "$EXISTING" ] || { echo "  지울 값이 없습니다."; exit 0; }
  printf '  지울 값: %s\n' $EXISTING
  confirm "이 값들을 지울까요? (되돌릴 수 없습니다)"
  # shellcheck disable=SC2086  # 이름마다 따로 넘긴다
  awsq ssm delete-parameters --names $EXISTING --query 'DeletedParameters' >/dev/null || die "값을 지우지 못했습니다."
  echo "  지웠습니다. 웹 서버의 /etc/sbrain/*.env 는 그대로 남아 있습니다(서버를 지우면 함께 사라진다)."
  exit 0
fi
confirm "이 계정 · 스택의 앱 설정을 넣고 웹 서버에 env 파일을 만들까요?"

# 값을 JSON 파일로 넘긴다 — 명령줄(프로세스 목록)에 값이 드러나지 않게
put_param() {
  local name="$1" value="$2"
  ( umask 077
    printf '{"Name":"%s","Value":"%s","Type":"SecureString","Overwrite":true}\n' "$PREFIX/$name" "$value" > "$PARAM_FILE" )
  awsq ssm put-parameter --cli-input-json "file://$PARAM_FILE" --query Version >/dev/null \
    || { rm -f "$PARAM_FILE"; die "$name 을 넣지 못했습니다."; }
  rm -f "$PARAM_FILE"
}

random_secret() { head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

step "2/3 값 넣기 (입력하는 글자는 화면에 보이지 않습니다)"
for name in $NAMES; do
  if has_param "$name" && ! is_word_in "$name" "$RESETS"; then
    echo "  $name: 이미 있음(그대로 둠 — 바꾸려면 --reset $name)"
    continue
  fi
  value=""
  read -r -s -p "  $name 값: " value || true
  echo
  value="$(printf '%s' "$value" | tr -d '\r')"
  if [ -z "$value" ]; then
    if [ "$name" = JWT_SECRET ]; then
      value="$(random_secret)"
      echo "  $name: 무작위 값을 만들었습니다."
    elif is_word_in "$name" "$REQUIRED"; then
      die "$name 은 필수입니다."
    else
      echo "  $name: 넣지 않음(그 기능만 꺼집니다)"
      continue
    fi
  fi
  # 서버의 env 파일(systemd)이 따로 풀어 읽는 글자(따옴표 · 빈칸 · 역슬래시 등)는 받지 않는다
  [[ "$value" =~ ^[A-Za-z0-9._~:/?#@!+=,%-]+$ ]] || die "$name 값에 쓸 수 없는 글자(따옴표 · 빈칸 · 역슬래시 등)가 있습니다."
  put_param "$name" "$value"
  echo "  $name: 넣었습니다."
done
value=""

step "3/3 웹 서버에 env 파일 만들기"
load_app_outputs
TOOL="$BUILD_DIR/write-app-env.sh"
tr -d '\r' < "$REL/app/write-app-env.sh" > "$TOOL"
aws s3 cp "$TOOL" "s3://$OUT_DeployBucketName/deploy/tools/write-app-env.sh" --only-show-errors \
  || die "서버 스크립트를 S3 에 올리지 못했습니다."
wait_ssm_online "$OUT_WebInstanceId" "웹 서버"
# shellcheck disable=SC2016  # $PATH 는 서버에서 풀린다
cmd='export PATH=$PATH:/snap/bin; '
cmd+="mkdir -p /opt/sbrain/tools && aws s3 cp s3://$OUT_DeployBucketName/deploy/tools/write-app-env.sh /opt/sbrain/tools/write-app-env.sh --only-show-errors --region $REGION"
cmd+=" && bash /opt/sbrain/tools/write-app-env.sh --region $REGION --stack $STACK_NAME --bucket $OUT_DeployBucketName"
if ! remote_run "$OUT_WebInstanceId" app-env "웹 서버" 1200 "$cmd"; then
  explain_app_error "웹 서버"
  case "$REMOTE_OUT$REMOTE_ERR" in
    *AccessDenied*|*"403"*|*Forbidden*)
      echo "  → 서버 권한이 아직 없습니다. 템플릿의 WebAppPolicy 를 반영하려면 'bash infra/aws/up.sh' 를 다시 실행하세요." >&2 ;;
    *db_env_missing*)
      echo "  → /etc/sbrain/db.env 가 없습니다. 'bash infra/aws/up.sh' 로 DB 세팅을 먼저 하세요." >&2 ;;
  esac
  die "웹 서버에 env 파일을 만들지 못했습니다 (상태: $REMOTE_STATUS)."
fi
report_app_remote "웹 서버"
echo
echo "다음: 'bash infra/aws/deploy-app.sh' 로 앱을 올립니다. 이미 떠 있던 앱은 새 값으로 다시 띄웠습니다."
