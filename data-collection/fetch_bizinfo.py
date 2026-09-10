"""기업마당 API 원본 스냅샷 확보. 기존 수집·추천 데이터는 교체하지 않는다."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config

BASE = 'https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do'
HERE = Path(__file__).resolve().parent


def fetch_snapshot():
    key = config.require('BIZINFO_KEY')
    request = Request(BASE + '?' + urlencode({'crtfcKey': key, 'dataType': 'json'}),
                      headers={'User-Agent': 'S-Brain-POC/1.0'})
    try:
        with urlopen(request, timeout=60) as response:
            content = response.read()
        payload = json.loads(content.decode('utf-8-sig'))
        rows = payload.get('jsonArray') if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError('공고 배열 없음')
    except Exception as exc:
        # 예외의 URL에 인증키가 들어 있을 수 있어 원문 예외는 출력하지 않는다.
        raise RuntimeError('기업마당 수집 실패: ' + type(exc).__name__) from None
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = HERE / 'data/raw' / ('bizinfo_' + stamp + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(content)
    return path, len(rows)


def main():
    try:
        path, count = fetch_snapshot()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print('기업마당 응답 %d건 (서버 전체 건수와의 일치 여부는 별도 확인)' % count)
    print(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
