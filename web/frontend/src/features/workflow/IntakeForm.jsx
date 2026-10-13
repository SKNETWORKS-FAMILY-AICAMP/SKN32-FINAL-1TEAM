// 새 프로젝트 사전 정보 입력. 입력 부품은 마이페이지(features/mypage/ui.jsx)와 같은 것을 써서
// 두 화면이 같은 모양을 유지한다. 루트를 <section data-screen="intake">로 두면 styles.css의
// 옛 IntakeForm 전용 규칙(회색 입력칸, 버튼 높이 강제 등)이 걸리므로 <div> + 다른 이름을 쓴다.
import React, { useEffect, useState } from 'react';
import { Icon } from '../../components/Icons.jsx';
import { useMyPageStore } from '../../store/useMyPageStore.js';
import {
  CAREER_FIELDS, CERTS, EMPTY_TEAM_ROW, EQUIPMENT_FIELDS, HIRE_FIELDS, MIN_CEO_AGE, PARTNER_FIELDS, isUnderMinAge, latestBirthDate, profileToIntake,
} from '../mypage/derive.js';
import {
  ChipSelect, Check, IndustryField, ListEditor, RegionInput, Section, Segmented, Select, TextInput, errorFor, focusSection, textareaCls,
} from '../mypage/ui.jsx';
import { BackButton } from './shared.jsx';
import {
  BudgetEditor, BudgetScaleField, DevPeriodField, EMPTY_BUDGET_ROW, EMPTY_FUNDING, ListOrNone, ScheduleEditor, SelfFundingField,
  budgetFilled, emptySchedule, fundingFilled, periodFilled, rowsFilled, scheduleFilled, scheduleSectionsFor, schedulePastDevEnd, scheduleSpan, selfFundingMismatch,
  agreementMaxMonths,
} from './ProjectPlanFields.jsx';

const APPLICANT_TYPES = [['preliminary', '예비창업자'], ['individual', '개인사업자'], ['corp', '법인']];
const APPLICANT_LABEL = Object.fromEntries(APPLICANT_TYPES);
const TEAM_FIELDS = [
  { key: 'name', label: '이름', placeholder: '홍길동' },
  { key: 'role', label: '역할', placeholder: '대표 · 개발' },
  { key: 'career', label: '경력 · 학력', placeholder: '제빵 경력 8년' },
];
const PRICING_FIELDS = [
  { key: 'item', label: '상품 · 서비스', placeholder: '주문 1건당 수수료' },
  { key: 'price', label: '단가', placeholder: '500원' },
];
const EMPTY_PRICING_ROW = { item: '', price: '' };
const EMPTY_EXTRA = { region: { sido: '', sigungu: '' }, industry: '', certs: [], careers: [], skills: '' };

