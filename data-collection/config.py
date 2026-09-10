# -*- coding: utf-8 -*-
"""환경설정 로더 — .env 파일에서 비밀값을 읽는다.

  import config
  key = config.require('KSTARTUP_KEY')

python-dotenv 를 쓰지 않는다. 이 프로젝트의 수집 파이프라인은 표준 라이브러리만
쓰는 것이 원칙이라 의존성을 늘리지 않았다.

찾는 순서 (먼저 찾은 것 하나만 읽는다)
  1. poc/.env
  2. finak_mok/.env        ← 기본. 여러 폴더가 같은 키를 쓴다

이미 설정된 환경변수를 덮어쓰지 않는다. 작업 스케줄러나 CI 에서 주입한 값이
파일보다 우선한다.

주의 ─ 인증키는 **디코딩된 원본**을 넣는다.
  data.go.kr 이 보여주는 "인코딩된 인증키"(%2B, %2F, %3D 가 들어간 것)를 그대로
  넣으면 urlencode 가 % 를 다시 인코딩해 %252B 가 되어 인증이 실패한다.
  헷갈리면 load() 가 경고를 찍는다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = (
    os.path.join(HERE, '.env'),
    os.path.join(os.path.dirname(HERE), '.env'),
)

_loaded = False


def _parse(path):
    """KEY=VALUE 형식. # 주석과 빈 줄은 건너뛴다."""
    out = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].lstrip()
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            # 값 전체를 감싼 따옴표만 벗긴다
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '\'"':
                v = v[1:-1]
            out[k] = v
    return out


def load(verbose=False):
    """.env 를 읽어 os.environ 에 채운다. 여러 번 불러도 한 번만 읽는다."""
    global _loaded
    if _loaded:
        return
    _loaded = True

    for path in CANDIDATES:
        if not os.path.exists(path):
            continue
        for k, v in _parse(path).items():
            if k in os.environ:          # 기존 환경변수가 우선
                continue
            os.environ[k] = v
            if '%2B' in v or '%2F' in v or '%3D' in v:
                print('[config] 경고 - %s 값이 URL 인코딩된 것으로 보인다. '
                      '디코딩된 원본 키를 넣어야 한다.' % k, file=sys.stderr)
        if verbose:
            print('[config] %s 읽음' % path, file=sys.stderr)
        return


def get(name, default=None):
    load()
    return os.environ.get(name, default)


def require(name):
    """없으면 안내 메시지와 함께 종료한다."""
    v = get(name)
    if not v:
        print('환경변수 %s 가 없습니다.\n'
              '  .env.example 을 .env 로 복사해 값을 채우거나\n'
              '  PowerShell 에서  $env:%s = "..."  로 설정하세요.'
              % (name, name), file=sys.stderr)
        raise SystemExit(1)
    return v
