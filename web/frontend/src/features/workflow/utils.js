// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import {DOC_ITEMS_FAIL,DOC_ITEMS_PASS,CODE_CHECK_ITEMS_BY_CATEGORY,CODE_CHECK_FAILS_BY_OUTCOME,APPLICANT_TYPE_LABEL,PROJECT_STATUS_TONE,RERUN_CAP} from './data.js';

export const MOCK_TODAY = new Date('2026-09-08');

export function yearsSince(dateStr){
  const then = new Date(dateStr);
  let years = MOCK_TODAY.getFullYear() - then.getFullYear();
  const m = MOCK_TODAY.getMonth() - then.getMonth();
  if (m < 0 || (m === 0 && MOCK_TODAY.getDate() < then.getDate())) years--;
  return years;
}

// R-2(신청 자격 확인) 요약: 구조화 필드 비교만으로 통과·불통과를 정한다. LLM을 호출하지
// 않으므로 같은 입력에 항상 같은 결과가 나온다. COMP-ID-002: 설립일자 미입력 = 예비창업자.
export function evaluateEligibility(rule, company){
  const isPreFounding = !company.foundedAt;
  const ageYears = isPreFounding ? null : yearsSince(company.foundedAt);

  const typeOk =
    rule.applicantType === '제한없음' ? true :
    rule.applicantType === '예비창업자' ? isPreFounding :
    !isPreFounding && (rule.ageLimitYears == null || ageYears <= rule.ageLimitYears);

  const ageOk = rule.ageLimitYears == null ? true : isPreFounding ? true : ageYears <= rule.ageLimitYears;
  const deadlineOk = MOCK_TODAY <= new Date(rule.deadline);

  const rows = [
    {
      label: '지원대상 유형',
      criterion: rule.applicantType,
      actual: isPreFounding ? '예비창업자' : `업력 ${ageYears}년 기업`,
      passed: typeOk,
    },
    {
      label: '업력 상한',
      criterion: rule.ageLimitYears == null ? '제한없음' : `${rule.ageLimitYears}년 이내`,
      actual: isPreFounding ? '해당없음 (예비창업자)' : `${ageYears}년`,
      passed: ageOk,
    },
    {
      label: '접수기간',
      criterion: `${rule.deadline} 마감`,
      actual: deadlineOk ? '접수 중' : '마감 지남',
      passed: deadlineOk,
    },
  ];

  return { rows, passed: rows.every((r) => r.passed) };
}

// 목업 수정 요청서 v3 §4: reason(매칭 사유)은 모델이 생성한 요약이라 기획서 6-1이
// 출처 표기 + 원문 링크를 함께 요구한다. sourceNotice는 시연 로그(steps[2].data.
// candidates[].sourceNotice)와 동일하게 모든 공고에 같은 문구를 쓰고, originalUrl은
// 공고별로 다르다(초기창업패키지·예비창업패키지·창업도약패키지 3건은 시연 로그의
// 실제 K-Startup 공고 ID를 그대로 썼다).
export function buildGeneralInfo(itemInfo) {
  return [
    ['기업명', 'OOOOO'],
    ['개업연월일', itemInfo?.foundedAt || 'OO.OO.OO'],
    ['사업자 구분', APPLICANT_TYPE_LABEL[itemInfo?.applicantType] || '개인사업자 / 법인사업자'],
    ['창업아이템명', itemInfo?.item || 'OO기술이 적용된 OO제품·서비스'],
    ['지원 분야', '제조 / 지식서비스 중 택 1'],
  ];
}
export function buildOverview(itemTitle, sections) {
  return `${itemTitle ? `『${itemTitle}』 공고 기준. ` : ''}${sections?.[0]?.body || ''}`;
}

// PlanForm/계획서 보기 모달/비교 모달이 공통으로 쓰는 "□ 일반현황"·"□ 창업 아이템
// 개요(요약)" 블록 — 다운로드 파일(buildPlanDocx)과 같은 순서·제목을 화면에도 그대로 낸다.
export function sumScores(items){ return items.reduce((s, it) => s + it.score, 0); }
export function reasonsFromItems(items){
  return items.filter((it) => it.score < it.max).map((it) => `${it.name} ${it.score}/${it.max} — ${it.comment}`);
}

