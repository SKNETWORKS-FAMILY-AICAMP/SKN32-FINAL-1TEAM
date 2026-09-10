# -*- coding: utf-8 -*-
"""K-Startup 공고정보 수집 → data/notices.json

  python fetch.py

인증키는 KSTARTUP_KEY 에서 읽는다. (코드에 넣지 말 것)
  .env 파일에 넣거나 — 권장. .env.example 참조
  $env:KSTARTUP_KEY = "..."  로 환경변수에 직접 넣는다.

data.go.kr 의 "일반 인증키(Decoding)" 값을 쓴다. Encoding 값을 넣으면
아래 urlencode 가 % 를 다시 인코딩해 인증이 실패한다.
"""
import json
import os
import socket
import sys
import urllib.parse
import urllib.request
from datetime import date

import config

BASE = 'https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'data', 'notices.json')

socket.setdefaulttimeout(45)


def fetch_page(key, page, per_page=100, only_open=True):
    params = {
        'serviceKey': key,
        'page': page,
        'perPage': per_page,
        'returnType': 'json',
    }
    url = BASE + '?' + urllib.parse.urlencode(params, safe='')
    if only_open:
        # 서버측 조건 검색 — 모집중만. urlencode 하면 대괄호가 깨져서 직접 붙인다.
        url += '&cond[rcrt_prgs_yn::EQ]=Y'

    raw = urllib.request.urlopen(url).read().decode('utf-8', 'replace')
    return json.loads(raw)


def fetch_all(key, only_open=True):
    first = fetch_page(key, 1, only_open=only_open)
    total = first.get('matchCount') or first.get('totalCount') or 0
    rows = list(first.get('data') or [])
    page = 2
    while len(rows) < total:
        got = fetch_page(key, page, only_open=only_open).get('data') or []
        if not got:
            break
        rows += got
        page += 1
    return rows, total


def main():
    key = config.require('KSTARTUP_KEY')

    rows, total = fetch_all(key)
    payload = {
        'fetched_at': date.today().isoformat(),
        'source': 'K-Startup getAnnouncementInformation01 (rcrt_prgs_yn=Y)',
        'count': len(rows),
        'reported_total': total,
        'notices': rows,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print('수집 %d건 (서버 보고 %d건) → %s' % (len(rows), total, OUT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
