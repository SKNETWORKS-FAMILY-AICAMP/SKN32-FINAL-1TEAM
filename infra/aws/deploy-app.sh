#!/usr/bin/env bash
# shellcheck disable=SC2154  # OUT_* 변수는 load_outputs 가 printf -v 로 채운다
# S-Brain 앱 올리기 — 이 저장소의 커밋 하나를 웹 서버에 설치하고 워커 · 웹을 다시 띄운다
#
#   bash infra/aws/deploy-app.sh                 # 지금 갈래의 마지막 커밋(HEAD)을 올린다
#   bash infra/aws/deploy-app.sh --ref <커밋>     # 다른 커밋 · 갈래 · 태그를 올린다
#   공통 옵션: --profile 이름 · --region 리전 · --stack 이름 · --yes (up.sh 와 같다)
#
# 먼저(한 번씩): bash infra/aws/up.sh → bash infra/aws/app-env.sh
# 올리는 것: 그 커밋의 agent-orchestration/ · web/ · infra/aws/app/ (git archive — 커밋 안 된 변경 · .env · 시장 자료 폴더는 들어가지 않는다)
# 서버에서 하는 일: infra/aws/app/install-app.sh — 패키지 · 코드 · 가상환경 · 프론트 빌드 · 워커 점검(--once) · nginx · HTTPS.
#   워커 점검이나 웹 확인이 실패하면 서버가 바로 앞 코드로 되돌린다.
# 걸리는 시간: 처음 15~25분(LibreOffice · Node 설치), 다음부터 5~10분. 워커가 단계를 하던 중이면 그 단계가 끝날 때까지(최대 15분) 더 걸린다.
# 웹 주소: settings.env(.local)의 WEB_DOMAIN. DNS 에서 그 이름을 웹 서버 고정 IP 로 연결해 두면 처음 올릴 때 HTTPS 인증서를 받는다
#   (Let's Encrypt — 받으면 그 이용 약관에 동의한 것이 된다). 비워 두면 고정 IP 의 HTTP 로만 연다(구글 로그인은 HTTPS 가 있어야 된다).
set -euo pipefail
# shellcheck source=infra/aws/lib-app.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-app.sh"

usage() {
  cat <<'EOF'
사용법: bash infra/aws/deploy-app.sh [옵션]
  --ref 커밋       올릴 커밋 · 갈래 · 태그 (기본: HEAD)
  --profile 이름   다른 AWS 계정(프로필)
  --region 리전    리전 (기본: settings.env 의 REGION)
  --stack 이름     스택 이름 (기본: sbrain)
  --yes            확인 질문 없이 진행
EOF
}

parse_common_args "$@"
REF=HEAD
set -- ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
while [ $# -gt 0 ]; do
  case "$1" in
    --ref) [ $# -ge 2 ] || die "--ref 뒤에 커밋을 적으세요."; REF="$2"; shift 2 ;;
    *) usage >&2; die "모르는 옵션: $1" ;;
  esac
done

