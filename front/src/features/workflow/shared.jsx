// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef,useEffect} from 'react';
import {listProjects} from '../../api.js';

export function FloatingInput({inputRef,type,value,onChange,label}){
  return <label className="block text-[14px] text-[var(--muted-fg)]"><span className="block mb-2">{label}</span><input ref={inputRef} type={type} value={value} onChange={onChange} onInput={onChange} onBlur={onChange} className="w-full border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--fg)]"/></label>;
}
// 2026-09-16: 팀원이 실제로 만든 예시 산출물(gym-ai-landing-page.html, "짐세일즈 AI")을
// 실제 구현 에이전트가 붙기 전까지의 자리표시자로 쓴다 — 스크린샷 대신 그 파일의
// 실제 HTML(front/public/prototype-preview.html, 디자인 툴 내보내기 껍데기는 벗겨내고
// 안에 있던 순수 HTML만 추출함)을 iframe으로 띄운다. 나중에 구현 에이전트가 프로젝트별
// 실제 프로토타입 파일을 만들게 되면, 이 고정 경로 대신 백엔드가 내려주는 그 프로젝트의
// 결과물 URL을 iframe src에 넣기만 하면 된다 — 화면 쪽 구조는 이미 iframe이라 그대로 둔다.
// sandbox="allow-scripts"만 주고 allow-same-origin은 빼서, 안에서 도는 스크립트가 부모
// 페이지(로그인 세션 등)에 접근하지 못하게 격리한다.
// 카드 안 작은 미리보기 — 브라우저 카드 모양(테두리·상단 라벨바)으로 클릭이 안
// 먹게 막아두고 위쪽 일부만 잘라 보여준다. "미리보기" 팝업(ResultPreview)은 이
// 컴포넌트를 쓰지 않고 라이트박스로 직접 iframe을 띄운다(카드 없이 화면만 보여야
// 한다는 지적 — 이 컴포넌트의 카드 모양 자체가 그 "박스"였다).
export function SiteMock(){
  return (
    <div className="absolute inset-0 flex items-center justify-center p-5">
      <div className="w-full max-w-[420px] overflow-hidden rounded-xl border border-[var(--border)] bg-white shadow-lg">
        <div className="border-b border-[var(--border)] px-4 py-2 text-[12px] text-[var(--muted-fg)]">프로토타입 화면 예시</div>
        <div className="relative w-full overflow-hidden" style={{ height: 260 }}>
          <iframe src="/prototype-preview.html" title="프로토타입 화면 예시" sandbox="allow-scripts" tabIndex={-1}
            style={{ width: 1440, height: 900, border: 'none', transform: 'scale(0.29)', transformOrigin: 'top left', pointerEvents: 'none' }}/>
        </div>
      </div>
    </div>
  );
}
export function BackButton({ onClick, label = '이전 단계로 돌아가기' }){
  return (
    <button type="button" onClick={onClick}
      className="mb-6 inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-[var(--muted-fg)] hover:text-[var(--primary)] transition-[color,scale] duration-150 ease-out active:scale-[0.96]">
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M15 18l-6-6 6-6"/>
      </svg>
      {label}
    </button>
  );
}

// match_results.stage(back/app/pipeline_stages.py) 순서. 계획서는 plan_writing 이후면 완료,
// 프로토타입은 prototype_building 이후면 완료로 본다.
const STAGE_ORDER = ['plan_writing','plan_review_pending','prototype_building','artifact_review','final_review_pending','reviewing','done'];
const PROGRESS_POLL_MS = 5000;
const SEEN_KEY = 'sbrain-seen-progress-alerts';

function readSeen(){try{return new Set(JSON.parse(localStorage.getItem(SEEN_KEY)||'[]'))}catch(e){return new Set()}}
function writeSeen(set){try{localStorage.setItem(SEEN_KEY,JSON.stringify([...set]))}catch(e){}}

