import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createProfile, deleteProfile, listProfiles, updateProfile } from '../api.js';

// 마이페이지 프로필. 계정당 최대 3개까지 별도로 저장할 수 있다(예: 아이템별로 다른
// 신청자 정보). [2026-09-18] back/app/routers/profile.py(GET/POST /profile, PUT·DELETE
// /profile/{id})에 연결했다 — 로그인 직후(App.jsx) loadProfiles()로 서버 값을 끌어와야
// "다른 기기에서 로그인하면 안 보이던" 문제가 실제로 고쳐진다. persist(localStorage)는
// 여전히 켜두지만 로그인 상태 복원·계정 변경 시에는 캐시를 비우고 서버에서 다시 읽는다.
// 이전 계정의 요청 응답은 generation으로 구분해서 버린다.
// 로그아웃 시 reset()을 불러야 같은 브라우저의 다음 사용자에게 값이 안 보인다(App.jsx).
//
// 재창업/과거 사업 이력은 추적하지 않는다 — 신청자 유형(예비창업자 / 개인사업자·법인)
// 하나로만 화면이 갈린다.
export const MAX_PROFILES = 3;
let profileSequence = 0;
const newLocalId = () => `profile-${Date.now()}-${++profileSequence}`;

const emptyProfile = (name) => ({
  localId: newLocalId(),
  // profileId: 서버에 아직 한 번도 저장 안 한 슬롯이면 null — save()가 null이면 POST(생성),
  // 있으면 PUT(수정)으로 나눠 호출한다.
  profileId: null,
  name,
  basic: {
    applicantType: '', ceoName: '', birthDate: '', gender: '',
    region: { sido: '', sigungu: '' },
    industry: '',
    certs: [],
    // 예비창업자 전용
    budgetScale: '',
    // 개인사업자·법인 전용 (companyName은 사업계획서 일반현황 '기업명' 칸에 쓰인다)
    bizNo: '', companyName: '', openedAt: '',
    selfFunding: false, selfFundingMin: '', selfFundingMax: '',
  },
  // checkedNo: 조회에 쓴 번호 — 입력칸 값이 바뀌면 이 결과는 무효로 본다.
  bizStatus: null,
  capability: { careers: [], skills: '', soloFounder: false, team: [], hires: [], equipment: [], partners: [] },
});

// GET /profile 응답(ProfileOut) 한 건 -> 이 스토어의 profile 모양.
const profileFromServer = (p) => ({
  localId: newLocalId(),
  profileId: p.profile_id,
  name: p.name,
  basic: { ...emptyProfile('').basic, ...p.basic },
  bizStatus: p.bizStatus ?? null,
  capability: { ...emptyProfile('').capability, ...p.capability },
});

const initial = () => ({
  generation: 0,
  profiles: [emptyProfile('정보 1')],
  activeIndex: 0,
  // 저장 버튼을 눌러야만 true — 계정이 자기 정보를 한 번이라도 확정 저장했는지 나타낸다.
  // App.jsx가 이 값으로 "마이페이지 먼저 채우라" 강제 모달을 계속 띄울지 판단한다.
  onboarded: false,
  // loadProfiles()가 아직 한 번도 안 끝났으면 true — 로그인 직후 서버 값이 오기 전에
  // "onboarded:false"로 잘못 판단해 강제 모달을 띄우는 걸 막는 데 쓴다(App.jsx).
  loading: false,
});