load_settings
require_cli
WEB_DOMAIN="$(printf '%s' "${WEB_DOMAIN:-}" | tr 'A-Z' 'a-z')"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
[ -z "$WEB_DOMAIN" ] || [[ "$WEB_DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
  || die "WEB_DOMAIN 형식이 이상합니다: $WEB_DOMAIN (예: app.example.com)"
[ -z "$CERTBOT_EMAIL" ] || [[ "$CERTBOT_EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] \
  || die "CERTBOT_EMAIL 형식이 이상합니다: $CERTBOT_EMAIL"
command -v git >/dev/null 2>&1 || die "git 이 없습니다."

step "1/4 어느 계정에 올리는지 확인"
show_identity
SHA="$(git rev-parse --verify --quiet "$REF^{commit}")" || die "커밋을 찾지 못했습니다: $REF"
echo "  올릴 커밋 : ${SHA:0:12} ($(git log -1 --format=%s "$SHA" | cut -c1-70))"
if [ -n "$WEB_DOMAIN" ]; then echo "  웹 주소   : https://$WEB_DOMAIN"; else echo "  웹 주소   : (WEB_DOMAIN 없음 — 고정 IP 의 HTTP)"; fi
if [ "$REF" = HEAD ] && [ -n "$(git status --porcelain -- agent-orchestration web infra/aws/app 2>/dev/null)" ]; then
  warn "커밋하지 않은 변경이 있습니다. 올라가는 것은 마지막 커밋뿐입니다(git status 로 확인)."
fi
confirm "이 커밋을 웹 서버에 올리고 워커 · 웹을 다시 띄울까요?"

step "2/4 올릴 코드 묶기"
mkdir -p "$BUILD_DIR"
NAME="$(date -u +%Y%m%d%H%M%S)-${SHA:0:10}"
BUNDLE="$BUILD_DIR/release-$NAME.tar.gz"
TOOL="$BUILD_DIR/install-app.sh"
trap 'rm -f "$BUNDLE"' EXIT
# 윈도우에서 줄바꿈이 CRLF 로 바뀌어 나오지 않게 이 명령에서만 줄바꿈 변환을 끈다(서버는 리눅스)
git -c core.autocrlf=false -c core.eol=lf archive --format=tar.gz -o "$BUNDLE" "$SHA" \
    agent-orchestration web infra/aws/app \
  || die "코드를 묶지 못했습니다(그 커밋에 agent-orchestration · web · infra/aws/app 이 모두 있어야 합니다)."
git -c core.autocrlf=false show "$SHA:infra/aws/app/install-app.sh" | tr -d '\r' > "$TOOL" \
  || die "그 커밋에 infra/aws/app/install-app.sh 가 없습니다."
echo "  묶음: $NAME ($(( $(wc -c < "$BUNDLE") / 1024 / 1024 ))MB)"

step "3/4 S3 에 올리기"
load_app_outputs
aws s3 cp "$BUNDLE" "s3://$OUT_DeployBucketName/deploy/releases/$NAME.tar.gz" --only-show-errors \
  || die "코드 묶음을 S3 에 올리지 못했습니다."
aws s3 cp "$TOOL" "s3://$OUT_DeployBucketName/deploy/tools/install-app.sh" --only-show-errors \
  || die "설치 스크립트를 S3 에 올리지 못했습니다."
echo "  올렸습니다: deploy/releases/$NAME.tar.gz"

step "4/4 웹 서버에 설치 · 다시 띄우기"
wait_ssm_online "$OUT_WebInstanceId" "웹 서버"
# 첫 부팅 설치(aws CLI 등)가 끝나기를 최대 10분 기다린 뒤 실행한다(up.sh 와 같음). $PATH · $(seq) 는 서버에서 풀린다
# shellcheck disable=SC2016
cmd='export PATH=$PATH:/snap/bin; for i in $(seq 1 120); do [ -f /var/lib/sbrain-userdata.done ] && break; sleep 5; done; '
cmd+="mkdir -p /opt/sbrain/tools && aws s3 cp s3://$OUT_DeployBucketName/deploy/tools/install-app.sh /opt/sbrain/tools/install-app.sh --only-show-errors --region $REGION"
cmd+=" && bash /opt/sbrain/tools/install-app.sh --region $REGION --stack $STACK_NAME --bucket $OUT_DeployBucketName --release $NAME"
[ -n "$WEB_DOMAIN" ] && cmd+=" --domain $WEB_DOMAIN"
[ -n "$CERTBOT_EMAIL" ] && cmd+=" --email $CERTBOT_EMAIL"
if ! remote_run "$OUT_WebInstanceId" deploy "웹 서버" 3600 "$cmd"; then
  explain_app_error "웹 서버"
  case "$REMOTE_OUT$REMOTE_ERR" in
    *env_missing*)
      echo "  → env 파일이 없습니다. 'bash infra/aws/app-env.sh' 를 먼저 실행하세요." >&2 ;;
    *AccessDenied*|*"403"*|*Forbidden*)
      echo "  → 서버 권한이 아직 없습니다. 템플릿의 WebAppPolicy 를 반영하려면 'bash infra/aws/up.sh' 를 다시 실행하세요." >&2 ;;
  esac
  die "앱 올리기에 실패했습니다 (상태: $REMOTE_STATUS). 서버 기록: /var/log/sbrain/deploy/$NAME.log"
fi
report_app_remote "웹 서버"

echo
if [ -n "$WEB_DOMAIN" ]; then
  echo "웹 주소: https://$WEB_DOMAIN   (인증서를 아직 못 받았으면 http://$OUT_WebPublicIp)"
else
  echo "웹 주소: http://$OUT_WebPublicIp   (구글 로그인은 HTTPS 도메인이 있어야 된다 — settings.env.local 에 WEB_DOMAIN)"
fi
echo "서버 상태: ssh -F $OUT_DIR/ssh_config $STACK_NAME-web 로 들어가 'systemctl status sbrain-web sbrain-worker' · 'journalctl -u sbrain-worker -f'"
