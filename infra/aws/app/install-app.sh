#!/usr/bin/env bash
# 웹 서버(EC2) 안에서 root 로 실행된다. infra/aws/deploy-app.sh 가 원격 실행(SSM)으로 부르므로 손으로 부를 일은 거의 없다.
#
#   install-app.sh --region <리전> --stack <스택> --bucket <S3 버킷> --release <이름> [--domain <도메인>] [--email <메일>]
#
# 한 번에 하는 일 (몇 번을 다시 실행해도 안전하다)
#   1. 서버 패키지: nginx · certbot · LibreOffice(계획서 PDF) · 한글 글꼴 · Node 22(프론트 빌드) · rhwp(.hwp 내려받기)
#   2. 코드: S3 deploy/releases/<이름>.tar.gz → /opt/sbrain/releases/<이름> (그 안에 가상환경 .venv — 웹 · 워커가 함께 쓴다)
#   3. 프론트: web/frontend 를 빌드해 /var/www/sbrain 에 둔다(VITE_API_BASE=/api)
#   4. 워커를 멈추고(하던 단계를 끝낸 뒤) /opt/sbrain/current 를 새 코드로 바꾼 뒤 --once 로 한 바퀴 점검 → 워커 · 웹 시작
#      점검이나 웹 확인이 실패하면 바로 앞 코드로 되돌리고 멈춘다
#   5. nginx: /api/ → 127.0.0.1:8000, 나머지 → 프론트. 도메인이 있으면 Let's Encrypt 인증서를 받아 HTTPS 로 연다
#      (인증서를 받으면 Let's Encrypt 이용 약관에 동의한 것이 된다 — certbot --agree-tos)
#
# 먼저 있어야 하는 것: /etc/sbrain/db.env(up.sh) · /etc/sbrain/web.env · /etc/sbrain/worker.env(app-env.sh)
# 서버에 남는 것: 첨부 파일 /var/lib/sbrain/web/uploads · 웹 요청 로그 /var/log/sbrain/web · 워커 운영 로그 /var/log/sbrain/worker
#               — 코드를 다시 올려도 남지만 서버(디스크)를 새로 만들면 사라진다. 산출물 파일은 S3 에 있다.
# 표준출력은 '@@ 키 값' 영어 한 줄만 쓴다(윈도우 aws.exe 가 한글을 깨뜨릴 수 있어서). 자세한 기록은 /var/log/sbrain/deploy/<이름>.log
set -euo pipefail
export PATH="$PATH:/snap/bin"

REGION="" STACK="" BUCKET="" RELEASE="" DOMAIN="" EMAIL=""
ARGS_ERR=""
while [ $# -gt 0 ]; do
  if [ $# -lt 2 ]; then ARGS_ERR="missing value for $1"; break; fi
  case "$1" in
    --region)  REGION="$2" ;;
    --stack)   STACK="$2" ;;
    --bucket)  BUCKET="$2" ;;
    --release) RELEASE="$2" ;;
    --domain)  DOMAIN="$2" ;;
    --email)   EMAIL="$2" ;;
    *)         ARGS_ERR="unknown option $1"; break ;;
  esac
  shift 2
done

