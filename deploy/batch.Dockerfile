# syntax=docker/dockerfile:1
# 매일 수집 배치(data-collection) 실행 환경. 코드·데이터·.env 는 이미지에 넣지 않고 실행할 때 붙인다
# (docker-compose.yml 의 batch 서비스). 코드가 바뀌어도 이미지를 다시 만들 필요가 없다.
FROM python:3.12-slim

ARG TORCH_VERSION=2.14.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# CPU 판 torch. 기본 저장소의 torch 는 CUDA 판이라 이미지가 수 GB 커진다.
RUN pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu

COPY deploy/batch-requirements.txt /tmp/batch-requirements.txt
RUN pip install -r /tmp/batch-requirements.txt && rm /tmp/batch-requirements.txt

# 서버의 ubuntu 계정(uid 1000)과 같은 번호로 돌려, 붙인 폴더에 쓴 파일의 주인이 ubuntu 가 되게 한다.
# 임베딩 모델 캐시는 /home/app/.cache/huggingface (볼륨) — shared/embed.py 가 ~/.cache 경로를 읽는다.
RUN useradd --create-home --uid 1000 app \
 && mkdir -p /home/app/.cache/huggingface \
 && chown -R app:app /home/app
USER app
WORKDIR /app/data-collection

CMD ["python", "-m", "collect.daily_pipeline"]
