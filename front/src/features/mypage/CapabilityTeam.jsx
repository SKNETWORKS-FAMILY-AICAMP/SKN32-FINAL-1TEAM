import React from 'react';
import { useSection } from '../../store/useMyPageStore.js';
import { CAREER_FIELDS, EQUIPMENT_FIELDS, HIRE_FIELDS, PARTNER_FIELDS } from './derive.js';
import { Check, ListEditor, Section, textareaCls } from './ui.jsx';

export default function CapabilityTeam() {
  const [c, set] = useSection('capability');

  return (
    <>
      <Section title="대표자 이력" desc="사업계획서 '팀 구성' 항목 작성에 쓰여요. 증빙 서류가 있으면 표시해 주세요.">
        <ListEditor items={c.careers} onChange={set('careers')} cols={4} addLabel="이력 추가"
          emptyText="경력, 학력, 지원사업 수행, 수상 이력을 추가해 주세요."
          fields={CAREER_FIELDS} />
        <label className="block mt-5">
          <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">기술력 · 노하우 · 인적 네트워크</span>
          <textarea value={c.skills} onChange={(e) => set('skills')(e.target.value)} rows={4}
            placeholder="창업 아이템을 개발하거나 구체화할 수 있는 역량을 적어 주세요"
            className={textareaCls} />
        </label>
      </Section>

      <Section title="팀 구성원">
        <div className="mb-3"><Check checked={c.soloFounder} onChange={set('soloFounder')}>팀원 없이 혼자 준비하고 있어요</Check></div>
        {!c.soloFounder && (
          <ListEditor items={c.team} onChange={set('team')} cols={4} addLabel="팀원 추가"
            fields={[
              { key: 'name', label: '이름', placeholder: '홍길동' },
              { key: 'role', label: '역할', placeholder: 'CTO · 개발' },
              { key: 'career', label: '경력 · 학력', placeholder: 'AI 엔지니어 5년' },
              { key: 'status', label: '상태', type: 'select', options: ['재직 중', '합류 예정'] },
            ]} />
        )}
      </Section>

      <Section title="채용 계획" desc="협약 기간 안에 뽑을 인력이 있다면 적어 주세요.">
        <ListEditor items={c.hires} onChange={set('hires')} cols={4} addLabel="채용 계획 추가" fields={HIRE_FIELDS} />
      </Section>

      <Section title="장비 · 협력 기관">
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="text-[14px] font-semibold mb-2">장비 · 시설</h3>
            <ListEditor items={c.equipment} onChange={set('equipment')} cols={2} addLabel="장비 추가" fields={EQUIPMENT_FIELDS} />
          </div>
          <div>
            <h3 className="text-[14px] font-semibold mb-2">협력 파트너 · 기관</h3>
            <ListEditor items={c.partners} onChange={set('partners')} cols={2} addLabel="파트너 추가" fields={PARTNER_FIELDS} />
          </div>
        </div>
      </Section>
    </>
  );
}
