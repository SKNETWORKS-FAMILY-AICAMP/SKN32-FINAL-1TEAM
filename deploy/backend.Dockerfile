# syntax=docker/dockerfile:1
# 웹 백엔드(FastAPI) 이미지. 빌드 위치는 저장소 루트다(docker-compose.yml 의 context: ..).
#
# 백엔드 코드가 실행 중에 부르는 외부 프로그램 두 가지를 함께 넣는다.
#   LibreOffice — 사업계획서 docx → PDF (web/backend/app/pdf_export.py). 한글 폰트가 없으면 글자가 깨진다.
#   rhwp        — 사업계획서 .hwp 채우기 (web/backend/app/hwp_export.py). 공식 릴리즈의 리눅스판을 받는다.
FROM python:3.12-slim

ARG RHWP_VERSION=0.8.6
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui fonts-nanum ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# rhwp: 받은 파일을 릴리즈의 SHA256SUMS.txt 와 대조한 뒤에만 설치한다.
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) arch=x86_64 ;; \
      arm64) arch=aarch64 ;; \
      *) echo "rhwp 리눅스판이 없는 CPU: ${TARGETARCH}"; exit 1 ;; \
    esac; \
    file="rhwp-v${RHWP_VERSION}-linux-${arch}.tar.gz"; \
    base="https://github.com/edwardkim/rhwp/releases/download/v${RHWP_VERSION}"; \
    mkdir /tmp/rhwp && cd /tmp/rhwp; \
    curl -fsSLO "${base}/${file}"; \
    curl -fsSLO "${base}/SHA256SUMS.txt"; \
    grep -F "${file}" SHA256SUMS.txt | sha256sum -c -; \
    tar -xzf "${file}"; \
    install -m 755 "$(find . -type f -name rhwp | head -n 1)" /usr/local/bin/rhwp; \
    cd / && rm -rf /tmp/rhwp

WORKDIR /app
COPY web/backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY web/backend/ ./

# uploads/(첨부·산출물)와 logs/(요청 로그)는 코드가 /app 아래에 만든다. 볼륨으로 따로 보관한다.
RUN useradd --create-home --uid 10001 app \
 && mkdir -p uploads logs \
 && chown -R app:app /app
USER app

ENV RHWP_BIN=/usr/local/bin/rhwp \
    SOFFICE_BIN=/usr/bin/soffice

EXPOSE 8000
# 워커는 하나만 둔다. 생성 작업이 프로세스 안의 스레드로 돌고, 재시작 복구 루프도 프로세스마다 하나씩 뜬다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
