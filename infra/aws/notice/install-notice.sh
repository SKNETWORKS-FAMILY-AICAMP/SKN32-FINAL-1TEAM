#!/usr/bin/env bash
# 공고 서버(EC2) 안에서 root 로 실행된다. infra/aws/deploy-notice.sh 가 원격 실행(SSM)으로 부르므로 손으로 부를 일은 거의 없다.
#
#   install-notice.sh --region <리전> --stack <스택> --bucket <S3 버킷> --release <이름>
#                     [--data <파일 이름>] [--restore-db <파일 이름>] [--run-batch]
#
# 한 번에 하는 일 (몇 번을 다시 실행해도 안전하다)
#   1. 계정 · 폴더: sbrain-notice 계정, 데이터 폴더 /var/lib/sbrain-notice/data (코드를 다시 올려도 남는다)
#   2. 설정: SSM Parameter Store(/<스택>/notice/*) → /etc/sbrain/notice.env (root 만 읽음). DB 접속은 up.sh 의 /etc/sbrain/db.env
#   3. 코드: S3 deploy/notice/releases/<이름>.tar.gz → /opt/sbrain-notice/releases/<이름> (그 안에 가상환경 .venv — CPU 판 torch)
#   4. BGE-M3: 처음 한 번 받아 둔다(sbrain-notice 계정 홈 ~/.cache/huggingface, 약 2.3GB). 서비스는 켤 때 인터넷에 묻지 않는다
#   5. (--data)       배치 서버의 data/ 묶음을 데이터 폴더에 푼다 — 처음 한 번만(신청자 유형 · 업종 누적 결과 · 첨부 파일)
#      (--restore-db) 팀 EC2 백업(collect.backup_db)의 행을 새 DB 에 넣는다 — 공고 표 8개가 모두 비어 있을 때만.
#                     표는 up.sh 가 저장소 정의로 이미 만들었으므로 백업의 DROP · CREATE 는 건너뛰고 INSERT 만 한 트랜잭션으로 넣는다.
#                     첨부 원본(attachment_files)은 넣지 않는다 — 매일 배치 9단계가 data/attachments 에서 다시 올린다
#   6. 서비스: notice-server 를 새 코드로 다시 띄우고 /api/health 확인. 응답이 없으면 바로 앞 코드로 되돌리고 멈춘다
#   7. 매일 배치 예약(notice-batch.timer, 한국 09:00 — 끝나면 공고 서버를 다시 띄운다). (--run-batch) 배치를 한 번 바로 시작한다(기다리지 않는다)
#
# 먼저 있어야 하는 것: /etc/sbrain/db.env(up.sh) · SSM /<스택>/notice/*(deploy-notice.sh) · 이 서버 역할의 NoticeAppPolicy(up.sh)
# 표준출력은 '@@ 키 값' 영어 한 줄만 쓴다(윈도우 aws.exe 가 한글을 깨뜨릴 수 있어서). 자세한 기록은 /var/log/sbrain/notice-deploy/<이름>.log
set -euo pipefail
export PATH="$PATH:/snap/bin"

REGION="" STACK="" BUCKET="" RELEASE="" DATA_ARCHIVE="" RESTORE_DB="" RUN_BATCH=0
ARGS_ERR=""
while [ $# -gt 0 ]; do
  if [ "$1" = --run-batch ]; then RUN_BATCH=1; shift; continue; fi
  if [ $# -lt 2 ]; then ARGS_ERR="missing value for $1"; break; fi
  case "$1" in
    --region)     REGION="$2" ;;
    --stack)      STACK="$2" ;;
    --bucket)     BUCKET="$2" ;;
    --release)    RELEASE="$2" ;;
    --data)       DATA_ARCHIVE="$2" ;;
    --restore-db) RESTORE_DB="$2" ;;
    *)            ARGS_ERR="unknown option $1"; break ;;
  esac
  shift 2
done

