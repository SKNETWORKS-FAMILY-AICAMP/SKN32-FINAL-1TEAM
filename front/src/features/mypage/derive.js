// 입력값에서 바로 계산되는 판정들. 공고별 세부 기준(특별지원지역 목록 등)은 공고마다 달라
// 여기선 공통으로 쓰이는 것(청년·업력·수도권)만 계산한다.

export const SIDO = ['서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시', '세종특별자치시', '경기도', '강원특별자치도', '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도'];
const CAPITAL_AREA = ['서울특별시', '인천광역시', '경기도'];

// 초기창업패키지 등 신청서의 "지원 분야/전문기술분야" 체크박스 목록 그대로 — 개인사업자·
// 법인은 이미 사업자등록이 돼 있어 업종이 이 표 중 하나로 정해져 있으니 자유 입력 대신
// 여기서만 고르게 한다. 예비창업자는 업종이 아직 없을 수 있어 자유 입력을 유지한다.
export const INDUSTRY_OPTIONS = ['제조', '지식서비스', '기계·소재', '전기·전자', '정보·통신', '화공·섬유', '바이오·의료·생명', '에너지·자원', '공예·디자인'];

// 공고마다 요구하는 인증·가입 조건이 계속 늘어날 수 있어 특정 항목을 전용 필드로
// 박아두지 않고 칩 하나로 다룬다 — 목록에 없는 조건은 ChipSelect의 "+ 직접 입력"으로 추가.
export const CERTS = ['여성기업', '장애인기업', '벤처기업', '이노비즈', '메인비즈', '사회적기업', '노란우산공제'];

// 마이페이지 "대표자 이력"에서 경력/학력/지원사업/교육/수상을 하나의 목록으로 받을 때 쓰는 구분.
export const CAREER_TYPES = ['경력', '학력', '정부지원사업', '교육 이수', '수상', '자격증'];

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

// 예비창업패키지류 공고가 흔히 두는 상한(단위 만원) — 정확한 상한은 공고마다 다르므로
// 입력 자체를 이 값에서 못 넘어가게 막는 안내용 캡으로 쓴다.
export const PRELIMINARY_BUDGET_CAP_MANWON = 2000;

export function wonToNumber(v) {
  const d = String(v || '').replace(/[^0-9]/g, '');
  return d ? Number(d) : null;
}

export function formatWon(v) {
  const n = wonToNumber(v);
  return n == null ? '' : n.toLocaleString('ko-KR') + '원';
}

// 마이페이지 프로필 → 새 프로젝트 입력 폼(IntakeForm) 값. "내 정보 불러오기"가 쓰는
// 변환은 여기 한 곳에만 둔다 — 마이페이지 저장소가 나중에 서버로 옮겨가도 이 함수는 그대로.
// 아이디어·단가·첨부는 프로젝트마다 달라서 옮기지 않는다. 나머지는 전부 옮긴다 — 저장해둔
// 걸 잊고 프로젝트 화면에서 새로 쓰는 사람이 있을 수 있어, 불러온 뒤 그 자리에서 다 보고
// 고칠 수 있어야 한다(그래서 프로필 원본이 아니라 복사본을 준다).
export const EMPTY_TEAM_ROW = { name: '', role: '', career: '' };
export const CAREER_FIELDS = [
  { key: 'type', label: '구분', type: 'select', options: CAREER_TYPES },
  { key: 'title', label: '내용', placeholder: '○○전자 · 백엔드 개발' },
  { key: 'period', label: '기간', placeholder: '2019.03 – 2023.10' },
  { key: 'hasProof', label: '증빙 있음', type: 'check' },
];
export const HIRE_FIELDS = [
  { key: 'job', label: '직무', placeholder: '프론트엔드 개발' },
  { key: 'count', label: '인원', placeholder: '1명' },
  { key: 'skill', label: '요구 역량', placeholder: 'React 3년 이상' },
  { key: 'when', label: '채용 시기', type: 'month' },
];
export const EQUIPMENT_FIELDS = [
  { key: 'name', label: '이름', placeholder: 'GPU 서버' },
  { key: 'status', label: '상태', type: 'select', options: ['보유', '도입 예정'] },
];
export const PARTNER_FIELDS = [
  { key: 'name', label: '기관명 · 협력 내용', placeholder: '○○대학 · 실증 지원' },
  { key: 'status', label: '상태', type: 'select', options: ['협력 중', '예정'] },
];

export function profileToIntake(profile) {
  const { basic: b, capability: c } = profile;
  const team = c.team.map(({ name, role, career }) => ({ name, role, career }));
  const copyRows = (rows) => rows.map((r) => ({ ...r }));
  return {
    applicantType: b.applicantType,
    ceoName: b.ceoName,
    birthDate: b.birthDate,
    gender: b.gender,
    foundedAt: b.applicantType === 'preliminary' ? '' : b.openedAt,
    // 사업자등록번호는 입력 화면에 다시 노출하지 않고 값만 들고 간다 — 사업계획서 일반현황
    // (companies.business_reg_no)을 채우는 값이라, 안 넘기면 문서에 ○○○-○○-○○○○○로 남는다.
    // 마이페이지에서 이미 국세청 조회를 거친 값이라 여기서 다시 검증하지 않는다.
    // 예비창업자는 사업자등록번호 자체가 없다(설립일과 같은 규칙).
    bizNo: b.applicantType === 'preliminary' ? '' : (b.bizNo || ''),
    companyName: b.applicantType === 'preliminary' ? '' : (b.companyName || ''),
    noTeam: c.soloFounder,
    team: team.length ? team : [{ ...EMPTY_TEAM_ROW }],
    industry: b.industry,
    region: { ...b.region },
    certs: [...b.certs],
    careers: copyRows(c.careers),
    skills: c.skills,
  };
}

// 마이페이지 필수 항목 — 보유 인증·가입만 선택이다. 채용 계획·장비·협력 기관·자기부담금·
// 희망 사업 규모는 프로젝트마다 달라 프로젝트 작성 화면(IntakeForm)에서 받는다.
// 항목마다 tab/anchor를 같이 돌려줘서, 저장을 누르면 첫 빈 항목의 탭·섹션으로 바로 이동한다.
const teamRowFilled = (r) => r.name?.trim() && r.role?.trim() && r.career?.trim();
export function missingRequiredFields(profile) {
  const { basic, capability: cap } = profile;
  const biz = basic.applicantType === 'individual' || basic.applicantType === 'corp';
  const missing = [];
  const need = (cond, label, tab, anchor) => { if (cond) missing.push({ label, tab, anchor }); };
  need(!basic.applicantType, '신청자 유형', 'basic', 'mp-applicant');
  need(!basic.ceoName || !basic.birthDate || !basic.gender, '대표자 정보', 'basic', 'mp-ceo');
  need(!basic.region.sido || !basic.industry?.trim(), '지역 · 주업종', 'basic', 'mp-region');
  need(biz && (!basic.bizNo || !basic.companyName || !basic.openedAt), '사업자 정보', 'basic', 'mp-biz');
  need(!cap.careers.length || !cap.skills?.trim(), '대표자 이력', 'capability', 'mp-career');
  need(!cap.soloFounder && !(cap.team.length && cap.team.every(teamRowFilled)), '팀 구성원', 'capability', 'mp-team');
  return missing;
}
