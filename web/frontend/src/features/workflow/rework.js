// 재작성(화면 6 · 8 · 9) — 접수 → 진행 상태 확인 → 결과 조회.
// [SB-244] POST /retry-task는 접수만 하고 바로 돌아온다(ReworkAcceptedOut). 같은 화면에서 모으는 시간(잠정 2초) 안의
// 요청은 재작성 한 번(cycle_id 하나)으로 합쳐지고, 끝난 결과(전후 비교 · 실패 되돌림)는 GET /rework-result로 읽는다
// (웹연동_변경사항_웹팀전달.md 2.1 retry-task 행 · 3.7, 명세 5.3 · 6.3).
import {getProjectStatus, getReworkResult, retryTask} from '../../api.js';
import {reworkDiffFromChanged} from './utils.js';
import {DOC_REWORK_BUNDLES} from './data.js';

// 재작성이 실패하면 서버가 요청 전 결과로 되돌리고 기회를 돌려준다(E-RUN-ROLLBACK).
export const REWORK_FAILED_MESSAGE = '일시적인 문제로 다시 만들지 못해 이전 결과로 되돌렸습니다. 다시 만들 기회는 그대로 남아 있습니다.';
const POLL_MS = 2000;

// 고른 묶음(라벨 — 문제인식 · 실현가능성 · 성장전략 · 팀 구성 · 실행 파일 제작 · 인포그래픽 제작)마다 접수한다.
// 묶음마다 서버가 기회를 따로 세므로 하나로 뭉쳐 부르지 않는다.
// 일부만 거절될 수 있다(예: 한 묶음만 상한 E-G2-LIMIT) — 접수된 묶음은 서버에서 재작성이 돌기 때문에 끝까지 추적해야 한다.
// 돌려주는 값: {cycleId, labels(접수된 묶음), rejected([{label, error}])}. 모두 거절되면 첫 오류를 그대로 던진다.
export async function requestRework(projectId, labels, taskKeyByLabel) {
  const settled = await Promise.allSettled(labels.map((label) => retryTask(projectId, taskKeyByLabel[label], label)));
  const accepted = [];
  const rejected = [];
  settled.forEach((s, i) => (s.status === 'fulfilled' ? accepted.push({label: labels[i], value: s.value}) : rejected.push({label: labels[i], error: s.reason})));
  if (accepted.length === 0) {
    const err = rejected[0].error;
    if (err && typeof err === 'object') err.rejected = rejected; // 화면이 묶음별로 다시 고를 수 있게(상한 묶음은 빼고)
    throw err;
  }
  return {cycleId: accepted[0].value.cycle_id, labels: accepted.map((a) => a.label), rejected};
}

// 재작성 상한(E-G2-LIMIT) — 다시 고를 수 없는 묶음이다. 화면은 이 묶음을 다시 체크해 두지 않고 남은 횟수를 새로 받아 버튼을 끈다.
export const isReworkCapError = (err) => err?.code === 'E-G2-LIMIT';

// 거절당한 뒤 다시 체크해 둘 묶음 — 상한에 걸린 묶음은 뺀다. rejected가 없으면(요청 전 오류 등) 고른 묶음 그대로.
export function relabelAfterReject(picked, rejected) {
  return rejected ? rejected.filter((r) => !isReworkCapError(r.error)).map((r) => r.label) : picked;
}

// 거절된 묶음 안내 한 줄씩 — "성장전략: 이 항목은 다시 만들 수 있는 횟수를 모두 사용했어요."
export function rejectedReworkMessage(rejected) {
  return rejected.map((r) => `${r.label}: ${r.error?.message || '요청을 받지 못했어요.'}`).join('\n');
}

// cycleId의 재작성이 끝날 때까지(status 완료 · 실패) 기다려 결과(ReworkResultOut)를 돌려준다.
// rework-result는 '마지막 재작성 한 건'이라, 접수 직후엔 이전 재작성이 올 수 있어 cycle_id로 맞춘다.
// isAlive()가 거짓이 되면(화면을 떠남) null.
export async function waitRework(projectId, cycleId, isAlive = () => true) {
  for (;;) {
    let result = null;
    try {
      result = await getReworkResult(projectId);
    } catch (err) {
      if (err.status !== 404) throw err; // 404 = 아직 기록 없음 — 다시 본다
    }
    if (!isAlive()) return null;
    if (result && result.cycle_id === cycleId && result.status !== '진행중') return result;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    if (!isAlive()) return null;
  }
}

// 화면을 열 때 — 이 화면에서 요청한 재작성이 아직 진행 중이면 그 재작성(cycle_id · bundles)을 준다(화면을 나갔다 돌아온 경우).
// 진행 중인지는 /status의 rework_screen(재작성 중인 화면, 모으는 중 포함)으로 보고(SB-272), 기다릴 cycle_id와
// 묶음은 /rework-result에서 읽는다. 재작성 중이 아니면 /rework-result를 부르지 않는다.
export async function findRunningRework(projectId, screen) {
  const status = await getProjectStatus(projectId);
  if (status?.rework_screen !== screen) return null;
  try {
    const result = await getReworkResult(projectId);
    return result && result.status === '진행중' ? result : null;
  } catch (err) {
    if (err.status === 404 || err.status === 409) return null; // 아직 기록 없음 · 결과를 볼 수 없는 실행
    throw err;
  }
}

// 묶음 하나의 "변경 내역" 한 줄 — 재작성 결과의 changed에서 그 묶음 몫만 골라 만든다.
// 계획서 묶음은 계획서 전체를 다시 만들어(문서층 임시 처리) sections가 같고, 산출물 묶음은 그 파일 경로를 본다.
export function reworkDiffForLabel(changed, label) {
  if (!changed) return null;
  if (DOC_REWORK_BUNDLES.includes(label)) return reworkDiffFromChanged({sections: changed.sections});
  if (label === '실행 파일 제작') return reworkDiffFromChanged({executable_path: changed.executable_path});
  if (label === '인포그래픽 제작') return reworkDiffFromChanged({infographic_path: changed.infographic_path});
  return reworkDiffFromChanged(changed);
}
