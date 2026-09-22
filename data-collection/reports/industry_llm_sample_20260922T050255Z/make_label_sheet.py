# 업종 LLM v3 30건의 사람 정답 양식 만들기 (블라인드 — LLM 답을 넣지 않는다). SELECT 만.
import csv, io, os, sys
sys.path.insert(0, '.')
from experiments.sql_semantic import industry_llm_sample as s, config
from shared import store_mysql
RUN = 'reports/industry_llm_sample_20260922T050255Z'
rows = {r['notice_id']: r for r in s.read_jsonl(os.path.join(RUN, 'results.jsonl'))}
lab, src = config.connect(), store_mysql.connect()
ids, _ = s.pick_sample(lab)
items = s.load_items(lab, src, ids)
urls = {}
with lab.cursor() as cur:
    for nid in ids:
        cur.execute('SELECT url FROM lab_notices WHERE notice_id=%s', (nid,))
        urls[nid] = (cur.fetchone() or [''])[0]
lab.close(); src.close()
mismatch = [it['notice_id'] for it in items if it['document_sha256'] != rows[it['notice_id']]['document_sha256']]
if mismatch:
    raise SystemExit('LLM 이 받은 문서와 지금 문서가 다르다: %s' % mismatch)
with io.open(os.path.join(RUN, 'label_sheet.csv'), 'w', encoding='utf-8-sig', newline='') as f:
    w = csv.writer(f)
    w.writerow(['번호', 'notice_id', '제목', '원문 링크', 'document_sha256',
                '정답_상태(known/no_limit/unknown)', '정답_허용업종(원문 표현, ; 로 구분)',
                '정답_제외업종(원문 표현, ; 로 구분)', '정답_목록완전(Y/N/모름)', '메모'])
    for i, it in enumerate(items, 1):
        w.writerow([i, it['notice_id'], it['title'], urls.get(it['notice_id']) or '', it['document_sha256'],
                    '', '', '', '', ''])
lines = ['# 업종 정답 달기 — 30건 원문 발췌', '',
         'LLM 이 받은 것과 **똑같은 발췌**다(`document_sha256` 로 확인). 정답은 `label_sheet.csv` 에 적는다.', '',
         '## 판단 기준', '',
         '- **known**: 이 공고가 "어떤 업종만 신청할 수 있다"고 밝혔다. 허용 업종을 원문 표현 그대로 모두 적는다.',
         '- **no_limit**: "업종 제한 없음"·"전 업종"처럼 업종에 제한이 없다고 **명시**했다.',
         '- **unknown**: 업종 언급이 없거나, 제외 업종만 있거나, 애매하다.',
         '- 업종이 **아닌** 것: 중소기업·소상공인·중견기업·스타트업 같은 규모·형태, 지원 분야·사업 주제, 지역, 업력.',
         '- "바이오 분야 기업만"처럼 대상 기업을 분야로 한정하면 허용 업종으로 적는다(원문 표현 그대로).',
         '- 목록완전: 허용 업종을 **이 발췌에서** 빠짐없이 알 수 있으면 Y. 별표·붙임·"등"으로 끝나 전부 알 수 없으면 N.',
         '- 확신이 없으면 메모에 적고 unknown 으로 둔다. 빈칸은 "판정 안 함"으로 본다.', '',
         '**LLM 결과(`summary.md`)는 정답을 다 단 뒤에 본다.**', '']
for i, it in enumerate(items, 1):
    lines += ['---', '', '## %d. %s' % (i, it['title']), '',
              '`%s` · %s' % (it['notice_id'], urls.get(it['notice_id']) or '(링크 없음)'), '',
              '```', it['document'], '```', '']
with io.open(os.path.join(RUN, 'label_documents.md'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('\n'.join(lines) + '\n')
print('ok', len(items), 'rows · document hash 일치')
