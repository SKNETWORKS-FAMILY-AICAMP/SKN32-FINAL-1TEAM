// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState, useEffect} from 'react';
import {Icon} from '../../components/Icons.jsx';
import Preparation from '../../components/Preparation.jsx';
import {buildGeneralInfo,buildOverview,DOC_SCORE_BY_OUTCOME} from './utils.js';
import {FINAL_THRESHOLD,PLAN_AI_NOTICE,PLAN_CHART_EXAMPLE,PLAN_DOCUMENT_SECTIONS,PLAN_TABLE_EXAMPLE,PSST_OFFICIAL_HEADERS,SCORE_DISCLAIMER,WRITING_SUBTASKS} from './data.js';
import {getProjectStatus,retryTask} from '../../api.js';

// WRITING_SUBTASKS 3개는 전부 PLAN_STAGE_TASKS(data.js)에서 같은 '작성' Agent 몫이라
// 백엔드에도 별도 task_key 없이 하나(writing)로 묶여 있다 — app/schemas.py RetryTaskRequest 참고.
const TASK_KEY_BY_LABEL = { '사업계획서 본문 작성': 'writing', '그래프 생성': 'writing', '표 생성': 'writing' };

// 프로토타입 생성 중인지 확인하는 주기. 진행 중일 때만 돌고 끝나면 멈춘다.
const STATUS_POLL_MS = 2000;

// 화면 검토(audit.jsx)용 데모 타이머 버전 — 실제 흐름은 GenerationProgress가 서버 진행률을 쓴다.
export function PipelineProgress({onComplete}){return <Preparation kind="plan" onComplete={onComplete}/>;}