function LoadProfileModal({ open, profiles, onPick, onClose }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div role="dialog" aria-modal="true" aria-labelledby="load-profile-title" className="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)]">
        <div className="flex items-center justify-between mb-2">
          <h2 id="load-profile-title" className="font-bold text-[18px]">어떤 프로필을 불러올까요?</h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors"><Icon name="close" size={18} /></button>
        </div>
        <p className="text-[13px] text-[var(--muted-fg)] mb-4">불러온 내용은 이 프로젝트에만 복사돼요. 여기서 고쳐도 마이페이지는 바뀌지 않아요.</p>
        <div className="rounded-xl border border-[var(--border)] overflow-hidden">
          {profiles.map((p, i) => {
            const empty = !p.basic.applicantType;
            return (
              <button key={i} type="button" disabled={empty} onClick={() => onPick(p)}
                className={`w-full flex items-center justify-between gap-3 px-4 py-3 text-left transition-colors ${i > 0 ? 'border-t border-[var(--border)]' : ''} ${empty ? 'cursor-not-allowed' : 'hover:bg-[#f5f9ff]'}`}>
                <span className="min-w-0">
                  <span className={`block truncate text-[14.5px] font-semibold ${empty ? 'text-[#b0b8c1]' : ''}`}>{p.name}</span>
                  <span className="block text-[12.5px] text-[var(--muted-fg)]">
                    {empty ? '아직 비어 있어요' : [APPLICANT_LABEL[p.basic.applicantType], p.basic.ceoName].filter(Boolean).join(' · ')}
                  </span>
                </span>
                {!empty && <Icon name="chevron" size={16} className="text-[#b0b8c1] flex-shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// 묶음 머리말 — 사전 정보 입력은 구역이 16개 안팎이라 ① 아이디어 · ② 신청자 정보 · ③ 사업 계획으로 나눠 보인다.
function GroupHeader({ no, title, desc, action }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3 pb-3 mb-1 border-b-2 border-[var(--fg)]">
      <div>
        <h2 className="font-bold text-[21px]"><span className="mr-1.5 text-[var(--primary)]">{no}</span>{title}</h2>
        {desc && <p className="text-[13.5px] text-[var(--muted-fg)] mt-1">{desc}</p>}
      </div>
      {action}
    </div>
  );
}

// 프로필을 불러온 뒤의 신청자 정보 요약 — 마이페이지에서 이미 쓴 내용을 큰 입력칸으로 다시 펼쳐 두지 않는다.
// 입력칸을 없애는 것이 아니라 접어 두는 것이다: "펼쳐서 수정"을 누르면 아래 구역이 그대로 열리고,
// 빈 필수 칸이 하나라도 있으면 처음부터 펼친다(IntakeForm applicantOpen). 요약에는 받은 값을 모두 적는다.
function ApplicantSummary({ id, rows, profileName, onEdit }) {
  return (
    <div id={id} className="rounded-2xl border border-[var(--border)] bg-[#f9fafb] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-[14.5px] font-bold">‘{profileName}’ 프로필로 채웠어요</p>
          <p className="text-[12.5px] text-[var(--muted-fg)] mt-0.5">이 프로젝트에만 쓰여요. 고쳐도 마이페이지는 바뀌지 않아요.</p>
        </div>
        <button type="button" onClick={onEdit}
          className="h-9 px-4 rounded-lg border border-[var(--border)] bg-white text-[13px] font-semibold hover:bg-[var(--muted)] transition-colors">펼쳐서 수정</button>
      </div>
      <dl className="grid grid-cols-[104px_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-[13.5px]">
        {rows.map(([label, value]) => (
          <React.Fragment key={label}>
            <dt className="text-[var(--muted-fg)]">{label}</dt>
            <dd className="min-w-0 break-words">{value || <span className="text-[#b0b8c1]">없음</span>}</dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  );
}

// 넓은 화면 오른쪽에 따라다니는 입력 현황 — 구역마다 채웠는지(✓)를 보이고 누르면 그 구역으로 간다.
// 기획서 3-5 "요구 항목을 처음에 모두 보여주는 편이 예측 가능하다"에 맞춰 어디까지 했는지 한눈에 보이게 한다.
// 제출 버튼은 두지 않는다 — 따라다니는 상자 안에 버튼까지 넣으니 화면보다 길어져 버튼이 잘렸다(디자인 점검 10-12).
// 제출은 폼 맨 아래 "맞는 공고 찾기" 하나다. 상자가 그래도 화면보다 길면 상자 안에서만 스크롤된다.
function IntakeChecklist({ groups, onJump }) {
  const all = groups.flatMap((g) => g.items);
  const done = all.filter((c) => !c.bad).length;
  const complete = done === all.length;
  return (
    <aside className="hidden xl:block">
      <div className="sticky top-20 max-h-[calc(100vh-6.5rem)] overflow-y-auto rounded-2xl border border-[var(--border)] bg-white px-5 py-3.5">
        <div className="flex items-baseline justify-between">
          <p className="text-[13.5px] font-bold">입력 현황</p>
          <p className={`text-[12.5px] font-semibold tabular-nums ${complete ? 'text-[var(--ok)]' : 'text-[var(--muted-fg)]'}`}>{done} / {all.length}</p>
        </div>
        {complete && <p className="mt-1 text-[12px] font-semibold text-[var(--ok)]">필수 항목을 모두 채웠어요</p>}
        {groups.map((g) => (
          <div key={g.title} className="mt-2.5">
            <p className="text-[11.5px] font-bold text-[var(--muted-fg)] mb-0.5">{g.title}</p>
            <ul className="flex flex-col">
              {g.items.map((c) => (
                <li key={c.anchor}>
                  <button type="button" onClick={() => onJump(c.anchor)}
                    className="w-full flex items-center gap-2 py-[2px] text-left text-[12.5px] hover:text-[var(--primary)] transition-colors">
                    <span aria-hidden="true" className={`flex-shrink-0 w-3.5 h-3.5 rounded-full grid place-items-center text-[8px] font-bold ${c.bad ? 'border border-[#d1d6db]' : 'bg-[color-mix(in_srgb,var(--ok)_16%,white)] text-[var(--ok)]'}`}>{c.bad ? '' : '✓'}</span>
                    <span className={c.bad ? 'text-[var(--fg)]' : 'text-[var(--muted-fg)]'}>{c.label}</span>
                    {c.bad && c.hint && <span className="text-[11px] font-semibold text-[var(--danger)]">{c.hint}</span>}
                    <span className="sr-only">{c.bad ? c.hint || '아직 비어 있음' : '채움'}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </aside>
  );
}

export function IntakeForm({ onSubmit, onBack, initialValues, backLabel = '처음으로 돌아가기' }) {
  const draft = initialValues || {};
  const profiles = useMyPageStore((s) => s.profiles);
  const [applicantType, setApplicantType] = useState(draft.applicantType || '');
  const [ceoName, setCeoName] = useState(draft.ceoName || '');
  const [birthDate, setBirthDate] = useState(draft.birthDate || '');
  const [gender, setGender] = useState(draft.gender || '');
  const [foundedAt, setFoundedAt] = useState(draft.foundedAt || '');
  const [companyName, setCompanyName] = useState(draft.companyName || '');
  // 화면에 입력칸은 없고 "내 정보 불러오기"로만 채워지는 값 — 사업계획서 일반현황에 쓴다.
  const [bizNo, setBizNo] = useState(draft.bizNo || '');
  const [item, setItem] = useState(draft.item || '');
  // 목표 고객(선택, 200자 이내) — 오케스트레이터가 늘 '확인 필요'로 보내던 값을 사용자가 채울 수 있게(웹 백엔드 project_plan_inputs.target_customer,
  // 10-13 누리 님 제안 · 정원 님 답). 비우면 보내지 않는다(서버가 NULL로 저장).
  const [targetCustomer, setTargetCustomer] = useState(draft.targetCustomer || '');
  const [team, setTeam] = useState(draft.team || [{ ...EMPTY_TEAM_ROW }]);
  const [noTeam, setNoTeam] = useState(draft.noTeam ?? draft.team?.length === 0);
  const [pricing, setPricing] = useState(draft.pricing || [{ ...EMPTY_PRICING_ROW }]);
  // 사업 계획 — 프로젝트마다 달라서 마이페이지에서 불러오지 않고 여기서 새로 받는다(전부 필수).
  const [devPeriod, setDevPeriod] = useState(draft.devPeriod || { start: '', end: '' });
  const [budgetScale, setBudgetScale] = useState(draft.budgetScale || '');
  const [funding, setFunding] = useState(draft.selfFunding || EMPTY_FUNDING);
  const [hires, setHires] = useState(draft.hires || []);
  const [noHires, setNoHires] = useState(draft.noHires || false);
  const [equipment, setEquipment] = useState(draft.equipment || []);
  const [noEquipment, setNoEquipment] = useState(draft.noEquipment || false);
  const [partners, setPartners] = useState(draft.partners || []);
  const [noPartners, setNoPartners] = useState(draft.noPartners || false);
  // 사업비 집행 계획 · 추진 일정 — 계획서 사업비 표 · 일정 표의 원본(2026-10-09, 조율 · 백엔드 요청).
  const [budget, setBudget] = useState(draft.budget || [{ ...EMPTY_BUDGET_ROW }]);
  const [schedule, setSchedule] = useState(() => ({ ...emptySchedule(), ...draft.schedule }));
  const [errorAnchor, setErrorAnchor] = useState(null);
  // 대표자 역량·지역·주업종·보유 인증 — "내 정보 불러오기"로 채워지고 여기서 고칠 수 있다.
  const [extra, setExtra] = useState(() => ({
    region: draft.region || EMPTY_EXTRA.region, industry: draft.industry || '',
    certs: draft.certs || [], careers: draft.careers || [], skills: draft.skills || '',
  }));
  const [loadedFrom, setLoadedFrom] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  // 신청자 정보 구역을 펼쳐 둘지 — 프로필을 불러오면 요약으로 접고, 빈 필수 칸이 있거나 사용자가 펼치면 연다.
  const [applicantOpen, setApplicantOpen] = useState(true);
  const patchExtra = (key) => (value) => setExtra((prev) => ({ ...prev, [key]: value }));

  const isPreliminary = applicantType === 'preliminary';
  const regionLabel = isPreliminary ? '창업 예정 지역' : applicantType ? '사업장 소재지' : '사업장 또는 창업 예정 지역';
  const hasProfile = profiles.some((p) => p.basic.applicantType);
  const touched = applicantType || ceoName || birthDate || gender || team.some((r) => r.name || r.role || r.career);

  // 예비창업자(직접 입력) ↔ 개인·법인(목록 선택)으로 사용자가 바꿀 때만 업종을 비운다(마이페이지와 같은 규칙).
  const changeApplicantType = (next) => {
    if (applicantType && (applicantType === 'preliminary') !== (next === 'preliminary')) patchExtra('industry')('');
    setApplicantType(next);
  };

  const applyProfile = (profile) => {
    if (touched && !window.confirm('이미 입력한 신청자 정보를 불러온 내용으로 바꿀까요?')) return;
    const v = profileToIntake(profile);
    setApplicantType(v.applicantType);
    setCeoName(v.ceoName);
    setBirthDate(v.birthDate);
    setGender(v.gender);
    // 불러온 설립일도 프로젝트 입력 화면에서 확인·수정할 수 있다.
    setFoundedAt(v.foundedAt);
    setCompanyName(v.companyName);
    setBizNo(v.bizNo);
    setNoTeam(v.noTeam);
    setTeam(v.team);
    setExtra({ region: v.region, industry: v.industry, certs: v.certs, careers: v.careers, skills: v.skills });
    setLoadedFrom(profile.name);
    setApplicantOpen(false);
    setPickerOpen(false);
  };

  // 유형을 잠시 바꿔도 입력한 날짜는 유지한다. 예비창업자는 제출할 때만 제외한다.

  const ideaValid = item.trim().length > 5;
  const teamValid = noTeam || (team.length > 0 && team.every((r) => r.name.trim() && r.role.trim() && r.career.trim()));
  const pricingValid = pricing.length > 0 && pricing.every((r) => r.item.trim() && r.price.trim());

  // 개발 기간 끝보다 늦게 끝나는 협약기간 내 일정 줄 — 있으면 제출을 막는다(검증-1이 입력 오류로 봐서 다시 만들어도 안 고쳐진다).
  const scheduleOverrun = schedulePastDevEnd(schedule, devPeriod.end);
  // 협약기간 내 일정 전체가 최대 개월 수(예비창업자 8 · 사업자 10)를 넘으면 막는다 — 검증-1이 같은 셈으로 입력 오류를 낸다(조율 10-13 3번).
  const maxAgreementMonths = agreementMaxMonths(isPreliminary);
  const span = scheduleSpan(schedule);
  const scheduleTooLong = span && span.months > maxAgreementMonths ? span : null;
  // 필수 구역 — 묶음마다 화면 위에서부터의 순서. 제출하면 이 중 첫 빈 항목으로 스크롤하고, 오른쪽 입력 현황도 이걸 그린다.
  // show가 거짓인 구역(유형을 고르기 전의 사업비 등)은 화면에도 없으니 검사에서도 뺀다(예전 조건과 같다).
  const checkGroups = [
    { title: '① 아이디어', items: [
      { anchor: 'intake-idea', label: '아이디어 설명', bad: !ideaValid },
      { anchor: 'intake-pricing', label: '수익모델 단가', bad: !pricingValid },
    ] },
    { title: '② 신청자 정보', items: [
      { anchor: 'intake-applicant', label: '신청자 유형', bad: !applicantType },
      { anchor: 'intake-ceo', label: '대표자 정보', bad: !ceoName.trim() || !birthDate || !gender || isUnderMinAge(birthDate) },
      { anchor: 'intake-founded', label: '사업자 정보', show: !!applicantType && !isPreliminary, bad: !companyName || !foundedAt },
      { anchor: 'intake-career', label: '대표자 역량', bad: !extra.careers.length || !extra.skills.trim() },
      { anchor: 'intake-region', label: '지역 · 주업종', bad: !extra.region.sido || !extra.industry?.trim() },
      { anchor: 'intake-team', label: '팀 구성원', bad: !teamValid },
    ] },
    { title: '③ 사업 계획', items: [
      { anchor: 'intake-period', label: '개발 기간', bad: !periodFilled(devPeriod) },
      { anchor: 'intake-schedule', label: '추진 일정', show: !!applicantType, bad: !scheduleFilled(schedule, isPreliminary) || scheduleOverrun.length > 0 || !!scheduleTooLong,
        // 다 채웠는데 기간이 기준을 벗어난 경우 — 입력 현황에 '비어 있음'이 아니라 '기간 확인'으로 알린다.
        hint: scheduleFilled(schedule, isPreliminary) && (scheduleOverrun.length > 0 || !!scheduleTooLong) ? '기간 확인' : undefined },
      { anchor: 'intake-hires', label: '채용 계획', bad: !noHires && !rowsFilled(hires, HIRE_FIELDS) },
      { anchor: 'intake-equipment', label: '장비 · 시설', bad: !noEquipment && !rowsFilled(equipment, EQUIPMENT_FIELDS) },
      { anchor: 'intake-partners', label: '협력 기관', bad: !noPartners && !rowsFilled(partners, PARTNER_FIELDS) },
      { anchor: 'intake-funding', label: isPreliminary ? '예비창업자 정보' : '자기부담금', show: !!applicantType, bad: isPreliminary ? !budgetScale : !fundingFilled(funding) },
      { anchor: 'intake-budget', label: '사업비 집행 계획', show: !!applicantType, bad: !budgetFilled(budget, isPreliminary) },
    ] },
  ].map((g) => ({ ...g, items: g.items.filter((c) => c.show !== false) }));
  const missing = checkGroups.flatMap((g) => g.items).filter((c) => c.bad).map(({ label, anchor }) => ({ label, anchor }));
  const error = missing.find((m) => m.anchor === errorAnchor) || null;
  // 신청자 정보를 요약으로 접어 둘 수 있는 건 프로필을 불러왔고 그 구역에 빈 필수 칸이 없을 때뿐이다 — 빈 칸을 숨기지 않는다.
  const applicantMissing = checkGroups[1].items.some((c) => c.bad);
  // 자기부담 한도와 사업비 집행 계획이 어긋나면 사업비 표 아래에 안내만 띄운다(막지 않음). 예비창업자는 한도 칸이 없다.
  const fundingMismatch = applicantType && !isPreliminary ? selfFundingMismatch(funding, budget) : null;
  const applicantCollapsed = !applicantOpen && !applicantMissing;
  // 펼쳐 둔 신청자 정보를 다시 요약으로 접을 수 있을 때 — 불러온 프로필이 있고 빈 필수 칸이 없을 때만.
  const canFold = !!loadedFrom && !applicantMissing && !applicantCollapsed;
  useEffect(() => { if (applicantMissing && !applicantOpen) setApplicantOpen(true); }, [applicantMissing, applicantOpen]);
  const applicantAnchors = new Set(checkGroups[1].items.map((c) => c.anchor));
  const jumpTo = (anchor) => focusSection(applicantCollapsed && applicantAnchors.has(anchor) ? 'intake-applicant-summary' : anchor);
  // 요약 카드에 적는 값 — 신청자 정보 구역의 입력값을 빠짐없이 옮긴다(사업자등록번호처럼 입력칸 없이 불러오기로만 채워지는 값도).
  const summaryRows = [
    ['신청자 유형', APPLICANT_LABEL[applicantType]],
    ['대표자', [ceoName, birthDate, gender].filter(Boolean).join(' · ')],
    ...(applicantType && !isPreliminary ? [['사업자', [companyName, foundedAt && `설립 ${foundedAt}`, bizNo && `사업자등록번호 ${bizNo}`].filter(Boolean).join(' · ')]] : []),
    ['대표자 이력', extra.careers.map((c) => [c.type, c.title, c.period && `(${c.period})`].filter(Boolean).join(' ')).filter(Boolean).join(', ')],
    ['기술력 · 노하우', extra.skills],
    [regionLabel, [extra.region.sido, extra.region.sigungu].filter(Boolean).join(' ')],
    ['주업종', extra.industry],
    ['팀 구성원', noTeam ? '팀원 없이 혼자 준비' : team.filter((r) => r.name).map((r) => [r.name, r.role && `(${r.role})`, r.career].filter(Boolean).join(' ')).join(', ')],
    ['보유 인증 · 가입', extra.certs.join(', ')],
  ];

  // 실제 POST /projects는 App.jsx의 handleIntakeSubmit이 한다(project_id를 App 상태로 들고
  // 다음 화면에 넘겨야 해서). 여기서는 유효성 검사 후 값만 올려보내고, 요청 형식 변환은
  // App.jsx intakeDetailPayload가 맡는다.
  const handleSubmit = (e) => {
    e.preventDefault();
    if (missing.length > 0) {
      setErrorAnchor(missing[0].anchor);
      focusSection(missing[0].anchor);
      return;
    }
    onSubmit({
      applicantType, item, targetCustomer: targetCustomer.trim(),
      ceoName, birthDate, gender,
      foundedAt: isPreliminary ? '' : foundedAt,
      companyName: isPreliminary ? '' : companyName,
      bizNo: isPreliminary ? '' : bizNo,
      team: noTeam ? [] : team,
      pricing,
      industry: extra.industry,
      region: extra.region,
      careers: extra.careers,
      skills: extra.skills,
      certs: extra.certs,
      devPeriod,
      budgetScale: isPreliminary ? budgetScale : '',
      selfFunding: isPreliminary ? null : funding,
      hires: noHires ? [] : hires,
      equipment: noEquipment ? [] : equipment,
      partners: noPartners ? [] : partners,
      // 단계는 예비창업자만 쓴다. 예비창업자는 현물 칸이 없어 0으로 보낸다(백엔드 규칙). 일정은 지금 유형의 표 두 개만 보낸다.
      budget: budget.map((r) => (isPreliminary ? { ...r, inKind: '0' } : { ...r, phase: '' })),
      schedule: Object.fromEntries(scheduleSectionsFor(isPreliminary).map(({ key }) => [key, schedule[key] || []])),
      noTeam, noHires, noEquipment, noPartners,
    });
  };

  const loadButton = hasProfile && (
    <button type="button" onClick={() => setPickerOpen(true)}
      className="h-10 px-4 rounded-xl bg-[var(--primary)] text-white text-[14px] font-semibold hover:bg-[var(--primary-dim)] transition-colors">
      {loadedFrom ? '다른 프로필 불러오기' : '내 정보 불러오기'}
    </button>
  );

  // 화면은 ① 아이디어 → ② 신청자 정보 → ③ 사업 계획 순서다. 예전엔 16개 구역이 한 줄로 이어졌고, 화면 제목이 묻는
  // 아이디어 설명이 맨 끝에 있었다(디자인 점검 10-12). 구역 · 입력칸 · 필수 조건은 그대로이고 자리만 옮겼다.
  return (
    <div data-screen="intake-form" className="max-w-3xl xl:max-w-none mx-auto px-6 py-14">
      <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_224px] xl:gap-12">
        <div className="min-w-0">
          <BackButton onClick={onBack} label={backLabel} />
          <p className="text-[13px] font-semibold text-[var(--primary-dim)] mb-2">사전 정보 입력</p>
          <h1 className="font-bold text-[28px] md:text-[32px]">어떤 아이디어를 준비하고 있나요?</h1>
          <p className="text-[15px] text-[var(--muted-fg)] mt-2 mb-10">아이템과 신청자 정보를 알려주시면 맞는 공고를 찾아드릴게요.</p>

          <form id="intake-form" onSubmit={handleSubmit}>
            {/* 한 겹 감싼다 — styles.css의 옛 규칙 ".workflow-content form > div { margin-bottom: 40px }"이 묶음 머리말 · 묶음마다
                걸려 간격이 들쭉날쭉해졌다. 구역 위 여백(form [class*="border-t"] 35px)은 예전 화면과 같게 그대로 둔다. */}
            <div>
              <GroupHeader no="①" title="아이디어" desc="준비하고 있는 아이템과 수익모델이에요." />
              <div className="mb-14">
                <Section id="intake-idea" title="아이디어 설명" required error={errorFor(error, 'intake-idea')}>
                  <textarea value={item} onChange={(e) => setItem(e.target.value)} rows={5}
                    placeholder="예) 반려견 산책 도우미를 구해주는 매칭 플랫폼을 만들고 있어요"
                    className={textareaCls} />
                </Section>

                <Section id="intake-target" title="목표 고객" optional
                  desc="누구를 위한 서비스인지 적어 주세요. 계획서의 목표 고객 · 시장 설명에 쓰여요. 비워 두면 계획서에 '확인 필요'로 남을 수 있어요.">
                  <textarea value={targetCustomer} onChange={(e) => setTargetCustomer(e.target.value)} rows={2} maxLength={200}
                    placeholder="예) 회원 50 ~ 300명 규모의 동네 헬스장 운영자"
                    className={textareaCls} />
                  <p className="mt-1.5 text-right text-[12px] text-[var(--muted-fg)]">{targetCustomer.length} / 200</p>
                </Section>

                <Section id="intake-pricing" title="수익모델 단가" required error={errorFor(error, 'intake-pricing')} desc="매출을 예상하는 데 사용할 상품과 가격을 알려주세요.">
                  <ListEditor items={pricing} onChange={setPricing} cols={2} addLabel="항목 추가" fields={PRICING_FIELDS} />
                </Section>
              </div>

              <GroupHeader no="②" title="신청자 정보"
                desc={hasProfile ? (loadedFrom ? '불러온 내용을 확인하고 필요하면 고쳐 주세요.' : '마이페이지에 저장한 프로필을 불러오면 이 묶음이 채워져요.') : '신청자와 팀에 대해 알려 주세요.'}
                action={(loadButton || canFold) ? (
                <div className="flex items-center gap-2">
                  {canFold && (
                    <button type="button" onClick={() => setApplicantOpen(false)}
                      className="h-10 px-4 rounded-xl border border-[var(--border)] bg-white text-[14px] font-semibold text-[#4e5968] hover:bg-[var(--muted)] transition-colors">
                      요약으로 접기
                    </button>
                  )}
                  {loadButton}
                </div>
              ) : undefined} />
              <div className="mb-14">
                {applicantCollapsed ? (
                  <ApplicantSummary id="intake-applicant-summary" rows={summaryRows} profileName={loadedFrom} onEdit={() => setApplicantOpen(true)} />
                ) : (
                  <>
                    <Section id="intake-applicant" title="신청자 유형" required error={errorFor(error, 'intake-applicant')}>
                      <Segmented options={APPLICANT_TYPES} value={applicantType} onChange={changeApplicantType} />
                    </Section>

                    <Section id="intake-ceo" title="대표자 정보" required error={errorFor(error, 'intake-ceo')}>
                      <div className="grid gap-3 sm:grid-cols-3">
                        <TextInput label="이름" value={ceoName} placeholder="홍길동" onChange={setCeoName} />
                        <TextInput label="생년월일" type="date" min="1900-01-01" max={latestBirthDate()} value={birthDate} onChange={setBirthDate} />
                        <Select label="성별" value={gender} options={['남성', '여성']} onChange={setGender} />
                      </div>
                      {isUnderMinAge(birthDate) && <p role="alert" className="mt-2 text-[12px] text-[var(--danger)]">대표자는 만 {MIN_CEO_AGE}세 이상만 입력할 수 있어요.</p>}
                    </Section>

                    {applicantType && !isPreliminary && (
                      <Section id="intake-founded" title="사업자 정보" required error={errorFor(error, 'intake-founded')}>
                        {/* 기업명은 사업계획서 일반현황 첫 칸에 그대로 들어간다(companies.company_name). */}
                        <div className="grid gap-3 sm:grid-cols-2">
                          <TextInput label="기업명" value={companyName} placeholder="(주)에스브레인" onChange={setCompanyName} />
                          <TextInput label="설립일" type="date" value={foundedAt} onChange={setFoundedAt} />
                        </div>
                      </Section>
                    )}

                    <Section id="intake-career" title="대표자 역량" required error={errorFor(error, 'intake-career')} desc="경력·학력·지원사업 수행·수상 이력과 보유 역량을 적어 주세요.">
                      <ListEditor items={extra.careers} onChange={patchExtra('careers')} cols={4} addLabel="이력 추가" fields={CAREER_FIELDS} />
                      <label className="block mt-5">
                        <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">기술력 · 노하우 · 인적 네트워크</span>
                        <textarea value={extra.skills} onChange={(e) => patchExtra('skills')(e.target.value)} rows={3}
                          placeholder="창업 아이템을 개발하거나 구체화할 수 있는 역량을 적어 주세요" className={textareaCls} />
                      </label>
                    </Section>

                    <Section id="intake-region" title={`${regionLabel} · 주업종`} required error={errorFor(error, 'intake-region')}>
                      <RegionInput label={regionLabel} value={extra.region} onChange={patchExtra('region')} />
                      <div className="mt-3">
                        <IndustryField applicantType={applicantType} value={extra.industry} onChange={patchExtra('industry')} />
                      </div>
                    </Section>

                    <Section id="intake-team" title="팀 구성원" required error={errorFor(error, 'intake-team')}>
                      <div className="mb-3"><Check checked={noTeam} onChange={setNoTeam}>팀원 없이 혼자 준비하고 있어요</Check></div>
                      {!noTeam && <ListEditor items={team} onChange={setTeam} cols={3} addLabel="팀원 추가" fields={TEAM_FIELDS} />}
                    </Section>

                    <Section title="보유 인증 · 가입" optional desc="해당하는 것을 모두 골라 주세요.">
                      <ChipSelect options={CERTS} values={extra.certs} onChange={patchExtra('certs')} />
                    </Section>
                  </>
                )}
              </div>

              <GroupHeader no="③" title="사업 계획" desc="이 프로젝트의 일정과 돈, 사람 계획이에요. 프로젝트마다 새로 받아요." />
              {/* 성격별 순서 — 언제(개발 기간 → 그 안의 추진 일정) → 누구 · 무엇으로(채용 · 장비 · 협력) → 얼마로(자기부담 → 사업비).
                  개발 기간과 추진 일정을 붙여 두면 "큰 기간 → 세부 일정" 관계가 설명 없이 보인다(디자인 점검 10-12). */}
              <div>
                <Section id="intake-period" title="개발 기간" required error={errorFor(error, 'intake-period')}>
                  <DevPeriodField value={devPeriod} onChange={setDevPeriod} />
                </Section>

                {applicantType ? (
                  <Section id="intake-schedule" title="추진 일정" required error={errorFor(error, 'intake-schedule')}
                    desc="계획서의 추진 일정 표에 쓰여요. 구분 · 추진 내용 · 추진 기간(연도 포함)은 꼭 채워 주세요.">
                    {/* 협약기간 최대 개월 수는 2026년 공고 기준으로 고정이라(조율 10-13) 넘으면 막는다. 개발 기간을 넘는 것도 아래에서 막는다. */}
                    <p className="mb-4 text-[12.5px] leading-relaxed text-[var(--muted-fg)]">
                      협약기간 내 일정은 위 개발 기간 안에서 끝나야 하고, 첫 달부터 끝 달까지 {maxAgreementMonths}개월을 넘을 수 없어요(2026년 {isPreliminary ? '예비창업패키지' : '초기창업패키지'} 공고 기준).
                    </p>
                    <ScheduleEditor value={schedule} onChange={setSchedule} isPreliminary={isPreliminary} />
                    {scheduleTooLong && (
                      <div role="alert" className="mt-3 rounded-xl bg-[#fff0f0] px-4 py-3 text-[12.5px] leading-relaxed text-[var(--danger)]">
                        <p>협약기간 내 일정이 {scheduleTooLong.start.replace('-', '년 ')}월부터 {scheduleTooLong.end.replace('-', '년 ')}월까지 {scheduleTooLong.months}개월이에요. {isPreliminary ? '예비창업자는' : '개인사업자 · 법인은'} {maxAgreementMonths}개월까지 쓸 수 있어요.</p>
                        <p className="mt-1 font-semibold">협약기간 내 일정을 {maxAgreementMonths}개월 안으로 줄여 주세요.</p>
                      </div>
                    )}
                    {scheduleOverrun.length > 0 && (
                      <div role="alert" className="mt-3 rounded-xl bg-[#fff0f0] px-4 py-3 text-[12.5px] leading-relaxed text-[var(--danger)]">
                        {scheduleOverrun.map((row) => (
                          <p key={row.no}>협약기간 내 일정 {row.no}번째 줄{row.category ? `(${row.category})` : ''}이 {row.end.replace('-', '년 ')}월에 끝나 개발 기간 끝({devPeriod.end.replace('-', '년 ')}월)보다 늦어요.</p>
                        ))}
                        <p className="mt-1 font-semibold">일정을 개발 기간 안으로 맞추거나 개발 기간을 늘려 주세요.</p>
                      </div>
                    )}
                  </Section>
                ) : (
                  // 추진 일정 · 자기부담 · 사업비는 신청자 유형마다 칸이 달라 유형을 고른 뒤에 보인다 — 추진 일정이 나타날 자리에서 알린다.
                  <p className="py-8 border-t border-[var(--border)] text-[13.5px] text-[var(--muted-fg)]">
                    ② 신청자 유형을 고르면 이 묶음에 추진 일정 · 자기부담금 · 사업비 집행 계획 칸이 나타나요.
                  </p>
                )}

                <Section id="intake-hires" title="채용 계획" required desc="협약 기간 안에 뽑을 인력이 있다면 적어 주세요." error={errorFor(error, 'intake-hires')}>
                  <ListOrNone items={hires} onChange={setHires} none={noHires} onNoneChange={setNoHires}
                    noneLabel="채용 계획이 없어요" fields={HIRE_FIELDS} cols={4} addLabel="채용 계획 추가" />
                </Section>

                <Section id="intake-equipment" title="장비 · 시설" required error={errorFor(error, 'intake-equipment')}>
                  <ListOrNone items={equipment} onChange={setEquipment} none={noEquipment} onNoneChange={setNoEquipment}
                    noneLabel="필요한 장비·시설이 없어요" fields={EQUIPMENT_FIELDS} cols={2} addLabel="장비 추가" />
                </Section>

                <Section id="intake-partners" title="협력 기관" required error={errorFor(error, 'intake-partners')}>
                  <ListOrNone items={partners} onChange={setPartners} none={noPartners} onNoneChange={setNoPartners}
                    noneLabel="협력하는 기관이 없어요" fields={PARTNER_FIELDS} cols={2} addLabel="협력 기관 추가" />
                </Section>

                {applicantType && (
                  <>
                    {/* 자기부담 가능 범위는 "낼 수 있는 한도", 아래 사업비 집행 계획은 "실제로 쓸 계획"이다 — 둘 다 자기부담이 나와 헷갈려서 문구로 나눠 적는다 */}
                    <Section id="intake-funding" title={isPreliminary ? '예비창업자 정보' : '자기부담 가능 범위'} required error={errorFor(error, 'intake-funding')}
                      desc={isPreliminary ? undefined : '내 돈을 최대 얼마까지 낼 수 있는지(한도)예요. 실제로 어디에 얼마를 쓸지는 아래 사업비 집행 계획에 적어요.'}>
                      {isPreliminary
                        ? <BudgetScaleField value={budgetScale} onChange={setBudgetScale} />
                        : <SelfFundingField value={funding} onChange={setFunding} />}
                    </Section>

                    <Section id="intake-budget" title="사업비 집행 계획" required error={errorFor(error, 'intake-budget')}
                      desc={`실제로 어디에 얼마를 쓸지 적는 표예요. 계획서의 사업비 표에 그대로 들어가요. ${isPreliminary ? '1단계 · 2단계로 나눠 비목마다 한 줄씩 적어 주세요. 단계마다 한 줄 이상 필요해요.' : '비목마다 한 줄씩 적어 주세요.'} 금액 칸은 비워 둘 수 없어요(없으면 0). 총사업비는 정부지원사업비와 자기부담금을 더해 자동으로 계산돼요.`}>
                      <BudgetEditor rows={budget} onChange={setBudget} isPreliminary={isPreliminary} />
                      {fundingMismatch && <p role="status" className="funding-notice mt-3">{fundingMismatch}</p>}
                    </Section>
                  </>
                )}
              </div>

              <div className="pt-6 border-t border-[var(--border)]">
                <button type="submit"
                  className="w-full h-12 rounded-xl bg-[var(--primary)] text-white text-[15px] font-semibold hover:bg-[var(--primary-dim)] transition-colors">
                  맞는 공고 찾기
                </button>
                {missing.length > 0 && <p className="mt-2 text-[11.5px] text-[var(--muted-fg)] text-center">[필수] 항목을 먼저 채워 주세요 — {missing.map((m) => m.label).join(', ')}</p>}
              </div>
            </div>
          </form>
        </div>

        <IntakeChecklist groups={checkGroups} onJump={jumpTo} />
      </div>

      <LoadProfileModal open={pickerOpen} profiles={profiles} onPick={applyProfile} onClose={() => setPickerOpen(false)} />
    </div>
  );
}