export const DOC_SCORE_BY_OUTCOME = {
  fail: { raw: sumScores(DOC_ITEMS_FAIL), max: 70, items: DOC_ITEMS_FAIL, reasons: reasonsFromItems(DOC_ITEMS_FAIL) },
  pass: { raw: sumScores(DOC_ITEMS_PASS), max: 70, items: DOC_ITEMS_PASS, reasons: reasonsFromItems(DOC_ITEMS_PASS) },
};
// ---------------------------------------------------------------------------
// 서버 채점 결과 -> 화면이 쓰는 점수 모양
//
// 위 DOC_SCORE_BY_OUTCOME/ARTIFACT_SCORE_BY_OUTCOME는 채점 엔진이 없던 시절의
// 고정 표다. 이제 GET /projects/{id}/result가 실제 값을 내려준다(app/schemas.py):
//   verdict            — 층별 점수·총점·통과 기준(doc_score/code_score/plan_match_score…)
//   plan.score_reasons — 문서층 항목별 {item_code, score, max_score, reason_text}
//   artifact.score_reasons — 산출물층 항목별. item_code 접두어로 층을 가른다
//                        (back/app/routers/projects.py _VERIFY2_*_PREFIXES: CHECK-/FEATURE-)
// 화면 세 곳(문서 평가·산출물 확인·종합 평가)이 이미 쓰고 있는 모양을 그대로
// 만들어 돌려주므로, 각 화면은 "서버 값이 있으면 그걸, 없으면 기존 고정 표"만
// 고르면 된다. 판정 전(verdict=null, 프로토타입 채점 이전)이나 audit/render-check
// 처럼 결과 없이 컴포넌트만 그리는 경우가 있어서 fallback은 남겨둔다.
// ---------------------------------------------------------------------------
const num = (v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v));
// 'PSST-1-1' -> '1-1'. 그 코드가 가리키는 계획서 섹션 제목을 항목 이름으로 쓴다.
function itemNameFrom(itemCode, sections){
  if (!itemCode) return '항목';
  const tag = itemCode.replace(/^PSST-/, '');
  const section = (sections || []).find((s) => s.tag === tag);
  return section?.title || itemCode;
}
function reasonsToItems(reasons, sections){
  return (reasons || []).map((r) => ({
    name: itemNameFrom(r.item_code, sections),
    score: num(r.score) ?? 0,
    max: num(r.max_score) ?? 0,
    comment: r.reason_text || '',
  }));
}

export function scoresFromResult(result){
  const verdict = result?.verdict;
  if (!verdict) return null; // 아직 채점 전 — 화면은 기존 고정 표로 돌아간다
  const plan = result?.plan;
  const artifact = plan?.artifacts?.[0];
  const artifactReasons = artifact?.score_reasons || [];
  const isCross = (r) => (r.item_code || '').startsWith('FEATURE-');

  const docItems = reasonsToItems(plan?.score_reasons, plan?.sections);
  const docScore = {
    raw: num(verdict.doc_score) ?? sumScores(docItems),
    max: num(verdict.doc_max_score) ?? 70,
    items: docItems,
    reasons: reasonsFromItems(docItems),
  };

  const layer = (rows, score, max) => {
    const items = reasonsToItems(rows);
    return {
      raw: num(score) ?? sumScores(items),
      max: num(max) ?? 15,
      // 만점인 항목은 "미달 사유"가 아니다 — 화면이 이 배열을 그대로 사유로 쓴다.
      reasons: items.filter((it) => it.score < it.max).map((it) => it.comment || it.name),
    };
  };
  const artifactScore = {
    autoCheck: layer(artifactReasons.filter((r) => !isCross(r)), verdict.code_score, verdict.code_max_score),
    crossCheck: layer(artifactReasons.filter(isCross), verdict.plan_match_score, verdict.plan_match_max_score),
  };

  // 코드 검증 8항목 — 서버가 준 CHECK-* 항목을 그대로 쓴다. 이름은 item_code에서
  // 접두어만 떼고 보여준다(사람이 읽을 이름을 서버가 따로 주지 않는다).
  const codeCheckItems = artifactReasons.filter((r) => !isCross(r)).map((r, i) => ({
    id: r.item_code || `CHECK-${i}`,
    name: (r.item_code || '').replace(/^CHECK-/, '') || '검증 항목',
    passed: (num(r.score) ?? 0) >= (num(r.max_score) ?? 0),
    evidence: r.reason_text || null,
  }));

  return {
    docScore,
    artifactScore,
    codeCheckItems: codeCheckItems.length ? codeCheckItems : null,
    total: num(verdict.total_score),
    threshold: num(verdict.pass_threshold),
  };
}

