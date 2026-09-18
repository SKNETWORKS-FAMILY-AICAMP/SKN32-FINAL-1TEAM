import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// 마이페이지 프로필. 계정당 최대 3개까지 별도로 저장할 수 있다(예: 아이템별로 다른
// 신청자 정보). 아직 저장용 백엔드 API가 없어서 persist(localStorage)로 새로고침만
// 버티게 해둔다 — 서버 API가 생기면 patch 시점에 호출만 붙이면 된다.
// 로그아웃 시 reset()을 불러야 같은 브라우저의 다음 사용자에게 값이 안 보인다(App.jsx).
//
// 재창업/과거 사업 이력은 추적하지 않는다 — 신청자 유형(예비창업자 / 개인사업자·법인)
// 하나로만 화면이 갈린다.
export const MAX_PROFILES = 3;

const emptyProfile = (name) => ({
  name,
  basic: {
    applicantType: '', ceoName: '', birthDate: '', gender: '',
    region: { sido: '', sigungu: '' },
    industry: '',
    certs: [],
    // 예비창업자 전용
    budgetScale: '',
    // 개인사업자·법인 전용
    bizNo: '', openedAt: '',
    selfFunding: false, selfFundingMin: '', selfFundingMax: '',
  },
  // checkedNo: 조회에 쓴 번호 — 입력칸 값이 바뀌면 이 결과는 무효로 본다.
  bizStatus: null,
  capability: { careers: [], skills: '', soloFounder: false, team: [], hires: [], equipment: [], partners: [] },
});

const initial = () => ({
  profiles: [emptyProfile('정보 1')],
  activeIndex: 0,
  // 저장 버튼을 눌러야만 true — 계정이 자기 정보를 한 번이라도 확정 저장했는지 나타낸다.
  // App.jsx가 이 값으로 "마이페이지 먼저 채우라" 강제 모달을 계속 띄울지 판단한다.
  onboarded: false,
});

export const useMyPageStore = create(
  persist(
    (set) => ({
      ...initial(),

      patch: (section, values) => set((s) => {
        const profiles = s.profiles.slice();
        const p = { ...profiles[s.activeIndex] };
        p[section] = { ...p[section], ...values };
        profiles[s.activeIndex] = p;
        return { profiles };
      }),
      setBizStatus: (bizStatus) => set((s) => {
        const profiles = s.profiles.slice();
        profiles[s.activeIndex] = { ...profiles[s.activeIndex], bizStatus };
        return { profiles };
      }),

      selectProfile: (i) => set({ activeIndex: i }),
      addProfile: (name) => set((s) => {
        if (s.profiles.length >= MAX_PROFILES) return s;
        return { profiles: [...s.profiles, emptyProfile(name?.trim() || `정보 ${s.profiles.length + 1}`)], activeIndex: s.profiles.length };
      }),
      removeProfile: (i) => set((s) => {
        if (s.profiles.length <= 1) return s;
        const profiles = s.profiles.filter((_, idx) => idx !== i);
        return { profiles, activeIndex: Math.min(s.activeIndex, profiles.length - 1) };
      }),
      renameProfile: (i, name) => set((s) => {
        const profiles = s.profiles.slice();
        profiles[i] = { ...profiles[i], name };
        return { profiles };
      }),

      completeOnboarding: () => set({ onboarded: true }),

      reset: () => set(initial()),
    }),
    { name: 'sbrain-mypage' },
  ),
);

// 섹션 하나에 대한 [값, 필드 setter] — 컴포넌트마다 patch('basic', {...})를 반복하지 않게.
// 항상 "현재 선택된 프로필"의 섹션을 읽고 쓴다.
export function useSection(section) {
  const values = useMyPageStore((s) => s.profiles[s.activeIndex][section]);
  const patch = useMyPageStore((s) => s.patch);
  return [values, (key) => (value) => patch(section, { [key]: value })];
}