say0() { echo "@@ $*"; }
NAME_RE='^[A-Za-z0-9._-]{1,120}$'
[ -z "$ARGS_ERR" ] || { say0 "error bad_input $ARGS_ERR"; exit 1; }
[[ "$REGION" =~ ^[a-z0-9-]+$ ]]                        || { say0 "error bad_input region"; exit 1; }
[[ "$STACK" =~ ^[A-Za-z][A-Za-z0-9-]{0,31}$ ]]         || { say0 "error bad_input stack"; exit 1; }
[[ "$BUCKET" =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ ]]  || { say0 "error bad_input bucket"; exit 1; }
[[ "$RELEASE" =~ $NAME_RE ]]                           || { say0 "error bad_input release"; exit 1; }
[ -z "$DATA_ARCHIVE" ] || [[ "$DATA_ARCHIVE" =~ $NAME_RE ]] || { say0 "error bad_input data"; exit 1; }
[ -z "$RESTORE_DB" ] || [[ "$RESTORE_DB" =~ $NAME_RE ]]     || { say0 "error bad_input restore-db"; exit 1; }

# 자세한 출력은 기록 파일로, '@@' 줄만 원격 실행 결과(표준출력 · fd 3)로 보낸다
LOG_DIR=/var/log/sbrain/notice-deploy
mkdir -p "$LOG_DIR"
chmod 750 "$LOG_DIR"
LOG="$LOG_DIR/$RELEASE.log"
exec 3>&1 >>"$LOG" 2>&1
echo "=== install-notice.sh $(date -u +%FT%TZ) release=$RELEASE"
say()  { echo "@@ $*"; echo "@@ $*" >&3; }
fail() {
  say "error $*"
  { echo "--- last lines of $LOG ---"; tail -n 25 "$LOG"; } >&3
  exit 1
}
say "log $LOG"

ETC=/etc/sbrain
OPT=/opt/sbrain-notice
REL_ROOT="$OPT/releases"
REL_DIR="$REL_ROOT/$RELEASE"
CURRENT="$OPT/current"
SVC_USER=sbrain-notice
HOME_DIR=/var/lib/sbrain-notice
DATA_DIR="$HOME_DIR/data"
S3="s3://$BUCKET/deploy/notice"
# 개인 서버에서 매일 배치를 돌리던 판(SB-189 deploy/batch.Dockerfile)과 같다
TORCH_VERSION=2.14.0
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ -f "$ETC/db.env" ] || fail "env_missing $ETC/db.env (run infra/aws/up.sh first)"
for tool in aws python3 curl; do
  command -v "$tool" >/dev/null 2>&1 || fail "tools_missing $tool"
done

# 파이썬 도우미의 '@@' 줄을 그대로 넘기고, 실패면 마지막 오류 줄로 멈춘다
forward() { grep '^@@ ' "$1" | grep -v '^@@ error ' >&3 || true; }
fail_from() { fail "$(sed -n 's/^@@ error //p' "$1" | tail -1)"; }

export DEBIAN_FRONTEND=noninteractive
apt_get() { apt-get -y -o DPkg::Lock::Timeout=600 "$@"; }

# ------------------------------------------------------------ 1. 패키지 · 계정 · 폴더
apt_get update || fail "apt_update"
# build-essential · python3-dev: 휠이 없는 패키지가 섞여도 설치가 멈추지 않게
apt_get install python3-venv python3-dev build-essential ca-certificates curl || fail "apt_install python3-venv build-essential"
say "packages python3-venv build-essential"

id -u "$SVC_USER" >/dev/null 2>&1 \
  || useradd --system --home-dir "$HOME_DIR" --create-home --shell /usr/sbin/nologin "$SVC_USER"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 750 "$HOME_DIR" "$DATA_DIR"
install -d -m 755 "$OPT" "$REL_ROOT"
say "account $SVC_USER data=$DATA_DIR"

# ------------------------------------------------------------ 2. 설정 (수집 키)
# 값(JSON)을 파일로 받는다. snap 으로 깐 aws CLI 는 SSM 원격 실행 안에서 표준출력을 파일로 바로 돌리면
# 오류 없이 0바이트를 쓴다(setup-db.sh 와 같은 이유) — cat 을 거쳐 저장하고, 비었으면 멈춘다.
( umask 077
  aws ssm get-parameters-by-path --region "$REGION" --path "/$STACK/notice" --with-decryption \
    --output json 2> "$WORK/aws.err" | cat > "$WORK/params.json" ) \
  || fail "param_read $(head -c 300 "$WORK/aws.err" | tr '\n' ' ')"