// 표현 검수 화면의 문단 전/후 — GET /result의 plan.proofread_logs(실제 검수 기록)를 쓴다.
// 예전엔 시연 로그에서 베낀 고정 문단(REVIEW_PARAGRAPHS)만 보여줬다.
// [2026-09-29 수정] ProofreadLogOut이 attempt_no/passed/violation_note까지 내려주게
// 되면서(app/schemas.py) "1차 반려 → 2차 통과" 재시도 과정도 그릴 수 있게 됐다 — 지금
// 더미 구현(app/routers/projects.py review_token_check)은 같은 문단을 계속 이어 고치는
// 구조라 section_id로 묶으면 그게 한 문단의 시도 이력이 된다. 관계(BusinessPlan.
// proofread_logs)엔 order_by가 없어 배열 순서를 못 믿으므로 attempt_no로 직접 정렬한다.
export function reviewParagraphsFrom(plan){
  const logs = plan?.proofread_logs || [];
  if (!logs.length) return null; // 검수 기록이 없으면 화면이 기존 예시로 돌아간다

  const groups = new Map(); // section_id(없으면 'null') -> log[]
  for (const log of logs) {
    const key = log.section_id ?? 'null';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(log);
  }

  return Array.from(groups.values()).map((groupLogs, i) => {
    const sorted = [...groupLogs].sort((a, b) => (a.attempt_no ?? 0) - (b.attempt_no ?? 0));
    const id = `p-${String(i + 1).padStart(2, '0')}`;
    const first = sorted[0];

    // 시도가 하나뿐이고 통과했으면(재작업 과정을 보여줄 게 없으면) 기존 평평한 모양 그대로.
    if (sorted.length === 1 && first.passed !== false) {
      return { id, before: first.original_text || '', after: first.corrected_text || '', reason: first.reason || null };
    }

    return {
      id,
      spotlight: true,
      before: first.original_text || '',
      attempts: sorted.map((log) => ({
        try: log.attempt_no,
        passed: log.passed !== false,
        after: log.corrected_text || '',
        issue: log.passed === false ? (log.violation_note || log.reason || null) : null,
      })),
    };
  });
}

// 재작성 응답(POST /projects/{id}/retry-task)의 changed를 "변경 내역" 한 줄로 바꾼다.
// changed 모양은 task_key마다 다르다(app/schemas.py RetryTaskResponse):
//   writing            -> { sections: { '1-1': {before, after}, … } }
//   implement_*        -> { executable_path | infographic_path: {before, after} }
//   verify1_*/verify2_*-> { scores: {...}, doc_score|artifact_score: {before, after} }
// 서버가 쓸 만한 전/후를 안 준 경우엔 null을 돌려주고, 화면이 기존 고정 문구로 돌아간다.
export function reworkDiffFromChanged(changed){
  if (!changed) return null;
  const pair = (v) => (v && typeof v === 'object' && ('before' in v || 'after' in v) ? v : null);
  const fileName = (p) => (typeof p === 'string' ? p.split('/').pop() : null);

  if (changed.sections && typeof changed.sections === 'object') {
    const entries = Object.entries(changed.sections).map(([tag, v]) => [tag, pair(v)]).filter(([, v]) => v);
    if (entries.length) {
      const [tag, v] = entries[0];
      const more = entries.length > 1 ? ` 외 ${entries.length - 1}건` : '';
      return { before: `${tag} ${v.before ?? '(없음)'}`, after: `${tag} ${v.after ?? '(없음)'}${more}` };
    }
  }
  for (const key of ['executable_path', 'infographic_path']) {
    const v = pair(changed[key]);
    if (v) return { before: fileName(v.before) || '(없음)', after: fileName(v.after) || '(없음)' };
  }
  for (const key of ['doc_score', 'artifact_score']) {
    const v = pair(changed[key]);
    if (v) return { before: `${v.before ?? '-'}점`, after: `${v.after ?? '-'}점` };
  }
  return null;
}

