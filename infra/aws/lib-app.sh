# shellcheck shell=bash
# shellcheck disable=SC2154  # OUT_* 변수는 load_outputs 가 printf -v 로 채운다
# app-env.sh · deploy-app.sh 가 함께 쓰는 도우미. 직접 실행하지 않는다.
# lib.sh(설정 · 계정 확인 · 스택 결과)를 먼저 불러 쓰고, 서버 원격 실행(SSM)은 up.sh 와 같은 방식으로 한다.

# shellcheck source=infra/aws/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# 스택 결과를 읽고 앱 올리기에 필요한 값이 다 있는지 본다.
load_app_outputs() {
  load_outputs || die "스택 결과를 읽지 못했습니다. 먼저 'bash infra/aws/up.sh' 로 서버를 만드세요."
  local k v
  for k in WebInstanceId WebPublicIp DeployBucketName; do
    v="OUT_$k"
    [ -n "${!v:-}" ] || die "스택 결과에 $k 가 없습니다. 'bash infra/aws/up.sh' 를 다시 실행하세요."
  done
}

# 서버가 원격 실행(SSM)에 연결돼 있는지 본다. 첫 부팅 뒤 1~3분 걸린다(up.sh 와 같음).
wait_ssm_online() {
  local id="$1" label="$2" st
  printf '  %s 원격 실행 연결 확인' "$label"
  for _ in $(seq 1 60); do
    st="$(awsq ssm describe-instance-information --filters "Key=InstanceIds,Values=$id" \
      --query 'InstanceInformationList[0].PingStatus' 2>/dev/null || true)"
    if [ "$st" = Online ]; then
      echo " → 연결됨"
      return 0
    fi
    printf '.'
    sleep 10
  done
  echo
  die "$label($id)이 원격 실행(SSM)에 연결되지 않았습니다. 서버가 켜져 있는지 확인하세요."
}

# 서버에서 명령 한 줄을 root 로 실행하고 끝날 때까지 기다린다. 결과는 REMOTE_STATUS · REMOTE_OUT · REMOTE_ERR.
#   remote_run <인스턴스 ID> <짧은 이름> <보여 줄 이름> <최대 초> <명령>
# 명령에는 따옴표 · 역슬래시를 넣지 않는다(JSON 으로 그대로 보낸다). 비밀 값은 넣지 않는다 — 원격 실행 기록에 남는다.
remote_run() {
  local id="$1" tag="$2" label="$3" limit="$4" cmd="$5" cid polls
  local params_file="$BUILD_DIR/ssm-$tag.json"
  # shellcheck disable=SC1003
  case "$cmd" in *'"'*|*'\'*) die "원격 명령에 따옴표·역슬래시가 들어갔습니다: $cmd" ;; esac
  mkdir -p "$BUILD_DIR"
  printf '{"commands":["%s"],"executionTimeout":["%s"]}\n' "$cmd" "$limit" > "$params_file"
  cid="$(awsq ssm send-command --instance-ids "$id" --document-name AWS-RunShellScript \
    --comment "sbrain $tag" --timeout-seconds 600 \
    --parameters "file://$params_file" --query Command.CommandId)" \
    || die "$label 에 원격 실행을 보내지 못했습니다."

  REMOTE_STATUS=Pending
  polls=$(( limit / 5 + 12 ))
  printf '  %s 에서 실행 중' "$label"
  for _ in $(seq 1 "$polls"); do
    sleep 5
    REMOTE_STATUS="$(awsq ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
      --query Status 2>/dev/null || echo Pending)"
    case "$REMOTE_STATUS" in
      Pending|InProgress|Delayed) printf '.' ;;
      *) break ;;
    esac
  done
  echo " → $REMOTE_STATUS"
  REMOTE_OUT="$(awsq ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
    --query StandardOutputContent 2>/dev/null || true)"
  REMOTE_ERR="$(awsq ssm get-command-invocation --command-id "$cid" --instance-id "$id" \
    --query StandardErrorContent 2>/dev/null || true)"
  [ "$REMOTE_STATUS" = Success ]
}

# 서버 스크립트는 '@@ 키 값' 형식의 영어 한 줄로만 보고한다(윈도우 aws.exe 가 한글을 깨뜨릴 수 있어서).
# 여기서 한국어로 바꿔 보여 준다. 모르는 키는 그대로 보여 준다.
report_app_remote() {
  local label="$1" line key rest
  while IFS= read -r line; do
    case "$line" in "@@ "*) ;; *) continue ;; esac
    line="${line#@@ }"
    key="${line%% *}"
    rest="${line#"$key"}"
    rest="${rest# }"
    case "$key" in
      env_written)      echo "  [$label] env 파일 작성: $rest" ;;
      optional_missing) echo "  [$label] 넣지 않은 선택 값(그 기능만 꺼짐): $rest" ;;
      packages)         echo "  [$label] 서버 패키지 준비: $rest" ;;
      node)             echo "  [$label] Node: $rest" ;;
      rhwp)             echo "  [$label] rhwp(.hwp 내려받기): $rest" ;;
      release)          echo "  [$label] 코드 풀기: $rest" ;;
      venv)             echo "  [$label] 가상환경 설치: $rest" ;;
      frontend)         echo "  [$label] 프론트 빌드: $rest" ;;
      worker_stop)      echo "  [$label] 워커 멈춤(하던 단계를 끝내고): $rest" ;;
      worker_check)     echo "  [$label] 워커 한 바퀴 점검(--once): $rest" ;;
      worker)           echo "  [$label] 워커: $rest" ;;
      web)              echo "  [$label] 웹 백엔드: $rest" ;;
      nginx)            echo "  [$label] nginx: $rest" ;;
      https)            echo "  [$label] HTTPS: $rest" ;;
      https_pending)    warn "[$label] HTTPS 인증서를 아직 받지 못했습니다 — DNS 에서 도메인이 고정 IP 를 가리키는지 확인한 뒤 deploy-app.sh 를 다시 실행하세요 ($rest)" ;;
      cleanup)          echo "  [$label] 옛 코드 정리: $rest" ;;
      log)              echo "  [$label] 서버 기록 파일: $rest" ;;
      error)            ;;
      *)                echo "  [$label] $key $rest" ;;
    esac
  done <<< "$REMOTE_OUT"
}

# 실패했을 때 서버가 남긴 오류 한 줄과 오류 출력 끝부분을 보여 준다.
explain_app_error() {
  local label="$1" line
  line="$(printf '%s\n' "$REMOTE_OUT" | grep '^@@ error ' | tail -1 || true)"
  report_app_remote "$label"
  [ -n "$line" ] && echo "  서버 오류: ${line#@@ error }" >&2
  if [ -n "$REMOTE_ERR" ]; then
    { echo "--- $label 오류 출력 (마지막 20줄) ---"; printf '%s\n' "$REMOTE_ERR" | tail -20; } >&2
  fi
  return 0
}
