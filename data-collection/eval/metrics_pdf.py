# -*- coding: utf-8 -*-
"""지표 결과(eval/metrics_report.py 의 metrics.json)를 PDF 보고서로 만든다(2026-09-30).

  python -X utf8 -m eval.metrics_pdf [reports/metrics_<시각>]     기본은 가장 최근 metrics_ 폴더

HTML 을 만든 뒤 이 PC 의 Edge(headless)로 인쇄한다. 새 패키지를 설치하지 않는다.
결과: 같은 폴더의 지표_보고서.html · 지표_보고서.pdf
"""
import glob
import html
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EDGE = [r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        r'C:\Program Files\Microsoft\Edge\Application\msedge.exe']

# 쉬운 설명 — 지표 이름이 무엇을 뜻하는지 한 문장으로
PLAIN = {
    '누적 공고 수': 'DB에 쌓인 지원사업 공고 수. 매일 새 공고를 더하고 지우지 않는다.',
    '배치 성공률': '매일 수집 배치가 오류 없이 끝난 비율.',
    '배치 가동일 비율': '첫 배치부터 오늘까지 중 배치가 실제로 돈 날의 비율. 배치 PC가 꺼진 날은 돌지 않는다.',
    '배치 소요 시간(중앙값, 분)': '하루 배치(수집→정규화→저장→첨부→임베딩→LLM 판정)가 끝나는 데 걸린 시간.',
    'K-Startup 목록 완전 수집률': '받은 공고 수가 API가 알려 준 총 수와 정확히 같았던 날의 비율.',
    '배치일 평균 신규 공고': '배치가 돈 날 새로 들어온 공고 수의 평균.',
    '정규화 거부율(최근 저장)': '두 출처를 공통 형식으로 바꿀 때 필수값이 없어 버린 공고의 비율.',
    '접수기간 해석률': '접수기간 원문을 고정·예산 소진·상시·선착순으로 분류해 낸 비율.',
    '마감일 확보율': '마감일(날짜)이 있는 공고의 비율. 나머지는 원래 날짜가 없는 공고(예산 소진 등)가 대부분이다.',
    '첨부 공고문 본문 추출 성공률': '첨부 공고문(PDF·HWP 등)에서 글자를 뽑아낸 비율. 이미지 스캔본은 글자가 없다.',
    '임베딩 적용률': '의미 검색용 벡터가 만들어진 공고의 비율.',
    '판정표 적용 범위: 자격요건(금액·형태·업력)': 'LLM이 지원금·사업자 형태·업력을 뽑아 둔 공고의 비율(본문 있는 공고 기준).',
    '판정표 적용 범위: 신청자 유형': 'LLM이 예비창업자·개인사업자·법인 신청 가능 여부를 판정해 둔 공고의 비율.',
    '판정표 적용 범위: 업종': 'LLM이 신청 가능 업종을 판정해 둔 공고의 비율.',
    '신청자 유형 판정 지문 신선도': '판정이 지금 공고문과 같은 글을 보고 내린 것인지(지문 일치) 확인한 비율.',
    '예비창업자 "명시 불가" 판정 정밀도': '"예비창업자 불가"로 판정해 추천에서 뺀 공고가 실제로도 불가인 비율. 틀리면 신청 가능한 공고를 잃는다.',
    '신청자 유형 판정 일치율': '신청자 유형 판정이 별도 블라인드 판정과 같은 비율.',
    '업종 순위의 부당 밀림(공고)': '업종 신호로 뒤로 밀린 공고 중 밀리면 안 됐던 공고의 비율. 높아서 이 기능은 꺼 두었다.',
    '하루 LLM 비용(신청자 유형+업종, USD)': '매일 새 공고를 LLM으로 판정하는 데 든 비용.',
    '신청 불가@10': '추천 상위 10개 중 마감·업력·신청자 유형 때문에 신청할 수 없는 공고의 비율.',
    'P@3(2) 하한': '추천 상위 3개 중 "딱 맞는 공고"의 비율. 판정이 없는 칸은 틀린 것으로 셌다.',
    'P@3(2) 상한': '같은 지표에서 판정이 없는 칸을 맞은 것으로 센 값. 실제 값은 하한과 상한 사이다.',
    'nDCG@10(판정분)': '상위 10개의 순서까지 반영한 점수(0~1). 판정된 공고만으로 계산했다.',
    '쓸모@3 하한': '상위 3개 중 "내용이 맞고 신청도 가능한" 공고 수(최대 3).',
    '상위 10 미판정 비율': '추천 상위 10개 중 아직 사람·AI 판정이 없는 칸의 비율.',
    '판정자 일치율: LLM(gpt-4.1-mini) vs 사람': '관련도 판정을 LLM에 맡겼을 때 사람 판정과 같은 비율.',
    '판정자 일치율: Jev vs 사람': '평가 전용 모델 Jev의 판정이 사람 판정과 같은 비율.',
    '판정자 일치율: Codex vs 사람(대조군)': 'Codex 판정이 사람 판정과 같은 비율(대조군).',
    '매칭 응답 시간 중앙값(ms)': '추천 요청 하나에 답하는 데 걸린 시간(이 PC, 공고 전체 대상).',
    'Codex 검수·판정 결과 문서 수': '다른 AI(Codex)가 독립적으로 검수·판정한 결과 문서 수.',
    '자동 테스트 수': '코드가 바뀔 때마다 돌리는 자동 시험의 수.',
}
AREAS = {'A': '수집·운영', 'B': '전처리 품질', 'C': 'LLM 추출', 'D': '매칭 성능 (9/28 평가, 하이브리드 검색)',
         'E': '평가 신뢰도', 'F': '서비스·개발'}
