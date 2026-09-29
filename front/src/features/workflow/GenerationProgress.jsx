import React, {useEffect, useRef, useState} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {getProjectStatus, startPlanGeneration, startPrototypeGeneration} from '../../api.js';
import {detectItemCategory} from './utils.js';

// match_results.stage 순서(back/app/pipeline_stages.py).
const STAGES = ['plan_writing', 'plan_review_pending', 'prototype_building', 'artifact_review', 'final_review_pending', 'reviewing', 'done'];
const KINDS = {
  plan: {start: startPlanGeneration, running: 'plan_writing', doneFrom: 1},
  artifact: {start: startPrototypeGeneration, running: 'prototype_building', doneFrom: 3},
};
const POLL_MS = 1500;
// 사용자가 "다시 생성"을 눌렀는데 또 실패한 횟수가 이 값에 닿으면 버튼을 거두고 안내만 남긴다
// (서버 문제가 안 고쳐졌으면 몇 번을 눌러도 같다). 서버가 regenerate_cap/regenerate_fail_streak를
// 내려주면 그 값을 쓴다 — 백엔드_요청사항_3차.md B-2. 그 전까지는 이 화면 안에서만 센다.
const REGENERATE_CAP = 2;

function progressFor(kind, status) {
  const {running, doneFrom} = KINDS[kind];
  if (STAGES.indexOf(status?.stage) >= doneFrom) return 100;
  if (status?.stage === running) return Math.min(99, status.progress_percent ?? 0);
  return 0;
}

// 계획서·프로토타입 생성 진행 화면. 생성은 서버에서 돌고 이 화면은 진행률만 폴링하므로,
// 사용자가 나갔다 와도(onLeave) 다시 열면 그 시점 진행률부터 보인다.
export default function GenerationProgress({kind, projectId, itemInfo, onDone, onLeave}) {
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [retrying, setRetrying] = useState(false);
  // 완전 실패(서버·에이전트 문제로 결과물이 안 만들어짐). 연결 끊김 같은 폴링 오류(error)와 구분한다.
  const [failed, setFailed] = useState(null); // null | {streak, cap}
  const [resuming, setResuming] = useState(null); // 서버 자동 재개 대기 중이면 resume_count
  const localStreak = useRef(0);
  const countedRetry = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let failures = 0;
    setError('');
    const apply = (status) => {
      if (cancelled) return;
      failures = 0;
      setError('');
      setResuming(status?.match_status === 'waiting_resume' ? (status.resume_count ?? 0) : null);
      // [2026-09-23, 백엔드 전달사항 4번] 서버가 생성을 실패로 닫으면 stage가 더는 진행되지
      // 않아 진행률이 0에 멈춘 채 폴링만 끝없이 돌았다(화면엔 아무 안내도 안 떴다).
      // match_status로 실패를 먼저 가려내고, 사유(failure_reason)를 "다시 시도" 옆에 띄운다.
      if (status?.match_status === 'failed') {
        // "다시 생성"으로 시작한 시도가 또 실패했으면 한 번만 센다(폴링마다 세지 않게).
        if (retry > 0 && countedRetry.current !== retry) { countedRetry.current = retry; localStreak.current += 1; }
        setFailed({
          streak: status.regenerate_fail_streak ?? localStreak.current,
          cap: status.regenerate_cap ?? REGENERATE_CAP,
        });
        setRetrying(false);
        return; // 폴링 중단 — "다시 시도"를 누르면 effect가 다시 돌며 재개한다.
      }
      setFailed(null);
      setRetrying(false);
      const next = progressFor(kind, status);
      setProgress(next);
      if (next < 100) timer = setTimeout(poll, POLL_MS);
    };
    const fail = (err, again) => {
      if (cancelled) return;
      console.error('생성 진행 상황을 불러오지 못했어요', err);
      failures += 1;
      const transient = !err.status || err.status >= 500 || err.status === 429;
      if (transient && failures <= 3) {
        setError('연결이 잠시 끊겼어요. 진행 상황을 다시 확인하고 있어요.');
        timer = setTimeout(again, POLL_MS * failures);
      } else {
        setRetrying(false);
        setError(err.message || '진행 상황을 불러오지 못했어요. 다시 시도해 주세요.');
      }
    };
    const poll = () => getProjectStatus(projectId).then(apply).catch(err => fail(err, poll));
    // 시작 API는 중복 호출해도 이미 실행 중인 작업을 다시 생성하지 않는다.
    const start = () => KINDS[kind].start(projectId).then(apply).catch(err => fail(err, start));
    // 실패한 작업은 상태를 먼저 보여준다. 재실행 버튼을 누를 때만 시작 API를 호출한다.
    const check = () => getProjectStatus(projectId).then(status=>{
      if(cancelled)return;
      if(status.match_status==='failed' && retry===0)apply(status);
      else start();
    }).catch(err=>fail(err,check));
    check();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [kind, projectId, retry]);

  const compact = kind === 'artifact' && detectItemCategory(itemInfo?.item) === 'onepage';
  const regenerate = () => {setRetrying(true);setFailed(null);setRetry(n => n + 1)};
  if (failed) return <GenerationFailed kind={kind} streak={failed.streak} cap={failed.cap} retrying={retrying} onRegenerate={regenerate} onLeave={onLeave}/>;
  return (
    <>
      <Preparation kind={kind} compact={compact} progress={progress} onComplete={onDone} onLeave={onLeave}/>
      {resuming !== null && !error && <p className="matched-note text-center" role="status">일시적인 문제로 자동으로 다시 시도하고 있어요{resuming > 0 ? ` (${resuming}/5)` : ''}</p>}
      {error && <div className="text-center">
        <p className="matched-note" role="alert">{error}</p>
        <button type="button" className="btn btn-muted small" disabled={retrying} onClick={() => {setRetrying(true);setRetry(n => n + 1)}}>{retrying?'다시 확인하는 중…':'다시 시도'}</button>
      </div>}
    </>
  );
}

// 완전 실패(서버·에이전트 문제로 결과물이 안 만들어짐) 카드. task별 재작성(사용자 선택, 횟수
// 차감)과 다른 경우라 "재작성"이라는 말을 쓰지 않는다. 화면 검토(audit.jsx)에서도 서버 없이
// 띄워볼 수 있게 따로 뺐다.
export function GenerationFailed({kind, streak = 0, cap = REGENERATE_CAP, retrying = false, onRegenerate, onLeave}) {
  const exhausted = streak >= cap;
  const label = kind === 'plan' ? '사업계획서를' : '프로토타입을';
  return (
    <section className="preparation generation-failed" role="alert">
      <div className="preparation-heading">
        <span className="generation-failed-symbol"><Icon name="close" size={30}/></span>
        <h1>{label} 만들지 못했어요</h1>
        <span>{exhausted
          ? '서비스 쪽 문제가 계속되고 있어요. 관리자에게 알렸으니 잠시 후 다시 시도해 주세요.'
          : '서비스 쪽 문제로 생성이 중단됐어요. 입력하신 내용은 그대로 남아 있어요.'}</span>
      </div>
      <div className="generation-failed-actions">
        {!exhausted && <button type="button" className="btn" disabled={retrying} onClick={onRegenerate}>{retrying ? '다시 생성하는 중…' : '처음부터 다시 생성하기'}</button>}
        {onLeave && <button type="button" className="btn btn-muted" onClick={onLeave}>대시보드로</button>}
      </div>
      {!exhausted && <p className="generation-failed-note">이 재생성은 재작성 횟수에서 차감되지 않아요.</p>}
    </section>
  );
}