export const useMyPageStore = create(
  persist(
    (set, get) => ({
      ...initial(),

      patch: (section, values) => set((s) => {
        const profiles = s.profiles.slice();
        const p = { ...profiles[s.activeIndex] };
        p[section] = { ...p[section], ...values };
        profiles[s.activeIndex] = p;
        return { profiles };
      }),
      setBizStatus: (localId, generation, bizStatus) => set((s) => {
        if (s.generation !== generation) return s;
        const index = s.profiles.findIndex(p => p.localId === localId);
        if (index < 0 || s.profiles[index].basic.bizNo !== bizStatus.checkedNo) return s;
        const profiles = s.profiles.slice();
        profiles[index] = { ...profiles[index], bizStatus };
        return { profiles };
      }),

      selectProfile: (i) => set({ activeIndex: i }),
      addProfile: (name) => set((s) => {
        if (s.profiles.length >= MAX_PROFILES) return s;
        return { profiles: [...s.profiles, emptyProfile(name?.trim() || `정보 ${s.profiles.length + 1}`)], activeIndex: s.profiles.length };
      }),
      // 서버에 저장된 적 있는 슬롯(profileId 있음)이면 DELETE부터 성공해야 로컬에서도 지운다
      // — 실패하면 그대로 throw해서 호출부(MyPage.jsx)가 사용자에게 알릴 수 있게 한다.
      removeProfile: async (i) => {
        const s = get();
        if (s.profiles.length <= 1) return;
        const target = s.profiles[i];
        if (target.profileId != null) await deleteProfile(target.profileId);
        set((s2) => {
          if (s2.generation !== s.generation) return s2;
          const selectedId = s2.profiles[s2.activeIndex]?.localId;
          const profiles = s2.profiles.filter(p => p.localId !== target.localId);
          if (!profiles.length) profiles.push(emptyProfile('정보 1'));
          const selectedIndex = profiles.findIndex(p => p.localId === selectedId);
          return { profiles, activeIndex: selectedIndex < 0 ? 0 : selectedIndex };
        });
      },
      renameProfile: (i, name) => set((s) => {
        const profiles = s.profiles.slice();
        profiles[i] = { ...profiles[i], name };
        return { profiles };
      }),

      // 로그인 직후(App.jsx)와 로그인 상태 복원 시 호출 — 서버가 가진 슬롯 목록으로
      // 로컬 상태를 완전히 교체한다. 서버에 저장된 슬롯이 하나도 없으면(신규 계정이거나
      // 아직 저장 전) 빈 슬롯 하나로 초기화하고 onboarded를 false로 되돌린다 — 로그인한
      // 계정이 바뀌었는데 이전 계정의 로컬 캐시가 "저장된 적 있음"으로 잘못 남아있을 수
      // 있어서다.
      loadProfiles: async () => {
        const generation = get().generation + 1;
        set({ ...initial(), generation, loading: true });
        try {
          const rows = await listProfiles();
          if (get().generation !== generation) return;
          if (rows.length === 0) {
            set({ profiles: [emptyProfile('정보 1')], activeIndex: 0, onboarded: false, loading: false });
          } else {
            set({ profiles: rows.map(profileFromServer), activeIndex: 0, onboarded: true, loading: false });
          }
        } catch (err) {
          if (get().generation !== generation) return;
          set({ loading: false });
        }
      },

      // "저장" 버튼 — 현재 활성 슬롯을 서버에 만들거나(최초) 갱신한다(그 다음부터).
      // 실패하면 throw하므로 호출부가 try/catch로 사용자에게 알려야 한다.
      saveActiveProfile: async () => {
        const s = get();
        const savingIndex = s.activeIndex;
        const active = s.profiles[savingIndex];
        const body = { name: active.name, basic: active.basic, capability: active.capability };
        const saved = active.profileId == null
          ? await createProfile(body)
          : await updateProfile(active.profileId, body);
        // 배열 순서가 바뀌어도 요청 당시 슬롯만 갱신하고, 로그아웃 전 응답은 버린다.
        set((s2) => {
          if (s2.generation !== s.generation) return s2;
          const index = s2.profiles.findIndex(p => p.localId === active.localId);
          if (index < 0) return s2;
          const profiles = s2.profiles.slice();
          // 요청 이후 입력한 내용은 유지하고 새 서버 ID만 연결한다.
          profiles[index] = profiles[index] === active
            ? { ...profileFromServer(saved), localId: active.localId }
            : { ...profiles[index], profileId: saved.profile_id };
          return { profiles, onboarded: true };
        });
      },

      reset: () => set(s => ({ ...initial(), generation: s.generation + 1 })),
    }),
    { name: 'sbrain-mypage', partialize: (s) => ({ profiles: s.profiles, activeIndex: s.activeIndex, onboarded: s.onboarded }),
      merge: (saved, current) => ({ ...current, ...saved,
        profiles: saved?.profiles?.length ? saved.profiles.map(p => ({ ...p, localId: newLocalId() })) : current.profiles,
        activeIndex: Math.max(0, Math.min(saved?.activeIndex || 0, (saved?.profiles?.length || 1) - 1)),
      }),
    },
  ),
);

// 섹션 하나에 대한 [값, 필드 setter] — 컴포넌트마다 patch('basic', {...})를 반복하지 않게.
// 항상 "현재 선택된 프로필"의 섹션을 읽고 쓴다.
export function useSection(section) {
  const values = useMyPageStore((s) => s.profiles[s.activeIndex][section]);
  const patch = useMyPageStore((s) => s.patch);
  return [values, (key) => (value) => patch(section, { [key]: value })];
}