export function progressAlertsFrom(projects){
  const alerts = [];
  for (const p of projects) {
    const i = STAGE_ORDER.indexOf(p.stage);
    if (i < 0) continue;
    const name = p.description || '내 프로젝트';
    const project = { id: p.project_id, matched: true, announcementTitle: p.notice_title };
    const planDone = i > 0;
    alerts.push({ key: `${p.project_id}:plan`, project, projectName: name, kind: '사업계획서', done: planDone,
      percent: planDone ? 100 : p.progress_percent, view: planDone ? 'plan-form' : 'plan-progress' });
    if (i >= 2) {
      const protoDone = i > 2;
      alerts.push({ key: `${p.project_id}:prototype`, project, projectName: name, kind: '프로토타입', done: protoDone,
        percent: protoDone ? 100 : p.progress_percent, view: protoDone ? 'artifact-result' : 'artifact-progress' });
    }
  }
  // 진행 중인 것을 위로
  return alerts.sort((a, b) => Number(a.done) - Number(b.done));
}

// refreshKey(현재 화면)가 바뀔 때마다 다시 불러온다 — 생성을 막 시작한 뒤에도 진행 중
// 항목을 바로 잡아 폴링을 이어가기 위해서다. 이 세션에서 진행 중이던 게 끝나면 토스트를 띄운다.
export function NotificationBell({ enabled, onToggle, onOpenProject, refreshKey }){
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState([]);
  const [seen, setSeen] = useState(readSeen);
  const [toast, setToast] = useState(null);
  const runningKeys = useRef(new Set());

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer = null;
    const load = () => listProjects().then((rows) => {
      if (cancelled) return;
      const next = progressAlertsFrom(rows);
      const finished = next.find((a) => a.done && runningKeys.current.has(a.key));
      if (finished) setToast(finished);
      runningKeys.current = new Set(next.filter((a) => !a.done).map((a) => a.key));
      setAlerts(next);
      if (next.some((a) => !a.done)) timer = setTimeout(load, PROGRESS_POLL_MS);
    }).catch((err) => console.error('진행 알림을 불러오지 못했어요', err));
    load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [enabled, refreshKey]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 8000);
    return () => clearTimeout(t);
  }, [toast]);

  const openAlert = (a) => {
    setOpen(false);
    setToast(null);
    onOpenProject?.(a.project, a.view);
  };

  const activeAlerts = enabled ? alerts : [];
  const hasUnread = activeAlerts.some((a) => a.done && !seen.has(a.key));

  const toggleOpen = () => {
    setOpen((v) => {
      if (!v) {
        const next = new Set(seen);
        activeAlerts.filter((a) => a.done).forEach((a) => next.add(a.key));
        writeSeen(next);
        setSeen(next);
      }
      return !v;
    });
  };

  return (
    <div className="relative">
      <button onClick={toggleOpen} aria-label="알림"
        className="relative w-9 h-9 rounded-full flex items-center justify-center text-[var(--muted-fg)] hover:bg-[var(--muted)] hover:text-[var(--fg)] transition-[background-color,color] duration-150 ease-out">
        <svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        {hasUnread && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[var(--primary)]"></span>
        )}
      </button>

      {open && (
        <React.Fragment>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)}></div>
          <div className="absolute right-0 top-11 w-[340px] max-w-[calc(100vw-32px)] rounded-2xl border border-[var(--border)] bg-white shadow-[0_20px_48px_-16px_rgba(20,23,31,.25)] z-50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3.5 border-b border-[var(--border)]">
              <p className="text-[13.5px] font-bold">제작 진행 알림</p>
              <button type="button" role="switch" aria-checked={enabled} aria-label="제작 진행 알림" className="flex items-center gap-2 cursor-pointer select-none" onClick={onToggle}>
                <span className="text-[11.5px] text-[var(--muted-fg)]">{enabled ? '켜짐' : '꺼짐'}</span>
                <span className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-150 ease-out" style={{ backgroundColor: enabled ? 'var(--primary)' : '#d1d6db' }}>
                  <span className="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform duration-150 ease-out" style={{ transform: enabled ? 'translateX(18px)' : 'translateX(3px)' }}></span>
                </span>
              </button>
            </div>

            {!enabled ? (
              <p className="px-4 py-6 text-[12.5px] text-[var(--muted-fg)] text-center">알림이 꺼져 있어요 — 켜면 사업계획서·프로토타입 제작 상황을 알려드려요</p>
            ) : activeAlerts.length === 0 ? (
              <p className="px-4 py-6 text-[12.5px] text-[var(--muted-fg)] text-center">아직 제작 중인 사업계획서·프로토타입이 없어요</p>
            ) : (
              <div className="soft-scroll max-h-72 overflow-y-auto divide-y divide-[var(--border)]">
                {activeAlerts.map((a) => (
                  <button type="button" key={a.key} onClick={() => openAlert(a)} className="block w-full text-left px-4 py-3.5 hover:bg-[#f9fafb] transition-colors">
                    <p className="text-[11.5px] text-[var(--muted-fg)] mb-1 truncate">『{a.projectName}』</p>
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[13px] font-semibold">{a.kind} {a.done ? '제작이 끝났어요' : '만드는 중이에요'}</p>
                      <span className={'text-[11.5px] font-semibold flex-shrink-0 ' + (a.done ? 'text-[var(--ok)]' : 'text-[var(--primary)]')}>
                        {a.done ? '완료' : a.percent != null ? `진행 중 ${a.percent}%` : '진행 중'}
                      </span>
                    </div>
                    {!a.done && a.percent != null && (
                      <div className="mt-2 h-1 rounded-full bg-[var(--muted)] overflow-hidden">
                        <div className="h-full rounded-full bg-[var(--primary)]" style={{ width: `${a.percent}%` }} />
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}

            <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border)] opacity-45">
              <span className="text-[12px] text-[var(--muted-fg)]">이메일로도 받기</span>
              <span className="text-[11px] text-[var(--muted-fg)]">최종발표 이후 지원 예정</span>
            </div>
          </div>
        </React.Fragment>
      )}
      {toast && (
        <div role="status" className="progress-toast">
          <p><b>{toast.kind === '프로토타입' ? '프로토타입이' : '사업계획서가'}</b> 완성됐어요 <span>『{toast.projectName}』</span></p>
          <button type="button" onClick={() => openAlert(toast)}>보러 가기</button>
          <button type="button" aria-label="닫기" className="progress-toast-close" onClick={() => setToast(null)}>✕</button>
        </div>
      )}
    </div>
  );
}