RATIO_KEEP = ('nDCG', '쓸모')          # 0~1 이지만 퍼센트로 쓰지 않는 것


def show(m):
    v, name = m['value'], m['name']
    if v is None:
        return '-'
    if '(ms)' in name:
        return '%.0fms' % v
    if '(분' in name:
        return '%.1f분' % v
    if 'USD' in name:
        return '$%.3f' % v
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and v > 1):
        return format(int(v), ',')
    if any(k in name for k in RATIO_KEEP):
        return '%.2f' % v if 'nDCG' in name else '%.2f건' % v
    if name.startswith('판정자 일치율'):
        return '%.2f' % v
    if 0 <= v <= 1:
        return '%.1f%%' % (100 * v)
    return '%.1f' % v


def target(m):
    t = str(m['target'])
    return t.replace('1.00', '100%') if t.startswith('1.00') else ('0%' if t == '0' else t)


def pick(items, name):
    return next((m for m in items if m['name'] == name), None)


def tiles(items):
    out = []
    n = pick(items, '누적 공고 수')
    b = pick(items, '배치 성공률')
    i = pick(items, '신청 불가@10')
    p = pick(items, 'P@3(2) 하한')
    g = pick(items, '예비창업자 "명시 불가" 판정 정밀도')
    t = pick(items, '매칭 응답 시간 중앙값(ms)')
    if n:
        out.append(('공고 데이터', show(n), n['detail'].replace('bizinfo', '기업마당').replace('kstartup', 'K-Startup')))
    if b:
        out.append(('매일 배치 성공', b['detail'].split('회')[0] + '회', '가동일 %s' % show(pick(items, '배치 가동일 비율'))))
    if i:
        out.append(('신청 불가 추천', '24.3% → 0%', '상위 10개 중 (처음 방식 → 지금)'))
    if p:
        out.append(('딱 맞는 공고 비율', '49% → 62%', '상위 3개, 하한 (처음 → 지금)'))
    if g:
        out.append(('"예비창업자 불가" 정밀도', g['detail'].split(' ')[0], '신청 가능한 공고를 뺀 오류 0건'))
    if t:
        out.append(('추천 응답 시간', show(t), 'p95 ' + t['detail'].split('p95 ')[1].split(' ')[0]))
    return out


WEAK = [
    ('배치 가동일 59%', '배치가 개인 PC에서 돌아 PC가 꺼진 날(9/19~20, 9/23~27)에는 수집이 멈췄다. 상시 서버(EC2)로 옮기면 해결된다.'),
    ('상위 10 미판정 32%', '추천 상위 10개 중 약 3분의 1은 아직 판정이 없다. 그래서 지금 방식의 상위 3개 정밀도가 62%(하한)~75%(상한) 사이로 벌어진다. 이 빈칸 448쌍을 Codex가 판정 중이다.'),
    ('판정자 일치율 0.64 < 기준 0.70', '관련도 정답의 대부분이 LLM 판정이다. LLM은 사람과 64%만 같게 판정했다(기준 70%). 사람 판정은 143쌍뿐이다.'),
    ('평가 질의 58개', '질의가 적어 방식 차이의 95% 구간이 ±5%p 안팎이다. 이보다 작은 개선은 수치로 증명하기 어렵다.'),
    ('순서 점수(nDCG) 제자리', '신청 불가 공고를 없애고 상위 3개 정밀도를 올렸지만, 판정된 공고끼리의 순서 점수는 0.60으로 그대로다. 실패 분석에서 정답 292건이 11~50위에 밀려 있었다.'),
    ('업종 순위 꺼짐', '업종으로 순위를 조정하면 34개 중 11개 공고가 부당하게 밀려 기능을 꺼 두었다.'),
]


