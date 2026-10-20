#!/usr/bin/env bash
# shellcheck disable=SC2154  # OUT_* 변수는 load_outputs 가 printf -v 로 채운다
# S-Brain 공고 서버 올리기 — 이 저장소의 커밋 하나를 공고 서버에 설치하고 공고 서버 · 매일 배치를 띄운다
#
#   bash infra/aws/deploy-notice.sh                          # 지금 갈래의 마지막 커밋(HEAD)을 올린다
#   bash infra/aws/deploy-notice.sh --data data.tar.gz --restore-db backup.sql
#                                                            # 처음 한 번: 배치 서버 data/ · 팀 EC2 공고 표를 새 서버 · 새 DB 로 옮긴다
#   bash infra/aws/deploy-notice.sh --run-batch              # 올린 뒤 매일 배치를 한 번 바로 시작한다(끝나기를 기다리지 않는다)
#   bash infra/aws/deploy-notice.sh --reset OPENAI_API_KEY   # 그 수집 키를 다시 넣는다(여러 번 줄 수 있다)
#   bash infra/aws/deploy-notice.sh --worktree               # 시험용: 커밋하지 않은 지금 파일로 올린다(.gitignore 에 든 .env · data/ 등은 빠진다)
#   공통 옵션: --profile 이름 · --region 리전 · --stack 이름 · --yes (up.sh 와 같다)
#
# 먼저(한 번씩): bash infra/aws/up.sh — 공고 서버 · DB · 이 스크립트가 쓰는 공고 서버 권한(NoticeAppPolicy)
# 수집 키: KSTARTUP_KEY · BIZINFO_KEY · OPENAI_API_KEY — 없는 값만 묻고 SSM Parameter Store /<스택>/notice/<이름>(SecureString)에 둔다.
#   입력하는 글자는 화면 · 명령줄 · 원격 실행 기록에 나오지 않는다. down.sh 는 이 값을 지우지 않는다.
# 올리는 것: 그 커밋의 data-collection/(docs/ 제외) · infra/aws/notice/ (git archive — 커밋 안 된 변경 · .env 는 들어가지 않는다)
# 서버에서 하는 일: infra/aws/notice/install-notice.sh — 가상환경 · BGE-M3 · 설정 파일 · (데이터 옮기기) · 공고 서버 · 매일 배치 예약.
#   공고 서버가 응답하지 않으면 바로 앞 코드로 되돌린다. 끝나면 웹 서버에서 공고 서버 8000 번에 닿는지 확인한다.
# 걸리는 시간: 처음 15~30분(torch · BGE-M3 내려받기 · 데이터 옮기기), 다음부터 5~10분.
#
# 옮길 데이터 만들기 (처음 한 번 — 그날 매일 배치가 끝난 뒤에. 수집 상태는 마지막 저장이 24시간 안이어야 '정상'이다)
#   data.tar.gz : 매일 배치를 돌리던 서버에서   tar -czf data.tar.gz -C <data-collection 폴더> data
#   backup.sql  : 팀 EC2 DB 에 닿는 PC 에서      python -m collect.backup_db --out backup.sql   (--include-files 는 쓰지 않는다 —
#                 첨부 원본은 매일 배치 9단계가 data/attachments 에서 다시 올린다)
#   옮긴 뒤에는 옛 배치 서버의 매일 예약을 끈다. 두 곳에서 돌면 같은 날 배치가 두 번 돈다.
set -euo pipefail
# lib.sh 가 저장소 루트로 옮겨 가기 전에, 사람이 적은 상대 경로의 기준을 기억해 둔다
ORIG_PWD="$PWD"
# shellcheck source=infra/aws/lib-app.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib-app.sh"

