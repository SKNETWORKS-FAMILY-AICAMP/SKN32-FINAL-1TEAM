// 새 프로젝트 사전 정보 입력. 입력 부품은 마이페이지(features/mypage/ui.jsx)와 같은 것을 써서
// 두 화면이 같은 모양을 유지한다. 루트를 <section data-screen="intake">로 두면 styles.css의
// 옛 IntakeForm 전용 규칙(회색 입력칸, 버튼 높이 강제 등)이 걸리므로 <div> + 다른 이름을 쓴다.
import React, { useEffect, useState } from 'react';
import { Icon } from '../../components/Icons.jsx';
import { useMyPageStore } from '../../store/useMyPageStore.js';
import {
  CAREER_FIELDS, CERTS, EMPTY_TEAM_ROW, EQUIPMENT_FIELDS, HIRE_FIELDS, PARTNER_FIELDS, profileToIntake,
} from '../mypage/derive.js';
import {
  ChipSelect, Check, Collapsible, IndustryField, ListEditor, RegionInput, Section, Segmented, TextInput, textareaCls,
} from '../mypage/ui.jsx';
import { BackButton, FileAttach } from './shared.jsx';

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
const EMPTY_EXTRA = { region: { sido: '', sigungu: '' }, industry: '', certs: [], careers: [], skills: '', hires: [], equipment: [], partners: [] };

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