def build_html(data, items):
    e = html.escape
    rows = []
    for area, title in AREAS.items():
        part = [m for m in items if m['area'] == area]
        if not part:
            continue
        rows.append('<h2>%s. %s</h2><table><thead><tr><th class="n">지표</th><th class="v">값</th><th class="t">기준·목표</th>'
                    '<th>무슨 뜻인가 · 내용</th></tr></thead><tbody>' % (area, e(title)))
        for m in part:
            rows.append('<tr><td class="n">%s</td><td class="v">%s</td><td class="t">%s</td><td><div class="plain">%s</div>'
                        '<div class="det">%s</div><div class="src">근거: %s</div></td></tr>'
                        % (e(m['name']), e(show(m)), e(target(m)), e(PLAIN.get(m['name'], '')),
                           e(m['detail']), e(m['source'])))
        rows.append('</tbody></table>')
    tile_html = ''.join('<div class="tile"><div class="tl">%s</div><div class="tv">%s</div><div class="ts">%s</div></div>'
                        % (e(a), e(b), e(c)) for a, b, c in tiles(items))
    weak = ''.join('<li><b>%s</b> — %s</li>' % (e(a), e(b)) for a, b in WEAK)
    run_at = data['run_at'].replace('T', ' ')[:16]
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공고팀 작업 지표</title><style>
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
body { font-family: "Malgun Gothic", "맑은 고딕", sans-serif; color: #17202e; font-size: 9.6pt; line-height: 1.5; margin: 0; }
header { border-bottom: 2px solid #1f4f8f; padding-bottom: 8px; margin-bottom: 12px; }
.eyebrow { color: #56627a; font-size: 8.5pt; letter-spacing: .05em; }
h1 { font-size: 19pt; margin: 2px 0 4px; color: #0f2c55; }
.meta { color: #56627a; font-size: 8.5pt; }
h2 { font-size: 12pt; color: #0f2c55; margin: 16px 0 6px; break-after: avoid; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 10px 0 4px; }
.tile { border: 1px solid #c9d3e3; border-radius: 6px; padding: 7px 9px; background: #f5f8fc; }
.tl { font-size: 8.3pt; color: #3b4a63; } .tv { font-size: 15pt; font-weight: 700; color: #0f2c55; } .ts { font-size: 7.8pt; color: #56627a; }
table { width: 100%%; border-collapse: collapse; margin-bottom: 4px; break-inside: auto; }
tr { break-inside: avoid; }
th, td { border-bottom: 1px solid #dde3ec; padding: 5px 6px; vertical-align: top; text-align: left; }
thead th { background: #eef2f8; font-size: 8.3pt; color: #3b4a63; }
td.n { width: 25%%; font-weight: 600; } td.v { width: 11%%; text-align: right; font-weight: 700; color: #0f2c55; white-space: nowrap; }
td.t { width: 14%%; font-size: 8.3pt; color: #3b4a63; } th.v { text-align: right; }
.plain { } .det { color: #3b4a63; font-size: 8.4pt; } .src { color: #7a8599; font-size: 7.6pt; }
ul.weak { margin: 4px 0 0; padding-left: 16px; } ul.weak li { margin-bottom: 4px; }
.note { font-size: 8.3pt; color: #56627a; margin-top: 4px; }
code { font-family: Consolas, monospace; font-size: 8.3pt; }
</style></head><body>
<header><div class="eyebrow">SKN 27기 1팀 · 공고 수집·매칭 (data-collection)</div>
<h1>공고팀 작업 지표</h1>
<div class="meta">측정 %s KST · 작성 이근준 · 공용 DB 조회만, 유료 API 호출 없음 · 매칭 수치는 9/28 평가(질의 58개, 판정 1,617쌍)</div></header>
<h2>한눈에 보기</h2><div class="tiles">%s</div>
<p class="note">매칭 정밀도는 판정이 없는 칸을 틀린 것으로 센 하한이다. 판정은 사람 143쌍, 나머지는 LLM·AI 판정이다. 약점은 맨 아래에 정리했다.</p>
%s
<h2>약점과 다음 할 일</h2><ul class="weak">%s</ul>
<h2>다시 재는 방법</h2>
<p class="note"><code>python -X utf8 -m eval.metrics_report --latency --tests</code> → <code>reports/metrics_&lt;시각&gt;/metrics.json</code>,
<code>python -X utf8 -m eval.metrics_pdf</code> → 이 PDF. 같은 명령으로 언제든 다시 잴 수 있다. 판정 기준(topic-v2)과 판정 신뢰 기준(정확 일치 ≥0.70·가중 카파 ≥0.60)은 평가 폴더(<code>eval/</code>)에 있다.</p>
</body></html>''' % (e(run_at), tile_html, ''.join(rows), weak)


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(os.path.join(ROOT, 'reports', 'metrics_*')))[-1]
    folder = os.path.abspath(folder)
    data = json.load(open(os.path.join(folder, 'metrics.json'), encoding='utf-8'))
    page = build_html(data, data['metrics'])
    html_path = os.path.join(folder, '지표_보고서.html')
    pdf_path = os.path.join(folder, '지표_보고서.pdf')
    open(html_path, 'w', encoding='utf-8').write(page)
    edge = next((p for p in EDGE if os.path.exists(p)), None)
    if not edge:
        sys.exit('Edge 를 찾지 못했다. HTML 만 만들었다: ' + html_path)
    subprocess.run([edge, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                    '--print-to-pdf=' + pdf_path, 'file:///' + html_path.replace('\\', '/')], check=True, timeout=120)
    print('PDF:', pdf_path)


if __name__ == '__main__':
    main()
