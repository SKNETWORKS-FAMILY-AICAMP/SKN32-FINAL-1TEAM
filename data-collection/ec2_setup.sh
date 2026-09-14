#!/usr/bin/env bash
# EC2 안에서 실행한다. 벡터 색인 갱신 환경을 만들고 매일 자동 갱신을 걸어둔다.
#
#   bash ec2_setup.sh
#
# 하는 일
#   1  ~/s-brain 에 파이썬 가상환경을 만든다
#   2  pymysql · numpy · chromadb 를 넣는다 (torch 는 넣지 않는다)
#   3  .env 를 만든다 (127.0.0.1 로 붙으므로 TLS 없음)
#   4  색인을 처음 만든다
#   5  crontab 에 매일 09:10 갱신을 등록한다
#
# 여러 번 실행해도 안전하다. 이미 있는 것은 건너뛴다.
set -euo pipefail

DIR="$HOME/s-brain"
PY="$DIR/.venv/bin/python"

echo "== 1. 디렉터리 =="
mkdir -p "$DIR/data"
cd "$DIR"
if [ ! -f ec2_vecstore.py ]; then
    echo "  ec2_vecstore.py 가 없습니다. 먼저 이 디렉터리로 복사하세요:"
    echo "    scp -i <키> ec2_vecstore.py ubuntu@<서버>:~/s-brain/"
    exit 1
fi
echo "  $DIR"

echo "== 2. 가상환경 =="
if [ ! -x "$PY" ]; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-venv python3-dev build-essential
    python3 -m venv .venv
fi
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet "PyMySQL[rsa]>=1.1,<2" "numpy>=1.26" "chromadb>=1.0"
echo "  설치 완료: $("$PY" -c 'import pymysql,numpy,chromadb; print("pymysql",pymysql.__version__,"numpy",numpy.__version__,"chromadb",chromadb.__version__)')"

echo "== 3. .env =="
if [ ! -f .env ]; then
    cat > .env <<'ENVEOF'
# EC2 안에서 도는 색인 갱신용. MySQL 이 같은 서버에 있으므로 127.0.0.1 로 붙는다.
#
# 이 서버는 require_secure_transport=ON 이라 같은 기계 안에서 붙어도 평문을
# 거부한다. 그래서 TLS 를 켜야 한다.
#
#   MYSQL_SSL=1     암호화만 하고 서버 인증서는 검증하지 않는다
#
# 루프백(127.0.0.1)이라 중간에서 가로챌 구간이 없어 인증서 검증이 의미가 없다.
# 검증까지 하려면 MYSQL_SSL 을 비우고 아래를 쓴다. 서버 인증서에 IP 이름이
# 없어서 코드가 hostname 검사를 끈다.
#
#   MYSQL_SSL_CA=/home/ubuntu/s-brain/ec2-ca.pem
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_DATABASE=s_brain
MYSQL_USER=s_brain_team
MYSQL_PASSWORD=
MYSQL_SSL=1
MYSQL_SSL_CA=
ENVEOF
    chmod 600 .env
    echo "  .env 를 만들었습니다. MYSQL_PASSWORD 를 채우고 다시 실행하세요."
    echo "  비밀번호 위치: /home/ubuntu/.config/s-brain/db.env 의 DB_PASSWORD"
    exit 1
fi
if ! grep -q '^MYSQL_PASSWORD=.\+' .env; then
    echo "  MYSQL_PASSWORD 가 비어 있습니다. .env 를 채우고 다시 실행하세요."
    exit 1
fi
echo "  확인됨"

echo "== 4. 색인 생성 =="
"$PY" ec2_vecstore.py --stat || true
"$PY" ec2_vecstore.py
echo
"$PY" ec2_vecstore.py --stat

echo "== 5. crontab =="
# PC 배치가 09:00 에 시작해 약 80초 걸린다. 끝난 뒤인 09:10 에 갱신한다.
LINE="10 9 * * * cd $DIR && $PY ec2_vecstore.py >> $DIR/data/vecstore.log 2>&1"
if crontab -l 2>/dev/null | grep -qF 'ec2_vecstore.py'; then
    echo "  이미 등록돼 있습니다:"
    crontab -l | grep -F 'ec2_vecstore.py'
else
    # crontab 이 아직 하나도 없으면 `crontab -l` 이 실패한다. set -e 가 켜져 있어
    # 그대로 두면 서브셸이 거기서 죽고 echo 가 실행되지 않는다. || true 로 막는다.
    { crontab -l 2>/dev/null || true; echo "$LINE"; } | crontab -
    echo "  등록했습니다: 매일 09:10"
    crontab -l | grep -F 'ec2_vecstore.py'
fi

echo
echo "완료. 확인 방법:"
echo "  $PY ec2_vecstore.py --stat        색인 상태"
echo "  tail -20 $DIR/data/vecstore.log   갱신 기록"
echo "  crontab -l                        예약 확인"