export function IntakeForm({ onSubmit, onBack, backLabel = '처음으로 돌아가기' }) {
  const profiles = useMyPageStore((s) => s.profiles);
  const [applicantType, setApplicantType] = useState('');
  const [ceoName, setCeoName] = useState('');
  const [foundedAt, setFoundedAt] = useState('');
  const [item, setItem] = useState('');
  const [files, setFiles] = useState([]);
  const [team, setTeam] = useState([{ ...EMPTY_TEAM_ROW }]);
  const [noTeam, setNoTeam] = useState(false);
  const [pricing, setPricing] = useState([{ ...EMPTY_PRICING_ROW }]);
  // 아이디어·팀·단가처럼 서버로 보내는 값은 아니지만, "저장해둔 걸 잊고 여기서 새로
  // 입력하는 사람"이 있을 수 있어 불러온 나머지 마이페이지 항목도 전부 보여주고 고치게 한다.
  const [extra, setExtra] = useState(EMPTY_EXTRA);
  const [loadedFrom, setLoadedFrom] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const patchExtra = (key) => (value) => setExtra((prev) => ({ ...prev, [key]: value }));

  const isPreliminary = applicantType === 'preliminary';
  const hasProfile = profiles.some((p) => p.basic.applicantType);
  const touched = applicantType || ceoName || foundedAt || team.some((r) => r.name || r.role || r.career);

  const applyProfile = (profile) => {
    if (touched && !window.confirm('이미 입력한 신청자 정보를 불러온 내용으로 바꿀까요?')) return;
    const v = profileToIntake(profile);
    setApplicantType(v.applicantType);
    setCeoName(v.ceoName);
    setFoundedAt(v.foundedAt);
    setNoTeam(v.noTeam);
    setTeam(v.team);
    setExtra({ region: v.region, industry: v.industry, certs: v.certs, careers: v.careers, skills: v.skills, hires: v.hires, equipment: v.equipment, partners: v.partners });
    setLoadedFrom(profile.name);
    setPickerOpen(false);
  };

  // 예비창업자로 바꾸면 설립일자는 쓰지 않으므로 남아 있던 값이 제출되지 않게 비운다.
  useEffect(() => { if (isPreliminary) setFoundedAt(''); }, [isPreliminary]);

  const companyValid = isPreliminary || (ceoName.trim() && foundedAt);
  const ideaValid = item.trim().length > 5;
  const teamValid = noTeam || (team.length > 0 && team.every((r) => r.name.trim() && r.role.trim() && r.career.trim()));
  const pricingValid = pricing.length > 0 && pricing.every((r) => r.item.trim() && r.price.trim());
  const valid = applicantType && companyValid && ideaValid && teamValid && pricingValid;

  // 실제 POST /projects는 App.jsx의 handleIntakeSubmit이 한다(project_id를 App 상태로 들고
  // 다음 화면에 넘겨야 해서). 여기서는 유효성 검사 후 값만 올려보낸다. extra의 careers·skills·
  // hires·equipment·partners·certs는 지금 서버 스키마에 자리가 없어 화면 확인·수정용으로만
  // 쓰고 제출엔 안 싣는다 — industry·region만 보낸다(업종·알림 지역 기본값 대신 실제 값).
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!valid) return;
    onSubmit({
      applicantType, item, files,
      ceoName: isPreliminary ? '' : ceoName,
      foundedAt: isPreliminary ? '' : foundedAt,
      team: noTeam ? [] : team,
      pricing,
      industry: extra.industry,
      region: extra.region.sido,
    });
  };

  const hint = !applicantType ? '신청자 유형을 선택해 주세요'
    : !companyValid ? '대표자명과 설립일자를 입력해 주세요'
    : !ideaValid ? '아이디어 설명을 6자 이상 입력해 주세요'
    : !teamValid ? '팀원 정보를 모두 입력하거나 팀원 없음을 선택해 주세요'
    : '수익모델 단가 항목을 모두 입력해 주세요';

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
        <Section title="신청자 유형">
          <Segmented options={APPLICANT_TYPES} value={applicantType} onChange={setApplicantType} />
          {applicantType && !isPreliminary && (
            <div className="grid gap-3 sm:grid-cols-2 mt-4">
              <TextInput label="대표자명" value={ceoName} placeholder="홍길동" onChange={setCeoName} />
              <TextInput label="설립일자" type="date" value={foundedAt} onChange={setFoundedAt} />
            </div>
          )}
        </Section>

        {loadedFrom && (
          <Section title="불러온 정보" desc="마이페이지에 저장해둔 나머지 정보예요. 필요하면 여기서 바로 고칠 수 있어요.">
            <Collapsible title="지역 · 주업종 · 보유 인증">
              <RegionInput label="지역" value={extra.region} onChange={patchExtra('region')} />
              <IndustryField applicantType={applicantType} value={extra.industry} onChange={patchExtra('industry')} />
              <div>
                <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">보유 인증 · 가입</span>
                <ChipSelect options={CERTS} values={extra.certs} onChange={patchExtra('certs')} />
              </div>
            </Collapsible>
            <Collapsible title="대표자 역량">
              <ListEditor items={extra.careers} onChange={patchExtra('careers')} cols={4} addLabel="이력 추가" fields={CAREER_FIELDS} />
              <label className="block">
                <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">기술력 · 노하우 · 인적 네트워크</span>
                <textarea value={extra.skills} onChange={(e) => patchExtra('skills')(e.target.value)} rows={3} className={textareaCls} />
              </label>
            </Collapsible>
            <Collapsible title="채용 계획 · 장비 · 협력 파트너" defaultOpen={false}>
              <ListEditor items={extra.hires} onChange={patchExtra('hires')} cols={4} addLabel="채용 계획 추가" fields={HIRE_FIELDS} />
              <div className="grid gap-6 md:grid-cols-2">
                <div>
                  <h3 className="text-[13px] font-semibold text-[#4e5968] mb-2">장비 · 시설</h3>
                  <ListEditor items={extra.equipment} onChange={patchExtra('equipment')} cols={2} addLabel="장비 추가" fields={EQUIPMENT_FIELDS} />
                </div>
                <div>
                  <h3 className="text-[13px] font-semibold text-[#4e5968] mb-2">협력 파트너 · 기관</h3>
                  <ListEditor items={extra.partners} onChange={patchExtra('partners')} cols={2} addLabel="파트너 추가" fields={PARTNER_FIELDS} />
                </div>
              </div>
            </Collapsible>
          </Section>
        )}

        <Section title="팀 구성원 경력">
          <div className="mb-3"><Check checked={noTeam} onChange={setNoTeam}>팀원 없이 혼자 준비하고 있어요</Check></div>
          {!noTeam && <ListEditor items={team} onChange={setTeam} cols={3} addLabel="팀원 추가" fields={TEAM_FIELDS} />}
        </Section>

        <Section title="수익모델 단가" desc="매출을 예상하는 데 사용할 상품과 가격을 알려주세요.">
          <ListEditor items={pricing} onChange={setPricing} cols={2} addLabel="항목 추가" fields={PRICING_FIELDS} />
        </Section>

        <Section title="아이디어 설명">
          <textarea value={item} onChange={(e) => setItem(e.target.value)} rows={5}
            placeholder="예) 반려견 산책 도우미를 구해주는 매칭 플랫폼을 만들고 있어요"
            className={textareaCls} />
          <FileAttach files={files} onAdd={(added) => setFiles((prev) => [...prev, ...added])}
            onRemove={(i) => setFiles((prev) => prev.filter((_, idx) => idx !== i))} />
        </Section>

        <div className="pt-6 border-t border-[var(--border)]">
          <button type="submit" disabled={!valid}
            className="w-full h-12 rounded-xl bg-[var(--primary)] text-white text-[15px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            맞는 공고 찾기
          </button>
          {!valid && <p className="mt-2 text-[12.5px] text-[var(--muted-fg)] text-center">{hint}</p>}
        </div>
      </form>

      <LoadProfileModal open={pickerOpen} profiles={profiles} onPick={applyProfile} onClose={() => setPickerOpen(false)} />
    </div>
  );
}
