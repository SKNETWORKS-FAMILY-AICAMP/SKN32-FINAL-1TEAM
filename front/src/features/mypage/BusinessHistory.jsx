import React from 'react';
import { useMyPageStore, useSection } from '../../store/useMyPageStore.js';
import { formatMonths, monthsBetween } from './derive.js';
import { Badges, ListEditor, Section } from './ui.jsx';

export default function BusinessHistory() {
  const [h, set] = useSection('history');
  const isRestart = useMyPageStore((s) => s.basic.startType === 'restart');

  const pastBadge = (row) => {
    if (!row.openedAt) return null;
    const m = monthsBetween(row.openedAt, row.closedAt || undefined);
    return m == null ? null : <Badges items={[{ tone: 'ok', text: `업력 ${formatMonths(m)}` }]} />;
  };

  return (
    <Section title="과거 사업 이력"
      desc={isRestart ? '재창업 자격과 과거 업력 계산에 쓰여요.' : "기본 정보에서 '첫 창업'을 골랐다면 비워 두셔도 돼요."}>
      <ListEditor items={h.pastBusinesses} onChange={set('pastBusinesses')} cols={4} addLabel="사업체 추가" extra={pastBadge}
        emptyText={isRestart ? '폐업한 사업체 정보를 추가해 주세요.' : undefined}
        fields={[
          { key: 'name', label: '상호', placeholder: '이전 상호' },
          { key: 'bizNo', label: '사업자등록번호', placeholder: '000-00-00000' },
          { key: 'openedAt', label: '개업일', type: 'date' },
          { key: 'closedAt', label: '폐업일', type: 'date' },
          { key: 'size', label: '기업 규모', type: 'select', options: ['소상공인', '소기업', '중기업'] },
          { key: 'industry', label: '업종', placeholder: '음식점업' },
          { key: 'region', label: '소재지', placeholder: '시/군/구' },
          { key: 'closeReason', label: '폐업 사유', type: 'select', options: ['경영 악화', '업종 전환', '개인 사정', '기타'] },
        ]} />
    </Section>
  );
}
