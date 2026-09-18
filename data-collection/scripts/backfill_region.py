# -*- coding: utf-8 -*-
"""이미 저장된 공고의 지역 칸을 채운다 (raw 를 다시 읽어 region.py 로 정규화).

  python -X utf8 backfill_region.py --plan     무엇이 바뀌는지만 본다
  python -X utf8 backfill_region.py            실제로 채운다

앞으로 들어오는 공고는 normalize.py 가 알아서 채운다. 이 스크립트는 그 전에
쌓인 공고를 한 번 메우기 위한 것이다. 여러 번 돌려도 결과는 같다.

**임베딩·BM25 색인은 건드리지 않는다.** 지역은 임베딩 입력(embed.FIELDS)에
들어가지 않으므로 검색 결과와 평가 수치가 달라지지 않는다.
"""
import argparse
import json
import sys

from shared import region
from shared import store_mysql


def parse(source, title, raw):
    """normalize.normalize_notice 와 같은 규칙이어야 한다."""
    if source == 'kstartup':
        return region.normalize(raw.get('supt_regin'))
    return region.merge(region.from_tags(raw.get('hashtags')), region.from_title(title))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', action='store_true', help='바뀔 건수만 본다')
    args = ap.parse_args()

    connection = store_mysql.connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT notice_id, source, title, region, raw FROM notices')
            rows = cursor.fetchall()

        changes = []
        for notice_id, source, title, before, raw in rows:
            after = parse(source, title, json.loads(raw))
            if (after or None) != (before or None):
                changes.append((notice_id, source, before, after))

        filled = sum(1 for _, _, b, a in changes if not b and a)
        cleared = sum(1 for _, _, b, a in changes if b and not a)
        print('공고 %d건 · 바뀔 것 %d건 (새로 채움 %d · 비움 %d)'
              % (len(rows), len(changes), filled, cleared))
        for notice_id, source, before, after in changes[:5]:
            print('  %s  %s → %s' % (notice_id, before, after))
        if args.plan or not changes:
            print('\n--plan 이라 저장하지 않는다.' if args.plan else '\n바꿀 것이 없다.')
            return 0

        with connection.cursor() as cursor:
            cursor.executemany('UPDATE notices SET region=%s WHERE notice_id=%s',
                               [(after, notice_id) for notice_id, _, _, after in changes])
        connection.commit()
        print('\n저장했다. 서버를 다시 켜면 화면에 반영된다.')
    finally:
        connection.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
