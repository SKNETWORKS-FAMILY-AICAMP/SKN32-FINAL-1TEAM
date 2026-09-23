import React, {useEffect, useState} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {getProjectStatus, startPlanGeneration, startPrototypeGeneration} from '../../api.js';
import {detectItemCategory} from './utils.js';

// match_results.stage 순서(back/app/pipeline_stages.py).
const STAGES = ['plan_writing', 'plan_review_pending', 'prototype_building', 'artifact_review', 'final_review_pending', 'reviewing', 'done'];
const KINDS = {
  plan: {start: startPlanGeneration, running: 'plan_writing', doneFrom: 1},
  artifact: {start: startPrototypeGeneration, running: 'prototype_building', doneFrom: 3},
};
const POLL_MS = 1500;

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

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let failures = 0;
    setError('');
    const apply = (status) => {
      if (cancelled) return;
      failures = 0;
      setError('');
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
        setError(err.message || '진행 상황을 불러오지 못했어요. 다시 시도해 주세요.');
      }
    };
    const poll = () => getProjectStatus(projectId).then(apply).catch(err => fail(err, poll));
    // 시작 API는 중복 호출해도 이미 실행 중인 작업을 다시 생성하지 않는다.
    const start = () => KINDS[kind].start(projectId).then(apply).catch(err => fail(err, start));
    start();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [kind, projectId, retry]);

  const compact = kind === 'artifact' && detectItemCategory(itemInfo?.item) === 'onepage';
  return (
    <>
      <Preparation kind={kind} compact={compact} progress={progress} onComplete={onDone} onLeave={onLeave}/>
      {error && <div className="text-center">
        <p className="matched-note" role="alert">{error}</p>
        <button type="button" className="btn btn-muted small" onClick={() => setRetry(n => n + 1)}>다시 시도</button>
      </div>}
    </>
  );
}
