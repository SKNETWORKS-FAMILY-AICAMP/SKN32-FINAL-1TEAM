// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import {DOC_ITEMS_FAIL,DOC_ITEMS_PASS,CODE_CHECK_ITEMS_BY_CATEGORY,CODE_CHECK_FAILS_BY_OUTCOME,APPLICANT_TYPE_LABEL,PROJECT_STATUS_TONE,RERUN_CAP,PLAN_TAGS,GENERAL_SECTION_LABEL,DIAGRAM_BUNDLE_LABEL,ALL_DOC_BUNDLES,DELIVERABLE_NOTICES,FINAL_THRESHOLD,bundleOfTag,headerOfTag} from './data.js';

export const MOCK_TODAY = new Date('2026-09-08');

// 화면에 보이는 큰 점수(총점 · 층 · 소계)는 정수로 — 소수 둘째 자리(64.09 / 70점)까지 보일 필요가 없다(10-13 재희 님).
// 얻은 점수는 내림: 반올림하면 79.6점이 '80점'인데 기준 80 '미달'로 보여 숫자와 판정이 어긋난다. 내림이면 늘 맞는다(기준은 정수).
// 1e-6은 소수 덧셈 오차(79.99999…가 사실 80)를 바로잡는 몫. 만점은 반올림(설정 배점이라 보통 정수). 항목별 작은 점수(만점 2.9점 등)는 쓰지 않는다.
export const scoreInt = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.floor(v + 1e-6) : v);
export const maxInt = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : v);

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
// 창업아이템명 — 아이디어 설명에서 글자가 있는 첫 줄, 앞뒤 공백을 떼고 60자까지. 웹 백엔드 hwp · docx(projects.py _item_name,
// SB-384)와 오케스트레이터(조율 10-13 입력반영알림)가 같은 규칙이라 화면 일반현황도 맞춘다. 예전에는 설명 전체를 그대로 보여
// 여러 줄 설명이면 화면과 내려받은 계획서의 이름이 달랐다. 줄 나눔은 파이썬 splitlines, 글자 수는 코드 포인트로 센다.
const ITEM_NAME_MAX = 60;
export function itemNameOf(description) {
  const line = String(description || '').split(/\r\n|[\n\r\v\f\x1c-\x1e\x85]|\p{Zl}|\p{Zp}/u).map((s) => s.trim()).find(Boolean);
  return line ? Array.from(line).slice(0, ITEM_NAME_MAX).join('') : '';
}
export function buildGeneralInfo(itemInfo) {
  return [
    ['기업명', 'OOOOO'],
    ['개업연월일', itemInfo?.foundedAt || 'OO.OO.OO'],
    ['사업자 구분', APPLICANT_TYPE_LABEL[itemInfo?.applicantType] || '개인사업자 / 법인사업자'],
    ['창업아이템명', itemNameOf(itemInfo?.item) || 'OO기술이 적용된 OO제품·서비스'],
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
// 점수 항목의 item_code가 가리키는 계획서 항목 제목을 항목 이름으로 쓴다. 새 모양(백엔드 응답모양변경 10-11)은
// item_code가 항목 번호('2.4.1')라 sections[].section_code와 맞추고, 옛 모양은 'PSST-1-1' -> '1-1'로 tag와 맞춘다.
function itemNameFrom(itemCode, sections){
  if (!itemCode) return '항목';
  const tag = itemCode.replace(/^PSST-/, '');
  const section = (sections || []).find((s) => (s.section_code != null && s.section_code === itemCode) || s.tag === tag);
  return section?.title || itemCode;
}
function reasonsToItems(reasons, sections){
  return (reasons || []).map((r) => ({
    name: itemNameFrom(r.item_code, sections),
    score: num(r.score) ?? 0,
    max: num(r.max_score) ?? 0,
    comment: r.reason_text || '',
    // 점수 항목의 웹 태그(새 모양) — 칸이 아예 없는 옛 응답과 null(일반현황 · 개요)을 구분한다.
    ...('tag' in r ? { tag: r.tag ?? null } : {}),
  }));
}

// 문서층 점수 항목을 묶음(일반현황 · 개요 → 문제인식 → … → 팀 구성)별로 모은다. 새 모양은 항목이 24개 안팎이라
// 하나씩 늘어놓지 않고 묶음 합계로 보인다. 항목에 tag 칸이 없는 옛 응답(4항목)은 null — 화면이 예전처럼 항목별로 보인다.
export function docGroupsFrom(items){
  if (!(items || []).some((it) => 'tag' in it)) return null;
  const labels = [GENERAL_SECTION_LABEL, DIAGRAM_BUNDLE_LABEL, ...PLAN_TAGS.map(bundleOfTag)];
  return labels.map((label) => {
    const mine = items.filter((it) => bundleOfTag(it.tag) === label);
    return { label, score: sumScores(mine), max: mine.reduce((s, it) => s + it.max, 0), items: mine };
  }).filter((g) => g.items.length);
}
// 묶음 미달 사유 한 줄 — "문제인식 12/20 — 시장 규모, 경쟁 분석". 깎인 항목이 많으면 앞의 셋만 이름을 적는다.
function groupReason(g){
  const missed = g.items.filter((it) => it.score < it.max).map((it) => it.name);
  const names = missed.slice(0, 3).join(', ') + (missed.length > 3 ? ` 외 ${missed.length - 3}개` : '');
  return `${g.label} ${g.score}/${g.max}${names ? ` — ${names}` : ''}`;
}

export function scoresFromResult(result){
  const verdict = result?.verdict;
  const plan = result?.plan;
  const docItems = reasonsToItems(plan?.score_reasons, plan?.sections);
  const docGroups = docGroupsFrom(docItems);
  // 묶음 통과 비율 — 전체 통과 기준(100점 만점 기준점, 화면 9 verdict.pass_threshold · 화면 6 plan.threshold)과 같은 비율(bundleScoreOf).
  const passRatio = (num(verdict?.pass_threshold) ?? num(plan?.threshold) ?? FINAL_THRESHOLD) / 100;
  const docScoreOf = (raw, max) => ({
    raw: num(raw) ?? sumScores(docItems),
    max: num(max) ?? num(plan?.doc_max_score) ?? 70,
    items: docItems,
    groups: docGroups,
    passRatio,
    reasons: docGroups ? docGroups.filter((g) => g.score < g.max).map(groupReason) : reasonsFromItems(docItems),
  });
  const noticesOf = (list) => (list || []).map((n) => (typeof n === 'string' ? n : n?.message)).filter(Boolean);

  // 화면 6(문서 평가) — 종합 판정 전이라 verdict가 없다(조율 종합 점수 보고서가 아직 없음). 문서층 점수 · 기준 · 안내는 plan에 있다
  // (백엔드 BusinessPlanOut doc_score · doc_max_score · threshold · notices). 예전엔 verdict가 없으면 null을 돌려 화면 6이 서버 점수 대신
  // 예시 점수(DOC_SCORE_BY_OUTCOME)를 보였다. 문서 점수도 아직 없으면(채점 전) null — 화면은 기존 고정 표로 돌아간다.
  if (!verdict) {
    if (num(plan?.doc_score) == null) return null;
    return {
      docScore: docScoreOf(plan.doc_score, plan.doc_max_score),
      artifactScore: null,
      codeCheckItems: null,
      artifactLayer: null,
      total: null,
      threshold: num(plan.threshold),
      notices: noticesOf(plan.notices),
    };
  }
  const artifact = plan?.artifacts?.[0];
  const artifactReasons = artifact?.score_reasons || [];
  const isCross = (r) => (r.item_code || '').startsWith('FEATURE-');
  const docScore = docScoreOf(verdict.doc_score, verdict.doc_max_score);

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
  // [SB-301] 계획서 대조 판정이 보류되면(plan_match_withheld) 점수는 0점으로 합산돼 오지만 기능이 빠진 게 아니다 —
  // 화면은 0점 · 누락 기능 대신 "대조 불가"로 보인다. 서버 사유 문구("…대조 불가…0점으로 합산")는 누락 기능으로 세지 않는다.
  if (verdict.plan_match_withheld) {
    artifactScore.crossCheck = { ...artifactScore.crossCheck, withheld: true, reasons: [] };
  }

  // 코드 검증 8항목 — 서버가 준 CHECK-* 항목을 그대로 쓴다. 이름은 item_code에서
  // 접두어만 떼고 보여준다(사람이 읽을 이름을 서버가 따로 주지 않는다).
  // weight(배점) · earned(얻은 점수)도 넘긴다 — 검증결과서 PDF 표가 이 둘로 칸을 채운다(없으면 undefined · NaN으로 찍혔다).
  const codeCheckItems = artifactReasons.filter((r) => !isCross(r)).map((r, i) => ({
    id: r.item_code || `CHECK-${i}`,
    name: r.display_name || (r.item_code || '').replace(/^CHECK-/, '') || '검증 항목',
    weight: num(r.max_score) ?? 0,
    earned: num(r.score) ?? 0,
    passed: (num(r.score) ?? 0) >= (num(r.max_score) ?? 0),
    // 검사할 대상이 없는 항목(백엔드 응답모양변경 10-11 1-2) — 점수 0 · 만점 0이라 passed가 참이지만 통과로 세지 않는다.
    applicable: r.applicable !== false,
    evidence: r.reason_text || null,
  }));

  return {
    docScore,
    artifactScore,
    codeCheckItems: codeCheckItems.length ? codeCheckItems : null,
    // 산출물층(코드 점검 + 계획서 대조)을 그 실행 건 배점으로 환산한 값 — 없으면(옛 응답) 화면이 두 칸을 더한다.
    artifactLayer: num(verdict.artifact_max_score) != null ? { raw: num(verdict.artifact_score) ?? 0, max: num(verdict.artifact_max_score) } : null,
    total: num(verdict.total_score),
    threshold: num(verdict.pass_threshold),
    // 종합 평가 점수 보고서의 안내(화면 9 — 입력 확인 필요 · 입력 오류, 조율 10-12). 화면 6의 안내는 plan.notices(위). 칸이 없으면 빈 목록.
    notices: noticesOf(verdict.notices),
  };
}

// 표현 검수 화면의 문단 전/후 — GET /result의 plan.proofread_logs(실제 검수 기록)를 쓴다.
// 예전엔 시연 로그에서 베낀 고정 문단(REVIEW_PARAGRAPHS)만 보여줬다.
// [2026-09-29 수정] ProofreadLogOut이 attempt_no/passed/violation_note까지 내려주게
// 되면서(app/schemas.py) "1차 반려 → 2차 통과" 재시도 과정도 그릴 수 있게 됐다 — 지금
// 더미 구현(app/routers/projects.py review_token_check)은 같은 문단을 계속 이어 고치는
// 구조라 section_id로 묶으면 그게 한 문단의 시도 이력이 된다. 관계(BusinessPlan.
// proofread_logs)엔 order_by가 없어 배열 순서를 못 믿으므로 attempt_no로 직접 정렬한다.
// 결과물 화면 고지 4줄 — 백엔드 /result의 deliverable(SB-371, 10-13)에 문구가 있으면 그것으로 바꾼다.
// submission_notice → [제출 안내](공고별 제출 요건 확인), disclaimer → [계획서](내려받는 계획서 첫 장과 같은 문구).
// 결과물이 아직 없거나(deliverable null) 칸이 비면 고정 문구(DELIVERABLE_NOTICES) 그대로.
export function deliverableNoticesFrom(deliverable){
  const fromServer = { '계획서': deliverable?.disclaimer, '제출 안내': deliverable?.submission_notice };
  return DELIVERABLE_NOTICES.map((n) => {
    const text = typeof fromServer[n.label] === 'string' ? fromServer[n.label].trim() : '';
    return text ? { ...n, text } : n;
  });
}

// 결과물 화면 "제출 전에 보완하면 좋은 항목" — /result deliverable.shortfall_items(SB-371, 오케스트레이터 결과 통합 10-13).
// 계획서(document) · 프로토타입(artifact)으로 나누고 받은 순서 그대로. 계획서 줄은 웹 태그로 묶음 이름을 앞에 붙이고(태그 없음 = 일반현황 · 개요),
// 점수 · 배점이 둘 다 있으면 소수 한 자리로 붙인다(반올림 몰아주기로 0.01처럼 오는 값도 0으로). 코드 점검 부분 점수 줄도 빼지 않는다 —
// 화면 8이 만점이 아닌 코드 점검을 이미 '미달'로 보여서다. 칸이 없거나 빈 목록이면 null(화면이 칸을 그리지 않음).
export function shortfallFrom(deliverable){
  const rows = deliverable?.shortfall_items;
  if (!Array.isArray(rows) || !rows.length) return null;
  const one = (v) => Math.round(v * 10) / 10;
  const line = (row, i) => {
    const score = num(row?.score), max = num(row?.max_score);
    return {
      key: `${row?.layer}-${row?.kind}-${row?.code ?? i}-${i}`,
      bundle: row?.layer === 'document' ? bundleOfTag(row?.tag ?? null) : null,
      name: row?.name || row?.code || '항목',
      // 코드 점검 줄은 오케스트레이터가 사유 앞에 '1.25/1.88점 — '를 붙여 준다 — 점수는 points로 따로 붙이므로 떼어 낸다.
      reason: String(row?.reason || '').replace(/^\s*\d+(?:\.\d+)?\s*\/\s*\d+(?:\.\d+)?\s*점\s*[—-]\s*/, ''),
      points: score != null && max != null ? `${one(score)}/${one(max)}점` : null,
      inputError: row?.kind === 'inputError',
    };
  };
  const all = rows.map(line);
  const pick = (layer) => all.filter((_, i) => rows[i]?.layer === layer);
  return { document: pick('document'), artifact: pick('artifact') };
}

// 결과물 화면 '프로토타입' 받기에 담을 실제 파일 — 실행 파일과 인포그래픽(결과의 artifacts[0] 주소). 없는 칸은 빼고,
// 같은 파일을 두 칸이 가리키면(원페이지형은 실행 파일 = 인포그래픽) 한 번만 담는다. 이름은 주소의 마지막 조각.
export function prototypeFilesOf(plan){
  const artifact = plan?.artifacts?.[0];
  const paths = [...new Set([artifact?.executable_path, artifact?.infographic_path].filter(Boolean))];
  return paths.map((path) => ({ path, name: decodeURIComponent(String(path).split('?')[0].split('/').pop() || '') || 'file' }));
}

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

// 계획서 보기(화면 9)에 그릴 모양. 새 모양(항목에 section_code · content_type, 백엔드 응답모양변경 10-11)은 항목이
// 24개 안팎이라 묶음별로 모은다 — 일반현황 · 개요(tag가 1-1 ~ 4-1이 아닌 항목), 그림(diagrams), 문제인식 ~ 팀 구성.
// 그림 항목(content_type 'image')은 문장이 없어 본문으로 그리지 않는다 — tag가 '2-1'로 와도 diagrams로 보인다(10-12 답변 3).
// 옛 모양(4항목)은 legacy — 화면이 예전처럼 항목마다 공식 머리말로 그린다. 계획서가 없으면 null.
export function planViewFrom(plan){
  const sections = plan?.sections || [];
  if (!sections.length) return null;
  if (!sections.some((s) => 'section_code' in s || 'content_type' in s)) return { legacy: true, sections };
  const text = sections.filter((s) => s.content_type !== 'image');
  // 표를 만들지 못해 본문으로 대신한 항목 → 사용자용 안내(백엔드 plan.table_fallbacks[].display_reason, 10-13).
  // 담당자 판정 원문(reason)은 내부 진단용이라 백엔드가 싣지 않는다 — 옛 모양으로 오면 그것이라도 보인다.
  const fallbacks = Object.fromEntries((plan.table_fallbacks || [])
    .map((f) => [f?.section_code, f?.display_reason || f?.reason]).filter(([code, reason]) => code && reason));
  // 표 항목(content_type 'table')의 실제 표 — plan.tables[](headers · rows, source_ref = 항목 번호). 내려받는 워드 · 한글처럼 화면도 표로 그린다
  // (예전엔 표 항목도 담당자 서술 문장 한 줄만 보였다). 표를 본문으로 대신한 항목(fallbacks)은 표가 없으므로 넣지 않는다.
  const tables = Object.fromEntries((plan.tables || [])
    .filter((t) => t?.source_ref && Array.isArray(t.headers) && t.headers.length && Array.isArray(t.rows) && t.rows.length && !fallbacks[t.source_ref])
    .map((t) => [t.source_ref, { headers: t.headers.map(String), rows: t.rows.map((r) => (Array.isArray(r) ? r.map((c) => (c == null ? '' : String(c))) : [])) }]));
  return {
    legacy: false,
    fallbacks,
    tables,
    general: text.filter((s) => !PLAN_TAGS.includes(s.tag)),
    diagrams: (plan.diagrams || []).filter((d) => d && d.image_url),
    bundles: PLAN_TAGS.map((tag) => ({ tag, header: headerOfTag(tag), sections: text.filter((s) => s.tag === tag) }))
      .filter((b) => b.sections.length),
  };
}

// 재작성 결과 changed.sections를 항목 목록으로 편다. 옛 모양은 키가 웹 태그('1-1')이고, 새 모양(백엔드 재작성결과 보충
// 10-11)은 키가 항목 번호('2.4.1')이고 값에 tag · title이 붙는다. 묶음 순서(1-1 → 4-1, 일반현황 · 개요는 맨 앞)로 정렬한다.
export function sectionDiffEntries(sections){
  const order = (tag) => (tag == null ? -1 : PLAN_TAGS.indexOf(tag));
  return Object.entries(sections || {})
    .filter(([, v]) => v && typeof v === 'object' && ('before' in v || 'after' in v))
    .map(([key, v]) => {
      const hasTag = 'tag' in v;
      const tag = hasTag ? v.tag : (PLAN_TAGS.includes(key) ? key : null);
      return { key, tag, hasTag, bundle: hasTag || PLAN_TAGS.includes(key) ? bundleOfTag(tag) : key,
        title: v.title || key, before: v.before, after: v.after };
    })
    .sort((a, b) => order(a.tag) - order(b.tag) || a.key.localeCompare(b.key, undefined, { numeric: true }));
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
    const entries = sectionDiffEntries(changed.sections);
    if (entries.length) {
      const first = entries[0];
      // 새 모양(키 = 항목 번호, 값에 tag · title)은 묶음 이름으로 "문제인식 3개 항목 변경"처럼 모아 보인다.
      if (first.hasTag) {
        const counts = new Map();
        entries.forEach((e) => counts.set(e.bundle, (counts.get(e.bundle) || 0) + 1));
        const summary = [...counts].map(([b, n]) => `${b} ${n}개 항목`).join(' · ');
        return { before: `${first.title} ${first.before ?? '(없음)'}`, after: `${first.title} ${first.after ?? '(없음)'} — ${summary} 변경` };
      }
      const more = entries.length > 1 ? ` 외 ${entries.length - 1}건` : '';
      return { before: `${first.bundle} ${first.before ?? '(없음)'}`, after: `${first.bundle} ${first.after ?? '(없음)'}${more}` };
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
const DOC_BUNDLE_SET = new Set(ALL_DOC_BUNDLES);
const sameItem = (a, b) => String(a || '').replace(/\s/g, '') === String(b || '').replace(/\s/g, '');

// 계획서 묶음 하나의 판정과 깎인 항목. 새 모양은 묶음 합계(docScore.groups), 옛 모양은 이름이 같은 항목 하나다.
// 화면 6 · 9가 체크박스 옆에 통과 · 미달을, 그 아래에 이유를 붙인다(예전엔 묶음 이름 · 점수가 미달 사유 목록과 재작성 목록에 두 번 나왔다).
//   passed  — 깎인 항목이 하나도 없다. 검증-1이 주의 · 미달로 본 항목은 재작성 후보라(기획서 5-6) 하나라도 있으면 미달이다.
//             화면은 묶음 점수(12/17) 대신 이것만 보인다 — 화면 8 코드 점검처럼 통과 · 미달로(디자인 점검 10-12).
//   lines   — 깎인 항목마다 "이름 — 이유"(앞의 셋, 나머지는 "외 N개 항목"). 옛 모양은 그 항목의 이유 한 줄.
//             항목 점수(3/6 같은)는 붙이지 않는다 — 기획서가 요구하는 건 미달 항목이고(4-7 화면 6), 잘게 쪼갠 숫자는
//             실제 심사 점수처럼 읽힌다(3-6). 점수는 묶음 합계까지만 보인다.
//   summary — 좁은 칸(화면 6 왼쪽)에 쓰는 한 줄. 새 모양은 깎인 항목 이름만, 옛 모양은 이유.
// 그 묶음 점수 항목이 없으면 null.
export function bundleScoreOf(label, docScore){
  // 통과 = 만점 대비 전체 통과 기준과 같은 비율(기본 80%) 이상. 예전엔 한 점이라도 깎이면 미달이라, 86점 통과인데
  // 묶음 넷이 다 미달로 보였다(10-13 스텁 실행). 깎인 항목 이름(lines · summary)은 통과여도 그대로 보인다 — 다시 만들 근거.
  const ratio = docScore.passRatio ?? FINAL_THRESHOLD / 100;
  const meets = (score, max) => score + 1e-9 >= max * ratio; // 2.4 × 5 = 11.999… 같은 소수 오차
  const group = docScore.groups?.find((g) => g.label === label);
  if (group) {
    const missed = group.items.filter((it) => it.score < it.max);
    const more = missed.length > 3 ? missed.length - 3 : 0;
    return {
      score: group.score, max: group.max, passed: meets(group.score, group.max),
      lines: [...missed.slice(0, 3).map((it) => `${it.name}${it.comment ? ` — ${it.comment}` : ''}`), ...(more ? [`외 ${more}개 항목`] : [])],
      summary: missed.slice(0, 3).map((it) => it.name).join(', ') + (more ? ` 외 ${more}개` : ''),
    };
  }
  if (docScore.groups) return null;
  const item = (docScore.items || []).find((it) => sameItem(it.name, label));
  if (!item) return null;
  const comment = item.score < item.max ? item.comment || '' : '';
  return { score: item.score, max: item.max, passed: meets(item.score, item.max), lines: comment ? [comment] : [], summary: comment };
}

// 재작성 목록의 묶음 아래에 붙이는 "왜 다시 만들어야 하는지". 계획서 묶음은 bundleScoreOf의 lines, 실행 파일은 산출물층 사유.
export function taskReasons(label, docScore, artifactScore){
  const bundle = bundleScoreOf(label, docScore);
  if (bundle) return bundle.lines;
  if (DOC_BUNDLE_SET.has(label)) return [];
  if (label === '실행 파일 제작') return [...artifactScore.autoCheck.reasons, ...artifactScore.crossCheck.reasons];
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
