// 원래 이 파일 하나(2235줄)에 파이프라인 화면 10여 개가 다 들어있었다. features/workflow/
// 아래로 화면 단위 파일로 쪼개고, 여기는 얇은 배럴(barrel)로 남겨 export 목록을 그대로
// 유지한다 — App.jsx / Workspace.jsx / audit.jsx / scripts/render-check.mjs가 전부
// './features/Workflow.jsx'에서 이 이름들을 import하고 있어서, 그 4곳은 한 줄도 안 바꿔도 된다.
export { IntakeForm } from './workflow/IntakeForm.jsx';
export { MatchProgress, MatchResults } from './workflow/MatchResults.jsx';
export { EligibilityGate } from './workflow/EligibilityGate.jsx';
export { PipelineProgress, PlanForm } from './workflow/PlanForm.jsx';
export { ArtifactProgress, ArtifactResult } from './workflow/ArtifactResult.jsx';
export { FinalVerdict } from './workflow/FinalVerdict.jsx';
export { ReviewScreen } from './workflow/ReviewScreen.jsx';
export { NotificationBell } from './workflow/shared.jsx';
export { SIMILAR_ANNOUNCEMENT_ALERTS, ANNOUNCEMENTS, MY_PROJECTS } from './workflow/data.js';
