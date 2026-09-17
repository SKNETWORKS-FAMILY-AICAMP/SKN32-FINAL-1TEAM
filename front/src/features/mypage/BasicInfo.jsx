import React from 'react';
import { useSection } from '../../store/useMyPageStore.js';
import BizNoField from './BizNoField.jsx';
import { careerBadge, regionBadge, youthBadge } from './derive.js';
import { Badges, Check, ChipSelect, RegionInput, Section, Segmented, Select, TextInput } from './ui.jsx';

const APPLICANT_TYPES = [['preliminary', '예비창업자', '사업자등록 전'], ['individual', '개인사업자'], ['corp', '법인']];
const CERTS = ['여성기업', '장애인기업', '벤처기업', '이노비즈', '메인비즈', '사회적기업'];

export default function BasicInfo({ onGoTab }) {
  const [b, set] = useSection('basic');
  const pre = b.applicantType === 'preliminary';
  const hqSido = pre ? b.home.sido : (b.hqSameAsHome ? b.home.sido : b.hq.sido);

  return (
    <>
      <Section title="신청자 유형" desc="유형에 따라 필요한 항목만 보여드려요.">
        <Segmented options={APPLICANT_TYPES} value={b.applicantType} onChange={set('applicantType')} />
      </Section>

      <Section title="대표자">
        <div className="grid gap-3 sm:grid-cols-3">
          <TextInput label="이름" value={b.ceoName} placeholder="홍길동" onChange={set('ceoName')} />
          <TextInput label="생년월일" type="date" value={b.birthDate} onChange={set('birthDate')} />
          <Select label="성별" value={b.gender} options={['남성', '여성']} onChange={set('gender')} />
        </div>
        <Badges items={[youthBadge(b.birthDate), b.gender === '여성' && { tone: 'info', text: '여성 대표자' }]} />
      </Section>

      {b.applicantType && !pre && (
        <Section title="사업자 정보">
          <BizNoField value={b.bizNo} onChange={set('bizNo')} />
          <div className="grid gap-3 sm:grid-cols-2 mt-3">
            <TextInput label="개업일" type="date" value={b.openedAt} onChange={set('openedAt')} />
            <TextInput label="주업종" value={b.industry} placeholder="예) 응용 소프트웨어 개발" onChange={set('industry')} />
          </div>
          <Badges items={[careerBadge(b.openedAt)]} />
        </Section>
      )}

      <Section title="창업 구분" desc="재창업이면 지원 가능한 공고와 가산점이 달라져요.">
        <Segmented value={b.startType} onChange={set('startType')}
          options={[['first', '첫 창업', '사업을 운영한 적이 없어요'], ['restart', '재창업', '폐업 후 다시 창업해요']]} />
        {b.startType === 'restart' && (
          <div className="mt-4 rounded-2xl bg-[#f9fafb] p-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <Select label="재창업 횟수" value={b.restartCount} options={['1회', '2회', '3회 이상']} onChange={set('restartCount')} />
              <TextInput label="직전 폐업일" type="date" value={b.lastClosedAt} onChange={set('lastClosedAt')} />
              <Select label="채무 상태" value={b.debtStatus} options={['해당 없음', '변제 완료', '조정·변제 중']} onChange={set('debtStatus')} />
            </div>
            <button type="button" onClick={() => onGoTab('history')} className="mt-3 text-[13.5px] font-semibold text-[var(--primary)] hover:underline">
              이전 사업체 정보 입력하기 →
            </button>
          </div>
        )}
      </Section>

      <Section title="지역" desc="공고마다 거주지·본점·사업장 중 기준이 달라서 따로 받아요.">
        <div className="flex flex-col gap-4">
          <RegionInput label="거주지" value={b.home} onChange={set('home')} />
          {b.applicantType && !pre && (
            <>
              <Check checked={b.hqSameAsHome} onChange={set('hqSameAsHome')}>본점 소재지가 거주지와 같아요</Check>
              {!b.hqSameAsHome && <RegionInput label="본점" value={b.hq} onChange={set('hq')} />}
              <Check checked={b.hasSeparateSite} onChange={set('hasSeparateSite')}>본점과 다른 사업장·공장이 있어요</Check>
              {b.hasSeparateSite && <RegionInput label="사업장" value={b.site} onChange={set('site')} />}
            </>
          )}
          <Check checked={b.relocationPlanned} onChange={set('relocationPlanned')}>협약 후 지역을 옮길 계획이 있어요</Check>
        </div>
        <Badges items={[regionBadge(hqSido)]} />
      </Section>

      <Section title="보유 인증 · 확인서" desc="해당하는 것을 모두 골라 주세요.">
        <ChipSelect options={CERTS} values={b.certs} onChange={set('certs')} />
      </Section>
    </>
  );
}
