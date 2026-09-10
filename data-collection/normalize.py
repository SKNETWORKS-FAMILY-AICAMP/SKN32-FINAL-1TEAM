"""API 응답을 공통 공고로 변환한다. 기존 notices.json과 무관한 검증 출력."""
import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
BASES = {'kstartup': 'https://www.k-startup.go.kr/', 'bizinfo': 'https://www.bizinfo.go.kr/'}


class TextParser(HTMLParser):
    """본문의 문단·목록 경계는 살리고 script/style 내용은 제외한다."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden and tag in ('p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3'):
            self.parts.append('\n')
        elif not self.hidden and tag in ('td', 'th'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def text(value):
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError('문자열 필드에 지원하지 않는 자료형')
    parser = TextParser()
    parser.feed(str(value))
    parser.close()
    lines = [re.sub(r'[^\S\n]+', ' ', line).strip() for line in ''.join(parser.parts).splitlines()]
    return '\n'.join(line for line in lines if line) or None


def clean_url(value, source, field, issues):
    if value is None or value == '':
        return None
    value = str(value).strip().replace('&amp;', '&')
    if not value:
        return None
    try:
        url = urljoin(BASES[source], value)
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or re.search(r'\s', url)):
            raise ValueError()
        # 잘못된 포트도 판별하되 실제 접속은 하지 않는다.
        parsed.port
        return url
    except ValueError:
        issues.append({'field': field, 'code': 'invalid_url'})
        return None


def clean_date(value, field, issues):
    value = text(value)
    if not value:
        return None
    match = re.fullmatch(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})|([0-9]{4})([0-9]{2})([0-9]{2})', value)
    try:
        if not match:
            raise ValueError()
        parts = match.groups()[:3] if match.group(1) else match.groups()[3:]
        return date(*(int(v) for v in parts)).isoformat()
    except ValueError:
        issues.append({'field': field, 'code': 'invalid_date'})
        return None


def period(row, source, issues):
    if source == 'kstartup':
        raw = {'start': row.get('pbanc_rcpt_bgng_dt'), 'end': row.get('pbanc_rcpt_end_dt')}
        start = clean_date(raw['start'], 'apply_start', issues)
        end = clean_date(raw['end'], 'apply_end', issues)
        kind = 'fixed' if start and end else 'unknown'
    else:
        raw = row.get('reqstBeginEndDe')
        value = text(raw) or ''
        pattern = r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})\s*~\s*(\d{4}[-./]\d{1,2}[-./]\d{1,2})'
        match = re.fullmatch(pattern, value)
        start = end = None
        kind = 'unknown'
        if match:
            start = clean_date(match.group(1), 'apply_start', issues)
            end = clean_date(match.group(2), 'apply_end', issues)
            kind = 'fixed' if start and end else 'unknown'
        elif '예산' in value and '소진' in value:
            kind = 'budget_exhaustion'
        elif '상시' in value or '수시' in value:
            kind = 'rolling'
        elif '선착순' in value or '모집 완료' in value or '모집 마감' in value:
            kind = 'until_filled'
        elif value:
            issues.append({'field': 'apply_period_raw', 'code': 'unparsed_period'})
    if start and end and start > end:
        issues.append({'field': 'apply_period_raw', 'code': 'reversed_period'})
        start = end = None
        kind = 'unknown'
    return start, end, raw, kind


def normalize_notice(row, source):
    if source not in BASES:
        raise ValueError('지원하지 않는 출처')
    if not isinstance(row, dict):
        raise ValueError('공고 행은 객체여야 함')
    k = source == 'kstartup'
    source_id = text(row.get('pbanc_sn' if k else 'pblancId'))
    title = text(row.get('biz_pbanc_nm' if k else 'pblancNm'))
    if not source_id or not title:
        raise ValueError('필수 ID 또는 제목 누락')
    issues = []
    start, end, period_raw, period_type = period(row, source, issues)
    target = text(row.get('aply_trgt_ctnt')) if k else None
    status = {'Y': 'open', 'N': 'closed'}.get(text(row.get('rcrt_prgs_yn')), 'unknown') if k else 'unknown'
    attachments = []
    if not k:
        for url_key, name_key, role in [('printFlpthNm', 'printFileNm', 'notice'), ('flpthNm', 'fileNm', 'form')]:
            url = clean_url(row.get(url_key), source, url_key, issues)
            if url:
                attachments.append({'role': role, 'url': url, 'name': text(row.get(name_key)), 'status': 'not_downloaded'})
    return {
        'schema_version': 1, 'notice_id': source + ':' + source_id,
        'source': source, 'source_id': source_id, 'title': title,
        'body': text(row.get('pbanc_ctnt' if k else 'bsnsSumryCn')),
        'target_text': target, 'target_text_status': 'available' if target else 'not_available',
        'target_category': text(row.get('aply_trgt' if k else 'trgetNm')),
        'exclude_text': text(row.get('aply_excl_trgt_ctnt')) if k else None,
        'age_condition_raw': text(row.get('biz_enyy')) if k else None,
        'region': text(row.get('supt_regin')) if k else None,
        'category': text(row.get('supt_biz_clsfc' if k else 'pldirSportRealmLclasCodeNm')),
        'subcategory': None if k else text(row.get('pldirSportRealmMlsfcCodeNm')),
        'organizer': text(row.get('pbanc_ntrp_nm')) if k else None,
        'supervising_org': None if k else text(row.get('jrsdInsttNm')),
        'executing_org': None if k else text(row.get('excInsttNm')),
        'apply_start': start, 'apply_end': end, 'apply_period_raw': period_raw,
        'apply_period_type': period_type, 'recruitment_status': status,
        'url': clean_url(row.get('detl_pg_url' if k else 'pblancUrl'), source, 'url', issues),
        'apply_url': clean_url(row.get('biz_aply_url' if k else 'rceptEngnHmpgUrl'), source, 'apply_url', issues),
        'attachments': attachments,
        'attachment_discovery_status': 'pending_crawl' if k else ('api_links_available' if attachments else 'not_available'),
        'source_updated_at_raw': row.get('updtPnttm') if not k else None,
        'issues': issues, 'raw': row,
    }


def rows_from(payload, source):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        keys = ('notices', 'data') if source == 'kstartup' else ('jsonArray',)
        for key in keys:
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError('API 응답의 공고 배열을 찾을 수 없음')


def normalize_sources(sources):
    notices = {}
    rejected = []
    duplicates = []
    counts = {}
    for source, payload in sources:
        rows = rows_from(payload, source)
        counts[source] = counts.get(source, 0) + len(rows)
        for index, row in enumerate(rows):
            try:
                record = normalize_notice(row, source)
            except (ValueError, TypeError) as exc:
                rejected.append({'source': source, 'row_index': index, 'reason': str(exc), 'raw': row})
                continue
            key = record['notice_id']
            if key in notices:
                duplicates.append({'notice_id': key, 'policy': 'last_valid_row_wins', 'replaced_raw': notices[key]['raw']})
            notices[key] = record
    # 출처 간 제목 완전일치만 검토 후보로 남긴다. 실제 동일 사업 판정은 하지 않는다.
    titles = defaultdict(list)
    for record in notices.values():
        titles[' '.join(record['title'].casefold().split())].append(record)
    candidates = [
        {'reason': 'same_title_cross_source', 'notice_ids': [r['notice_id'] for r in group]}
        for group in titles.values() if len({r['source'] for r in group}) > 1
    ]
    records = list(notices.values())
    return {
        'schema_version': 1, 'notices': records, 'rejected': rejected,
        'same_source_duplicates': duplicates, 'cross_source_candidates': candidates,
        'summary': {'input_counts': counts, 'accepted_count': len(records),
                    'rejected_count': len(rejected), 'same_source_duplicate_count': len(duplicates),
                    'cross_source_candidate_groups': len(candidates),
                    'issue_counts': dict(Counter(i['code'] for r in records for i in r['issues']))},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kstartup', type=Path)
    ap.add_argument('--bizinfo', type=Path)
    ap.add_argument('--output', type=Path, help='새 출력 파일. 기존 파일 덮어쓰기 금지')
    args = ap.parse_args()
    inputs = [('kstartup', args.kstartup), ('bizinfo', args.bizinfo)]
    if not any(path for _, path in inputs):
        inputs = [('kstartup', HERE / 'data/notices.json')]
    sources, metadata = [], []
    for source, path in inputs:
        if path is None:
            continue
        raw_bytes = path.read_bytes()
        sources.append((source, json.loads(raw_bytes.decode('utf-8-sig'))))
        metadata.append({'source': source, 'input_file': str(path.resolve()),
                         'sha256': hashlib.sha256(raw_bytes).hexdigest()})
    result = normalize_sources(sources)
    now = datetime.now(timezone.utc)
    result.update({'generated_at': now.isoformat(), 'inputs': metadata})
    output = args.output or HERE / 'data/normalized' / ('notices_' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result['summary'], ensure_ascii=False))
    print(str(output.resolve()))
    return 2 if result['rejected'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
