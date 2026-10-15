#!/usr/bin/env bash
# EC2 안에서 root 로 실행된다. up.sh 가 원격 실행(SSM)으로 부르므로 손으로 부를 일은 거의 없다.
#
#   공고 서버: setup-db.sh --mode full     DB · 앱 계정 · 테이블을 만들고 /etc/sbrain/db.env 작성
#   웹 서버  : setup-db.sh --mode env-only /etc/sbrain/db.env 만 작성
#   두 경우 모두 마지막에 앱 계정으로 실제 접속해 본다.
#
# 표준출력은 up.sh 가 읽어 한국어로 바꿔 보여 준다. 그래서 '@@ 키 값' 형식의 영어 한 줄만 쓴다
# (윈도우 aws.exe 가 서버에서 온 한글 출력을 깨뜨릴 수 있어서).
# 몇 번을 다시 실행해도 안전하다.
set -euo pipefail
export PATH="$PATH:/snap/bin"

say()  { echo "@@ $*"; }
fail() { say "error $*"; exit 1; }

MODE="" REGION="" DB_HOST="" DB_PORT=3306 DB_NAME="" MASTER_SECRET="" APP_SECRET=""
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || fail "bad_input missing value for $1"
  case "$1" in
    --mode)          MODE="$2" ;;
    --region)        REGION="$2" ;;
    --db-host)       DB_HOST="$2" ;;
    --db-port)       DB_PORT="$2" ;;
    --db-name)       DB_NAME="$2" ;;
    --master-secret) MASTER_SECRET="$2" ;;
    --app-secret)    APP_SECRET="$2" ;;
    *)               fail "bad_input unknown option $1" ;;
  esac
  shift 2
done

case "$MODE" in full|env-only) ;; *) fail "bad_input mode=$MODE" ;; esac
[[ "$REGION" =~ ^[a-z0-9-]+$ ]]        || fail "bad_input region"
[[ "$DB_HOST" =~ ^[A-Za-z0-9.-]+$ ]]   || fail "bad_input db-host"
[[ "$DB_PORT" =~ ^[0-9]+$ ]]           || fail "bad_input db-port"
[[ "$DB_NAME" =~ ^[A-Za-z0-9_]+$ ]]    || fail "bad_input db-name"
[ -n "$APP_SECRET" ]                   || fail "bad_input app-secret"
[ "$MODE" = env-only ] || [ -n "$MASTER_SECRET" ] || fail "bad_input master-secret"

for tool in aws mysql python3 curl; do
  command -v "$tool" >/dev/null 2>&1 || fail "tools_missing $tool"
done

HERE="$(cd "$(dirname "$0")" && pwd)"
ETC=/etc/sbrain
CA="$ETC/rds-ca.pem"
# RDS 주소 그대로 접속하면 인증서 이름까지 확인한다. 다른 이름(별칭 등)으로 붙을 때만 VERIFY_CA 로 낮춘다.
SSL_MODE="${SBRAIN_DB_SSL_MODE:-VERIFY_IDENTITY}"
case "$SSL_MODE" in VERIFY_IDENTITY|VERIFY_CA) ;; *) fail "bad_input ssl mode $SSL_MODE" ;; esac
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$ETC"

# RDS 인증서 묶음. 이걸로 DB 서버 신원까지 확인한다(공고 수집 코드의 MYSQL_SSL_CA 도 이 파일을 쓴다).
curl -fsS --retry 5 --max-time 60 -o "$WORK/ca.pem" \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem || fail "ca_download"
install -m 644 "$WORK/ca.pem" "$CA"

# 비밀값(JSON)을 파일로 받는다. 비밀번호가 명령줄(프로세스 목록)에 드러나지 않게 한다.
# snap 으로 깐 aws CLI 는 SSM 원격 실행 안에서 표준출력을 파일로 바로 돌리면 오류 없이 0바이트를 쓴다
# (2026-10-15 실제 서버에서 확인, 파이프로는 정상). 그래서 cat 을 거쳐 저장하고, 비었으면 멈춘다.
read_secret() {
  ( umask 077
    aws secretsmanager get-secret-value --region "$REGION" --secret-id "$1" \
      --query SecretString --output text 2> "$WORK/aws.err" | cat > "$2" ) \
    || fail "secret_read $(head -c 300 "$WORK/aws.err" | tr '\n' ' ')"
  [ -s "$2" ] || fail "secret_read empty output from aws cli"
}

# mysql 클라이언트 설정 파일. 비밀번호는 여기에만 두고 명령줄에 넣지 않는다.
write_cnf() {
  python3 - "$1" "$2" "$DB_HOST" "$DB_PORT" "$CA" "$SSL_MODE" <<'PY'
import json, os, sys
src, dst, host, port, ca, ssl_mode = sys.argv[1:7]
s = json.load(open(src))

def q(v):
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'

fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('[client]\n')
    f.write('host=%s\nport=%s\n' % (host, port))
    f.write('user=%s\npassword=%s\n' % (q(s['username']), q(s['password'])))
    f.write('ssl-ca=%s\nssl-mode=%s\n' % (ca, ssl_mode))
    f.write('default-character-set=utf8mb4\n')
PY
}

