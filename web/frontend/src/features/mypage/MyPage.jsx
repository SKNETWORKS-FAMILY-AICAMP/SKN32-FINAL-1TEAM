import React, { useEffect, useState } from 'react';
import { Icon } from '../../components/Icons.jsx';
import { deleteAccount } from '../../api.js';
import { MAX_PROFILES, useMyPageStore } from '../../store/useMyPageStore.js';
import BasicInfo from './BasicInfo.jsx';
import CapabilityTeam from './CapabilityTeam.jsx';
import { missingRequiredFields } from './derive.js';
import { focusSection, inputCls } from './ui.jsx';

// 기본 정보 · 역량 · 팀은 예전엔 탭 두 개였다. 전부 7구역이라 한 페이지로 충분하고, 탭이면 첫 탭만 채우고 저장했다가
// 둘째 탭으로 끌려가는 일이 생겨 묶음 제목만 두고 이어 붙였다(디자인 점검 10-12). 구역 · 입력칸은 그대로다.
const GROUPS = [
  ['기본 정보', BasicInfo],
  ['역량 · 팀', CapabilityTeam],
];

// "새 프로필"을 누르면 이름을 먼저 정하는 모달이 뜬다.
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

// 프로필 고르기 — 위쪽 작은 탭 줄. 예전엔 세로 목록 + 파란 큰 "프로필 추가" 버튼이라 진짜 주 버튼(저장)과 겨뤘고,
// 이름 바꾸기는 "고른 이름을 한 번 더 누르기"라 찾기 어려웠고 삭제 X가 이름마다 늘 떠 있었다. 이름 바꾸기는 연필 버튼으로,
// 삭제는 페이지 아래 "이 프로필 삭제"로 옮겼다(디자인 점검 10-12).
function ProfileSwitcher() {
  const profiles = useMyPageStore((s) => s.profiles);
  const activeIndex = useMyPageStore((s) => s.activeIndex);
  const selectProfile = useMyPageStore((s) => s.selectProfile);
  const addProfile = useMyPageStore((s) => s.addProfile);
  const renameProfile = useMyPageStore((s) => s.renameProfile);
  const [editingIndex, setEditingIndex] = useState(null);
  const [addOpen, setAddOpen] = useState(false);

  return (
    <div className="mb-10">
      <p className="text-[13px] font-semibold text-[#4e5968] mb-2">내 프로필 <span className="font-medium text-[var(--muted-fg)]">{profiles.length}/{MAX_PROFILES}</span></p>
      <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label="내 프로필">
        {profiles.map((p, i) => {
          const active = i === activeIndex;
          if (active && editingIndex === i) {
            return (
              <input key={p.localId || i} autoFocus value={p.name} aria-label="프로필 이름" onChange={(e) => renameProfile(i, e.target.value)}
                onBlur={() => setEditingIndex(null)} onKeyDown={(e) => e.key === 'Enter' && setEditingIndex(null)}
                className="h-10 w-56 px-4 rounded-full border border-[var(--primary)] bg-white outline-none text-[14px] font-semibold" />
            );
          }
          return (
            <div key={p.localId || i}
              className={`inline-flex items-center h-10 rounded-full border transition-colors ${active ? 'border-[var(--primary)] bg-[#eef4fe]' : 'border-[var(--border)] bg-white hover:border-[#d1d6db]'}`}>
              <button type="button" role="tab" aria-selected={active} onClick={() => selectProfile(i)}
                className={`max-w-[220px] truncate pl-4 ${active ? 'pr-1' : 'pr-4'} text-[14px] font-semibold ${active ? 'text-[var(--primary-dim)]' : 'text-[#4e5968]'}`}>
                {p.name}
              </button>
              {active && (
                <button type="button" aria-label={`${p.name} 이름 바꾸기`} title="이름 바꾸기" onClick={() => setEditingIndex(i)}
                  className="w-8 h-8 mr-1 grid place-items-center rounded-full text-[var(--primary-dim)] hover:bg-white transition-colors">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z" /><path d="M13.5 6.5l4 4" /></svg>
                </button>
              )}
            </div>
          );
        })}
        {profiles.length < MAX_PROFILES && (
          <button type="button" onClick={() => setAddOpen(true)}
            className="h-10 px-4 rounded-full border border-dashed border-[#d1d6db] text-[14px] font-semibold text-[var(--primary)] hover:bg-[#f5f9ff] transition-colors">
            + 새 프로필
          </button>
        )}
      </div>
      <AddProfileModal open={addOpen} onClose={() => setAddOpen(false)} onCreate={addProfile} />
    </div>
  );
}

