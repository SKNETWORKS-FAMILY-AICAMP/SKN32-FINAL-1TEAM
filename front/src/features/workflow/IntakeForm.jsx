// 새 프로젝트 사전 정보 입력. 입력 부품은 마이페이지(features/mypage/ui.jsx)와 같은 것을 써서
// 두 화면이 같은 모양을 유지한다. 루트를 <section data-screen="intake">로 두면 styles.css의
// 옛 IntakeForm 전용 규칙(회색 입력칸, 버튼 높이 강제 등)이 걸리므로 <div> + 다른 이름을 쓴다.
import React, { useState } from 'react';
import { Icon } from '../../components/Icons.jsx';
import { useMyPageStore } from '../../store/useMyPageStore.js';
import {
  CAREER_FIELDS, CERTS, EMPTY_TEAM_ROW, EQUIPMENT_FIELDS, HIRE_FIELDS, PARTNER_FIELDS, profileToIntake,
} from '../mypage/derive.js';
import {
  ChipSelect, Check, IndustryField, ListEditor, RegionInput, Section, Segmented, Select, TextInput, errorFor, focusSection, textareaCls,
} from '../mypage/ui.jsx';
import { BackButton, FileAttach } from './shared.jsx';
import {
  BudgetScaleField, DevPeriodField, EMPTY_FUNDING, ListOrNone, SelfFundingField, fundingFilled, periodFilled, rowsFilled,
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
  const [files, setFiles] = useState(draft.files || []);
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
  const [errorAnchor, setErrorAnchor] = useState(null);
  // 대표자 역량·지역·주업종·보유 인증 — "내 정보 불러오기"로 채워지고 여기서 고칠 수 있다.
  const [extra, setExtra] = useState(() => ({
    region: draft.region || EMPTY_EXTRA.region, industry: draft.industry || '',
    certs: draft.certs || [], careers: draft.careers || [], skills: draft.skills || '',
  }));
  const [loadedFrom, setLoadedFrom] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
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
    setPickerOpen(false);
  };

  // 유형을 잠시 바꿔도 입력한 날짜는 유지한다. 예비창업자는 제출할 때만 제외한다.

  const ideaValid = item.trim().length > 5;
  const teamValid = noTeam || (team.length > 0 && team.every((r) => r.name.trim() && r.role.trim() && r.career.trim()));
  const pricingValid = pricing.length > 0 && pricing.every((r) => r.item.trim() && r.price.trim());

  // 화면 위에서부터의 순서 — 제출하면 이 중 첫 빈 항목으로 스크롤한다.
  const missing = [
    [!applicantType, '신청자 유형', 'intake-applicant'],
    [!ceoName.trim() || !birthDate || !gender, '대표자 정보', 'intake-ceo'],
    [applicantType && !isPreliminary && (!companyName || !foundedAt), '사업자 정보', 'intake-founded'],
    [!extra.careers.length || !extra.skills.trim(), '대표자 역량', 'intake-career'],
    [!extra.region.sido || !extra.industry?.trim(), '지역 · 주업종', 'intake-region'],
    [!teamValid, '팀 구성원', 'intake-team'],
    [!noHires && !rowsFilled(hires, HIRE_FIELDS), '채용 계획', 'intake-hires'],
    [!periodFilled(devPeriod), '개발 기간', 'intake-period'],
    [!noEquipment && !rowsFilled(equipment, EQUIPMENT_FIELDS), '장비 · 시설', 'intake-equipment'],
    [!noPartners && !rowsFilled(partners, PARTNER_FIELDS), '협력 기관', 'intake-partners'],
    [applicantType && (isPreliminary ? !budgetScale : !fundingFilled(funding)), isPreliminary ? '예비창업자 정보' : '자기부담금', 'intake-funding'],
    [!pricingValid, '수익모델 단가', 'intake-pricing'],
    [!ideaValid, '아이디어 설명', 'intake-idea'],
  ].filter(([bad]) => bad).map(([, label, anchor]) => ({ label, anchor }));
  const error = missing.find((m) => m.anchor === errorAnchor) || null;

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
      applicantType, item, files,
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
      noTeam, noHires, noEquipment, noPartners,
    });
  };

  return (
    <div data-screen="intake-form" className="max-w-3xl mx-auto px-6 py-14">
      <BackButton onClick={onBack} label={backLabel} />
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] mb-2">사전 정보 입력</p>
      <h1 className="font-bold text-[28px] md:text-[32px]">어떤 아이디어를 준비하고 있나요?</h1>
      <p className="text-[15px] text-[var(--muted-fg)] mt-2 mb-6">아이템과 신청자 정보를 알려주시면 맞는 공고를 찾아드릴게요.</p>

      {hasProfile && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#d6e4fb] bg-[#f5f9ff] px-4 py-3 mb-2">
          <span className="text-[14px] text-[#1b3f80]">
            {loadedFrom ? <>‘<b>{loadedFrom}</b>’ 프로필을 불러왔어요 — 아래에서 내용을 확인하고 고칠 수 있어요</> : '마이페이지에 저장된 정보가 있어요'}
          </span>
          <button type="button" onClick={() => setPickerOpen(true)}
            className="h-11 px-5 rounded-xl bg-[var(--primary)] text-white text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] transition-colors">
            {loadedFrom ? '다른 프로필 불러오기' : '내 정보 불러오기'}
          </button>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        <Section id="intake-applicant" title="신청자 유형" required error={errorFor(error, 'intake-applicant')}>
          <Segmented options={APPLICANT_TYPES} value={applicantType} onChange={changeApplicantType} />
        </Section>

        <Section id="intake-ceo" title="대표자 정보" required error={errorFor(error, 'intake-ceo')}>
          <div className="grid gap-3 sm:grid-cols-3">
            <TextInput label="이름" value={ceoName} placeholder="홍길동" onChange={setCeoName} />
            <TextInput label="생년월일" type="date" value={birthDate} onChange={setBirthDate} />
            <Select label="성별" value={gender} options={['남성', '여성']} onChange={setGender} />
          </div>
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

        <Section id="intake-hires" title="채용 계획" required desc="협약 기간 안에 뽑을 인력이 있다면 적어 주세요." error={errorFor(error, 'intake-hires')}>
          <ListOrNone items={hires} onChange={setHires} none={noHires} onNoneChange={setNoHires}
            noneLabel="채용 계획이 없어요" fields={HIRE_FIELDS} cols={4} addLabel="채용 계획 추가" />
        </Section>

        <Section id="intake-period" title="개발 기간" required error={errorFor(error, 'intake-period')}>
          <DevPeriodField value={devPeriod} onChange={setDevPeriod} />
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
          <Section id="intake-funding" title={isPreliminary ? '예비창업자 정보' : '자기부담 가능 범위'} required error={errorFor(error, 'intake-funding')}>
            {isPreliminary
              ? <BudgetScaleField value={budgetScale} onChange={setBudgetScale} />
              : <SelfFundingField value={funding} onChange={setFunding} />}
          </Section>
        )}

        <Section title="보유 인증 · 가입" optional desc="해당하는 것을 모두 골라 주세요.">
          <ChipSelect options={CERTS} values={extra.certs} onChange={patchExtra('certs')} />
        </Section>

        <Section id="intake-pricing" title="수익모델 단가" required error={errorFor(error, 'intake-pricing')} desc="매출을 예상하는 데 사용할 상품과 가격을 알려주세요.">
          <ListEditor items={pricing} onChange={setPricing} cols={2} addLabel="항목 추가" fields={PRICING_FIELDS} />
        </Section>

        <Section id="intake-idea" title="아이디어 설명" required error={errorFor(error, 'intake-idea')}>
          <textarea value={item} onChange={(e) => setItem(e.target.value)} rows={5}
            placeholder="예) 반려견 산책 도우미를 구해주는 매칭 플랫폼을 만들고 있어요"
            className={textareaCls} />
          <FileAttach files={files} onAdd={(added) => setFiles((prev) => [...prev, ...added])}
            onRemove={(i) => setFiles((prev) => prev.filter((_, idx) => idx !== i))} />
        </Section>

        <div className="pt-6 border-t border-[var(--border)]">
          <button type="submit"
            className="w-full h-12 rounded-xl bg-[var(--primary)] text-white text-[15px] font-semibold hover:bg-[var(--primary-dim)] transition-colors">
            맞는 공고 찾기
          </button>
          {missing.length > 0 && <p className="mt-2 text-[11.5px] text-[var(--muted-fg)] text-center">[필수] 항목을 먼저 채워 주세요 — {missing.map((m) => m.label).join(', ')}</p>}
        </div>
      </form>

      <LoadProfileModal open={pickerOpen} profiles={profiles} onPick={applyProfile} onClose={() => setPickerOpen(false)} />
    </div>
  );
}