// 사업계획서 표준 4대 항목(PSST: Problem·Solution·Scale-up·Team) — 정부지원사업 사업계획서의
// 실제 목차 구조를 그대로 예시 본문에 쓴다. 표·그래프 예시도 같이 넣어서 "구현 Task가
// 실제로 뭘 만드는지" 목업만 보고도 감이 오게 한다.
// 내용은 시연 로그(sbrain_demo_run.json)의 실제 아이템 — "동네 헬스장 회원 관리·예약
// 서비스"(대표 김서준, 법인, steps[1].data.formInput) — 그대로다. 이전엔 점수만 이
// 시나리오에 맞추고 본문은 옛 예시(반려견 산책 대행)로 남아 있었다 — 프로젝트를 열면
// 점수·이름은 헬스장인데 계획서 내용은 완전히 다른 얘기가 나오는 불일치였다(사용자 지적).
// 각 섹션은 DOC_ITEMS_FAIL의 미달 사유를 실제로 "보여주는" 서술이 되도록 썼다 — 예:
// 문제인식은 "수치가 1건뿐"이라는 지적대로 근거 수치를 하나만("12개소") 담았다.
// 2026-09-16: 사용자가 첨부해준 실제 정부지원사업 서식(초기창업패키지 사업계획서 양식)의
// 항목 번호·영문 병기를 그대로 썼다 — 다운로드 파일(dummyDeliverables.js)뿐 아니라
// 화면에 계획서를 보여주는 곳(작성 화면/보기 모달/재작성 비교 모달) 전부 이 표기로
// 통일한다(사용자 지적: 다운로드 파일만 바꾸면 화면이랑 달라 보인다).
export function GeneralInfoBlock({ itemInfo, itemTitle, sections }) {
  const rows = buildGeneralInfo(itemInfo);
  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-2">□ 일반현황</p>
        <div className="rounded-lg border border-[var(--border)] overflow-hidden">
          {rows.map(([label, value], i) => (
            <div key={label} className={`grid grid-cols-[140px_1fr] text-[13px] ${i !== rows.length - 1 ? 'border-b border-[var(--border)]' : ''}`}>
              <div className="p-3 font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">{label}</div>
              <div className="p-3">{value}</div>
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-2">□ 창업 아이템 개요(요약)</p>
        <p className="text-[14px] leading-relaxed text-[var(--fg)]">{buildOverview(itemTitle, sections)}</p>
      </div>
    </div>
  );
}

export function PlanExtrasBlock({ size = 'full' }){
  const compact = size === 'compact';
  const headingClass = compact ? 'font-display font-bold text-[15px] mb-2' : 'font-display font-bold text-[17px] mb-3';
  const cellClass = compact ? 'p-2.5 text-[12.5px]' : 'p-3 text-[13.5px]';
  return (
    <React.Fragment>
      <div>
        <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［표］</p>
        <h2 className={headingClass}>05. {PLAN_TABLE_EXAMPLE.title}</h2>
        <div className="rounded-lg border border-[var(--border)] overflow-hidden">
          <div className="grid grid-cols-2 text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
            {PLAN_TABLE_EXAMPLE.columns.map((c) => <div key={c} className={compact ? 'p-2.5' : 'p-3'}>{c}</div>)}
          </div>
          {PLAN_TABLE_EXAMPLE.rows.map((row, i) => (
            <div key={i} className={`grid grid-cols-2 ${i !== PLAN_TABLE_EXAMPLE.rows.length - 1 ? 'border-b border-[var(--border)]' : ''}`}>
              {row.map((cell, j) => <div key={j} className={cellClass}>{cell}</div>)}
            </div>
          ))}
        </div>
      </div>

      <div>
        <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［그래프］</p>
        <h2 className={headingClass}>06. {PLAN_CHART_EXAMPLE.title}</h2>
        {/* 막대 높이(%)를 라벨까지 포함한 열의 높이(h-full) 기준으로 계산하면, 값이 100%인
            막대가 라벨 자리까지 침범해 잘려 보인다(사용자 지적). 막대 영역(h-24, 고정)과
            라벨 줄을 아예 분리해서 막대의 %가 항상 막대 영역 자기 자신만을 기준으로
            계산되게 하고, 위쪽에 pt-3만큼 여백을 둬 최댓값 막대도 천장에 닿지 않게 한다.
            또 막대 자체가 아니라 그 막대를 담는 열에 max-width를 줬더니 세 열이 카드
            왼쪽에 몰리고 오른쪽에 빈 여백만 남았다(사용자 지적: "좌우 간격이 안맞아").
            열은 폭 제한 없이 flex-1로 표(05)처럼 전체 너비를 고르게 나눠 갖게 하고,
            그 안에서 막대만 최대 52px로 가운데 정렬한다. */}
        <div className="pt-3 px-2">
          <div className="flex items-end gap-6 h-24">
            {PLAN_CHART_EXAMPLE.bars.map((b) => (
              <div key={b.label} className="flex-1 h-full flex items-end justify-center">
                <div className="w-full max-w-[52px] rounded-t-md" style={{ height: `${b.value}%`, backgroundColor: '#90bfff' }}></div>
              </div>
            ))}
          </div>
          <div className="flex gap-6 mt-2">
            {PLAN_CHART_EXAMPLE.bars.map((b) => (
              <span key={b.label} className="flex-1 text-center text-[11.5px] text-[var(--muted-fg)]">{b.label}</span>
            ))}
          </div>
        </div>
      </div>
    </React.Fragment>
  );
}

// 기획서 4-5: 문서층 70 + 산출물층 30 = 100점 단일 총점 구조. 문서 평가(문서 작성
// 직후, 프로토타입 아직 없음) 시점엔 문서층 원점수만 100점 만점으로 환산해 보여주고,
// 종합 평가(프로토타입까지 나온 뒤) 시점엔 두 층 원점수를 그대로 더해 100점 총점을
// 보여준다 — 두 화면 숫자가 서로 다른 채점이라는 걸 이름(문서 평가/종합 평가)으로
// 구분한다. 내부 기준는 두 시점 모두 80점.
// 대시보드 예시 프로젝트마다 상태 라벨이 다르므로("검증 미달" vs "제출 완료") 점수도
// pass/fail 두 갈래로 둔다 — fail이 기본값(새로 시작하는 플로우는 항상 미달 예시를
// 보여줘 재작성 UI가 실제로 보이게 한다), 대시보드에서 "제출 완료"로 표시된 프로젝트를
// 열 때만 pass로 전환한다(App의 scoreOutcome state, MY_PROJECTS의 scoreOutcome 필드).
// 목업 수정 요청서 v3 §12: 문서층 점수를 시연 로그(sbrain_demo_run.json)의 실제
// 루브릭 값으로 정렬한다. steps[5](문서 평가 1차, 52/70)·steps[7](재작성 후 2차,
// 60/70)의 RB-PSST-2026 루브릭 4항목(EV-01~04)을 그대로 옮겼다 — reasons는 이
// items에서 만점 미달 항목만 뽑아 만든다(하드코딩된 문구 2줄이던 이전 값보다
// 항목별 근거가 분명하다).
export function PlanForm({ announcement, onGenerate, scoreOutcome = 'fail', itemInfo, projectId }){
  const docScore = DOC_SCORE_BY_OUTCOME[scoreOutcome];
  const docScoreScaled = Math.round((docScore.raw / docScore.max) * 100);
  const passed = docScoreScaled >= FINAL_THRESHOLD;
  const [confirmProceed, setConfirmProceed] = useState(false);
  const [checkedTasks, setCheckedTasks] = useState([]);
  const [runningTasks, setRunningTasks] = useState([]);
  // 재작성 스피너가 끝나도 "완료됐다"는 표시가 전혀 없어 사용자가 헷갈린다는
  // 지적에 따라, 방금 재작성한 항목을 완료 표시로 남겨둔다 — 같은 항목을 다시
  // 체크해 재작성을 걸면(toggleTask) 그 항목의 완료 표시는 지운다.
  const [completedTasks, setCompletedTasks] = useState([]);
  // 레퍼런스(makedeck)의 좌측 히스토리 사이드바처럼, 문서 평가 패널을 접었다 펼 수 있게 —
  // 기본은 펼친 상태(사용자 지적: 처음엔 점수가 바로 보여야 함).
  const [scoreOpen, setScoreOpen] = useState(true);

  // 프로토타입 생성이 서버에서 도는 동안(stage='prototype_building') 알림을 통해 이 화면으로
  // 되돌아올 수 있다 — 계획서는 이미 끝난 상태라 알림이 "완료"로 뜨고 plan-form으로 보낸다
  // (shared.jsx progressAlertsFrom). 그런데 생성 버튼이 그대로 눌리는 상태로 남아 있어서
  // 아직 시작 전인 것처럼 보였다(사용자 지적). 서버는 중복 요청을 무시하지만
  // (app/routers/projects.py _start_generation) 화면만으로는 구분이 안 되므로,
  // 진행 중인 동안 버튼을 잠그고 라벨로 상태를 알린다.
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    let timer = null;
    const poll = () => getProjectStatus(projectId).then((status) => {
      if (cancelled) return;
      const running = status?.stage === 'prototype_building' && status?.match_status !== 'failed';
      setGenerating(running);
      // 이미 생성이 돌고 있으면 점수 미달 확인창은 의미가 없다.
      if (running) setConfirmProceed(false);
      // 진행 중일 때만 이어서 확인한다 — 끝나면 폴링을 멈추고 버튼이 다시 풀린다.
      if (running) timer = setTimeout(poll, STATUS_POLL_MS);
    }).catch((err) => {
      // 상태를 못 읽었다고 버튼까지 막지는 않는다.
      if (cancelled) return;
      console.error('생성 상태를 확인하지 못했어요', err);
      timer = setTimeout(poll, STATUS_POLL_MS);
    });
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [projectId]);

  const handleGenerateClick = () => {
    if (generating || runningTasks.length > 0) return;
    if (!passed) { setConfirmProceed(true); return; }
    onGenerate();
  };

  const toggleTask = (label) => {
    setCheckedTasks((prev) => (prev.includes(label) ? prev.filter((t) => t !== label) : [...prev, label]));
    setCompletedTasks((prev) => prev.filter((t) => t !== label));
  };

  // POST /projects/{id}/retry-task를 실제로 호출한다(app/routers/projects.py retry_task) —
  // 예전엔 setTimeout으로 스피너만 흉내 내고 서버 호출이 없어 DB에 아무 변화도 안 남았다.
  // 체크한 라벨이 전부 같은 task_key('writing')로 묶이므로 중복 없이 한 번만 호출한다.
  const handleRewrite = async () => {
    // 프로토타입이 이 계획서로 만들어지는 중이라 지금 본문을 다시 쓰면 둘이 어긋난다.
    if (generating || runningTasks.length > 0) return;
    if (checkedTasks.length === 0) return;
    const picked = checkedTasks;
    setRunningTasks(picked);
    setCheckedTasks([]);
    const taskKeys = [...new Set(picked.map((label) => TASK_KEY_BY_LABEL[label]).filter(Boolean))];
    try {
      if (projectId) await Promise.all(taskKeys.map((key) => retryTask(projectId, key)));
      setCompletedTasks((prev) => [...new Set([...prev, ...picked])]);
    } catch (err) {
      console.error('재작성 요청이 실패했어요', err);
      window.alert(err.message || '재작성에 실패했어요. 다시 시도해 주세요.');
      setCheckedTasks(picked);
    } finally {
      setRunningTasks([]);
    }
  };

  return (
    <React.Fragment>
    <section data-screen="plan" className="max-w-6xl mx-auto px-6 py-12">
      <div className={`grid gap-6 items-start transition-[grid-template-columns] duration-200 ${scoreOpen ? 'md:grid-cols-[290px_1fr]' : 'md:grid-cols-[auto_1fr]'}`}>
        {/* 좌측 — 문서 평가: 문서층 70점을 100점 만점으로 환산해 표시 (기획서 4-5).
            우측 본문과 한 박스로 묶으면(카드 하나 공유) 내용이 짧은 이쪽이 긴 본문
            높이에 맞춰 억지로 늘어나면서 빈 여백만 커진다(사용자 지적) — 그래서 서로
            독립된 카드로 분리하고, 내용 길이만큼만 높이를 차지하게 한다. 접으면 얇은
            칸으로 줄고 우측 본문이 그만큼 넓어진다. 기본은 펼친 상태. */}
        {!scoreOpen && (
          <button type="button" onClick={() => setScoreOpen(true)} aria-label="문서 평가 펼치기"
            className="hidden md:flex flex-col items-center gap-3 w-11 py-5 md:sticky md:top-24 text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors">
            <Icon name="chevron" size={13} />
            <span className={`font-display font-bold text-[14px] leading-none ${passed ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}`}>{docScoreScaled}</span>
          </button>
        )}
        {scoreOpen && (
        <aside className="relative md:sticky md:top-24">
          <button type="button" onClick={() => setScoreOpen(false)} aria-label="문서 평가 접기"
            className="hidden md:grid absolute -right-3.5 top-6 w-7 h-7 place-items-center rounded-full border border-[var(--border)] bg-white shadow-[0_2px_8px_-1px_rgba(15,23,42,.15)] hover:bg-[var(--muted)] transition-colors z-10">
            <Icon name="chevron" size={12} className="rotate-180 text-[var(--muted-fg)]" />
          </button>
          <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">문서 평가</p>
          <p className="text-[11.5px] text-[var(--muted-fg)] mb-5">문서층 70점을 100점 만점으로 환산, {FINAL_THRESHOLD}점부터 통과</p>

          <div className="flex items-end gap-1.5 mb-2">
            <p className={`font-display font-bold text-[44px] leading-none ${passed ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}`}>{docScoreScaled}</p>
            <p className="text-[14px] text-[var(--muted-fg)] mb-1">/ 100점</p>
          </div>
          <div className="h-1.5 rounded-full bg-[var(--muted)] overflow-hidden mb-3">
            <div className={`h-full rounded-full ${passed ? 'bg-[var(--ok)]' : 'bg-[var(--danger)]'}`} style={{ width: `${docScoreScaled}%` }} />
          </div>
          <p className={`text-[12.5px] font-bold mb-1 ${passed ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}`}>
            {passed ? `［내부 기준 ${FINAL_THRESHOLD}점 통과］` : `［내부 기준 ${FINAL_THRESHOLD}점 미달］`}
          </p>
          <p className="text-[11px] text-[var(--muted-fg)] leading-relaxed">{SCORE_DISCLAIMER}</p>

          {!passed && (
            <div className="mt-4 rounded-xl bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-4">
              <p className="text-[12.5px] font-bold text-[var(--danger)] mb-2">점수 미달 사유</p>
              <ul className="flex flex-col gap-1.5">
                {docScore.reasons.map((r) => (
                  <li key={r} className="text-[12.5px] text-[var(--fg)] leading-relaxed">· {r}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-5 rounded-xl border border-[var(--border)] p-4">
            <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-3">다시 준비할 항목</p>
            <div className="flex flex-col gap-2">
              {WRITING_SUBTASKS.map((label) => {
                const isRunning = runningTasks.includes(label);
                const isDone = !isRunning && completedTasks.includes(label);
                return (
                  <label key={label} className={`flex items-center gap-2.5 text-[13px] ${isRunning || generating ? 'text-[var(--muted-fg)]' : 'text-[var(--fg)] cursor-pointer'}`}>
                    {isRunning ? (
                      <span className="rewrite-indicator" aria-hidden="true"></span>
                    ) : (
                      <input type="checkbox" checked={checkedTasks.includes(label)} onChange={() => toggleTask(label)}
                        disabled={generating}
                        className="w-4 h-4 accent-[var(--primary)] disabled:cursor-not-allowed" />
                    )}
                    <span>
                      {isRunning ? `${label} 재작성 중…` : label}
                      {isDone && <span className="ml-1.5 text-[11.5px] font-semibold text-[var(--ok)]">✓ 재작성 완료</span>}
                    </span>
                  </label>
                );
              })}
            </div>
            <button onClick={handleRewrite} disabled={generating || checkedTasks.length === 0 || runningTasks.length > 0}
              className="w-full mt-3 rounded-lg border border-[var(--border)] py-2.5 text-[13.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              선택 항목 재작성
            </button>
            {generating && (
              <p className="mt-2 text-[11.5px] text-[var(--muted-fg)] leading-relaxed">
                프로토타입을 만드는 중에는 계획서를 다시 쓸 수 없어요. 생성이 끝나면 다시 열려요.
              </p>
            )}
          </div>

          <div className="flex flex-col gap-2 mt-4">
            <button onClick={handleGenerateClick} disabled={generating || runningTasks.length > 0}
              className="w-full rounded-xl bg-[var(--primary)] text-white py-3 text-[14.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              {generating ? '프로토타입 생성 중…' : '프로토타입 생성'}
            </button>
            {generating && (
              <p className="text-[11.5px] text-[var(--muted-fg)] leading-relaxed">
                프로토타입을 만들고 있어요. 진행 상황은 알림에서 확인할 수 있어요.
              </p>
            )}
          </div>

          {confirmProceed && (
            <div className="mt-4 rounded-xl border border-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-4">
              <p className="text-[13px] font-semibold text-[var(--danger)] mb-3">점수 미달입니다 — 그래도 진행하시겠습니까</p>
              <div className="flex items-center gap-4">
                <button onClick={() => setConfirmProceed(false)}
                  className="text-[13px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-[color,scale] duration-150 ease-out active:scale-[0.96]">
                  취소
                </button>
                <button disabled={generating || runningTasks.length > 0} onClick={()=>{if(!generating && runningTasks.length===0)onGenerate()}} className="text-[13px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
                  그래도 진행하기
                </button>
              </div>
            </div>
          )}
        </aside>
        )}

        {/* 우측 — 작성된 사업계획서 미리보기 */}
        <div className="rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
          <div className="border-b border-[var(--border)] px-9 py-6 flex items-start justify-between gap-4 flex-wrap">
            <div>
              {/* 공고 제목을 제목 문장 안에 끼워 넣으면(『긴 공고명』 사업계획서) 제목이 길 때
                  줄이 어중간하게 끊기고 뒤 단어만 남아 어색해진다(사용자 지적). 공고명은
                  윗줄에 따로 두고, 제목은 길이가 고정된 짧은 문장만 남긴다. */}
              <p className="text-[13px] font-semibold text-[var(--primary-dim)] leading-snug mb-1.5">『{announcement ? announcement.title : ''}』</p>
              <h1 className="font-display font-bold text-[23px] mb-1.5">사업계획서</h1>
              <p className="text-[12px] text-[var(--muted-fg)]">{PLAN_AI_NOTICE}</p>
            </div>
          </div>

          <div className="px-9 py-8 flex flex-col gap-7">
            <GeneralInfoBlock itemInfo={itemInfo} itemTitle={announcement ? announcement.title : ''} sections={PLAN_DOCUMENT_SECTIONS} />

            {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
              <div key={s.title}>
                <h2 className="font-display font-bold text-[17px] mb-2">{PSST_OFFICIAL_HEADERS[i]}</h2>
                <p className="text-[14px] leading-relaxed text-[var(--fg)]">{s.body}</p>
              </div>
            ))}

            <PlanExtrasBlock />
          </div>
        </div>
      </div>
    </section>
    </React.Fragment>
  );
}

// PRJ-ID-008/구현 Agent 스펙: 카테고리(원페이지/웹개발/AI API)는 내부 판정값이라
// 사용자에게 선택 UI로 노출하지 않는다 — 아이템 설명 텍스트에서 휴리스틱으로
// 추정한다(실제로는 조율 Agent가 판정). 원페이지는 실행 파일 Task 자체가 생략되므로
// "빈 슬롯"을 보여주는 대신 그 카드를 아예 렌더링하지 않는다 — 없는 걸 없다고
// 티내면 카테고리 로직이 사용자에게 역으로 드러난다.