usage() {
  cat <<'EOF'
사용법: bash infra/aws/deploy-notice.sh [옵션]
  --ref 커밋            올릴 커밋 · 갈래 · 태그 (기본: HEAD)
  --worktree            시험용: 커밋하지 않은 지금 파일로 올린다 (--ref 와 함께 쓰지 않는다)
  --data 파일           배치 서버 data/ 묶음(.tar.gz)을 공고 서버 데이터 폴더에 푼다 (처음 한 번)
  --restore-db 파일     팀 EC2 백업(collect.backup_db 의 .sql)의 공고 표 8개를 빈 새 DB 에 넣는다 (처음 한 번)
  --run-batch           올린 뒤 매일 배치를 한 번 바로 시작한다
  --reset 이름          그 수집 키를 다시 넣는다 (KSTARTUP_KEY · BIZINFO_KEY · OPENAI_API_KEY)
  --profile 이름        다른 AWS 계정(프로필)
  --region 리전         리전 (기본: settings.env 의 REGION)
  --stack 이름          스택 이름 (기본: sbrain)
  --yes                 확인 질문 없이 진행 (값 입력은 그래도 묻는다)
EOF
}

NAMES="KSTARTUP_KEY BIZINFO_KEY OPENAI_API_KEY"
is_word_in() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
# 사람이 적은 파일 경로 → 절대 경로(bash 용) · aws.exe 가 읽는 경로(윈도우 Git Bash 면 C:\...)
abs_path() { case "$1" in /*|[A-Za-z]:[\\/]*) printf '%s' "$1" ;; *) printf '%s/%s' "$ORIG_PWD" "$1" ;; esac; }
aws_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

parse_common_args "$@"
REF=HEAD
REF_GIVEN=0
WORKTREE=0
DATA_FILE=""
DB_FILE=""
RUN_BATCH=0
RESETS=""
set -- ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)        [ $# -ge 2 ] || die "--ref 뒤에 커밋을 적으세요."; REF="$2"; REF_GIVEN=1; shift 2 ;;
    --worktree)   WORKTREE=1; shift ;;
    --data)       [ $# -ge 2 ] || die "--data 뒤에 파일을 적으세요."; DATA_FILE="$(abs_path "$2")"; shift 2 ;;
    --restore-db) [ $# -ge 2 ] || die "--restore-db 뒤에 파일을 적으세요."; DB_FILE="$(abs_path "$2")"; shift 2 ;;
    --run-batch)  RUN_BATCH=1; shift ;;
    --reset)
      [ $# -ge 2 ] || die "--reset 뒤에 이름을 적으세요."
      is_word_in "$2" "$NAMES" || die "모르는 이름입니다: $2 (쓸 수 있는 이름: $NAMES)"
      RESETS="$RESETS $2"
      shift 2 ;;
    *) usage >&2; die "모르는 옵션: $1" ;;
  esac
done

load_settings
require_cli
command -v git >/dev/null 2>&1 || die "git 이 없습니다."
[ "$WORKTREE" = 1 ] && [ "$REF_GIVEN" = 1 ] && die "--worktree 와 --ref 는 함께 쓸 수 없습니다."

if [ -n "$DATA_FILE" ]; then
  [ -f "$DATA_FILE" ] || die "--data 파일이 없습니다: $DATA_FILE"
  case "$DATA_FILE" in *.tar.gz|*.tgz) ;; *) die "--data 는 tar -czf 로 만든 .tar.gz 묶음이어야 합니다: $DATA_FILE" ;; esac
fi
if [ -n "$DB_FILE" ]; then
  [ -f "$DB_FILE" ] || die "--restore-db 파일이 없습니다: $DB_FILE"
  grep -q -m1 -E '^-- notices \([0-9]+행\)$' "$DB_FILE" \
    || die "collect.backup_db 로 만든 백업이 아닙니다(notices 구역이 없음): $DB_FILE"
  if grep -q -m1 -E '^-- attachment_files \(' "$DB_FILE"; then
    warn "백업에 첨부 원본(attachment_files)이 들어 있습니다. 서버는 이 표를 넣지 않습니다(매일 배치 9단계가 다시 올림) — 올리는 시간만 늘어납니다."
  fi
fi

PREFIX="/$STACK_NAME/notice"
mkdir -p "$BUILD_DIR"
PARAM_FILE="$BUILD_DIR/notice-param.json"

step "1/6 어느 계정에 올리는지 확인"
show_identity
if [ "$WORKTREE" = 1 ]; then
  # 지금 파일의 스냅샷(트리)을 임시 색인으로 만든다 — 커밋 · 갈래 · 진짜 색인은 건드리지 않는다.
  # git add 를 거치므로 .gitignore 에 든 파일(.env · .venv · data/ 등)은 빠지고 줄바꿈은 커밋할 때처럼 LF 로 맞춰진다
  TMP_INDEX="$BUILD_DIR/notice-worktree.index"
  rm -f "$TMP_INDEX"
  GIT_INDEX_FILE="$TMP_INDEX" git read-tree HEAD || die "임시 색인을 만들지 못했습니다."
  GIT_INDEX_FILE="$TMP_INDEX" git add -A -- data-collection infra/aws/notice || { rm -f "$TMP_INDEX"; die "지금 파일을 묶지 못했습니다."; }
  SHA="$(GIT_INDEX_FILE="$TMP_INDEX" git write-tree)" || { rm -f "$TMP_INDEX"; die "지금 파일을 묶지 못했습니다."; }
  rm -f "$TMP_INDEX"
  HEAD_TREE="$(git rev-parse HEAD^{tree})"
  echo "  올릴 코드 : 지금 파일 (커밋 안 됨 — 기준 커밋 $(git rev-parse --short=12 HEAD))"
  changed="$(git diff --name-status "$HEAD_TREE" "$SHA" -- data-collection infra/aws/notice)"
  if [ -n "$changed" ]; then
    echo "  커밋과 다른 파일 $(printf '%s\n' "$changed" | wc -l | tr -d ' ')개:"
    printf '%s\n' "$changed" | head -15 | sed 's/^/    /'
  fi
else
  SHA="$(git rev-parse --verify --quiet "$REF^{commit}")" || die "커밋을 찾지 못했습니다: $REF"
  echo "  올릴 커밋 : ${SHA:0:12} ($(git log -1 --format=%s "$SHA" | cut -c1-70))"
fi
[ -n "$DATA_FILE" ] && echo "  data/ 묶음: $DATA_FILE ($(( $(wc -c < "$DATA_FILE") / 1024 / 1024 ))MB) → 공고 서버 데이터 폴더 (처음 한 번)"
[ -n "$DB_FILE" ] && echo "  DB 백업   : $DB_FILE ($(( $(wc -c < "$DB_FILE") / 1024 / 1024 ))MB) → 빈 새 DB 의 공고 표 (처음 한 번)"
[ "$RUN_BATCH" = 1 ] && echo "  매일 배치 : 올린 뒤 한 번 바로 시작"
if [ "$WORKTREE" = 0 ] && [ "$REF" = HEAD ] && [ -n "$(git status --porcelain -- data-collection infra/aws/notice 2>/dev/null)" ]; then
  warn "커밋하지 않은 변경이 있습니다. 올라가는 것은 마지막 커밋뿐입니다(git status 로 확인). 지금 파일로 시험하려면 --worktree"
fi
if [ "$WORKTREE" = 1 ]; then what="지금 파일을"; else what="이 커밋을"; fi
confirm "$what 공고 서버에 올리고 공고 서버 · 매일 배치를 다시 띄울까요?"

step "2/6 수집 키 (입력하는 글자는 화면에 보이지 않습니다)"
echo "  값 이름    : $PREFIX/<이름>"
EXISTING="$(awsq ssm get-parameters-by-path --path "$PREFIX" --query 'Parameters[].Name' | tr '\t' '\n' | sed -e '/^$/d' -e '/^None$/d')" \
  || die "Parameter Store 를 읽지 못했습니다. 로그인 정보 · 권한을 확인하세요."
has_param() { printf '%s\n' "$EXISTING" | grep -qx "$PREFIX/$1"; }

# 값을 JSON 파일로 넘긴다 — 명령줄(프로세스 목록)에 값이 드러나지 않게
put_param() {
  local name="$1" value="$2"
  ( umask 077
    printf '{"Name":"%s","Value":"%s","Type":"SecureString","Overwrite":true}\n' "$PREFIX/$name" "$value" > "$PARAM_FILE" )
  awsq ssm put-parameter --cli-input-json "file://$PARAM_FILE" --query Version >/dev/null \
    || { rm -f "$PARAM_FILE"; die "$name 을 넣지 못했습니다."; }
  rm -f "$PARAM_FILE"
}

for name in $NAMES; do
  if has_param "$name" && ! is_word_in "$name" "$RESETS"; then
    echo "  $name: 이미 있음(그대로 둠 — 바꾸려면 --reset $name)"
    continue
  fi
  value=""
  read -r -s -p "  $name 값: " value || true
  echo
  value="$(printf '%s' "$value" | tr -d '\r')"
  [ -n "$value" ] || die "$name 은 필수입니다(매일 배치가 씁니다)."
  # 서버의 env 파일(systemd)이 따로 풀어 읽는 글자(따옴표 · 빈칸 · 역슬래시 등)는 받지 않는다
  [[ "$value" =~ ^[A-Za-z0-9._~:/?#@!+=,%-]+$ ]] || die "$name 값에 쓸 수 없는 글자(따옴표 · 빈칸 · 역슬래시 등)가 있습니다."
  put_param "$name" "$value"
  echo "  $name: 넣었습니다."
done
value=""

step "3/6 올릴 코드 묶기"
if [ "$WORKTREE" = 1 ]; then NAME="$(date -u +%Y%m%d%H%M%S)-wt-${SHA:0:10}"; else NAME="$(date -u +%Y%m%d%H%M%S)-${SHA:0:10}"; fi
BUNDLE="$BUILD_DIR/notice-$NAME.tar.gz"
TOOL="$BUILD_DIR/install-notice.sh"
trap 'rm -f "$BUNDLE" "$PARAM_FILE"' EXIT
# 윈도우에서 줄바꿈이 CRLF 로 바뀌어 나오지 않게 이 명령에서만 줄바꿈 변환을 끈다(서버는 리눅스). 문서(docs/)는 서버에 필요 없다
git -c core.autocrlf=false -c core.eol=lf archive --format=tar.gz -o "$BUNDLE" "$SHA" -- \
    data-collection infra/aws/notice ':(exclude)data-collection/docs' \
  || die "코드를 묶지 못했습니다(그 커밋에 data-collection · infra/aws/notice 가 모두 있어야 합니다)."
git -c core.autocrlf=false show "$SHA:infra/aws/notice/install-notice.sh" | tr -d '\r' > "$TOOL" \
  || die "그 커밋에 infra/aws/notice/install-notice.sh 가 없습니다."
echo "  묶음: $NAME ($(( $(wc -c < "$BUNDLE") / 1024 / 1024 ))MB)"

step "4/6 S3 에 올리기"
load_app_outputs
for k in NoticeInstanceId NoticePrivateIp; do
  v="OUT_$k"
  [ -n "${!v:-}" ] || die "스택 결과에 $k 가 없습니다. 'bash infra/aws/up.sh' 를 다시 실행하세요."
done
S3="s3://$OUT_DeployBucketName/deploy/notice"
aws s3 cp "$BUNDLE" "$S3/releases/$NAME.tar.gz" --only-show-errors || die "코드 묶음을 S3 에 올리지 못했습니다."
aws s3 cp "$TOOL" "$S3/tools/install-notice.sh" --only-show-errors || die "설치 스크립트를 S3 에 올리지 못했습니다."
echo "  올렸습니다: deploy/notice/releases/$NAME.tar.gz"
DATA_KEY=""
DB_KEY=""
if [ -n "$DATA_FILE" ]; then
  DATA_KEY="$NAME-data.tar.gz"
  aws s3 cp "$(aws_path "$DATA_FILE")" "$S3/data/$DATA_KEY" --only-show-errors || die "data/ 묶음을 S3 에 올리지 못했습니다."
  echo "  올렸습니다: deploy/notice/data/$DATA_KEY (끝나면 지운다)"
fi
if [ -n "$DB_FILE" ]; then
  DB_KEY="$NAME-db.sql"
  aws s3 cp "$(aws_path "$DB_FILE")" "$S3/data/$DB_KEY" --only-show-errors || die "DB 백업을 S3 에 올리지 못했습니다."
  echo "  올렸습니다: deploy/notice/data/$DB_KEY (끝나면 지운다)"
fi
# 옮긴 데이터는 서버가 받아 간 뒤 S3 에 남겨 두지 않는다
remove_data_objects() {
  local k
  for k in "$DATA_KEY" "$DB_KEY"; do
    [ -n "$k" ] || continue
    aws s3 rm "$S3/data/$k" --only-show-errors >/dev/null 2>&1 || warn "S3 에 옮긴 데이터가 남았습니다: deploy/notice/data/$k"
  done
}

# 서버 스크립트는 '@@ 키 값' 형식의 영어 한 줄로만 보고한다. 여기서 한국어로 바꿔 보여 준다. 모르는 키는 그대로 보여 준다.
report_notice() {
  local label="$1" line key rest
  while IFS= read -r line; do
    case "$line" in "@@ "*) ;; *) continue ;; esac
    line="${line#@@ }"
    key="${line%% *}"
    rest="${line#"$key"}"
    rest="${rest# }"
    case "$key" in
      log)          echo "  [$label] 서버 기록 파일: $rest" ;;
      packages)     echo "  [$label] 서버 패키지 준비: $rest" ;;
      account)      echo "  [$label] 계정 · 데이터 폴더: $rest" ;;
      env_written)  echo "  [$label] 설정 파일 작성: $rest" ;;
      release)      echo "  [$label] 코드 풀기: $rest" ;;
      venv)         echo "  [$label] 가상환경 설치: $rest" ;;
      model)        echo "  [$label] 임베딩 모델: $rest" ;;
      data_restore) echo "  [$label] data/ 옮기기: $rest" ;;
      db_restore)   echo "  [$label] DB 옮기기: $rest" ;;
      server)       echo "  [$label] 공고 서버: $rest" ;;
      boot_errors)  warn "[$label] 공고 서버는 켜졌지만 일부를 올리지 못했습니다: $rest (공고 데이터가 아직 없으면 정상 — 옮기기 · 배치 뒤 다시 확인)" ;;
      collection)   echo "  [$label] 수집 상태: $rest (ok = 정상 · delayed = 지연 · failed = 실패)" ;;
      timer)        echo "  [$label] 매일 배치(한국 09:00) 다음 실행: $rest" ;;
      batch)        echo "  [$label] 매일 배치: $rest (서버에서 journalctl -u notice-batch -f)" ;;
      rollback)     warn "[$label] 바로 앞 코드로 되돌렸습니다: $rest" ;;
      cleanup)      echo "  [$label] 옛 코드 정리: $rest" ;;
      error)        ;;
      *)            echo "  [$label] $key $rest" ;;
    esac
  done <<< "$REMOTE_OUT"
}

step "5/6 공고 서버에 설치 · 다시 띄우기"
wait_ssm_online "$OUT_NoticeInstanceId" "공고 서버"
# 첫 부팅 설치(aws CLI 등)가 끝나기를 최대 10분 기다린 뒤 실행한다(up.sh 와 같음). $PATH · $(seq) 는 서버에서 풀린다
# shellcheck disable=SC2016
cmd='export PATH=$PATH:/snap/bin; for i in $(seq 1 120); do [ -f /var/lib/sbrain-userdata.done ] && break; sleep 5; done; '
cmd+="mkdir -p /opt/sbrain-notice/tools && aws s3 cp $S3/tools/install-notice.sh /opt/sbrain-notice/tools/install-notice.sh --only-show-errors --region $REGION"
cmd+=" && bash /opt/sbrain-notice/tools/install-notice.sh --region $REGION --stack $STACK_NAME --bucket $OUT_DeployBucketName --release $NAME"
[ -n "$DATA_KEY" ] && cmd+=" --data $DATA_KEY"
[ -n "$DB_KEY" ] && cmd+=" --restore-db $DB_KEY"
[ "$RUN_BATCH" = 1 ] && cmd+=" --run-batch"
if ! remote_run "$OUT_NoticeInstanceId" deploy-notice "공고 서버" 5400 "$cmd"; then
  report_notice "공고 서버"
  line="$(printf '%s\n' "$REMOTE_OUT" | grep '^@@ error ' | tail -1 || true)"
  [ -n "$line" ] && echo "  서버 오류: ${line#@@ error }" >&2
  if [ -n "$REMOTE_ERR" ]; then
    { echo "--- 공고 서버 오류 출력 (마지막 20줄) ---"; printf '%s\n' "$REMOTE_ERR" | tail -20; } >&2
  fi
  remove_data_objects
  case "$REMOTE_OUT$REMOTE_ERR" in
    *AccessDenied*|*"403"*|*Forbidden*)
      echo "  → 공고 서버 권한이 아직 없습니다. 템플릿의 NoticeAppPolicy 를 반영하려면 'bash infra/aws/up.sh' 를 다시 실행하세요." >&2 ;;
    *db_not_empty*)
      echo "  → 새 DB 의 공고 표가 비어 있지 않아 옮기지 않았습니다. 이미 옮겼다면 --restore-db 없이 다시 실행하세요." >&2 ;;
    *data_dir_not_empty*)
      echo "  → 이 서버가 이미 배치를 돌려 data/ 를 덮어쓰지 않았습니다. --data 없이 다시 실행하세요." >&2 ;;
  esac
  die "공고 서버 올리기에 실패했습니다 (상태: $REMOTE_STATUS). 서버 기록: /var/log/sbrain/notice-deploy/$NAME.log"
fi
report_notice "공고 서버"
remove_data_objects

step "6/6 웹 서버에서 공고 서버 확인"
URL="http://$OUT_NoticePrivateIp:8000/api/collection_status"
code=""
remote_run "$OUT_WebInstanceId" notice-check "웹 서버" 120 "curl -s --max-time 15 -o /dev/null -w HTTP=%{http_code} $URL" || true
code="$(printf '%s' "$REMOTE_OUT" | grep -o 'HTTP=[0-9]*' | tail -1 | cut -d= -f2 || true)"
case "$code" in
  200) echo "  웹 서버 → 공고 서버: 200 (닿음)" ;;
  ""|000) warn "웹 서버에서 공고 서버($URL)에 닿지 않습니다. 공고 서버에서 'systemctl status notice-server' 를 확인하세요." ;;
  *) warn "웹 서버 → 공고 서버: HTTP $code (503 이면 공고 서버가 DB 를 읽지 못한 것 — 'journalctl -u notice-server -n 100')" ;;
esac

echo
echo "공고 서버 주소(웹 서버 안에서만): http://$OUT_NoticePrivateIp:8000"
echo "다음: 'bash infra/aws/app-env.sh' 에서 SBRAIN_NOTICE_API_URL 에 위 주소를 넣고 'bash infra/aws/deploy-app.sh' (이미 넣었으면 그대로)"
echo "서버 상태: ssh -F $OUT_DIR/ssh_config $STACK_NAME-notice 로 들어가 'systemctl status notice-server' · 'systemctl list-timers notice-batch.timer' · 'journalctl -u notice-batch -n 100'"
