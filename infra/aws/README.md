# AWS 원버튼 배포 (infra/aws)

명령 한 줄로 서버 두 대, 고정 IP, RDS MySQL, 테이블 세팅까지 만들고, 한 줄로 전부 지운다.
AWS 계정을 바꿔도 같은 명령으로 그대로 돌아간다.

```bash
bash infra/aws/up.sh      # 만들기 (처음 15~20분)
bash infra/aws/down.sh    # 전부 지우기
```

비유하면 `sbrain-stack.yml`은 **주문서**, AWS CloudFormation은 **주방**이다. 주문서를 넘기면 주방이 순서대로 만들고,
중간에 실패하면 만들던 것을 스스로 치운다. "다 치워 줘"도 주문서 이름 하나로 끝난다.

## 무엇이 만들어지나

```
AWS 클라우드 (리전)
├─ VPC 10.20.0.0/16
│   ├─ Internet Gateway                 인터넷과 VPC 사이의 문
│   ├─ 공개 서브넷 10.20.1.0/24
│   │   ├─ [웹 EC2]                     고정 IP · nginx (웹 · 워커)
│   │   └─ [NAT 게이트웨이]             고정 IP · 사설 서브넷이 밖으로 나갈 때만
│   ├─ 사설 서브넷 A 10.20.11.0/24
│   │   ├─ [공고 서버 EC2]              내부 고정 주소 10.20.11.10 · 바깥 주소 없음
│   │   └─ [RDS MySQL 8.4]              DB s_brain · 테이블 56개 · 바깥 공개 안 함
│   ├─ 사설 서브넷 B 10.20.12.0/24      RDS 예비 자리
│   └─ S3 게이트웨이 엔드포인트         두 서브넷 → S3 (무료)
└─ [S3 버킷]  ← VPC 밖(리전 서비스)
       bootstrap/ = DB 세팅 묶음, deploy/ = 코드 묶음(deploy-app.sh), app/ = 앱이 쓸 자리
```

| 흐름 | 지나는 길 |
|---|---|
| 사용자 → 웹 | 인터넷 → Internet Gateway → 웹 EC2 (80 · 443) |
| 웹 → 공고 서버 | VPC 안 사설 IP로 바로 (8000, 웹에서만). NAT를 거치지 않는다 |
| 웹 · 공고 서버 → RDS | VPC 안 사설 IP로 바로 (3306, 두 서버에서만). NAT를 거치지 않는다 |
| 웹 → 외부 (OpenAI · KIET 등) | Internet Gateway로 바로 (웹 EC2의 고정 IP) |
| 공고 서버 → 외부 (K-Startup · OpenAI · 모델 내려받기) | NAT 게이트웨이(공개 서브넷) → Internet Gateway |
| 웹 · 공고 서버 → S3 | S3 게이트웨이 엔드포인트. NAT · 인터넷을 거치지 않는다 |

- VPC 안 통신은 라우팅 테이블마다 AWS가 자동으로 넣는 VPC 대역(10.20.0.0/16) 경로를 탄다. 이 경로가 바깥으로 나가는 기본 경로(0.0.0.0/0)보다 먼저라 NAT · Internet Gateway를 거치지 않는다.
- S3 게이트웨이 엔드포인트는 공개 · 사설 라우팅 테이블 모두에 붙어 있다. 같은 리전의 S3로 가는 길만 바꾼다.

| 만드는 것 | 내용 |
|---|---|
| 웹 EC2 | `c7i-flex.large`(4GB), Ubuntu 24.04, 고정 IP(탄력적 IP) 연결, nginx 설치 |
| 공고 서버 EC2 | `m7i-flex.large`(8GB), 바깥 주소 없음, 내부 고정 주소 `10.20.11.10`, 스왑 2GB |
| RDS | MySQL 8.4, `db.t4g.micro`, 20GB, 암호화, 1일 백업 |
| DB 세팅 | `s_brain` DB, [schema-order.txt](schema-order.txt) 순서대로 SQL 10개 적용, 앱 계정 `sbrain_app` |
| 접속 정보 파일 | 두 서버의 `/etc/sbrain/db.env` (`MYSQL_HOST` · `MYSQL_USER` · `MYSQL_PASSWORD` … 기존 `.env`와 같은 이름) |
| SSH | 키는 `~/.ssh/<스택>-<리전>.pem`에 자동 저장, 22번은 지금 PC의 IP만 허용 |
| 비밀번호 | 사람이 정하지 않는다. AWS Secrets Manager가 만들어 보관한다 |