json_field() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }

read_secret "$APP_SECRET" "$WORK/app.json"
APP_USER="$(json_field "$WORK/app.json" username)"
APP_PASS="$(json_field "$WORK/app.json" password)"
# 웹 백엔드가 비밀번호를 SQLAlchemy 주소에 그대로 넣으므로 영문·숫자만 허용한다.
[[ "$APP_USER" =~ ^[A-Za-z0-9_]{1,32}$ ]] || fail "bad_input app user name"
[[ "$APP_PASS" =~ ^[A-Za-z0-9]{16,}$ ]]   || fail "bad_input app password must be letters and digits"
write_cnf "$WORK/app.json" "$WORK/app.cnf"

if [ "$MODE" = full ]; then
  read_secret "$MASTER_SECRET" "$WORK/master.json"
  write_cnf "$WORK/master.json" "$WORK/admin.cnf"
  m() { mysql --defaults-extra-file="$WORK/admin.cnf" "$@"; }

  # 방금 만든 RDS 는 접속이 잠깐 늦을 수 있다. 최대 5분 기다린다.
  for i in $(seq 1 30); do
    if m -e 'SELECT 1' >/dev/null 2> "$WORK/m.err"; then break; fi
    [ "$i" = 30 ] && fail "db_unreachable $(head -c 300 "$WORK/m.err" | tr '\n' ' ')"
    sleep 10
  done
  say "db_ready"

  m -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
  say "database $DB_NAME"

  # 어떤 SQL 파일을 이미 적용했는지 기록한다. 같은 파일을 두 번 적용하지 않기 위해서다.
  m "$DB_NAME" -e "CREATE TABLE IF NOT EXISTS infra_schema_history (
      source_path VARCHAR(255) NOT NULL PRIMARY KEY,
      sha256 CHAR(64) NOT NULL,
      applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
    ) COMMENT='SQL files applied by infra/aws/up.sh'"

  while IFS=$'\t' read -r file src || [ -n "$file" ]; do
    [ -n "$file" ] || continue
    [[ "$src" =~ ^[A-Za-z0-9_./-]+$ ]] || fail "bad_input schema path $src"
    sum="$(sha256sum "$HERE/sql/$file" | cut -d' ' -f1)"
    prev="$(m -N -B "$DB_NAME" -e "SELECT sha256 FROM infra_schema_history WHERE source_path='$src'")"
    if [ -n "$prev" ]; then
      if [ "$prev" = "$sum" ]; then say "schema skipped $src"; else say "schema changed $src"; fi
      continue
    fi
    m "$DB_NAME" < "$HERE/sql/$file" 2> "$WORK/m.err" \
      || fail "schema_failed $src $(head -c 400 "$WORK/m.err" | tr '\n' ' ')"
    m "$DB_NAME" -e "INSERT INTO infra_schema_history (source_path, sha256) VALUES ('$src', '$sum')"
    say "schema applied $src"
  done < "$HERE/sql/order.tsv"

  # MySQL 기본 로그인 방식(caching_sha2_password)으로 만든다. PyMySQL 1.2 이상은 서버가 지원하면
  # 알아서 암호화해 접속하므로 cryptography 패키지 없이도 로그인된다(MySQL 8.4 · DB 재시작 직후로 확인).
  # 비밀번호가 명령줄에 드러나지 않게 표준입력으로 넘긴다.
  m <<SQL
CREATE USER IF NOT EXISTS '$APP_USER'@'%' IDENTIFIED BY '$APP_PASS';
ALTER USER '$APP_USER'@'%' IDENTIFIED BY '$APP_PASS';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$APP_USER'@'%';
SQL
  say "app_user $APP_USER"
fi

# 앱이 읽을 접속 정보. 기존 .env 와 같은 이름(MYSQL_*)이라 그대로 복사해 쓰면 된다.
# MYSQL_SSL_CA 는 공고 수집 코드만 읽어 서버 신원까지 확인한다. 웹 백엔드는 이 값을 읽지 않지만
# PyMySQL 1.2 이상이면 암호화는 된다(인증서 확인만 안 함).
umask 077
cat > "$WORK/db.env" <<EOF
MYSQL_HOST=$DB_HOST
MYSQL_PORT=$DB_PORT
MYSQL_DATABASE=$DB_NAME
MYSQL_USER=$APP_USER
MYSQL_PASSWORD=$APP_PASS
MYSQL_SSL_CA=$CA
EOF
if getent group ubuntu >/dev/null 2>&1; then
  install -o root -g ubuntu -m 640 "$WORK/db.env" "$ETC/db.env"
else
  install -m 600 "$WORK/db.env" "$ETC/db.env"
fi
say "env_written $ETC/db.env"

# 앱 계정으로 실제로 붙어 본다(이 서버 → DB 보안그룹 · 비밀번호 · 권한 확인).
tables="$(mysql --defaults-extra-file="$WORK/app.cnf" -N -B \
  -e "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA='$DB_NAME'" 2> "$WORK/m.err")" \
  || fail "db_unreachable app user: $(head -c 300 "$WORK/m.err" | tr '\n' ' ')"
say "tables $tables"
