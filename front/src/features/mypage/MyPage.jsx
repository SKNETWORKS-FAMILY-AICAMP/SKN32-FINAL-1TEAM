import React, { useEffect, useState } from 'react';
import { Icon } from '../../components/Icons.jsx';
import { MAX_PROFILES, useMyPageStore } from '../../store/useMyPageStore.js';
import BasicInfo from './BasicInfo.jsx';
import CapabilityTeam from './CapabilityTeam.jsx';
import { missingRequiredFields } from './derive.js';
import { focusSection, inputCls } from './ui.jsx';

const TABS = [
  ['basic', '기본 정보', BasicInfo],
  ['capability', '역량 · 팀', CapabilityTeam],
];

// 깃허브의 "New branch" 목록 + 생성 모달과 같은 구조 — 브랜치 목록처럼 프로필을 세로
// 목록으로 보여주고, "프로필 추가"를 누르면 이름을 먼저 정하는 모달이 뜬다.
function AddProfileModal({ open, onClose, onCreate }) {
  const [name, setName] = useState('');
  useEffect(() => { if (open) setName(''); }, [open]);
  if (!open) return null;
  const submit = () => { onCreate(name); onClose(); };
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div role="dialog" aria-modal="true" aria-labelledby="add-profile-title" className="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)]">
        <div className="flex items-center justify-between mb-5">
          <h2 id="add-profile-title" className="font-bold text-[18px]">새 프로필 만들기</h2>
          <button type="button" onClick={onClose} aria-label="닫기" className="text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors"><Icon name="close" size={18} /></button>
        </div>
        <label className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">프로필 이름</label>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="예) 두 번째 아이템"
          onKeyDown={(e) => e.key === 'Enter' && submit()} className={inputCls} />
        <div className="flex gap-2 mt-6">
          <button type="button" onClick={onClose}
            className="flex-1 h-11 rounded-xl bg-[var(--muted)] text-[#4e5968] text-[14.5px] font-semibold hover:bg-[#e5e8eb] transition-colors">취소</button>
          <button type="button" onClick={submit}
            className="flex-1 h-11 rounded-xl bg-[var(--primary)] text-white text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] transition-colors">만들기</button>
        </div>
      </div>
    </div>
  );
}

