# syntax=docker/dockerfile:1
# 화면(React) 빌드 + Caddy. 빌드 위치는 저장소 루트다(docker-compose.yml 의 context: ..).
#
# Caddy 한 컨테이너가 세 가지를 한다.
#   /        빌드한 화면 파일을 내준다
#   /api/*   앞의 /api 를 떼고 백엔드로 넘긴다 → 화면과 API 가 같은 주소라 CORS·쿠키 문제가 없다
#   HTTPS    SITE_ADDRESS 에 도메인을 넣으면 인증서를 자동으로 받는다(Let's Encrypt)

FROM node:22-alpine AS build
WORKDIR /src
COPY web/frontend/package.json web/frontend/package-lock.json ./
RUN npm ci
COPY web/frontend/ ./
# 빌드할 때 화면 코드에 박히는 값이다. 바꾸면 다시 빌드해야 한다.
ARG VITE_GOOGLE_CLIENT_ID=""
ARG VITE_API_BASE=/api
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID} \
    VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
