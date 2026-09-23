import { create } from 'zustand';

// App.jsx가 들고 있던 9개 useState(현재 진행 중인 프로젝트/워크플로우 데이터)를 하나로
// 묶은 전역 스토어. S-Brain_기술스택_선정서_v1.0.docx 3-2 "전역 상태" 전환 항목 반영.
// 화면 컴포넌트들의 prop 시그니처는 그대로 유지한다(App.jsx가 여기서 값을 읽어 props로
// 넘기는 방식은 안 바뀜) — audit.jsx / scripts/render-check.mjs가 컴포넌트를 mock props로
// 직접 렌더하는 방식에 의존하고 있어서다.
export const useWorkflowStore = create((set) => ({
  itemInfo: null,
  announcement: null,
  checkedFailedTitles: [],
  returnToDashboard: false,
  scoreOutcome: 'fail',
  docOutcome: 'fail',
  artifactOutcome: 'fail',
  projectId: null,
  pipelineResult: null,
  matchCandidates: null,
  // [2026-09-23] GET /result의 verdict는 산출물 채점까지 끝나야 나오므로 프로토타입 생성
  // 중엔 null이다(app/schemas.py DemoGenerateResponse.verdict). "아직 판정 전"과 "미달"은
  // 전혀 다른 상태라 scoreOutcome('pass'/'fail')만으론 구분이 안 돼 따로 들고 있는다.
  verdictPending: false,

  setItemInfo: (itemInfo) => set({ itemInfo }),
  setAnnouncement: (announcement) => set({ announcement }),
  setCheckedFailedTitles: (updater) =>
    set((s) => ({
      checkedFailedTitles: typeof updater === 'function' ? updater(s.checkedFailedTitles) : updater,
    })),
  setReturnToDashboard: (returnToDashboard) => set({ returnToDashboard }),
  setDocOutcome: (docOutcome) => set({ docOutcome }),
  setArtifactOutcome: (artifactOutcome) => set({ artifactOutcome }),
  setProjectId: (projectId) => set({ projectId }),
  setPipelineResult: (pipelineResult) => set({ pipelineResult }),
  setMatchCandidates: (matchCandidates) => set({ matchCandidates }),
  setVerdictPending: (verdictPending) => set({ verdictPending }),

  resetScoreOutcome: (v) => set({ scoreOutcome: v, docOutcome: v, artifactOutcome: v }),
  resetProject: () =>
    set({ projectId: null, itemInfo: null, announcement: null, checkedFailedTitles: [], pipelineResult: null, matchCandidates: null, returnToDashboard: false, verdictPending: false }),
}));