// 클릭하면 OS 네이티브 파일 탐색창이 뜨는 첨부 위젯 — 실제 <input type="file">을
// 숨겨두고 버튼으로 그 클릭을 대신 트리거한다.
export function FileAttach({ files, onAdd, onRemove }){
  const inputRef = useRef(null);
  return (
    <div className="mt-4">
      <input ref={inputRef} type="file" multiple className="hidden"
        onChange={(e) => { onAdd(Array.from(e.target.files)); e.target.value = ''; }} />
      <button type="button" onClick={() => inputRef.current.click()}
        className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-white px-3.5 py-2 text-[13px] font-semibold text-[var(--muted-fg)] hover:border-[var(--muted-fg)] hover:text-[var(--fg)] transition-[border-color,color,scale] duration-150 ease-out active:scale-[0.96]">
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.49-8.48"/>
        </svg>
        파일 첨부
      </button>

      {files.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between gap-3 rounded-lg bg-[var(--muted)] px-3.5 py-2 text-[13px]">
              <span className="truncate">{f.name}</span>
              <button type="button" onClick={() => onRemove(i)} aria-label={`${f.name} 삭제`}
                className="flex-shrink-0 text-[var(--muted-fg)] hover:text-[var(--danger)] transition-[color,scale] duration-150 ease-out active:scale-[0.9]">
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                  <path d="M6 6l12 12M18 6L6 18"/>
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11.5px] text-[var(--muted-fg)]">사업자등록증·포트폴리오 등 참고자료를 첨부하면 계획서 작성 시 참고합니다 — 선택사항입니다</p>
    </div>
  );
}

// 기획서 4-1/4-2①: 입력은 대화가 아니라 폼으로, 그것도 한 화면에서 한 번에 받는다 —
// 자격 판정·계획서 작성에 필요한 항목(신청자 유형·대표자·설립일자·팀·단가·아이디어)을
// 처음에 모두 모아두면 신청 자격 확인 이후로는 사용자에게 되묻지 않고 끝까지
// 진행할 수 있다. 예비창업자는 대표자·설립일자가 아예 해당 없으므로 그 값들을
// 비워둔 채(=업력 계산상 예비창업자로 판정) 다음 단계로 넘긴다.
// 가산점은 공고마다 붙는 점수라 만점 기준이 없다 — 비율 게이지 대신 점수만 크게 보여준다.
export function formatBonus(value){return `+${Number(value)}`;}
export function BonusScore({value}){
  return (
    <div className="bonus-score" role="img" aria-label={`가산점 ${Number(value)}점`}>
      <b>{formatBonus(value)}</b><span>점</span>
    </div>
  );
}