say0() { echo "@@ $*"; }
[ -z "$ARGS_ERR" ] || { say0 "error bad_input $ARGS_ERR"; exit 1; }
[[ "$REGION" =~ ^[a-z0-9-]+$ ]]                        || { say0 "error bad_input region"; exit 1; }
[[ "$STACK" =~ ^[A-Za-z][A-Za-z0-9-]{0,31}$ ]]         || { say0 "error bad_input stack"; exit 1; }
[[ "$BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]  || { say0 "error bad_input bucket"; exit 1; }
[[ "$RELEASE" =~ ^[A-Za-z0-9._-]{1,80}$ ]]             || { say0 "error bad_input release"; exit 1; }
[ -z "$DOMAIN" ] || [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
  || { say0 "error bad_input domain (lowercase host name)"; exit 1; }
[ -z "$EMAIL" ] || [[ "$EMAIL" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { say0 "error bad_input email"; exit 1; }

# 자세한 출력은 기록 파일로, '@@' 줄만 원격 실행 결과(표준출력 · fd 3)로 보낸다
LOG_DIR=/var/log/sbrain/deploy
mkdir -p "$LOG_DIR"
chmod 750 "$LOG_DIR"
LOG="$LOG_DIR/$RELEASE.log"
exec 3>&1 >>"$LOG" 2>&1
echo "=== install-app.sh $(date -u +%FT%TZ) release=$RELEASE"
say()  { echo "@@ $*"; echo "@@ $*" >&3; }
fail() {
  say "error $*"
  { echo "--- last lines of $LOG ---"; tail -n 25 "$LOG"; } >&3
  exit 1
}
say "log $LOG"

ETC=/etc/sbrain
OPT=/opt/sbrain
REL_ROOT="$OPT/releases"
REL_DIR="$REL_ROOT/$RELEASE"
CURRENT="$OPT/current"
WEB_HOME=/var/lib/sbrain/web
WWW=/var/www/sbrain
APP_SRC=""   # 이 릴리스 안의 infra/aws/app (단위 파일 · nginx 설정)

for f in db.env web.env worker.env; do
  [ -f "$ETC/$f" ] || fail "env_missing $ETC/$f (run infra/aws/up.sh then infra/aws/app-env.sh)"
done
command -v aws >/dev/null 2>&1 || fail "tools_missing aws"

export DEBIAN_FRONTEND=noninteractive
apt_get() { apt-get -y -o DPkg::Lock::Timeout=600 "$@"; }

# ------------------------------------------------------------ 1. 서버 패키지
apt_get update || fail "apt_update"
apt_get install nginx certbot curl ca-certificates fonts-nanum fonts-noto-cjk || fail "apt_install nginx certbot fonts"
if ! command -v soffice >/dev/null 2>&1; then
  # 화면 없는 서버용 LibreOffice Writer(계획서 docx → PDF). 이름이 다른 판이면 일반 Writer 를 깐다
  apt_get install --no-install-recommends libreoffice-writer-nogui \
    || apt_get install --no-install-recommends libreoffice-writer \
    || fail "apt_install libreoffice"
fi
say "packages nginx certbot libreoffice fonts-nanum fonts-noto-cjk"

# Node 22.12 이상(프론트 vite 8 빌드에 필요). Ubuntu 기본 nodejs 는 낡아서 NodeSource 22.x 저장소에서 깐다
node_ok() {
  local v
  v="$(node -v 2>/dev/null || true)"
  [[ "$v" =~ ^v([0-9]+)\.([0-9]+) ]] || return 1
  [ "${BASH_REMATCH[1]}" -gt 22 ] || { [ "${BASH_REMATCH[1]}" -eq 22 ] && [ "${BASH_REMATCH[2]}" -ge 12 ]; }
}
if ! node_ok; then
  curl -fsSL --retry 3 -o /tmp/nodesource_setup.sh https://deb.nodesource.com/setup_22.x || fail "node_download nodesource setup"
  bash /tmp/nodesource_setup.sh || fail "node_repo nodesource setup"
  rm -f /tmp/nodesource_setup.sh
  apt_get install nodejs || fail "apt_install nodejs"
  node_ok || fail "node_version $(node -v 2>/dev/null || echo none)"
fi
say "node $(node -v)"

# rhwp — 계획서 .hwp 내려받기. 없어도 서버는 돌고 .hwp 내려받기만 500 이다(웹 README)
RHWP_VERSION=v0.8.6
RHWP_URL="https://github.com/edwardkim/rhwp/releases/download/$RHWP_VERSION/rhwp-$RHWP_VERSION-linux-x86_64.tar.gz"
install -d -m 755 "$OPT/bin"
if [ -x "$OPT/bin/rhwp" ] && [ "$(cat "$OPT/bin/.rhwp-version" 2>/dev/null || true)" = "$RHWP_VERSION" ]; then
  say "rhwp $RHWP_VERSION already installed"
else
  t="$(mktemp -d)"
  if curl -fsSL --retry 3 -o "$t/rhwp.tgz" "$RHWP_URL" && tar -xzf "$t/rhwp.tgz" -C "$t"; then
    bin="$(find "$t" -type f -name rhwp | head -1)"
    if [ -n "$bin" ]; then
      install -m 755 "$bin" "$OPT/bin/rhwp"
      echo "$RHWP_VERSION" > "$OPT/bin/.rhwp-version"
      say "rhwp $RHWP_VERSION installed"
    else
      say "rhwp not_found_in_archive (hwp download disabled)"
    fi
  else
    say "rhwp download_failed (hwp download disabled) $RHWP_URL"
  fi
  rm -rf "$t"
fi

# ------------------------------------------------------------ 계정 · 폴더
mkdir -p /var/lib/sbrain
id -u sbrain >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin sbrain
id -u sbrain-web >/dev/null 2>&1 \
  || useradd --system --home-dir "$WEB_HOME" --create-home --shell /usr/sbin/nologin sbrain-web
install -d -o sbrain -g sbrain -m 750 /var/log/sbrain/worker
install -d -o sbrain-web -g sbrain-web -m 750 "$WEB_HOME" "$WEB_HOME/uploads" /var/log/sbrain/web
install -d -m 755 "$REL_ROOT" "$WWW" /var/www/certbot /etc/nginx/snippets

# ------------------------------------------------------------ 2. 코드 · 가상환경
if [ -f "$REL_DIR/.installed" ]; then
  say "release $RELEASE already unpacked"
else
  rm -rf "$REL_DIR"
  t="$(mktemp -d)"
  aws s3 cp "s3://$BUCKET/deploy/releases/$RELEASE.tar.gz" "$t/release.tar.gz" --region "$REGION" --only-show-errors \
    || fail "release_download"
  mkdir -p "$t/x"
  tar -xzf "$t/release.tar.gz" -C "$t/x" || fail "release_extract"
  [ -f "$t/x/agent-orchestration/pyproject.toml" ] && [ -f "$t/x/web/backend/app/main.py" ] \
    && [ -d "$t/x/web/frontend" ] && [ -d "$t/x/infra/aws/app" ] || fail "release_layout"
  mv "$t/x" "$REL_DIR"
  rm -rf "$t"

  # 웹이 코드 폴더 안에 쓰는 곳(첨부 파일 · 요청 로그)은 코드 밖 폴더를 가리키게 한다 — 코드를 다시 올려도 남는다
  rm -rf "$REL_DIR/web/backend/uploads" "$REL_DIR/web/backend/logs"
  ln -s "$WEB_HOME/uploads" "$REL_DIR/web/backend/uploads"
  ln -s /var/log/sbrain/web "$REL_DIR/web/backend/logs"

  # 가상환경 하나에 웹 의존성과 오케스트레이터(sbrain — boto3 · botocore 포함)를 함께 깐다. 웹과 워커가 같은 코드를 쓴다
  V="$REL_DIR/.venv"
  python3 -m venv "$V" || fail "venv_create"
  "$V/bin/python" -m pip install --quiet --upgrade pip || fail "venv_pip"
  "$V/bin/python" -m pip install --quiet -r "$REL_DIR/web/backend/requirements.txt" || fail "venv_web_requirements"
  "$V/bin/python" -m pip install --quiet "$REL_DIR/agent-orchestration" || fail "venv_orchestrator"
  "$V/bin/python" -c "import boto3, botocore, fastapi, uvicorn, sbrain.worker, sbrain.store_s3" || fail "venv_check"

  chown -R root:root "$REL_DIR"
  chmod -R go-w "$REL_DIR"
  touch "$REL_DIR/.installed"
  say "release $RELEASE unpacked"
  say "venv $REL_DIR/.venv"
fi
APP_SRC="$REL_DIR/infra/aws/app"

# ------------------------------------------------------------ 3. 프론트 빌드
GOOGLE_CLIENT_ID_VALUE="$(sed -n 's/^GOOGLE_CLIENT_ID=//p' "$ETC/web.env" | head -1)"
[ -n "$GOOGLE_CLIENT_ID_VALUE" ] || fail "web_env GOOGLE_CLIENT_ID missing (run infra/aws/app-env.sh)"
BUILD="$WEB_HOME/frontend-build"
rm -rf "$BUILD"
cp -a "$REL_DIR/web/frontend" "$BUILD"
chown -R sbrain-web:sbrain-web "$BUILD"
# 빌드는 웹 계정으로 한다(npm 이 패키지 스크립트를 실행하므로 root 로 돌리지 않는다).
# 구글 클라이언트 ID 는 원래 브라우저에 공개되는 값이라 빌드 결과에 들어간다
runuser -u sbrain-web -- env HOME="$WEB_HOME" VITE_API_BASE=/api VITE_GOOGLE_CLIENT_ID="$GOOGLE_CLIENT_ID_VALUE" \
  bash -c "cd '$BUILD' && npm ci --no-audit --no-fund && npm run build" || fail "frontend_build"
[ -f "$BUILD/dist/index.html" ] || fail "frontend_dist index.html missing"
rm -rf "$WWW.new" "$WWW.old"
cp -a "$BUILD/dist" "$WWW.new"
chown -R root:root "$WWW.new"
chmod -R a+rX,go-w "$WWW.new"
say "frontend built"

# ------------------------------------------------------------ 4. 서비스 바꾸기
install_unit() { tr -d '\r' < "$APP_SRC/$1" > "/etc/systemd/system/$1" && chmod 644 "/etc/systemd/system/$1"; }
install_unit sbrain-worker.service || fail "unit_install sbrain-worker.service"
install_unit sbrain-web.service || fail "unit_install sbrain-web.service"
systemctl daemon-reload

PREV=""
[ -L "$CURRENT" ] && PREV="$(readlink -f "$CURRENT" || true)"
point_current() { ln -sfn "$1" "$CURRENT.new" && mv -Tf "$CURRENT.new" "$CURRENT"; }
roll_back() {
  if [ -n "$PREV" ] && [ -d "$PREV" ] && [ "$PREV" != "$REL_DIR" ]; then
    point_current "$PREV"
    systemctl start sbrain-worker || true
    systemctl restart sbrain-web || true
    say "rollback current=$(basename "$PREV")"
  fi
}

# 워커는 1대만 — 옛 워커를 먼저 멈춘다(하던 단계를 끝낼 때까지 최대 15분 기다린다)
if systemctl is-active --quiet sbrain-worker; then
  systemctl stop sbrain-worker || fail "worker_stop"
  say "worker_stop done"
fi
point_current "$REL_DIR"

# 한 바퀴만 돌려 본다(DB 접속 · 설정 · S3 시작 확인). 0 이 아니면 앞 코드로 되돌린다 — 2 설정 오류 · 영구, 1 일시
set +e
(
  set -a
  # shellcheck disable=SC1091
  . "$ETC/worker.env"
  set +a
  cd /
  exec runuser -u sbrain -- env PYTHONDONTWRITEBYTECODE=1 "$CURRENT/.venv/bin/sbrain-worker" --once
)
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
  roll_back
  case "$rc" in
    2) fail "worker_check exit=2 config or permanent error (worker message in the last lines below)" ;;
    1) fail "worker_check exit=1 temporary error, try again later (worker message in the last lines below)" ;;
    *) fail "worker_check exit=$rc (worker message in the last lines below)" ;;
  esac
fi
say "worker_check ok"

systemctl enable sbrain-worker sbrain-web >/dev/null 2>&1 || true
systemctl start sbrain-worker || { roll_back; fail "worker start"; }
systemctl restart sbrain-web || { roll_back; fail "web restart"; }
ok=0
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/health; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != 1 ]; then
  journalctl -u sbrain-web -n 40 --no-pager || true
  roll_back
  fail "web_health http://127.0.0.1:8000/health did not answer"
fi
say "worker started"
say "web started (health ok)"

# 프론트는 백엔드가 뜬 뒤에 바꾼다
[ -d "$WWW" ] && mv "$WWW" "$WWW.old"
mv "$WWW.new" "$WWW"
rm -rf "$WWW.old"

# ------------------------------------------------------------ 5. nginx · HTTPS
SITE=/etc/nginx/sites-available/sbrain
render_site() {   # $1 = http | https
  tr -d '\r' < "$APP_SRC/nginx-app.conf" > /etc/nginx/snippets/sbrain-app.conf
  if [ "$1" = https ]; then
    tr -d '\r' < "$APP_SRC/nginx-https.conf" | sed -e "s/__DOMAIN__/$DOMAIN/g" > "$SITE"
  else
    tr -d '\r' < "$APP_SRC/nginx-http.conf" | sed -e "s/__SERVER_NAME__/${DOMAIN:-_}/g" > "$SITE"
  fi
  ln -sfn "$SITE" /etc/nginx/sites-enabled/sbrain
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
}
cert_ready() { [ -n "$DOMAIN" ] && [ -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; }

if cert_ready; then mode=https; else mode=http; fi
render_site "$mode" || fail "nginx_config $mode (nginx -t failed)"
systemctl enable nginx >/dev/null 2>&1 || true
systemctl reload nginx || systemctl restart nginx || fail "nginx_reload"
say "nginx $mode ${DOMAIN:-no-domain}"

if [ -n "$DOMAIN" ] && ! cert_ready; then
  if [ -n "$EMAIL" ]; then email_args=(-m "$EMAIL"); else email_args=(--register-unsafely-without-email); fi
  # 갱신은 certbot 패키지의 타이머가 한다. 갱신하면 nginx 를 다시 읽는다(--deploy-hook 이 갱신 설정에 남는다)
  if certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --non-interactive --agree-tos "${email_args[@]}" \
       --deploy-hook "systemctl reload nginx"; then
    render_site https || fail "nginx_config https (nginx -t failed)"
    systemctl reload nginx || fail "nginx_reload"
    say "https certificate issued for $DOMAIN"
  else
    say "https_pending certbot failed for $DOMAIN, see $LOG"
  fi
elif cert_ready; then
  say "https active for $DOMAIN"
fi

# ------------------------------------------------------------ 옛 코드 정리 (지금 · 바로 앞 · 그 앞 셋만 남긴다)
keep="$(readlink -f "$CURRENT")"
removed=0
n=0
for d in $(ls -1dt "$REL_ROOT"/*/ 2>/dev/null); do
  d="${d%/}"
  n=$((n + 1))
  [ "$n" -le 3 ] && continue
  [ "$d" = "$keep" ] && continue
  [ -n "$PREV" ] && [ "$d" = "$PREV" ] && continue
  rm -rf "$d"
  removed=$((removed + 1))
done
say "cleanup removed $removed old release(s)"
echo "=== done $(date -u +%FT%TZ)"
