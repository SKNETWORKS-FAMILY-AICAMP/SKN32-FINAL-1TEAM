import React, {useEffect, useState} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {getProjectStatus, startPlanGeneration, startPrototypeGeneration} from '../../api.js';
import {detectItemCategory} from './utils.js';
import {formatKstClock} from '../../time.js';

// match_results.stage 순서(back/app/pipeline_stages.py).
const STAGES = ['plan_writing', 'plan_review_pending', 'prototype_building', 'artifact_review', 'final_review_pending', 'reviewing', 'done'];
// review: 표현 검수(화면 9 → 10). 시작은 종합 평가 화면이 review/start로 하고, 이 화면은 검수 중에 이어하기로
// 돌아왔을 때 진행만 보여 준다(시작 API 없음).
const KINDS = {
  plan: {start: startPlanGeneration, running: 'plan_writing', doneFrom: 1},
  artifact: {start: startPrototypeGeneration, running: 'prototype_building', doneFrom: 3},
  review: {start: null, running: 'reviewing', doneFrom: 6},
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
  const [retrying, setRetrying] = useState(false);
  // 완전 실패(서버·에이전트 문제로 결과물이 안 만들어짐). 연결 끊김 같은 폴링 오류(error)와 구분한다.
  const [failed, setFailed] = useState(false);
  const [resuming, setResuming] = useState(null); // 서버 자동 재개 대기 중이면 {count, at(다음 시도 시각)}

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    let failures = 0;
    setError('');
    const apply = (status) => {
      if (cancelled) return;
      failures = 0;
      setError('');
      setResuming(status?.match_status === 'waiting_resume' ? {count: status.resume_count ?? 0, at: status.next_retry_at} : null);
      // [2026-09-23, 백엔드 전달사항 4번] 서버가 생성을 실패로 닫으면 stage가 더는 진행되지
      // 않아 진행률이 0에 멈춘 채 폴링만 끝없이 돌았다(화면엔 아무 안내도 안 떴다).
      // match_status로 실패를 먼저 가려낸다. 실패한 작업은 다시 시작하지 않는다 — 새 작업으로
      // 시작하라는 안내만 띄운다(웹연동_변경사항_웹팀전달.md 3.2 · 5절, E-RUN-FAIL).
      if (status?.match_status === 'failed') {
        setFailed(true);
        setRetrying(false);
        return; // 폴링 중단
      }
      setFailed(false);
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
    // 실패한 작업은 상태만 보여 주고 시작 API를 부르지 않는다.
    const check = () => getProjectStatus(projectId).then(status=>{
      if(cancelled)return;
      if(status.match_status==='failed'||!KINDS[kind].start)apply(status);
      else start();
    }).catch(err=>fail(err,check));
    check();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [kind, projectId, retry]);

  const compact = kind === 'artifact' && detectItemCategory(itemInfo?.item) === 'onepage';
  if (failed) return <GenerationFailed onLeave={onLeave}/>;
  return (
    <>
      <Preparation kind={kind} compact={compact} progress={progress} onComplete={onDone} onLeave={onLeave}/>
      {resuming !== null && !error && <p className="matched-note text-center" role="status">
        {/* 재개 대기 — 서버가 다음 시도 시각(next_retry_at, UTC)을 준다. 한국 시간으로 보여 준다. */}
        일시적인 문제로 잠시 멈췄어요. {formatKstClock(resuming.at) ? `${formatKstClock(resuming.at)}에 ` : ''}자동으로 다시 시도해요{resuming.count > 0 ? ` (${resuming.count}/5)` : ''}
      </p>}
      {error && <div className="text-center">
        <p className="matched-note" role="alert">{error}</p>
        <button type="button" className="btn btn-muted small" disabled={retrying} onClick={() => {setRetrying(true);setRetry(n => n + 1)}}>{retrying?'다시 확인하는 중…':'다시 시도'}</button>
      </div>}
    </>
  );
}

// 완전 실패(서버·에이전트 문제로 결과물이 안 만들어짐) 카드. task별 재작성(사용자 선택, 횟수
// 차감)과 다른 경우라 "재작성"이라는 말을 쓰지 않는다. 실패한 실행 건은 다시 시작할 수 없어서
// "처음부터 다시 생성"은 없앴다 — 안내 문구는 E-RUN-FAIL 그대로. 화면 검토(audit.jsx)에서도
// 서버 없이 띄워볼 수 있게 따로 뺐다.
export function GenerationFailed({onLeave}) {
  return (
    <section className="preparation generation-failed" role="alert">
      <div className="preparation-heading">
        <span className="generation-failed-symbol"><Icon name="close" size={30}/></span>
        {/* 어느 단계에서 멈췄든 같은 안내다(E-RUN-FAIL) — 예전엔 계획서 · 프로토타입 두 문구라 검수 중 실패도 '프로토타입'으로 보였다. */}
        <h1>작업을 완료하지 못했어요</h1>
        <span>일시적인 문제로 작업을 완료하지 못했습니다. 새 작업으로 다시 시작해주세요.</span>
      </div>
      <div className="generation-failed-actions">
        {onLeave && <button type="button" className="btn" onClick={onLeave}>대시보드로</button>}
      </div>
    </section>
  );
}
