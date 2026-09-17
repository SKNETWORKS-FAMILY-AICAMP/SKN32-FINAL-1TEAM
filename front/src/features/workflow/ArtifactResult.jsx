// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef,useEffect} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {SiteMock} from './shared.jsx';
import {detectItemCategory,buildCodeCheckItems} from './utils.js';
import {ARTIFACT_CATEGORY_COPY,ARTIFACT_SCORE_BY_OUTCOME,ARTIFACT_SUBTASKS_BY_CATEGORY,EXECUTABLE_COPY,PROTOTYPE_PAGE} from './data.js';

export function InfographicMock(){
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6" style={{ background:'#f2f4f6' }}>
      <img src="/infographic-preview.png" alt="인포그래픽 예시" className="max-w-full max-h-full rounded-sm shadow-xl"/>
    </div>
  );
}

// 구현 Agent 산출 Task도 카테고리별로 다르다 — 원페이지는 실행 파일 Task 자체가
// 생략되므로 "지금 하는 일" 목록도 인포그래픽 제작 하나만 보여준다(사업계획서 작성
// 진행 화면과 같은 패턴, 없는 Task를 나열하지 않는다는 원칙도 동일하게 적용).
export function ArtifactProgress({onComplete,itemInfo}){return <Preparation kind="artifact" compact={detectItemCategory(itemInfo?.item)==='onepage'} onComplete={onComplete}/>;}