[ -s "$WORK/params.json" ] || fail "param_read empty output from aws cli $(head -c 300 "$WORK/aws.err" | tr '\n' ' ')"

if ! python3 - "$WORK/params.json" "$STACK" "$WORK/notice.env" > "$WORK/py.out" <<'PY'
import json, os, re, sys

params_path, stack, out = sys.argv[1:4]
prefix = '/%s/notice/' % stack
vals = {}
for p in json.load(open(params_path)).get('Parameters', []):
    if p['Name'].startswith(prefix):
        vals[p['Name'][len(prefix):]] = p['Value']

# systemd EnvironmentFile 은 따옴표 · 빈칸 · 역슬래시를 따로 풀어 읽는다. 그런 글자가 든 값은 받지 않는다(이름만 알린다).
SAFE = re.compile(r'^[A-Za-z0-9._~:/?#@!+=,%-]+$')
REQUIRED = ('KSTARTUP_KEY', 'BIZINFO_KEY', 'OPENAI_API_KEY')
missing = [n for n in REQUIRED if not vals.get(n)]
if missing:
    print('@@ error param_missing ' + ','.join(missing) + ' (run infra/aws/deploy-notice.sh)')
    sys.exit(3)
for n in REQUIRED:
    if not SAFE.match(vals[n]):
        print('@@ error bad_value ' + n)
        sys.exit(3)
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, 'w') as f:
    f.write('# generated by infra/aws/notice/install-notice.sh - change values with infra/aws/deploy-notice.sh --reset, not here\n')
    for n in REQUIRED:
        f.write('%s=%s\n' % (n, vals[n]))
PY
then
  fail_from "$WORK/py.out"
fi
install -m 600 -o root -g root "$WORK/notice.env" "$ETC/notice.env"
rm -f "$WORK/notice.env" "$WORK/params.json"
say "env_written $ETC/notice.env"

# ------------------------------------------------------------ 3. 코드 · 가상환경
if [ -f "$REL_DIR/.installed" ]; then
  say "release $RELEASE already unpacked"
