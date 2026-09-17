import { create } from 'zustand';
import { persist } from 'zustand/middleware';

// 마이페이지 프로필. 아직 저장용 백엔드 API가 없어서 persist(localStorage)로 새로고침만
// 버티게 해둔다 — 서버 API가 생기면 patch 시점에 호출만 붙이면 된다.
// 로그아웃 시 reset()을 불러야 같은 브라우저의 다음 사용자에게 값이 안 보인다(App.jsx).
const region = () => ({ sido: '', sigungu: '' });

const initial = () => ({
  basic: {
    applicantType: '', ceoName: '', birthDate: '', gender: '',
    bizNo: '', openedAt: '', industry: '',
    startType: 'first', restartCount: '', lastClosedAt: '', debtStatus: '',
    home: region(), hq: region(), hqSameAsHome: false,
    site: region(), hasSeparateSite: false, relocationPlanned: false,
    certs: [],
  },
  // checkedNo: 조회에 쓴 번호 — 입력칸 값이 바뀌면 이 결과는 무효로 본다.
  bizStatus: null,
  capability: { careers: [], skills: '', soloFounder: false, team: [], hires: [], equipment: [], partners: [] },
  history: { pastBusinesses: [], yellowUmbrella: false, yellowUmbrellaJoinedAt: '' },
});

export const useMyPageStore = create(
  persist(
    (set) => ({
      ...initial(),
      patch: (section, values) => set((s) => ({ [section]: { ...s[section], ...values } })),
      setBizStatus: (bizStatus) => set({ bizStatus }),
      reset: () => set(initial()),
    }),
    { name: 'sbrain-mypage' },
  ),
);

// 섹션 하나에 대한 [값, 필드 setter] — 컴포넌트마다 patch('basic', {...})를 반복하지 않게.
export function useSection(section) {
  const values = useMyPageStore((s) => s[section]);
  const patch = useMyPageStore((s) => s.patch);
  return [values, (key) => (value) => patch(section, { [key]: value })];
}
