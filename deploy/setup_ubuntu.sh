#!/usr/bin/env bash
# 새 Ubuntu EC2 에서 한 번만 돌린다. Docker 와 스왑을 준비한다.
#
#   bash deploy/setup_ubuntu.sh
#
# 끝나면 한 번 로그아웃했다가 다시 접속한다(docker 그룹 반영).
set -euo pipefail

echo "== 1. 패키지 =="
sudo apt-get update
# Ubuntu 기본 저장소의 Docker 와 compose 플러그인. 외부 설치 스크립트를 내려받아 실행하지 않는다.
sudo apt-get install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker

echo "== 2. docker 그룹 =="
sudo usermod -aG docker "$USER"

echo "== 3. 스왑 2GB =="
# 4GB 서버에서 빌드(npm·LibreOffice 설치)나 PDF 변환이 겹칠 때 메모리 부족으로 죽지 않게 하는 안전망.
if swapon --show | grep -q '/swapfile'; then
    echo "이미 있음"
else
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    grep -qF '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo "== 확인 =="
docker --version
docker compose version
free -h
echo
echo "다음: 로그아웃 후 다시 접속 → cd deploy → cp .env.example .env → 값 채우기 → docker compose up -d --build"