// 목업 수정 요청서 v3 §12: 산출물층 30점 = 코드 기준 자동 검증 15 + 계획서 대조 15.
// 값은 시연 로그 steps[9]/steps[10](산출물 확인·종합 평가 1차, 자동검증 12/15·대조
// 7/15)와 steps[11]/steps[13](재작성 후, 자동검증 15/15·대조 11/15)을 그대로 옮겼다.
// 대조 사유(누락 기능 2건)도 시연 로그 featureMatch.findings 그대로다 — 계획서
// 한 벌만으로는 나올 수 없는, 두 산출물을 독립적으로 대조해야만 나오는 지적이다.
export function PrototypeFrame({ className = '' }){
  const boxRef = useRef(null);
  const [boxW, setBoxW] = useState(0);
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = () => setBoxW(el.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const scale = boxW ? boxW / PROTOTYPE_PAGE.w : 0;
  return (
    <div ref={boxRef} className={`soft-scroll overflow-y-auto overflow-x-hidden ${className}`} style={{ scrollbarGutter: 'auto' }}>
      <div style={{ width: boxW || '100%', height: PROTOTYPE_PAGE.h * scale }}>
        {scale > 0 && (
          <iframe src="/prototype-preview.html" title="프로토타입 화면 예시" sandbox="allow-scripts"
            style={{ width: PROTOTYPE_PAGE.w, height: PROTOTYPE_PAGE.h, border: 'none', transform: `scale(${scale})`, transformOrigin: 'top left' }}/>
        )}
      </div>
    </div>
  );
}

export function ResultPreview({kind,onClose}){
 const ref=useRef(null);
 useEffect(()=>{const d=ref.current;d?.showModal();return()=>d?.close()},[]);
 return <dialog ref={ref} className="result-preview-lightbox" onCancel={onClose}
   onClick={(e)=>{ if (e.target===ref.current) onClose(); }} aria-label="산출물 미리보기">
   <button onClick={onClose} aria-label="미리보기 닫기" className="result-preview-lightbox-close"><Icon name="close"/></button>
   {kind==='site'
     ? <PrototypeFrame className="result-preview-lightbox-frame"/>
     : <img src="/infographic-preview.png" alt="인포그래픽 예시" className="result-preview-lightbox-img"/>}
 </dialog>;
}

export function ArtifactResult({ announcement, itemInfo, onBack, onFinalize, scoreOutcome = 'fail' }){
  const [preview,setPreview]=useState(null);
  const category = detectItemCategory(itemInfo && itemInfo.item);
  const hasExecutable = category !== 'onepage';
  const copy = ARTIFACT_CATEGORY_COPY[category];
  const artifactScore = ARTIFACT_SCORE_BY_OUTCOME[scoreOutcome];
  const codeCheckItems = buildCodeCheckItems(category, scoreOutcome);
  const passedItems = codeCheckItems.filter((item) => item.passed);
  const failedItems = codeCheckItems.filter((item) => !item.passed);
  const missingFeatures = artifactScore.crossCheck.reasons;
  const subtasks = ARTIFACT_SUBTASKS_BY_CATEGORY[category] || ARTIFACT_SUBTASKS_BY_CATEGORY.webdev;
  const [checkedTasks, setCheckedTasks] = useState([]);
  const [runningTasks, setRunningTasks] = useState([]);
  // 재작성 스피너가 끝나도 완료 표시가 없어 헷갈린다는 지적에 따라, 방금 재작성한
  // 항목을 완료 표시로 남긴다 — 같은 항목을 다시 체크하면 완료 표시는 지운다.
  const [completedTasks, setCompletedTasks] = useState([]);

  const toggleTask = (label) => {
    setCheckedTasks((prev) => (prev.includes(label) ? prev.filter((t) => t !== label) : [...prev, label]));
    setCompletedTasks((prev) => prev.filter((t) => t !== label));
  };
  const handleRewrite = () => {
    if (checkedTasks.length === 0) return;
    const picked = checkedTasks;
    setRunningTasks(picked);
    setCheckedTasks([]);
    setTimeout(() => {
      setRunningTasks([]);
      setCompletedTasks((prev) => [...new Set([...prev, ...picked])]);
    }, 1600);
  };

  return (
    <section data-screen="artifact" className="max-w-6xl mx-auto px-6 py-16">
      <button onClick={onBack} className="mb-6 text-[13.5px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
        ‹ 사업계획서로 돌아가기
      </button>

      <div className="grid md:grid-cols-[1fr_340px] gap-6">
        <div className="flex flex-col">
          <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">산출물</p>
          <p className="text-[14px] text-[var(--muted-fg)] leading-snug mb-1.5">『{announcement ? announcement.title : ''}』</p>
          <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">프로토타입이 준비됐어요</h1>
          <p className="text-[14.5px] text-[var(--muted-fg)] mb-8">
            {hasExecutable ? '사업계획서와 함께 제출할 실행 파일·인포그래픽입니다' : copy.note}
          </p>

          <div className={`flex-1 grid gap-6 ${hasExecutable ? 'sm:grid-cols-2' : 'sm:grid-cols-1 max-w-md'}`}>
            <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
              <div className="relative flex-1 aspect-[4/3] overflow-hidden">
                <InfographicMock />
              </div>
              <div className="p-4">
                <p className="font-bold text-[14.5px] mb-1">인포그래픽</p>
                <p className="text-[12.5px] text-[var(--muted-fg)] mb-3">사업계획서에 삽입할 요약 인포그래픽입니다</p>
                <div className="flex items-center justify-between text-[12px] font-mono text-[var(--muted-fg)]">
                  <span>infographic.png</span>
                  <button onClick={()=>setPreview("info")} className="font-semibold text-[var(--primary)] hover:underline">미리보기</button>
                </div>
              </div>
            </div>

            {hasExecutable && (
              <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
                <div className="relative flex-1 aspect-[4/3] overflow-hidden">
                  <SiteMock />
                </div>
                <div className="p-4">
                  <p className="font-bold text-[14.5px] mb-1">{EXECUTABLE_COPY.title}</p>
                  <p className="text-[12.5px] text-[var(--muted-fg)] mb-3">{EXECUTABLE_COPY.desc}</p>
                  <div className="flex items-center justify-between text-[12px] font-mono text-[var(--muted-fg)]">
                    <span>index.html</span>
                    <button onClick={()=>setPreview("site")} className="font-semibold text-[var(--primary)] hover:underline">크게 보기</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 우측 — 산출물 점검: 합격선은 물론 점수 자체도 표기하지 않는다(사용자 요청) —
            판정에 쓰일 숫자는 종합 평가에서만 보여주고, 여기서는 항목별 통과 여부만
            본다. 8항목을 2열로 접어 체크리스트 하나 때문에 사이드바가 길게 늘어지지
            않게 한다. */}
        <aside className="rounded-2xl border border-[var(--border)] bg-white p-5 md:sticky md:top-24">
          <p className="text-[13px] font-semibold text-[var(--muted-fg)] mb-1">산출물 점검</p>
          <p className="text-[11.5px] text-[var(--muted-fg)] mb-4">코드 검증과 계획서 대조 결과입니다</p>

          <div className="mb-4">
            <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-2">코드 검증 8항목</p>
            {/* 통과·미달이 섞여 있으면 무엇을 고쳐야 하는지 한눈에 안 들어와서 왼쪽 통과, 오른쪽 미달로 나눈다. */}
            <div className="grid grid-cols-2 gap-x-3">
              <div className="flex flex-col gap-2">
                <p className="text-[11px] font-semibold text-[var(--ok)]">통과 {passedItems.length}</p>
                {passedItems.map((item) => (
                  <div key={item.id} className="flex items-center gap-1.5 text-[12px] leading-snug">
                    <span className="flex-shrink-0 w-3.5 h-3.5 rounded-full flex items-center justify-center text-[9px] font-bold bg-[color-mix(in_srgb,var(--ok)_16%,white)] text-[var(--ok)]" aria-hidden="true">✓</span>
                    <span className="text-[var(--fg)]">{item.name}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-col gap-2">
                <p className="text-[11px] font-semibold text-[var(--danger)]">미달 {failedItems.length}</p>
                {failedItems.length === 0 ? (
                  <p className="text-[12px] text-[var(--muted-fg)]">없음</p>
                ) : failedItems.map((item) => (
                  <div key={item.id} className="text-[12px] leading-snug">
                    <div className="flex items-center gap-1.5">
                      <span className="flex-shrink-0 w-3.5 h-3.5 rounded-full flex items-center justify-center text-[9px] font-bold bg-[color-mix(in_srgb,var(--danger)_12%,white)] text-[var(--danger)]" aria-hidden="true">✕</span>
                      <span className="text-[var(--fg)]">{item.name}</span>
                    </div>
                    <p className="pl-5 mt-0.5 text-[11px] text-[var(--danger)] leading-snug">{item.evidence}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="mb-4">
            <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-2">계획서 대조 — 누락 기능</p>
            {missingFeatures.length === 0 ? (
              <p className="text-[12.5px] text-[var(--muted-fg)]">누락된 기능 없음</p>
            ) : (
              <ul className="flex flex-col gap-1.5">
                {missingFeatures.map((r) => (
                  <li key={r} className="text-[12.5px] text-[var(--danger)] leading-relaxed">· {r}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-[var(--border)] p-4">
            <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-3">다시 준비할 항목</p>
            <div className="flex flex-col gap-2">
              {subtasks.map((label) => {
                const isRunning = runningTasks.includes(label);
                const isDone = !isRunning && completedTasks.includes(label);
                return (
                  <label key={label} className={`flex items-center gap-2.5 text-[13px] ${isRunning ? 'text-[var(--muted-fg)]' : 'text-[var(--fg)] cursor-pointer'}`}>
                    {isRunning ? (
                      <span className="rewrite-indicator" aria-hidden="true"></span>
                    ) : (
                      <input type="checkbox" checked={checkedTasks.includes(label)} onChange={() => toggleTask(label)}
                        className="w-4 h-4 accent-[var(--primary)]" />
                    )}
                    <span>
                      {isRunning ? `${label} 재작성 중…` : label}
                      {isDone && <span className="ml-1.5 text-[11.5px] font-semibold text-[var(--ok)]">✓ 재작성 완료</span>}
                    </span>
                  </label>
                );
              })}
            </div>
            <button onClick={handleRewrite} disabled={checkedTasks.length === 0 || runningTasks.length > 0}
              className="w-full mt-3 rounded-lg border border-[var(--border)] py-2.5 text-[13.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              선택 항목 재작성
            </button>
          </div>
        </aside>
      </div>

      {/* 다음 단계 버튼 — 파일 미리보기 옆 좁은 사이드바 대신, 화면 하단에 전체 폭으로 둔다.
          이 화면엔 합격선이 없으므로(기획서 4-5) 진행을 막는 컨펌 게이트도 두지 않는다. */}
      <div className="mt-10 pt-8 border-t border-[var(--border)] flex items-center justify-between gap-4 flex-wrap">
        <p className="text-[13.5px] text-[var(--muted-fg)]">사업계획서와 이 산출물을 대조한 최종 결과는 종합 평가에서 확인합니다</p>
        <button onClick={onFinalize}
          className="rounded-xl bg-[var(--primary)] text-white px-6 py-3 text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.97] flex-shrink-0">
          종합 평가 확인하기
        </button>
      </div>
      {preview&&<ResultPreview kind={preview} onClose={()=>setPreview(null)}/>}
    </section>
  );
}

// 기획서 4-5: 종합 평가는 문서층(70)+산출물층(30) 원점수를 그대로 더한 100점
// 단일 총점이다 — 문서 평가처럼 각각 환산해 AND로 묶지 않는다. 층별 내역은
// 참고 정보로만 보여주고, 그 자체로 별도 pass/fail을 매기지 않는다.
// 기획서 4-7: "재작성은 화면을 이동하지 않는다 — 6·8·9번 모두 같은 화면에서 다시
// 만들 항목을 고르고, 완료되면 그 화면의 점수와 목록만 갱신된다." 종합 평가(9번)는
// 계획서 Task와 프로토타입 Task를 한 목록으로 합쳐 보여준다(9번에서 계획서 항목을
// 함께 제시해야, 산출물만 다시 만들고 계획서는 그대로 둬 총점이 기준에 못 미치는
// 경우를 사용자가 스스로 피할 수 있다). "산출물 열람" 버튼은 재작성 여부와 무관하게
// 상단에 상시 배치하고 모달로 연다 — 종합 평가는 화면 이동 없이 판정을 보는 자리다.
// 목업 수정 요청서 v3 §2: Task마다 왜 재작성 대상인지 한 줄을 붙인다. 실제 채점
// 엔진이 없는 목업이라 층별로 이미 있는 사유 문구를 자연스럽게 짝지을 수 있는
// 항목에만 붙이고, 짝지을 근거가 없는 항목(그래프·표·인포그래픽)은 사유 없이
// 체크박스만 둔다 — 없는 근거를 지어내는 것보다 빈 자리가 낫다(기획서 4-6과 같은 원칙).
// docScore.reasons(EV 4항목 중 미달분)·artifact reasons가 여러 줄일 수 있어 첫 줄만
// 보여주면 나머지 미달 사유가 묻힌다 — 전부 반환해 한 줄씩 보여준다.
