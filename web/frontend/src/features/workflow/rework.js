// 재작성(화면 6 · 8 · 9) — 접수 → 진행 상태 확인 → 결과 조회.
// [SB-244] POST /retry-task는 접수만 하고 바로 돌아온다(ReworkAcceptedOut). 같은 화면에서 모으는 시간(잠정 2초) 안의
// 요청은 재작성 한 번(cycle_id 하나)으로 합쳐지고, 끝난 결과(전후 비교 · 실패 되돌림)는 GET /rework-result로 읽는다
// (웹연동_변경사항_웹팀전달.md 2.1 retry-task 행 · 3.7, 명세 5.3 · 6.3).
import {getReworkResult, retryTask} from '../../api.js';
import {reworkDiffFromChanged} from './utils.js';
import {DOC_REWORK_BUNDLES} from './data.js';

// 재작성이 실패하면 서버가 요청 전 결과로 되돌리고 기회를 돌려준다(E-RUN-ROLLBACK).
export const REWORK_FAILED_MESSAGE = '일시적인 문제로 다시 만들지 못해 이전 결과로 되돌렸습니다. 다시 만들 기회는 그대로 남아 있습니다.';
const POLL_MS = 2000;

// 고른 묶음(라벨 — 문제인식 · 실현가능성 · 성장전략 · 팀 구성 · 실행 파일 제작 · 인포그래픽 제작)마다 접수한다.
// 묶음마다 서버가 기회를 따로 세므로 하나로 뭉쳐 부르지 않는다. 돌려주는 값은 접수 응답 목록(같은 cycle_id).
export function requestRework(projectId, labels, taskKeyByLabel) {
  return Promise.all(labels.map((label) => retryTask(projectId, taskKeyByLabel[label], label)));
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

// 화면을 열 때 — 이 화면에서 요청한 재작성이 아직 진행 중이면 그 결과를 준다(화면을 나갔다 돌아온 경우).
// /status에 rework_screen이 생기면 그걸 쓰는 쪽으로 바꾼다(백엔드_요청사항_프론트_2026-10-06.md 1번).
export async function findRunningRework(projectId, screen) {
  try {
    const result = await getReworkResult(projectId);
    return result && result.status === '진행중' && result.screen === screen ? result : null;
  } catch (err) {
    if (err.status === 404 || err.status === 409) return null; // 재작성한 적 없음 · 결과를 볼 수 없는 실행
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
