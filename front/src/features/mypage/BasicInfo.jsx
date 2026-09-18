import React from 'react';
import { useSection } from '../../store/useMyPageStore.js';
import BizNoField from './BizNoField.jsx';
import { CERTS, PRELIMINARY_BUDGET_CAP_MANWON, careerBadge, regionBadge, youthBadge } from './derive.js';
import { Badge, Badges, Check, ChipSelect, Field, IndustryField, RegionInput, Section, Segmented, Select, TextInput, inputCls } from './ui.jsx';

const APPLICANT_TYPES = [['preliminary', '예비창업자'], ['individual', '개인사업자'], ['corp', '법인']];

// 만원 단위 숫자만 남기고 2,000(=2,000만원)을 못 넘게 그 자리에서 잘라낸다.
const clampBudget = (v) => {
  const digits = v.replace(/\D/g, '');
  if (!digits) return '';
  return String(Math.min(PRELIMINARY_BUDGET_CAP_MANWON, parseInt(digits, 10)));
};

export default function BasicInfo() {
  const [b, set] = useSection('basic');
  const pre = b.applicantType === 'preliminary';
  const biz = b.applicantType === 'individual' || b.applicantType === 'corp';

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

      <Section title="지역 · 주업종">
        <RegionInput label="지역" value={b.region} onChange={set('region')} />
        <div className="mt-3">
          <IndustryField applicantType={b.applicantType} value={b.industry} onChange={set('industry')} />
        </div>
        <Badges items={[regionBadge(b.region.sido)]} />
      </Section>

      <Section title="보유 인증 · 가입" desc="해당하는 것을 모두 골라 주세요.">
        <ChipSelect options={CERTS} values={b.certs} onChange={set('certs')} />
      </Section>

      {pre && (
        <Section title="예비창업자 정보">
          <div className="flex items-center gap-2 mb-4">
            <Badge tone="info">첫창업</Badge>
            <p className="text-[13px] text-[var(--muted-fg)]">예비창업자는 첫창업 기준으로 접수돼요.</p>
          </div>
          <Field label="희망 사업 규모">
            <div className="relative">
              <input inputMode="numeric" value={b.budgetScale} placeholder="예) 1500"
                onChange={(e) => set('budgetScale')(clampBudget(e.target.value))}
                className={`${inputCls} pr-14`} />
              <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[14px] text-[var(--muted-fg)]">만원</span>
            </div>
          </Field>
          <p className="text-[12.5px] text-[var(--muted-fg)] mt-1.5">
            최대 2,000만원까지 입력할 수 있어요. 실제 상한은 공고마다 다르니 지원 전 다시 확인해 주세요.
          </p>
        </Section>
      )}

      {biz && (
        <Section title="사업자 정보">
          <BizNoField value={b.bizNo} onChange={set('bizNo')} />
          <div className="grid gap-3 sm:grid-cols-2 mt-3">
            <TextInput label="설립일" type="date" value={b.openedAt} onChange={set('openedAt')} />
          </div>
          <Badges items={[careerBadge(b.openedAt)]} />

          <div className="mt-5 pt-5 border-t border-[var(--border)]">
            <Check checked={b.selfFunding} onChange={set('selfFunding')}>자기부담금을 부담할 수 있어요</Check>
            {b.selfFunding && (
              <div className="grid gap-3 sm:grid-cols-2 mt-3">
                <TextInput label="최소 금액" value={b.selfFundingMin} placeholder="예) 5,000,000" onChange={set('selfFundingMin')} />
                <TextInput label="최대 금액" value={b.selfFundingMax} placeholder="예) 10,000,000" onChange={set('selfFundingMax')} />
              </div>
            )}
          </div>
        </Section>
      )}
    </>
  );
}
