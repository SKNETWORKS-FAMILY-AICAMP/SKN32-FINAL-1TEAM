// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef,useEffect} from 'react';

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

// 신규 공고 매칭은 임베딩으로 후보를 먼저 좁힌 뒤, 상위 N건만 LLM으로 세부 비교한다
// — 신규 공고 전체를 LLM으로 돌리면 공고 건수에 비례해 비용이 선형으로 늘어난다.
// 이 파이프라인 자체는 백엔드 영역이라 목업엔 없고, 그 결과(유사도 점수)만 더미로 흉내낸다.
// 목업 수정 요청서 v3 §9: 등록 단위는 프로젝트(계획서)가 아니라 아이템이다 — 계획서는
// 선택 공고의 양식·마감일·지원규모에 종속되어 다른 공고에 재사용할 수 없어서(기획서
// 4-2⑧), 계획서 기반 알림은 성립하지 않는다. 아이템 자체는 공고와 무관하게 남아
// 여러 신규 공고와 계속 비교될 수 있다는 게 차이다.
export function NotificationBell({ enabled, onToggle, alerts = [] }){
  const [open, setOpen] = useState(false);
  const activeAlerts = enabled ? alerts : [];

  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="알림"
        className="relative w-9 h-9 rounded-full flex items-center justify-center text-[var(--muted-fg)] hover:bg-[var(--muted)] hover:text-[var(--fg)] transition-[background-color,color] duration-150 ease-out">
        <svg className="w-[18px] h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
        </svg>
        {activeAlerts.length > 0 && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-[var(--primary)]"></span>
        )}
      </button>

      {open && (
        <React.Fragment>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)}></div>
          <div className="absolute right-0 top-11 w-[340px] max-w-[calc(100vw-32px)] rounded-2xl border border-[var(--border)] bg-white shadow-[0_20px_48px_-16px_rgba(20,23,31,.25)] z-50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3.5 border-b border-[var(--border)]">
              <p className="text-[13.5px] font-bold">유사 공고 알림</p>
              <button type="button" role="switch" aria-checked={enabled} aria-label="유사 공고 알림" className="flex items-center gap-2 cursor-pointer select-none" onClick={onToggle}>
                <span className="text-[11.5px] text-[var(--muted-fg)]">{enabled ? '켜짐' : '꺼짐'}</span>
                <span className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-150 ease-out" style={{ backgroundColor: enabled ? 'var(--primary)' : '#d1d6db' }}>
                  <span className="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform duration-150 ease-out" style={{ transform: enabled ? 'translateX(18px)' : 'translateX(3px)' }}></span>
                </span>
              </button>
            </div>

            {!enabled ? (
              <p className="px-4 py-6 text-[12.5px] text-[var(--muted-fg)] text-center">알림이 꺼져 있어요 — 켜면 등록한 프로젝트와 비슷한 신규 공고를 알려드려요</p>
            ) : activeAlerts.length === 0 ? (
              <p className="px-4 py-6 text-[12.5px] text-[var(--muted-fg)] text-center">아직 새로 올라온 유사 공고가 없어요</p>
            ) : (
              <div className="soft-scroll max-h-72 overflow-y-auto divide-y divide-[var(--border)]">
                {activeAlerts.map((a) => (
                  <div key={a.id} className="px-4 py-3.5">
                    <p className="text-[11.5px] text-[var(--muted-fg)] mb-1">『{a.itemName}』 아이템과 유사</p>
                    <p className="text-[13px] font-semibold mb-0.5">{a.title}</p>
                    <p className="text-[11.5px] text-[var(--muted-fg)]">{a.org} · 유사도 {a.similarity}% · {a.detectedAt}</p>
                  </div>
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
      {/* 기획서 6-7 + 목업 수정 요청서 v3 §11: 첨부 원본은 텍스트 추출 직후 파기된다
          (시연 로그 steps[1].data.referenceDocs[].originalDiscardedAt) — 계정에 남는
          건 추출된 텍스트뿐, 원본 파일이 아니라는 걸 첨부 시점에 미리 알린다. */}
      <p className="mt-1 text-[11.5px] text-[var(--muted-fg)]">체험 모드에서는 파일이 서버로 전송되지 않아요.</p>
    </div>
  );
}

// 기획서 4-1/4-2①: 입력은 대화가 아니라 폼으로, 그것도 한 화면에서 한 번에 받는다 —
// 자격 판정·계획서 작성에 필요한 항목(신청자 유형·대표자·설립일자·팀·단가·아이디어)을
// 처음에 모두 모아두면 신청 자격 확인 이후로는 사용자에게 되묻지 않고 끝까지
// 진행할 수 있다. 예비창업자는 대표자·설립일자가 아예 해당 없으므로 그 값들을
// 비워둔 채(=업력 계산상 예비창업자로 판정) 다음 단계로 넘긴다.
export function FitGauge({value}){
  const r=42,c=2*Math.PI*r,offset=c*(1-Math.max(0,Math.min(100,value))/100);
  const tone=value>=80?'#3182f6':value>=60?'#d7a03c':'#d34b50';
  return (
    <svg viewBox="0 0 100 100" className="fit-gauge" role="img" aria-label={`아이템 적합도 ${value}%`}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="#eef1f4" strokeWidth="10"/>
      <circle cx="50" cy="50" r={r} fill="none" stroke={tone} strokeWidth="10" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={offset} transform="rotate(-90 50 50)" style={{transition:'stroke-dashoffset .4s ease-out'}}/>
      <text x="50" y="46" textAnchor="middle" fontSize="24" fontWeight="700" fill="#333d4b">{value}</text>
      <text x="50" y="65" textAnchor="middle" fontSize="10" fill="#8b95a1">% 적합</text>
    </svg>
  );
}

// [2026-09-15, 프론트 통합 임시 구현] 예전엔 ANNOUNCEMENTS(하드코딩 6건)를 그대로 3건
// 잘라 보여줬는데, 이제 마운트 시 GET /projects/{id}/match-candidates(api.js
// getMatchCandidates)로 실제 후보를 받아온다 — 백엔드가 아직 아무것도 저장하지 않은 채
// 후보만 계산해서 보여주는 단계라(app/routers/projects.py get_match_candidates 주석 참고),
// 사용자가 "신청 자격 확인하기"를 누르는 순간에만 POST /generate(generatePipeline)를 호출해
// 실제 매칭·자격판정·계획서·산출물·최종판정을 한 번에 만든다.
//
// [2026-09-16, 근거 패널 추가] 원래는 후보 목록 안에 매칭 근거를 한 줄로만 보여줬는데
// (사용자 지적 — "근거를 더 상세히 어필할 수 있게"), 왼쪽 목록/오른쪽 근거 패널로
// 나눠서 선택한 공고의 적합도 게이지·다른 후보와의 비교까지 오른쪽에 보여준다.
// candidates/onLoaded: 후보 목록은 App이 들고 있는다(2026-09-16). 자격 요건을 확인하러
// 갔다가 "매칭 결과로 돌아가기"로 되돌아오면 이 컴포넌트가 다시 마운트되는데, 그때마다
// GET /match-candidates를 다시 부르면 공고 3건과 적합도가 통째로 새로 뽑힌다 — 백엔드가
// 아직 아무것도 저장하지 않고 매번 random으로 점수를 매기는 임시 구현이라 그렇다
// (app/routers/projects.py get_match_candidates 주석 참고). 사용자 입장에선 방금 보던
// 공고 목록이 사라지는 버그로 보여서(사용자 지적), 한 프로젝트 안에서는 처음 받아온
// 후보를 계속 쓴다. 실제 매칭이 DB에 저장되기 시작하면 이 캐시는 없애도 된다.
export function GeneratingOverlay({children}){
 const ref=useRef(null);
 useEffect(()=>{const dialog=ref.current;dialog?.showModal();const heading=dialog?.querySelector("h1");if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}if(dialog)dialog.scrollTop=0;return()=>dialog?.close()},[]);
 return <dialog ref={ref} className="generation-dialog" aria-label="결과물 생성 진행" onCancel={e=>e.preventDefault()}>{children}</dialog>;
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