export function detectItemCategory(itemText){
  const text = itemText || '';
  if (/매장|오프라인|가게|매점|제조|공장|카페|식당/.test(text)) return 'onepage';
  if (/AI|인공지능|API|챗봇|추천\s*엔진|이미지\s*생성|모델(?!링)/i.test(text)) return 'aiapi';
  return 'webdev';
}

export function buildCodeCheckItems(category, scoreOutcome){
  const itemCategory = category === 'onepage' ? 'onepage' : 'standard';
  const fails = CODE_CHECK_FAILS_BY_OUTCOME[scoreOutcome][itemCategory];
  return CODE_CHECK_ITEMS_BY_CATEGORY[itemCategory].map((item) => ({
    ...item, passed: !(item.id in fails), evidence: fails[item.id] || null,
  }));
}

// 기획서 4-5: "산출물 확인" 화면은 합격선을 표기하지 않는다 — 코드 검증 8항목과 계획서
// 대조 누락 기능을 항목별로 보여주고, 판정(통과 여부)은 종합 평가에서 한 번만 말한다.
// 2026-09-16: 카드(제목·설명 문구·"확인했어요" 버튼) 안에 사진을 담는 구조였더니
// "박스 안에 담겨있다"는 지적을 받았다 — 그 카드 자체가 하나의 박스다. 제목/설명/
// 버튼을 다 걷어내고, 어두운 배경 위에 사진(또는 화면)만 뜨는 라이트박스로 바꾼다.
// 닫기는 우상단에 떠 있는 작은 버튼 하나, 또는 배경(다이얼로그 바깥 여백) 클릭.
// 프로토타입 HTML은 1440px 고정폭 디자인이라 보여줄 상자에 맞춰 축소해야 한다.
// 배율을 0.6처럼 고정해두면 상자 너비와 축소된 폭이 딱 떨어지지 않아서 옆에 흰 여백이
// 남거나 가로 스크롤바가 생긴다(사용자 지적: "좌,상단에 여백이 생긴다") — 상자의 실제
// 내용 너비(clientWidth, 세로 스크롤바를 뺀 값)를 재서 배율을 그때그때 계산한다.
// transform:scale은 그려지는 크기만 줄이고 레이아웃 박스는 원본(1440x3770) 그대로 두기
// 때문에, 축소된 크기로 감싸는 div를 하나 더 둬야 스크롤 범위가 눈에 보이는 높이와 맞는다.
// 서버가 내려주는 재작성 예산 — GET /result의 rework_cap + bundle_usages
// ([{bundle_id, layer, used, remaining}], back/app/schemas.py BundleUsageOut).
// [2026-09-29 수정, SB-165] 예전엔 retry_budget이 task_key로 묶여 있어서 계획서 묶음
// 여러 개가 같은 'writing' 예산 하나를 나눠 쓰는 문제가 있었다 — 서버가 bundle_id
// 단위로 내려주게 바뀌어서 이제 묶음(라벨)마다 독립적으로 잔여 횟수를 본다. 화면의
// 라벨 문자열이 곧 서버의 bundle_id다(PlanForm.jsx/FinalVerdict.jsx TASK_KEY_BY_LABEL
// 주석 참고).
// 서버가 rerun_type='rerun' AND status='completed'인 실행만 세므로 "첫 실행은 세지 않는다",
// "실패하면 기회를 돌려준다"가 서버 쪽에서 보장된다. 새로고침해도 유지된다.
export function reworkBudgetFrom(result){
  if (!result || result.rework_cap == null) return null;
  const remaining = {};
  for (const row of result.bundle_usages || []) remaining[row.bundle_id] = row.remaining;
  return { cap: result.rework_cap, remaining };
}

