// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import {DOC_ITEMS_FAIL,DOC_ITEMS_PASS,CODE_CHECK_ITEMS_BY_CATEGORY,CODE_CHECK_FAILS_BY_OUTCOME,APPLICANT_TYPE_LABEL,PROJECT_STATUS_TONE} from './data.js';

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
export function taskReasons(label, docScore, artifactScore){
  if (label === '사업계획서 본문 작성') return docScore.reasons.map((r) => `［문서층］ ${r}`);
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
