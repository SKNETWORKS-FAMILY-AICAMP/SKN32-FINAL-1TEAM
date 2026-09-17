import React from 'react';
import { useSection } from '../../store/useMyPageStore.js';
import { Check, ListEditor, Section, inputCls } from './ui.jsx';

// 목업에선 경력/학력/지원사업/교육/수상을 칸을 나눠 받았는데, 입력 방식이 같아서
// "구분" 하나로 합쳤다 — 사용자는 목록 하나에 순서대로 적기만 하면 된다.
const CAREER_TYPES = ['경력', '학력', '정부지원사업', '교육 이수', '수상', '자격증'];

export default function CapabilityTeam() {
  const [c, set] = useSection('capability');

  return (
    <>
      <Section title="대표자 이력" desc="사업계획서 '팀 구성' 항목 작성에 쓰여요. 증빙 서류가 있으면 표시해 주세요.">
        <ListEditor items={c.careers} onChange={set('careers')} cols={4} addLabel="이력 추가"
          emptyText="경력, 학력, 지원사업 수행, 수상 이력을 추가해 주세요."
          fields={[
            { key: 'type', label: '구분', type: 'select', options: CAREER_TYPES },
            { key: 'title', label: '내용', placeholder: '○○전자 · 백엔드 개발' },
            { key: 'period', label: '기간', placeholder: '2019.03 – 2023.10' },
            { key: 'hasProof', label: '증빙 있음', type: 'check' },
          ]} />
        <label className="block mt-5">
          <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">기술력 · 노하우 · 인적 네트워크</span>
          <textarea value={c.skills} onChange={(e) => set('skills')(e.target.value)} rows={4}
            placeholder="창업 아이템을 개발하거나 구체화할 수 있는 역량을 적어 주세요"
            className={`${inputCls} h-auto py-3 resize-none`} />
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
        <ListEditor items={c.hires} onChange={set('hires')} cols={4} addLabel="채용 계획 추가"
          fields={[
            { key: 'job', label: '직무', placeholder: '프론트엔드 개발' },
            { key: 'count', label: '인원', placeholder: '1명' },
            { key: 'skill', label: '요구 역량', placeholder: 'React 3년 이상' },
            { key: 'when', label: '채용 시기', type: 'month' },
          ]} />
      </Section>

      <Section title="장비 · 협력 기관">
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="text-[14px] font-semibold mb-2">장비 · 시설</h3>
            <ListEditor items={c.equipment} onChange={set('equipment')} cols={2} addLabel="장비 추가"
              fields={[
                { key: 'name', label: '이름', placeholder: 'GPU 서버' },
                { key: 'status', label: '상태', type: 'select', options: ['보유', '도입 예정'] },
              ]} />
          </div>
          <div>
            <h3 className="text-[14px] font-semibold mb-2">협력 파트너 · 기관</h3>
            <ListEditor items={c.partners} onChange={set('partners')} cols={2} addLabel="파트너 추가"
              fields={[
                { key: 'name', label: '기관명 · 협력 내용', placeholder: '○○대학 · 실증 지원' },
                { key: 'status', label: '상태', type: 'select', options: ['협력 중', '예정'] },
              ]} />
          </div>
        </div>
      </Section>
    </>
  );
}
