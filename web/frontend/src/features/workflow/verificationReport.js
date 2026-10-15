import { SCORE_DISCLAIMER } from './data.js';

// 최종 결과물의 "검증결과.pdf" — 원페이지형 검증결과서 양식(output/pdf/S-Brain_산출물검증결과서_원페이지형_개선안.pdf)을
// HTML로 그리고 브라우저 인쇄 창("PDF로 저장")으로 내보낸다. 브라우저에서 한글 폰트를 PDF에 직접 넣을 수
// 없어서, 인쇄를 거치면 디자인·한글이 그대로 PDF가 된다. 새 창 대신 숨긴 iframe을 써서 팝업 차단을 피한다.
// 배점 구조·항목명·고지 문구는 프로젝트 기획서 v1.8(4-5 2층 검증, 5-4 자동 검증 항목, 6-8 표기)을 따른다.

const DOC_ITEM_LABEL = { 문제인식: '문제 인식', 실현가능성: '실현 가능성', 성장전략: '성장 전략', '팀 구성': '팀 구성' };

const TYPE_COPY = {
  onepage: { crumb: '원페이지형 산출물', subtitle: '사업계획서 및 인포그래픽 검증 결과', type: '원페이지형 / 인포그래픽(SVG)', target: 'infographic.svg', autoTitle: 'SVG 지면 기준 자동 검증' },
  standard: { crumb: '프로토타입 산출물', subtitle: '사업계획서 및 프로토타입 검증 결과', type: '프로토타입 / HTML 실행 파일', target: 'index.html', autoTitle: '코드 기준 자동 검증' },
};

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function formatDateTime(d) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// projectName·announcementTitle·category('onepage' | 그 외), docScore(DOC_SCORE_BY_OUTCOME 값),
// codeCheckItems(buildCodeCheckItems 결과), crossCheck({raw, max, reasons}), threshold.
// verdict: GET /result의 VerdictOut(선택). 서버가 세 층 점수·총점·판정기준을 직접 내려주면
// "종합 판정"은 그 값을 그대로 쓴다 — 화면에서 다시 더하면 서버 판정과 숫자가 어긋날 수 있다.
export function buildVerificationReportHtml({ projectName, announcementTitle, category, docScore, codeCheckItems, crossCheck, threshold, verdict = null, createdAt = new Date() }) {
  const copy = TYPE_COPY[category === 'onepage' ? 'onepage' : 'standard'];
  const autoMax = codeCheckItems.reduce((s, it) => s + it.weight, 0);
  // 진입 파일(1번)이 없으면 나머지 항목 검사가 성립하지 않으므로 자동 검증 점수 전체를 0으로 본다(5-4).
  const entryMissing = codeCheckItems.some((it) => it.id === 1 && !it.passed);
  const autoRaw = entryMissing ? 0 : codeCheckItems.reduce((s, it) => s + (it.passed ? it.weight : 0), 0);

  // [2026-09-23, 백엔드 전달사항 10번] VerdictOut의 점수 필드는 전부 nullable이라 한 항목씩
  // 확인하고, 없으면(목업·데모 등 아직 서버 판정이 없는 경우) 지금까지처럼 화면 값으로 센다.
  const num = (v) => (typeof v === 'number' ? v : null);
  const vDoc = num(verdict?.doc_score), vDocMax = num(verdict?.doc_max_score);
  const vCode = num(verdict?.code_score), vCodeMax = num(verdict?.code_max_score);
  const vPlan = num(verdict?.plan_match_score), vPlanMax = num(verdict?.plan_match_max_score);

  const docRaw = vDoc ?? docScore.raw;
  const docMaxScore = vDocMax ?? docScore.max;
  // 산출물층 = 자동 검증 + 계획서 대조. 서버 값은 둘 다 있을 때만 쓴다(한쪽만 쓰면 합이 깨진다).
  const artifactRaw = vCode != null && vPlan != null ? vCode + vPlan : autoRaw + crossCheck.raw;
  const artifactMax = vCodeMax != null && vPlanMax != null ? vCodeMax + vPlanMax : autoMax + crossCheck.max;
  const total = num(verdict?.total_score) ?? docRaw + artifactRaw;
  const passThreshold = num(verdict?.pass_threshold) ?? threshold;
  const passed = total >= passThreshold;
  const failedItems = codeCheckItems.filter((it) => !it.passed);

  const opinion = crossCheck.reasons.length
    ? `사업계획서에 쓴 내용 중 산출물에서 확인되지 않는 항목이 ${crossCheck.reasons.length}건 있습니다.`
    : '사업계획서에 쓴 기능·정보가 산출물에 모두 있습니다.';
  const fixes = [
    ...failedItems.map((it) => `${it.name} 미충족 항목을 확인하고 보완하십시오.`),
    ...crossCheck.reasons,
  ];
  const evidence = failedItems.filter((it) => it.evidence).map((it) => `${it.name}: ${it.evidence}`);

  const docCells = docScore.items.map((it) => `
      <div class="doc-item"><span>${esc(DOC_ITEM_LABEL[it.name] || it.name)}</span><b>${it.score} / ${it.max}</b></div>`).join('');
  const checkRows = codeCheckItems.map((it) => `
        <tr class="${it.passed ? '' : 'fail'}"><td>${esc(it.name)}</td><td class="num">${it.weight}</td><td>${it.passed ? '충족' : '미충족'}</td><td class="num">${it.passed && !entryMissing ? it.weight : 0}</td></tr>`).join('');
  const lines = (arr, empty) => (arr.length ? arr.map((t) => `<p>${esc(t)}</p>`).join('') : `<p class="muted">${empty}</p>`);

  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>S-Brain_검증결과서</title>
<style>
  @page { size: A4; margin: 14mm 16mm; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { margin: 0; font-family: 'Pretendard', 'Noto Sans KR', 'Malgun Gothic', sans-serif; color: #1c2331; font-size: 11.5px; line-height: 1.55; }
  .top { display: flex; justify-content: space-between; align-items: baseline; padding-bottom: 8px; border-bottom: 1.5px solid #1c2331; }
  .top b { font-size: 14px; } .top span { color: #6b7684; font-size: 10.5px; }
  h1 { font-size: 30px; margin: 18px 0 4px; letter-spacing: -0.02em; }
  .sub { display: flex; justify-content: space-between; color: #6b7684; font-size: 12px; padding-bottom: 12px; border-bottom: 1px solid #dfe3e8; }
  .meta { display: grid; grid-template-columns: 90px 1fr 110px auto; row-gap: 8px; padding: 12px 0; border-bottom: 1px solid #dfe3e8; }
  .meta dt { color: #6b7684; } .meta dd { margin: 0; } .meta .strong { font-weight: 700; }
  .verdict { display: grid; grid-template-columns: 110px 1fr 1fr; align-items: center; gap: 20px; margin-top: 14px; padding: 16px 22px; background: #f1f4f8; }
  .verdict small { display: block; color: #6b7684; font-size: 10.5px; }
  .verdict .result { font-size: 22px; font-weight: 800; color: ${passed ? '#1f3f73' : '#9a3b2e'}; }
  .verdict .score { font-size: 34px; font-weight: 800; } .verdict .score span { font-size: 12px; font-weight: 400; color: #6b7684; margin-left: 6px; }
  .verdict .parts div { display: flex; justify-content: space-between; padding: 3px 0; } .verdict .parts b { font-size: 13px; }
  .rule { color: #6b7684; font-size: 10.5px; margin: 8px 0 14px; }
  h2 { display: flex; align-items: baseline; gap: 10px; font-size: 15px; margin: 16px 0 0; padding-bottom: 6px; border-bottom: 1.5px solid #1c2331; }
  h2 em { font-style: normal; color: #2f5597; font-size: 12px; } h2 small { margin-left: auto; font-weight: 400; color: #6b7684; font-size: 10.5px; }
  .doc { display: grid; grid-template-columns: repeat(4, 1fr); padding: 10px 0 12px; border-bottom: 1px solid #dfe3e8; }
  .doc-item span { display: block; color: #6b7684; } .doc-item b { font-size: 17px; }
  table { width: 100%; border-collapse: collapse; }
  th { background: #f1f4f8; text-align: left; font-weight: 700; padding: 6px 10px; }
  td { padding: 5px 10px; border-bottom: 1px solid #e8ebef; }
  th:nth-child(n+2), td:nth-child(n+2) { width: 70px; } .num { text-align: right; } th.num { text-align: right; }
  tr.fail td { background: #fbf3ec; font-weight: 700; } tr.fail td:nth-child(3) { color: #9a5b13; }
  .notes { display: grid; grid-template-columns: 90px 1fr; row-gap: 10px; padding-top: 10px; }
  .notes dt { font-weight: 700; } .notes dd { margin: 0; } .notes p { margin: 0 0 2px; } .muted { color: #6b7684; }
  .disclaimer { margin-top: 16px; padding-top: 8px; border-top: 1px solid #1c2331; color: #6b7684; font-size: 10px; }
  .foot { display: flex; justify-content: space-between; margin-top: 18px; color: #6b7684; font-size: 9.5px; }
</style></head>
<body>
  <div class="top"><b>S-Brain</b><span>검증결과서 / ${copy.crumb}</span></div>
  <h1>산출물 검증결과서</h1>
  <div class="sub"><span>${copy.subtitle}</span></div>
  <dl class="meta">
    <dt>프로젝트명</dt><dd class="strong">${esc(projectName) || '-'}</dd><dt>지원 공고</dt><dd>${esc(announcementTitle) || '-'}</dd>
    <dt>검증 대상</dt><dd>${copy.target}</dd><dt></dt><dd></dd>
    <dt>산출물 유형</dt><dd class="strong">${copy.type}</dd><dt>원본 생성 일시</dt><dd>${formatDateTime(createdAt)}</dd>
  </dl>
  <div class="verdict">
    <div><small>종합 판정</small><div class="result">${passed ? '통과' : '기준 미달'}</div></div>
    <div class="score">${total}<span>/ 100점</span></div>
    <div class="parts"><div><span>문서층 (사업계획서)</span><b>${docRaw} / ${docMaxScore}</b></div><div><span>산출물층 (자동 검증 + 계획서 대조)</span><b>${artifactRaw} / ${artifactMax}</b></div></div>
  </div>
  <p class="rule">판정 기준 ${passThreshold}점 이상${failedItems.length || crossCheck.reasons.length ? '  |  총점 판정과 별개로 미충족 항목의 보완이 필요합니다.' : ''}</p>

  <h2><em>01</em>사업계획서 평가<small>획득 점수 / 배점</small></h2>
  <div class="doc">${docCells}
  </div>

  <h2><em>02</em>${copy.autoTitle}<small>${autoRaw} / ${autoMax}점</small></h2>
  <table>
    <thead><tr><th>점검 항목</th><th class="num">배점</th><th>결과</th><th class="num">획득</th></tr></thead>
    <tbody>${checkRows}
    </tbody>
  </table>${entryMissing ? '\n  <p class="rule">진입 파일이 없어 나머지 항목 검사가 성립하지 않으므로 자동 검증 점수는 0점으로 처리됩니다.</p>' : ''}

  <h2><em>03</em>계획서 대조 의견 및 보완 사항<small>${crossCheck.raw} / ${crossCheck.max}점</small></h2>
  <dl class="notes">
    <dt>검증 의견</dt><dd>${lines([opinion], '')}</dd>
    <dt>보완 사항</dt><dd>${lines(fixes, '보완이 필요한 항목이 없습니다.')}</dd>
    <dt>근거 기록</dt><dd>${lines(evidence, '미충족 항목의 근거 기록이 없습니다.')}</dd>
  </dl>

  <p class="disclaimer">공개된 평가항목 기준 자체 점검 결과입니다. ${esc(SCORE_DISCLAIMER)}<br>층별 배점과 판정 기준은 서비스 설정값(기본값 기준)이며 조정될 수 있습니다.</p>
  <div class="foot"><span>S-Brain  |  산출물 검증결과서</span><span>1 / 1</span></div>
</body></html>`;
}

// 숨긴 iframe에 양식을 그리고 인쇄 창을 연다. 저장 파일 이름은 문서 제목을 따르므로 잠시 바꿨다가 되돌린다.
export function printVerificationReport(data) {
  const iframe = document.createElement('iframe');
  iframe.setAttribute('aria-hidden', 'true');
  iframe.style.cssText = 'position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden';
  document.body.appendChild(iframe);
  const doc = iframe.contentDocument;
  doc.open();
  doc.write(buildVerificationReportHtml(data));
  doc.close();

  const originalTitle = document.title;
  const fileTitle = `S-Brain_검증결과서_${(data.projectName || '프로젝트').slice(0, 30)}`;
  const cleanup = () => {
    document.title = originalTitle;
    setTimeout(() => iframe.remove(), 1000);
  };
  const win = iframe.contentWindow;
  win.addEventListener('afterprint', cleanup, { once: true });
  const ready = doc.fonts?.ready ?? Promise.resolve();
  ready.then(() => {
    document.title = fileTitle;
    doc.title = fileTitle;
    win.focus();
    win.print();
  });
}