// 지금 고른 프로필 지우기 — 예전엔 프로필 이름마다 X가 늘 떠 있었다. 프로필이 하나뿐이면 지울 수 없다(예전과 같은 조건).
function DeleteProfileButton() {
  const profiles = useMyPageStore((s) => s.profiles);
  const activeIndex = useMyPageStore((s) => s.activeIndex);
  const removeProfile = useMyPageStore((s) => s.removeProfile);
  if (profiles.length <= 1) return null;
  const name = profiles[activeIndex]?.name;
  return (
    <button type="button"
      onClick={() => {
        if (!window.confirm(`"${name}"을(를) 삭제할까요?`)) return;
        removeProfile(activeIndex).catch((err) => {
          console.error('프로필을 지우지 못했어요', err);
          window.alert('프로필을 지우지 못했어요. 다시 시도해 주세요.');
        });
      }}
      className="text-[13px] font-semibold text-[var(--muted-fg)] underline underline-offset-2 hover:text-[var(--danger)]">
      이 프로필 삭제
    </button>
  );
}

// [2026-09-28] 계정 탈퇴(DELETE /auth/me, 기획서 v1.10 6-7절). 서버가 계정·프로필·모든 실행
// 이력을 되돌릴 수 없게 지우므로, 백엔드 주석이 요구하는 대로 확인 단계를 반드시 거친다 —
// 여기서는 실수로 누르기 어렵게 계정 이메일을 그대로 입력해야 버튼이 열리게 했다.
function DeleteAccountSection({ email, onDeleted }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirmed = typed.trim() === (email || '').trim() && !!email;

  const handleDelete = async () => {
    setBusy(true);
    setError('');
    try {
      await deleteAccount();
      onDeleted?.();
    } catch (e) {
      console.error('계정 삭제 실패:', e);
      // BUSY — 진행 중인 작업 때문에 멈췄다. 서버가 남은 것부터 이어서 지우므로 같은 버튼을 다시 누르면 된다.
      setError(e?.code === 'BUSY'
        ? '진행 중인 작업이 있어 탈퇴를 마치지 못했어요. 잠시 뒤 탈퇴 버튼을 다시 눌러 주세요.'
        : (e.message || '탈퇴 처리 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.'));
      setBusy(false);
    }
  };

  return (
    <div className="mt-12 pt-6 border-t border-[var(--border)]">
      {!open ? (
        <button type="button" onClick={() => setOpen(true)}
          className="text-[13px] font-semibold text-[var(--muted-fg)] underline underline-offset-2 hover:text-[var(--danger)]">
          계정 탈퇴
        </button>
      ) : (
        <div className="rounded-2xl border border-[#f4c9c9] bg-[#fff1f1] p-5">
          <p className="text-[14px] font-bold text-[#bb3434] mb-1.5">정말 탈퇴하시겠어요?</p>
          <p className="text-[12.5px] text-[#874b4b] leading-relaxed mb-4">
            계정과 마이페이지 정보, 지금까지 만든 사업계획서·프로토타입과 검증 이력이 모두 삭제됩니다. 되돌릴 수 없어요.
          </p>
          <label className="block text-[12.5px] text-[#874b4b] mb-1.5">확인을 위해 계정 이메일 <span className="font-semibold">{email}</span> 을 입력해 주세요</label>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} disabled={busy}
            className={inputCls + ' bg-white mb-3'} placeholder={email || '계정 이메일'} />
          {error && <p className="text-[12.5px] font-semibold text-[var(--danger)] mb-2">{error}</p>}
          <div className="flex items-center gap-2">
            <button type="button" onClick={handleDelete} disabled={!confirmed || busy}
              className="h-10 px-4 rounded-xl bg-[var(--danger)] text-white text-[13.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed transition-[scale] active:scale-[0.98]">
              {busy ? '처리 중…' : '탈퇴하기'}
            </button>
            <button type="button" onClick={() => { setOpen(false); setTyped(''); setError(''); }} disabled={busy}
              className="h-10 px-4 rounded-xl border border-[var(--border)] bg-white text-[13.5px] font-semibold disabled:opacity-40">
              취소
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MyPage({ onSaved, user, onAccountDeleted }) {
  const activeIndex = useMyPageStore((s) => s.activeIndex);
  const activeProfile = useMyPageStore((s) => s.profiles[s.activeIndex]);
  const onboarded = useMyPageStore((s) => s.onboarded);
  const saveActiveProfile = useMyPageStore((s) => s.saveActiveProfile);
  const [justSaved, setJustSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const missing = missingRequiredFields(activeProfile);
  // 저장을 눌렀을 때 비어 있던 첫 필수 항목. 그 항목을 채우면 안내는 저절로 사라진다.
  const [errorAnchor, setErrorAnchor] = useState(null);
  const error = missing.find((m) => m.anchor === errorAnchor) || null;
  const [pendingFocus, setPendingFocus] = useState(null);

  // 프로필을 바꾸거나 새로 추가하면 이전 프로필의 안내 · 오류는 지운다.
  useEffect(() => { setErrorAnchor(null); setSaveError(''); }, [activeIndex]);
  // 빈 항목 안내가 그려진 다음 그 구역으로 스크롤한다.
  useEffect(() => {
    if (!pendingFocus) return;
    focusSection(pendingFocus);
    setPendingFocus(null);
  }, [pendingFocus]);

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
      setPendingFocus(first.anchor);
      return;
    }
    setSaving(true);
    setSaveError('');
    try {
      await saveActiveProfile();
      onSaved?.();
      setJustSaved(true);
      setTimeout(() => setJustSaved(false), 2500);
    } catch (err) {
      console.error('마이페이지 저장에 실패했어요', err);
      setSaveError(err?.status === 401 ? '로그인이 끊겼어요. 다시 로그인해 주세요.' : '저장하지 못했어요. 잠시 후 다시 시도해 주세요.');
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

      {GROUPS.map(([title, Group]) => (
        <div key={title} className="mb-12">
          <h2 className="font-bold text-[21px] pb-3 mb-8 border-b-2 border-[var(--fg)]">{title}</h2>
          <div><Group error={error} /></div>
        </div>
      ))}

      {/* 저장 줄은 화면 아래에 따라다닌다 — 한 페이지가 길어져 맨 아래까지 내려가야 저장할 수 있으면 안 된다. */}
      <div className="sticky bottom-0 z-10 -mx-6 px-6 py-4 flex items-center justify-between gap-4 bg-white/95 backdrop-blur-sm border-t border-[var(--border)]">
        <div className="min-h-5">
          {saveError ? (
            <p className="text-[12.5px] font-semibold text-[var(--danger)]">{saveError}</p>
          ) : justSaved ? (
            <p className="text-[12.5px] font-semibold text-[var(--ok)]">저장됐어요.</p>
          ) : missing.length > 0 ? (
            <p className="text-[11.5px] text-[var(--muted-fg)]">[필수] 항목을 먼저 채워 주세요 — {missing.map((m) => m.label).join(', ')}</p>
          ) : !onboarded ? (
            <p className="text-[12.5px] text-[var(--warn)]">아직 저장 전이에요. 저장을 눌러 주세요.</p>
          ) : (
            <p className="text-[12.5px] text-[var(--muted-fg)]">저장 버튼을 눌러야 이 프로필이 서버에 반영돼요.</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button type="button" onClick={handleSave} disabled={saving}
            className="h-11 px-6 rounded-xl bg-[var(--primary)] text-white text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] disabled:opacity-40 disabled:cursor-not-allowed transition-[background-color,scale] active:scale-[0.98]">
            {saving ? '저장 중…' : '저장'}
          </button>
        </div>
      </div>

      <div className="mt-10"><DeleteProfileButton /></div>
      <DeleteAccountSection email={user?.email} onDeleted={onAccountDeleted} />
    </div>
  );
}