else
  rm -rf "$REL_DIR"
  aws s3 cp "$S3/releases/$RELEASE.tar.gz" "$WORK/release.tar.gz" --region "$REGION" --only-show-errors \
    || fail "release_download"
  mkdir -p "$WORK/x"
  tar -xzf "$WORK/release.tar.gz" -C "$WORK/x" --no-same-owner || fail "release_extract"
  rm -f "$WORK/release.tar.gz"
  [ -f "$WORK/x/data-collection/search/app.py" ] && [ -f "$WORK/x/data-collection/collect/daily_pipeline.py" ] \
    && [ -f "$WORK/x/infra/aws/notice/requirements-notice.txt" ] || fail "release_layout"
  mv "$WORK/x" "$REL_DIR"

  # 코드가 쓰는 data/ 는 코드 밖 폴더를 가리키게 한다 — 코드를 다시 올려도 배치 누적 결과가 남는다.
  # 저장소에 든 파일(ec2-ca.pem 등)은 데이터 폴더에 없을 때만 옮겨 둔다
  if [ -d "$REL_DIR/data-collection/data" ]; then
    for f in "$REL_DIR/data-collection/data"/* "$REL_DIR/data-collection/data"/.[!.]*; do
      [ -e "$f" ] || continue
      [ -e "$DATA_DIR/$(basename "$f")" ] || cp -a "$f" "$DATA_DIR/"
    done
    rm -rf "$REL_DIR/data-collection/data"
  fi
  ln -s "$DATA_DIR" "$REL_DIR/data-collection/data"
  chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"

  V="$REL_DIR/.venv"
  python3 -m venv "$V" || fail "venv_create"
  "$V/bin/python" -m pip install --quiet --upgrade pip || fail "venv_pip"
  "$V/bin/python" -m pip install --quiet "torch==$TORCH_VERSION" --index-url https://download.pytorch.org/whl/cpu \
    || fail "venv_torch torch==$TORCH_VERSION (cpu)"
  "$V/bin/python" -m pip install --quiet -r "$REL_DIR/infra/aws/notice/requirements-notice.txt" || fail "venv_requirements"
  "$V/bin/python" -c "import torch, sentence_transformers, fastapi, uvicorn, pymysql, pdfplumber, olefile, chromadb, openai" \
    || fail "venv_check"

  chown -R root:root "$REL_DIR"
  chmod -R go-w "$REL_DIR"
  touch "$REL_DIR/.installed"
  say "release $RELEASE unpacked"
  say "venv $V torch=$TORCH_VERSION cpu"
fi

# ------------------------------------------------------------ 4. BGE-M3 (처음 한 번)
# shared/embed.py 가 계정 홈의 이 파일로 모델 리비전을 기록하므로 캐시 위치(HF_HOME)를 바꾸지 않는다
MODEL_REF="$HOME_DIR/.cache/huggingface/hub/models--BAAI--bge-m3/refs/main"
if [ -f "$MODEL_REF" ]; then
  say "model bge-m3 cached"
else
  (
    cd "$HOME_DIR"
    exec runuser -u "$SVC_USER" -- env HOME="$HOME_DIR" PYTHONDONTWRITEBYTECODE=1 "$REL_DIR/.venv/bin/python" -c \
      "from sentence_transformers import SentenceTransformer; m = SentenceTransformer('BAAI/bge-m3'); print('dim', m.get_sentence_embedding_dimension())"
  ) || fail "model_download BAAI/bge-m3 (needs internet through the NAT gateway)"
  [ -f "$MODEL_REF" ] || fail "model_download cache file missing $MODEL_REF"
  say "model bge-m3 downloaded"
fi

# ------------------------------------------------------------ 5-1. (--data) 배치 서버의 data/ 묶음
if [ -n "$DATA_ARCHIVE" ]; then
  MARK="$DATA_DIR/.restored-from-archive"
  if [ -f "$MARK" ]; then
    say "data_restore skipped already restored from $(head -c 120 "$MARK")"
  elif [ -e "$DATA_DIR/collect_log.jsonl" ]; then
    fail "data_dir_not_empty this server already ran the batch (collect_log.jsonl exists), not overwriting $DATA_DIR"
  else
    aws s3 cp "$S3/data/$DATA_ARCHIVE" "$WORK/data.tar.gz" --region "$REGION" --only-show-errors || fail "data_download"
    # tarfile filter='data': 절대 경로 · .. · 폴더 밖 링크 · 장치 파일을 막는다. 맨 위가 data/ 하나면 그 층을 벗긴다
    if ! python3 - "$WORK/data.tar.gz" "$DATA_DIR" > "$WORK/py.out" <<'PY'
import os, sys, tarfile

src, dest = sys.argv[1:3]
SKIP = {'.env', 'collection.lock'}
with tarfile.open(src, 'r:gz') as tf:
    members = [m for m in tf.getmembers() if m.name not in ('.', './')]
    names = [m.name[2:] if m.name.startswith('./') else m.name for m in members]
    under_data = bool(names) and all(n == 'data' or n.startswith('data/') for n in names)
    picked = []
    for m, n in zip(members, names):
        if under_data:
            if n == 'data':
                continue
            n = n[len('data/'):]
        base = os.path.basename(n.rstrip('/'))
        if not n or base in SKIP or base.endswith('.lock') or (base.startswith('backup_') and base.endswith('.sql')):
            continue
        m.name = n
        picked.append(m)
    try:
        tf.extractall(dest, members=picked, filter='data')
    except Exception as exc:
        print('@@ error data_archive %s: %s' % (type(exc).__name__, str(exc)[:200].replace('\n', ' ')))
        sys.exit(3)
files = sum(1 for m in picked if m.isfile())
print('@@ data_restore files=%d skipped=%d' % (files, len(members) - len(picked)))
PY
    then
      fail_from "$WORK/py.out"
    fi
    rm -f "$WORK/data.tar.gz"
    chown -R "$SVC_USER:$SVC_USER" "$DATA_DIR"
    echo "$DATA_ARCHIVE" > "$MARK"
    forward "$WORK/py.out"
  fi
fi

# ------------------------------------------------------------ 5-2. (--restore-db) 팀 EC2 백업의 행
DB_MARK="$HOME_DIR/.restored-db"
if [ -n "$RESTORE_DB" ] && [ -f "$DB_MARK" ]; then
  say "db_restore skipped already restored from $(head -c 120 "$DB_MARK")"
elif [ -n "$RESTORE_DB" ]; then
  aws s3 cp "$S3/data/$RESTORE_DB" "$WORK/backup.sql" --region "$REGION" --only-show-errors || fail "db_backup_download"
  set +e
  (
    set -a
    # shellcheck disable=SC1091
    . "$ETC/db.env"
    set +a
    # collect.backup_db 의 백업 파일 읽기(_scan)를 그대로 쓴다 — 형식을 만든 쪽과 읽는 쪽을 하나로 둔다
    cd "$REL_DIR/data-collection"
    exec "$REL_DIR/.venv/bin/python" -X utf8 - "$WORK/backup.sql"
  ) > "$WORK/py.out" <<'PY'
import os, sys, time

import pymysql

from collect import backup_db

path = sys.argv[1]
# 공고 · 판정 표 8개. 첨부 원본(attachment_files)은 넣지 않는다 — 매일 배치 9단계가 data/attachments 에서 다시 올린다
TABLES = tuple(backup_db.CORE_TABLES)


def stop(code, detail=''):
    print('@@ error %s %s' % (code, detail))
    sys.exit(3)


kw = dict(host=os.environ['MYSQL_HOST'], port=int(os.environ.get('MYSQL_PORT') or 3306),
          user=os.environ['MYSQL_USER'], password=os.environ['MYSQL_PASSWORD'],
          database=os.environ['MYSQL_DATABASE'], charset='utf8mb4', autocommit=False,
          max_allowed_packet=256 * 1024 * 1024, read_timeout=900, write_timeout=900)
if os.environ.get('MYSQL_SSL_CA'):
    kw.update(ssl_ca=os.environ['MYSQL_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
try:
    conn = pymysql.connect(**kw)
except Exception as exc:
    stop('db_connect', type(exc).__name__)

started = time.time()
rows = {}
try:
    with conn.cursor() as cur:
        busy = []
        for t in TABLES:
            cur.execute('SELECT COUNT(*) FROM `%s`' % t)
            n = cur.fetchone()[0]
            if n:
                busy.append('%s=%d' % (t, n))
        if busy:
            stop('db_not_empty', ','.join(busy) + ' (restore only into an empty notice DB)')
        cur.execute('SET FOREIGN_KEY_CHECKS = 0')
        cur.execute('SET UNIQUE_CHECKS = 0')

        def on_statement(table, statement):
            # 표는 up.sh 가 저장소 정의(schema-order.txt)로 이미 만들었다 — 백업의 DROP · CREATE 는 건너뛴다
            if not statement.lstrip().upper().startswith('INSERT INTO'):
                return
            cur.execute(statement)
            rows[table] = rows.get(table, 0) + cur.rowcount

        found = backup_db._scan(path, set(TABLES), on_statement=on_statement)
        if 'notices' not in found:
            stop('backup_layout', 'no notices section (make it with: python -m collect.backup_db)')
        bad = ['%s %d/%d' % (t, rows.get(t, 0), found[t]['rows']) for t in found if rows.get(t, 0) != found[t]['rows']]
        if bad:
            stop('row_count_mismatch', ','.join(bad))
        cur.execute('SET UNIQUE_CHECKS = 1')
        cur.execute('SET FOREIGN_KEY_CHECKS = 1')
    conn.commit()
except SystemExit:
    conn.rollback()
    raise
except Exception as exc:
    conn.rollback()
    stop('db_restore_failed', '%s: %s' % (type(exc).__name__, str(exc)[:200].replace('\n', ' ')))
finally:
    conn.close()

for t in TABLES:
    if t in found:
        print('@@ db_restore %s rows=%d' % (t, rows.get(t, 0)))
print('@@ db_restore done seconds=%d' % (time.time() - started))
PY
  rc=$?
  set -e
  rm -f "$WORK/backup.sql"
  [ "$rc" -eq 0 ] || fail_from "$WORK/py.out"
  echo "$RESTORE_DB" > "$DB_MARK"
  forward "$WORK/py.out"
fi

# ------------------------------------------------------------ 6. 서비스 바꾸기
SRC="$REL_DIR/infra/aws/notice"
install_unit() { tr -d '\r' < "$SRC/$1" > "/etc/systemd/system/$1" && chmod 644 "/etc/systemd/system/$1"; }
for unit in notice-server.service notice-batch.service notice-batch.timer; do
  install_unit "$unit" || fail "unit_install $unit"
done
systemctl daemon-reload

PREV=""
[ -L "$CURRENT" ] && PREV="$(readlink -f "$CURRENT" || true)"
point_current() { ln -sfn "$1" "$CURRENT.new" && mv -Tf "$CURRENT.new" "$CURRENT"; }
roll_back() {
  if [ -n "$PREV" ] && [ -d "$PREV" ] && [ "$PREV" != "$REL_DIR" ]; then
    point_current "$PREV"
    systemctl restart notice-server || true
    say "rollback current=$(basename "$PREV")"
  fi
}

point_current "$REL_DIR"
systemctl enable notice-server >/dev/null 2>&1 || true
systemctl restart notice-server || { roll_back; fail "server_start"; }
# 켤 때 공고 · 벡터 · BM25 · BGE-M3 를 메모리에 올린다(수십 초). 최대 5분 기다린다
ok=0
for _ in $(seq 1 100); do
  if curl -fsS --max-time 5 -o "$WORK/health.json" http://127.0.0.1:8000/api/health; then ok=1; break; fi
  sleep 3
done
if [ "$ok" != 1 ]; then
  journalctl -u notice-server -n 60 --no-pager || true
  roll_back
  fail "server_health http://127.0.0.1:8000/api/health did not answer (journalctl -u notice-server)"
fi

# 한글이 섞인 응답은 영어 요약으로만 넘긴다
python3 - "$WORK/health.json" > "$WORK/py.out" <<'PY' || true
import json, sys

h = json.load(open(sys.argv[1]))
types = h.get('applicant_types') or {}
print('@@ server health ok notices=%s vectors=%s bm25=%s applicant_types_used=%s'
      % (h.get('notices'), h.get('indexed'), h.get('bm25_indexed'), types.get('used')))
errors = sorted((h.get('boot_errors') or {}).keys())
if errors:
    print('@@ boot_errors ' + ','.join(errors))
PY
forward "$WORK/py.out"

code="$(curl -s --max-time 15 -o "$WORK/status.json" -w '%{http_code}' http://127.0.0.1:8000/api/collection_status || true)"
python3 - "$WORK/status.json" "${code:-000}" > "$WORK/py.out" <<'PY' || true
import json, sys

path, code = sys.argv[1:3]
try:
    status = json.load(open(path)).get('status')
except Exception:
    status = None
names = {'정상': 'ok', '지연': 'delayed', '실패': 'failed'}
print('@@ collection http=%s status=%s' % (code, names.get(status, status or 'unknown')))
PY
forward "$WORK/py.out"

# ------------------------------------------------------------ 7. 매일 배치
systemctl enable --now notice-batch.timer >/dev/null 2>&1 || fail "timer_enable notice-batch.timer"
say "timer next=$(systemctl show notice-batch.timer -p NextElapseUSecRealtime --value 2>/dev/null | tr ' ' '_')"
if [ "$RUN_BATCH" = 1 ]; then
  if systemctl is-active --quiet notice-batch.service; then
    say "batch already_running"
  else
    systemctl start --no-block notice-batch.service || fail "batch_start"
    say "batch started"
  fi
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