function ProfileSwitcher() {
  const profiles = useMyPageStore((s) => s.profiles);
  const activeIndex = useMyPageStore((s) => s.activeIndex);
  const selectProfile = useMyPageStore((s) => s.selectProfile);
  const addProfile = useMyPageStore((s) => s.addProfile);
  const removeProfile = useMyPageStore((s) => s.removeProfile);
  const renameProfile = useMyPageStore((s) => s.renameProfile);
  const [editingIndex, setEditingIndex] = useState(null);
  const [addOpen, setAddOpen] = useState(false);

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-semibold text-[#4e5968]">내 프로필 ({profiles.length}/{MAX_PROFILES})</span>
        <button type="button" onClick={() => setAddOpen(true)} disabled={profiles.length >= MAX_PROFILES}
          className="h-11 px-5 rounded-xl bg-[var(--primary)] text-white text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
          프로필 추가
        </button>
      </div>
      <div className="rounded-xl border border-[var(--border)] overflow-hidden">
        {profiles.map((p, i) => {
          const active = i === activeIndex;
          return (
            <div key={i} className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-[var(--border)]' : ''} ${active ? 'bg-[#eef4fe]' : 'hover:bg-[#f9fafb]'}`}>
              {active && editingIndex === i ? (
                <input autoFocus value={p.name} onChange={(e) => renameProfile(i, e.target.value)}
                  onBlur={() => setEditingIndex(null)} onKeyDown={(e) => e.key === 'Enter' && setEditingIndex(null)}
                  className="flex-1 bg-transparent outline-none text-[14.5px] font-semibold" />
              ) : (
                <button type="button" onClick={() => (active ? setEditingIndex(i) : selectProfile(i))}
                  className={`flex-1 text-left truncate text-[14.5px] font-semibold ${active ? 'text-[var(--primary-dim)]' : 'text-[var(--fg)]'}`}>
                  {p.name}
                </button>
              )}
              {profiles.length > 1 && (
                <button type="button" aria-label={`${p.name} 삭제`}
                  onClick={() => {
                    if (!window.confirm(`"${p.name}"을(를) 삭제할까요?`)) return;
                    removeProfile(i).catch((err) => {
                      console.error('프로필을 지우지 못했어요', err);
                      window.alert('프로필을 지우지 못했어요. 다시 시도해 주세요.');
                    });
                  }}
                  className="w-7 h-7 flex-shrink-0 grid place-items-center rounded-lg text-[#b0b8c1] hover:text-[var(--danger)] hover:bg-white transition-colors">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                </button>
              )}
            </div>
          );
        })}
      </div>
      <AddProfileModal open={addOpen} onClose={() => setAddOpen(false)} onCreate={addProfile} />
    </div>
  );
}

export default function MyPage({ onSaved }) {
  const [tab, setTab] = useState('basic');
  const activeIndex = useMyPageStore((s) => s.activeIndex);
  const activeProfile = useMyPageStore((s) => s.profiles[s.activeIndex]);
  const onboarded = useMyPageStore((s) => s.onboarded);
  const saveActiveProfile = useMyPageStore((s) => s.saveActiveProfile);
  const [justSaved, setJustSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const missing = missingRequiredFields(activeProfile);
  // 저장을 눌렀을 때 비어 있던 첫 필수 항목. 그 항목을 채우면 안내는 저절로 사라진다.
  const [errorAnchor, setErrorAnchor] = useState(null);
  const error = missing.find((m) => m.anchor === errorAnchor) || null;
  const [pendingFocus, setPendingFocus] = useState(null);

  // 정보 슬롯을 바꾸거나 새로 추가하면 그 전에 보고 있던 탭(역량·팀 등)이 아니라
  // 항상 기본 정보 탭부터 보여준다 — 슬롯마다 처음 보는 화면이 같아야 헷갈리지 않는다.
  useEffect(() => { setTab('basic'); setErrorAnchor(null); }, [activeIndex]);
  // 빈 항목이 다른 탭에 있으면 탭을 바꾼 뒤(그 섹션이 그려진 다음) 스크롤한다.
  useEffect(() => {
    if (!pendingFocus) return;
    focusSection(pendingFocus);
    setPendingFocus(null);
  }, [pendingFocus, tab]);

  const index = TABS.findIndex(([key]) => key === tab);
  const [, , Current] = TABS[index];
  const next = TABS[index + 1];
  const goTab = (key) => { setTab(key); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  // [2026-09-18] completeOnboarding()은 서버 저장 없이 로컬 onboarded만 true로
  // 바꾸던 옛 함수라 store에서 없어졌다(saveActiveProfile로 대체) — 여기서 이어서
  // 부르던 게 남아있어 저장 버튼을 눌러도 실제로는 아무 일도 안 일어나던 버그였다.
  // onSaved()는 App.jsx가 넘겨준 콜백(/auth/me 재조회로 user.has_profile 갱신) — 이걸
  // 안 부르면 저장에 성공해도 로그인 시점에 캐시된 has_profile=false가 세션 내내 그대로
  // 남아 "시작하기"/"내 프로젝트" 이동마다 마이페이지 입력 강제 모달이 계속 떴다(사용자 지적).
  const handleSave = async () => {
    if (saving) return;
    if (missing.length > 0) {
      const first = missing[0];
      setErrorAnchor(first.anchor);
      setTab(first.tab);
      setPendingFocus(first.anchor);
      return;
    }
    setSaving(true);
    try {
      await saveActiveProfile();
      onSaved?.();
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2500);
    } catch (err) {
      console.error('마이페이지 저장에 실패했어요', err);
      window.alert(err.message || '저장에 실패했어요. 다시 시도해 주세요.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div data-screen="mypage" className="max-w-3xl mx-auto px-6 py-14">
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] mb-2">마이페이지</p>
      <div className="mb-6">
        <h1 className="font-bold text-[28px] md:text-[32px]">내 창업 정보</h1>
        <p className="text-[15px] text-[var(--muted-fg)] mt-2">한 번 정리해 두면 공고 자격을 확인할 때 쓸 수 있어요. 최대 3개까지 따로 저장할 수 있어요.</p>
      </div>

      <ProfileSwitcher />

      <nav role="tablist" className="sticky top-0 z-10 flex gap-1 bg-white border-b border-[var(--border)] mb-8">
        {TABS.map(([key, label]) => {
          const active = key === tab;
          return (
            <button key={key} role="tab" aria-selected={active} onClick={() => goTab(key)}
              className={`relative px-4 py-3.5 text-[15px] font-semibold transition-colors ${active ? 'text-[var(--fg)]' : 'text-[#8b95a1] hover:text-[#4e5968]'}`}>
              {label}
              {active && <span className="absolute left-3 right-3 -bottom-px h-0.5 rounded-full bg-[var(--fg)]" />}
            </button>
          );
        })}
      </nav>

      <Current error={error} />

      <div className="flex items-center justify-between gap-4 mt-6 pt-6 border-t border-[var(--border)]">
        <div className="min-h-5">
          {justSaved ? (
            <p className="text-[12.5px] font-semibold text-[var(--ok)]">저장됐어요.</p>
          ) : missing.length > 0 ? (
            <p className="text-[11.5px] text-[var(--muted-fg)]">[필수] 항목을 먼저 채워 주세요 — {missing.map((m) => m.label).join(', ')}</p>
          ) : !onboarded ? (
            <p className="text-[12.5px] text-[var(--warn)]">아직 저장 전이에요. 저장을 눌러 주세요.</p>
          ) : (
            <p className="text-[12.5px] text-[var(--muted-fg)]">입력한 내용은 이 정보 슬롯에 자동으로 저장돼요.</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {next && (
            <button type="button" onClick={() => goTab(next[0])}
              className="h-11 px-6 rounded-xl bg-[var(--muted)] text-[#4e5968] text-[14.5px] font-semibold hover:bg-[#e5e8eb] transition-[background-color,scale] active:scale-[0.98]">
              다음
            </button>
          )}
          <button type="button" onClick={handleSave} disabled={saving}
            className="h-11 px-6 rounded-xl bg-[var(--primary)] text-white text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-40 disabled:cursor-not-allowed transition-[background-color,scale] active:scale-[0.98]">
            {saving ? '저장 중…' : '저장'}
          </button>
        </div>
      </div>
    </div>
  );
}
