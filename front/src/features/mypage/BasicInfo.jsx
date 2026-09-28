import React from 'react';
import { useSection } from '../../store/useMyPageStore.js';
import BizNoField from './BizNoField.jsx';
import { CERTS, careerBadge, regionBadge, youthBadge } from './derive.js';
import { Badges, ChipSelect, IndustryField, RegionInput, Section, Segmented, Select, TextInput, errorFor } from './ui.jsx';

const APPLICANT_TYPES = [['preliminary', '예비창업자'], ['individual', '개인사업자'], ['corp', '법인']];

export default function BasicInfo({ error }) {
  const [b, set] = useSection('basic');
  const biz = b.applicantType === 'individual' || b.applicantType === 'corp';
  const regionLabel = b.applicantType === 'preliminary' ? '창업 예정 지역' : b.applicantType ? '사업장 소재지' : '사업장 또는 창업 예정 지역';
  // 예비창업자(직접 입력) ↔ 개인·법인(목록 선택)을 사용자가 직접 바꿀 때만 업종을 비운다 —
  // 프로필 불러오기·전환에서는 값을 지우면 안 된다(IndustryField 주석 참고).
  const changeApplicantType = (next) => {
    const wasPre = b.applicantType === 'preliminary';
    const willPre = next === 'preliminary';
    set('applicantType')(next);
    if (b.applicantType && wasPre !== willPre) set('industry')('');
  };

  return (
    <>
      <Section id="mp-applicant" error={errorFor(error, 'mp-applicant')} title="신청자 유형" required desc="유형에 따라 필요한 항목만 보여드려요.">
        <Segmented options={APPLICANT_TYPES} value={b.applicantType} onChange={changeApplicantType} />
      </Section>

      <Section id="mp-ceo" error={errorFor(error, 'mp-ceo')} title="대표자" required>
        <div className="grid gap-3 sm:grid-cols-3">
          <TextInput label="이름" value={b.ceoName} placeholder="홍길동" onChange={set('ceoName')} />
          <TextInput label="생년월일" type="date" value={b.birthDate} onChange={set('birthDate')} />
          <Select label="성별" value={b.gender} options={['남성', '여성']} onChange={set('gender')} />
        </div>
        <Badges items={[youthBadge(b.birthDate), b.gender === '여성' && { tone: 'info', text: '여성 대표자' }]} />
      </Section>

      <Section id="mp-region" error={errorFor(error, 'mp-region')} title={`${regionLabel} · 주업종`} required>
        <RegionInput label={regionLabel} value={b.region} onChange={set('region')} />
        <div className="mt-3">
          <IndustryField applicantType={b.applicantType} value={b.industry} onChange={set('industry')} />
        </div>
        <Badges items={[regionBadge(b.region.sido)]} />
      </Section>


      {biz && (
        <Section id="mp-biz" error={errorFor(error, 'mp-biz')} title="사업자 정보" required>
          <BizNoField value={b.bizNo} onChange={set('bizNo')} />
          {/* 기업명은 사업계획서 일반현황 첫 칸(companies.company_name)에 그대로 들어간다 —
              받는 곳이 없어서 문서에 계속 ○○○으로 나왔다(사용자 지적). 예비창업자는
              아직 상호가 없으므로 이 구역(biz) 자체가 안 보인다. */}
          <div className="grid gap-3 sm:grid-cols-2 mt-3">
            <TextInput label="기업명" value={b.companyName} placeholder="(주)에스브레인" onChange={set('companyName')} />
            <TextInput label="설립일" type="date" value={b.openedAt} onChange={set('openedAt')} />
          </div>
          <Badges items={[careerBadge(b.openedAt)]} />
        </Section>
      )}

      <Section title="보유 인증 · 가입" optional desc="해당하는 것을 모두 골라 주세요.">
        <ChipSelect options={CERTS} values={b.certs} onChange={set('certs')} />
      </Section>
    </>
  );
}
