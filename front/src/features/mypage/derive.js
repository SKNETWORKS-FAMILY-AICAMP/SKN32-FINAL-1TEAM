// 입력값에서 바로 계산되는 판정들. 공고별 세부 기준(특별지원지역 목록 등)은 공고마다 달라
// 여기선 공통으로 쓰이는 것(청년·업력·수도권)만 계산한다.

export const SIDO = ['서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도', '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도'];
const CAPITAL_AREA = ['서울특별시', '인천광역시', '경기도'];

export function monthsBetween(from, to = new Date()) {
  const a = new Date(from);
  const b = new Date(to);
  if (Number.isNaN(a.getTime()) || Number.isNaN(b.getTime())) return null;
  const m = (b.getFullYear() - a.getFullYear()) * 12 + b.getMonth() - a.getMonth() - (b.getDate() < a.getDate() ? 1 : 0);
  return m < 0 ? null : m;
}

export function formatMonths(m) {
  const y = Math.floor(m / 12);
  const r = m % 12;
  if (!y) return `${r}개월`;
  return r ? `${y}년 ${r}개월` : `${y}년`;
}

export function youthBadge(birthDate) {
  const m = monthsBetween(birthDate);
  if (m == null) return null;
  const age = Math.floor(m / 12);
  return age <= 39 ? { tone: 'ok', text: `청년 · 만 ${age}세` } : { tone: 'muted', text: `만 ${age}세 · 청년 기준 초과` };
}

// 창업지원 공고에서 흔히 쓰는 업력 구간(초기 3년 / 도약 3~7년)
export function careerBadge(openedAt) {
  const m = monthsBetween(openedAt);
  if (m == null) return null;
  const text = `업력 ${formatMonths(m)}`;
  if (m <= 36) return { tone: 'ok', text: `${text} · 초기창업` };
  if (m <= 84) return { tone: 'ok', text: `${text} · 도약기` };
  return { tone: 'warn', text: `${text} · 7년 초과` };
}

export function regionBadge(sido) {
  if (!sido) return null;
  return CAPITAL_AREA.includes(sido) ? { tone: 'muted', text: '수도권' } : { tone: 'ok', text: '비수도권' };
}

export const formatBizNo = (v) => {
  const d = v.replace(/\D/g, '').slice(0, 10);
  return [d.slice(0, 3), d.slice(3, 5), d.slice(5)].filter(Boolean).join('-');
};

// 탭별 채움 정도 — [채운 개수, 전체]. 예비창업자는 사업자 항목을 세지 않는다.
export function progressOf(state) {
  const { basic, bizStatus, capability: cap, history } = state;
  const pre = basic.applicantType === 'preliminary';
  const bizChecked = bizStatus?.checkedNo === basic.bizNo && bizStatus?.valid;
  const basicChecks = [
    basic.applicantType, basic.ceoName, basic.birthDate, basic.gender, basic.home.sido,
    ...(pre ? [] : [bizChecked, basic.openedAt, basic.industry, basic.hqSameAsHome || basic.hq.sido]),
  ];
  const capChecks = [cap.careers.length, cap.skills.trim(), cap.soloFounder || cap.team.length];
  const historyChecks = basic.startType === 'restart' ? [history.pastBusinesses.length] : [];
  const count = (arr) => [arr.filter(Boolean).length, arr.length];
  return { basic: count(basicChecks), capability: count(capChecks), history: count(historyChecks) };
}