## 처음 한 번만 준비

1. **AWS CLI 2 설치** — https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
   윈도우는 설치 뒤 **Git Bash**에서 실행한다(PowerShell 아님).
2. **로그인 정보 넣기** — 관리자 권한(AdministratorAccess) 사용자의 액세스 키로:
   ```bash
   aws configure
   ```

## 다른 계정에서 쓰기

계정마다 달라지는 값(서버 이미지 번호, 가용영역, S3 이름, 내 IP)은 하나도 코드에 적혀 있지 않다. 실행할 때 그 계정에서 찾는다.

```bash
aws configure --profile team      # 다른 계정 키를 'team' 이름으로 등록 (한 번만)
bash infra/aws/up.sh --profile team
bash infra/aws/down.sh --profile team
```

- 시작할 때 **어느 계정·리전에 만드는지** 먼저 보여 주고 묻는다. 잘못된 계정에 만드는 일을 막기 위해서다.
- 같은 계정에 한 벌 더 만들려면 `--stack sbrain-test`처럼 이름만 바꾼다.
- **AWS CloudShell**(콘솔 위쪽 `>_` 아이콘)에서도 된다. CLI 설치가 필요 없다. 저장소를 `git clone` 한 뒤 같은 명령을 쓴다.
  단, SSH 허용 IP가 CloudShell 주소로 잡히므로 `settings.env.local`에 `ADMIN_CIDR=내PC공인IP/32`를 적는다.

## 다시 실행하면

`up.sh`는 몇 번을 다시 실행해도 안전하다.

- 이미 있으면 **바뀐 설정만** 반영한다. 서버를 새로 만들지 않는다.
- DB 세팅은 **아직 적용하지 않은 SQL 파일만** 적용한다(DB 안 `infra_schema_history` 표에 기록).
- 집·학원처럼 **내 IP가 바뀌어 SSH가 막혔을 때**도 다시 실행하면 새 IP로 열린다.

## 서버 접속

`up.sh`가 끝나면 접속 명령을 보여 준다.

```bash
ssh -F infra/aws/.out/sbrain-ap-northeast-2/ssh_config sbrain-web
```

```bash
ssh -F infra/aws/.out/sbrain-ap-northeast-2/ssh_config sbrain-notice
```

공고 서버는 바깥 주소가 없어서 웹 서버를 거쳐 들어간다(`ProxyJump`). 결과 요약은 `infra/aws/.out/<스택>-<리전>/summary.txt`에도 남는다.

## 앱에서 DB 쓰기

두 서버 모두 `/etc/sbrain/db.env`에 접속 정보가 있다. 앱의 `.env`에 이 줄들을 그대로 붙이면 된다.

```bash
sudo cat /etc/sbrain/db.env >> .env
```

- 공고 수집 코드는 `MYSQL_SSL_CA`(RDS 인증서)로 서버 신원까지 확인하며 접속한다.
- 웹 백엔드는 그 값을 읽지 않지만, PyMySQL 1.2 이상이면 자동으로 암호화해 접속한다(MySQL 8.4에서 확인).

## 설정 바꾸기

기본값은 [settings.env](settings.env)에 있다. 내 PC에서만 바꿀 값은 같은 폴더에 `settings.env.local`을 만들어 다시 적는다(커밋 안 됨).

| 값 | 언제 반영되나 |
|---|---|
| 서버 종류, DB 종류, DB 용량, SSH 허용 IP | 다시 실행할 때마다 (서버는 잠깐 재시작될 수 있음) |
| 가용영역, 서버 이미지, 공고 서버 내부 주소 | **처음 만들 때만**. 나중에 바뀌면 서버가 통째로 새로 만들어지기 때문에 막아 두었다 |