// [2026-09-15, 프론트 통합 임시 구현] 예전엔 클라이언트에서 evaluateEligibility(공고 조건 3개를
// 입력값과 비교하는 순수 함수)를 직접 돌렸는데, 이제 MatchResults가 이미 호출해둔
// POST /generate 응답의 eligibility(EligibilityCheckOut: passed/undecidable/failed_conditions/
// missing_inputs — app/schemas.py)를 그대로 받아 보여준다. 더미 백엔드(seed_dummy_pipeline.py)는
// 지금 항상 passed=True를 돌려주므로 실패/미결정 분기는 실제 오케스트레이터가 붙은 뒤에야
// 흔히 보이게 될 것이다.
export function RepeatableRow({ values, fields, onChange, onRemove, removable }){
  return (
    <div className="repeatable-row" style={{'--fields':fields.length}}>
      {fields.map((f) => (
        <label key={f.key} className="block">
          <span className="block text-[11.5px] font-semibold text-[var(--muted-fg)] mb-1">{f.label}</span>
          <input value={values[f.key] || ''} onChange={(e) => onChange(f.key, e.target.value)} placeholder={f.placeholder}
            className="w-full border border-[var(--border)] rounded-lg px-3 py-2 text-[14px] focus:border-[var(--primary)] focus:border-2 outline-none transition-colors" />
        </label>
      ))}
      <button type="button" onClick={onRemove} disabled={!removable} aria-label="행 삭제"
        className="justify-self-end sm:justify-self-auto sm:mt-6 text-[var(--muted-fg)] hover:text-[var(--danger)] disabled:opacity-30 disabled:cursor-not-allowed transition-[color,scale] duration-150 ease-out active:scale-[0.9]">
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18"/>
        </svg>
      </button>
    </div>
  );
}

// PRJ-ID-008: Task는 고정 목록, 조율 Agent가 실행할 Agent를 고르고 각 Task 지시문을
// 실행 시점에 작성한다 — 여기 보이는 문구는 그 지시문을 미리 보여주는 자리다.
// 목업 수정 요청서 v3 §7: PipelineProgress는 계획서 작성까지만 담당하는 화면인데,
// 분모에 아직 오지 않은 단계(구현·검증-2·검수)까지 세고 있었다. 기획서 4-4 Task
// 표의 전략(2)+작성(3)+검증-1(1)=6개만 이 화면의 분모로 쓴다 — 조율의 3개 Task
// (요구사항 해석/공고 매칭/작업 분해)는 이 화면 이전(매칭·자격 게이트)에 이미
// 끝난 일이라 포함하지 않는다.
// 재작성 전/후를 컬럼 두 개로 나란히 보여주면 같은 문단이 두 번(거의 그대로) 반복돼
// 문서가 길어진다(사용자 지적) — 코드 검증 화면의 diff처럼 한 줄에 합쳐서, 빠진 부분은
// 빨간 취소선, 새로 들어간 부분은 초록 배경으로만 표시한다.
export function DiffText({ parts }){
  return (
    <p className="text-[12.5px] leading-relaxed text-[var(--fg)]">
      {parts.map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 ? ' ' : ''}
          {p.type === 'same'
            ? <span>{p.text}</span>
            : p.type === 'removed'
              ? <mark className="rounded px-1 bg-[color-mix(in_srgb,var(--danger)_14%,white)] text-[var(--danger)] line-through">{p.text}</mark>
              : <mark className="rounded px-1 bg-[color-mix(in_srgb,var(--ok)_16%,white)] text-[var(--ok)]">{p.text}</mark>}
        </React.Fragment>
      ))}
    </p>
  );
}

// 좌/우를 각자 독립된 세로 스택 두 개로 그리면, 섹션마다 본문 길이가 달라서 같은
// 순번인데도 전/후 줄이 어긋나 보였다(사용자 지적 — "col을 맞추자"). 섹션 하나당
// 그리드 행을 하나씩 만들어서, 같은 섹션의 전/후는 항상 같은 높이에서 나란히 시작하게 한다.
