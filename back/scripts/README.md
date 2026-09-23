# rhwp 설치·실행 가이드

사업계획서 `.hwp` 다운로드(`app/hwp_export.py`)는 [rhwp](https://github.com/edwardkim/rhwp)라는
외부 CLI를 써서 `.hwp` 원본 양식에 실제 내용을 채워 넣는다.

**Windows용 실행 파일을 공식 릴리즈에서 받으면 된다** — git엔 안 올라가 있으니(용량 문제)
각자 다운로드해서 `back/rhwp.exe`로 저장하면 된다.

## 1. 다운로드

**다운로드: https://github.com/edwardkim/rhwp/releases/tag/v0.8.6**

위 페이지에서 `rhwp-v0.8.6-windows-x86_64.zip`을 받아 압축을 풀고, 안에 있는 실행 파일을
`back/rhwp.exe`로 저장한다(파일명·위치 그대로 맞출 것).

## 2. `.env`에 경로 설정

`back/.env`(없으면 `.env.example` 복사)에 이 줄만 추가/확인:

```
RHWP_BIN=./rhwp.exe
```

(절대경로로 `C:\...\back\rhwp.exe`처럼 넣어도 된다. PATH에 이미 `rhwp`가 등록돼 있으면 안 채워도
기본값 `'rhwp'`로 PATH에서 찾는다.)

## 3. 확인

서버(`uvicorn app.main:app --reload`)를 켜고 아래 중 하나로 확인:

- `python verify_plan_document_hwp.py` (`back/`에서 실행) — 실제로 계획서를 만들어서 본문 삽입·개인정보
  삭제·협력기관 매핑까지 24개 항목을 자동 검증한다. `RHWP_BIN`이 안 잡혀 있으면 이 검증은
  자동으로 건너뛰고 0으로 종료된다.
- Swagger(`/docs`)에서 `GET /projects/{id}/plan-document.hwp` 직접 호출 — 200이면 성공,
  500이면 `RHWP_BIN` 경로가 잘못된 것.