## 테이블이 늘어나면

새 변경 SQL 파일을 만들고 [schema-order.txt](schema-order.txt) 맨 아래에 경로를 추가한 뒤 `up.sh`를 다시 실행한다.
이미 적용한 파일(예: `app_schema.sql`)을 고치면 자동으로 다시 적용하지 않고 경고만 낸다. 이미 만든 표에 컬럼을 더하는 일은 변경 SQL로 한다.

## 요금 (서울, 대략)

| 항목 | 켜 둘 때 |
|---|---|
| NAT 게이트웨이 | 한 달 약 $43 + 데이터 처리 요금 (켜 두기만 해도 나감) |
| 고정 IP 2개(웹 · NAT) | 한 달 약 $7 |
| EC2 2대 · RDS · 디스크 | 종류에 따라. 프리 플랜 크레딧이 있으면 거기서 차감 |

다 쓰면 `down.sh`. RDS 마지막 스냅샷만 데이터 보관용으로 남기고, 지우는 명령을 마지막에 알려 준다.

## 이 스크립트가 하지 않는 일

- **앱 코드 올리기와 실행 설정** (웹 · 공고 서버 · 워커). 서버와 DB까지만 준비한다. 웹 · 워커는 [app/README.md](app/README.md)의 `app-env.sh` · `deploy-app.sh`로 올린다(공고 서버 앱은 공고팀 몫).
- **기존 팀 EC2 MySQL 데이터 옮기기**. 빈 DB로 시작한다. 옮기지 않으면 매일 배치가 모든 공고를 처음부터 다시 처리한다(LLM 추출 비용 포함).
- **HTTPS 인증서**. 443은 열어 두기만 한다. 인증서는 `settings.env.local`에 `WEB_DOMAIN`을 적고 DNS를 웹 서버 고정 IP로 연결한 뒤, `deploy-app.sh`가 Let's Encrypt에서 받는다([app/README.md](app/README.md)).

## 문제가 생기면

| 증상 | 할 일 |
|---|---|
| `예전에 실패한 스택이 남아 있습니다` | 처음 만들기가 실패해 AWS가 되돌린 상태. `down.sh` → 원인 고친 뒤 `up.sh` |
| 만들기 실패 + `vCPU` · `limit` · `quota` 문구 | 계정 한도 부족. AWS 콘솔 Service Quotas에서 늘리거나 서버 종류를 작게 |
| `... 를 쓸 수 없습니다` (서버 종류) | 그 계정·리전에 없는 종류. `settings.env.local`에서 바꾼다 (프리 플랜은 `c7i-flex.large` · `m7i-flex.large` 등만 허용) |
| DB 세팅 실패 | 표시된 원인을 고친 뒤 `up.sh` 다시 실행. 실패한 파일부터 이어서 한다 |
| SSH 시간 초과 | 내 IP가 바뀜. `up.sh` 다시 실행 |
| 서버 첫 부팅 로그를 보고 싶을 때 | 서버에서 `sudo cat /var/log/sbrain-userdata.log` |

## 파일

| 파일 | 하는 일 |
|---|---|
| [up.sh](up.sh) | 원버튼 만들기 |
| [down.sh](down.sh) | 원버튼 지우기 |
| [sbrain-stack.yml](sbrain-stack.yml) | AWS에 넘기는 설계도 (윈도우 AWS CLI가 한글을 못 읽을 수 있어 영어로만 씀) |
| [bootstrap/setup-db.sh](bootstrap/setup-db.sh) | 서버 안에서 DB · 앱 계정 · 테이블 · 접속 정보 파일을 만든다 |
| [schema-order.txt](schema-order.txt) | 적용할 SQL 파일과 순서 |
| [settings.env](settings.env) | 기본 설정 |
| [lib.sh](lib.sh) | up · down 공통 도우미 |
