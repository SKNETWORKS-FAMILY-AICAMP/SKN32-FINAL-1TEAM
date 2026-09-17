import React, { useState } from 'react';
import { useMyPageStore } from '../../store/useMyPageStore.js';
import BasicInfo from './BasicInfo.jsx';
import BusinessHistory from './BusinessHistory.jsx';
import CapabilityTeam from './CapabilityTeam.jsx';
import { progressOf } from './derive.js';

const TABS = [
  ['basic', '기본 정보', BasicInfo],
  ['capability', '역량 · 팀', CapabilityTeam],
  ['history', '사업 이력', BusinessHistory],
];

export default function MyPage() {
  const [tab, setTab] = useState('basic');
  const progress = progressOf(useMyPageStore());
  const [done, total] = Object.values(progress).reduce(([d, t], [a, b]) => [d + a, t + b], [0, 0]);
  const percent = total ? Math.round((done / total) * 100) : 0;

  const index = TABS.findIndex(([key]) => key === tab);
  const [, , Current] = TABS[index];
  const next = TABS[index + 1];
  const goTab = (key) => { setTab(key); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  return (
    <section data-screen="mypage" className="max-w-3xl mx-auto px-6 py-14">
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] mb-2">마이페이지</p>
      <div className="flex flex-wrap items-end justify-between gap-4 mb-8">
        <div>
          <h1 className="font-bold text-[28px] md:text-[32px]">내 창업 정보</h1>
          <p className="text-[15px] text-[var(--muted-fg)] mt-2">한 번 정리해 두면 공고 자격과 가산점을 확인할 때 쓸 수 있어요.</p>
        </div>
        <div className="w-full sm:w-52">
          <div className="flex justify-between text-[13px] mb-1.5">
            <span className="text-[var(--muted-fg)]">입력 완료</span>
            <b className="text-[var(--primary)]">{percent}%</b>
          </div>
          <div className="h-2 rounded-full bg-[var(--muted)] overflow-hidden">
            <div className="h-full rounded-full bg-[var(--primary)] transition-[width] duration-300" style={{ width: `${percent}%` }} />
          </div>
        </div>
      </div>

      <nav role="tablist" className="sticky top-0 z-10 flex gap-1 bg-white border-b border-[var(--border)] mb-8">
        {TABS.map(([key, label]) => {
          const [d, t] = progress[key];
          const active = key === tab;
          return (
            <button key={key} role="tab" aria-selected={active} onClick={() => goTab(key)}
              className={`relative px-4 py-3.5 text-[15px] font-semibold transition-colors ${active ? 'text-[var(--fg)]' : 'text-[#8b95a1] hover:text-[#4e5968]'}`}>
              {label}
              <span className={`ml-1.5 text-[12.5px] font-medium ${t && d === t ? 'text-[var(--ok)]' : 'text-[#b0b8c1]'}`}>{t ? `${d}/${t}` : '선택'}</span>
              {active && <span className="absolute left-3 right-3 -bottom-px h-0.5 rounded-full bg-[var(--fg)]" />}
            </button>
          );
        })}
      </nav>

      <Current onGoTab={goTab} />

      <div className="flex items-center justify-between gap-4 mt-6 pt-6 border-t border-[var(--border)]">
        <p className="text-[12.5px] text-[var(--muted-fg)]">입력한 내용은 자동으로 저장돼요.</p>
        {next && (
          <button type="button" onClick={() => goTab(next[0])}
            className="h-12 px-6 rounded-xl bg-[var(--primary)] text-white text-[15px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] active:scale-[0.98]">
            다음: {next[1]}
          </button>
        )}
      </div>
    </section>
  );
}