// 항목별 남은 재작성 횟수 — 라벨이 곧 bundle_id이므로 그대로 조회한다.
// 서버 예산이 있으면 그 값이 우선이다 — 서버가 상한을 409로 막으므로, 화면이 더 후하게
// 열어두면 눌렀을 때 에러만 난다.
// 서버 예산이 없으면(구버전 응답, 채점 전) 화면이 자체로 센 값으로 돌아간다.
export function rerunLeftOf(counts, label, budget){
  if (budget && budget.remaining[label] != null) return Math.max(0, budget.remaining[label]);
  const cap = budget?.cap ?? RERUN_CAP;
  return Math.max(0, cap - ((counts && counts[label]) || 0));
}
export function isRerunCapped(counts, label, budget){
  return rerunLeftOf(counts, label, budget) <= 0;
}

// 재작성 목록의 묶음 옆에 "왜 다시 만들어야 하는지" 한 줄을 붙인다.
// 문서 묶음은 이름이 채점 항목 이름과 같으므로(data.js DOC_REWORK_BUNDLES) 그 항목의
// 점수·코멘트를 그대로 쓴다 — 예전엔 문서층 사유 전부를 '사업계획서 본문 작성' 한 줄에
// 몰아 붙여서, 어느 항목이 왜 미달인지 묶음별로 구분되지 않았다.
// 묶음 이름은 화면 표기('문제인식')이고 서버 항목 이름은 계획서 섹션 제목('문제 인식')이라
// 띄어쓰기가 다르다 — 공백을 떼고 맞춘다. 이걸 안 하면 미달 사유가 하나도 안 붙는다.
const sameItem = (a, b) => String(a || '').replace(/\s/g, '') === String(b || '').replace(/\s/g, '');

export function taskReasons(label, docScore, artifactScore){
  const item = (docScore.items || []).find((it) => sameItem(it.name, label));
  if (item) {
    if (item.score >= item.max) return [];
    return [`［문서층］ ${item.name} ${item.score}/${item.max}${item.comment ? ` — ${item.comment}` : ''}`];
  }
  if (label === '실행 파일 제작') {
    return [...artifactScore.autoCheck.reasons, ...artifactScore.crossCheck.reasons].map((r) => `［산출물층］ ${r}`);
  }
  return [];
}

// 재작성 완료 후 "변경 내역"에 쓸 항목별 전/후 요약. 실행 파일 제작의 값은 시연
// 로그(steps[11].data.reworkDiff)를 그대로 옮겼다 — 나머지는 같은 결의 더미 값.
export function diffSentences(before, after){
  const a = before.split(/(?<=[.!?])\s+/).filter(Boolean), b = after.split(/(?<=[.!?])\s+/).filter(Boolean);
  const m = a.length, n = b.length;
  const lcs = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const parts = [];
  const push = (type, text) => {
    const last = parts[parts.length - 1];
    if (last && last.type === type) last.text += ' ' + text; else parts.push({ type, text });
  };
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { push('same', a[i]); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { push('removed', a[i]); i++; }
    else { push('added', b[j]); j++; }
  }
  while (i < m) { push('removed', a[i]); i++; }
  while (j < n) { push('added', b[j]); j++; }
  return parts;
}

export function projectStatusTone(status){
  if (/완료|통과/.test(status)) return PROJECT_STATUS_TONE.ok;
  if (/미달|불통과/.test(status)) return PROJECT_STATUS_TONE.danger;
  return PROJECT_STATUS_TONE.neutral;
}

// 기획서 4-7 + 목업 수정 요청서 v3 §8: 실행은 계정당 1건이다. 완료 건("제출 완료")은
// 제한 대상이 아니고, 그 외 상태는 전부 "진행 중"으로 본다.
