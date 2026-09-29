// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef,useEffect} from 'react';
import Preparation from '../../components/Preparation.jsx';
import {Icon} from '../../components/Icons.jsx';
import {SiteMock,RerunLeftBadge} from './shared.jsx';
import {detectItemCategory,buildCodeCheckItems,isRerunCapped,rerunLeftOf} from './utils.js';
import {ARTIFACT_CATEGORY_COPY,ARTIFACT_SCORE_BY_OUTCOME,ARTIFACT_SUBTASKS_BY_CATEGORY,EXECUTABLE_COPY,PROTOTYPE_PAGE,RERUN_CAP} from './data.js';
import {retryTask,fetchUploadBlob} from '../../api.js';

// ARTIFACT_SUBTASKS_BY_CATEGORY(data.js)의 라벨 -> app/schemas.py RetryTaskRequest.task_key.
const TASK_KEY_BY_LABEL = { '실행 파일 제작': 'implement_prototype', '인포그래픽 제작': 'implement_infographic' };

// src를 주면 서버가 만든 실제 인포그래픽을, 없으면 예시 이미지를 띄운다.
export function InfographicMock({ src = null }){
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6" style={{ background:'#f2f4f6' }}>
      <img src={src || '/infographic-preview.png'} alt={src ? '인포그래픽' : '인포그래픽 예시'} className="max-w-full max-h-full rounded-sm shadow-xl"/>
    </div>
  );
}

// 산출물 파일(/uploads/...)을 Blob으로 받아 화면에 띄울 주소로 바꾼다. 경로가 없거나
// 못 받으면 null을 돌려주고, 호출한 쪽이 기존 예시 파일로 돌아간다.
// objectURL은 띄우는 동안만 유효하므로 경로가 바뀌거나 화면을 벗어나면 반드시 회수한다.
// [url, failed]를 돌려준다. failed는 "경로는 있는데 못 받았다"일 때만 true다 — 경로 자체가
// 없는 경우(아직 생성 전, 렌더 테스트)와 구분해야 한다. 실패했는데 조용히 예시 파일로
// 돌아가면 사용자는 그 예시를 자기 산출물로 오해한다.
// expect='image'를 주면 받아온 파일이 실제 이미지인지까지 본다. 서버의 구현 Agent가
// 인포그래픽도 .html로 만들어 보내는 경우가 있는데(app/agents.py run_implement_agent_retry),
// 그대로 <img>에 걸면 깨진 이미지 자리만 남고 사용자는 이유를 알 수 없다.
export function useArtifactFile(path, { expect } = {}){
  const [state, setState] = useState({ url: null, failed: false });
  useEffect(() => {
    if (!path) { setState({ url: null, failed: false }); return; }
    let cancelled = false, objectUrl = '';
    setState({ url: null, failed: false });
    fetchUploadBlob(path).then((blob) => {
      if (cancelled) return;
      if (expect === 'image' && blob.type && !blob.type.startsWith('image/')) {
        console.error('인포그래픽 자리에 이미지가 아닌 파일이 왔어요', path, blob.type);
        setState({ url: null, failed: true });
        return;
      }
      objectUrl = URL.createObjectURL(blob);
      setState({ url: objectUrl, failed: false });
    }).catch((err) => {
      if (cancelled) return;
      console.error('산출물 파일을 불러오지 못했어요', path, err);
      setState({ url: null, failed: true });
    });
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [path, expect]);
  return [state.url, state.failed];
}

// 산출물 파일을 못 받았을 때 화면에 대신 띄우는 한 줄 — 지금 보이는 그림이 진짜 산출물이
// 아니라는 사실을 알린다.
export function ArtifactLoadError(){
  return (
    <p role="alert" className="mb-4 rounded-xl border border-[var(--warn)] bg-[color-mix(in_srgb,var(--warn)_8%,white)] px-4 py-3 text-[12.5px] text-[var(--fg)] leading-relaxed">
      산출물 파일을 불러오지 못해 예시 화면을 대신 보여주고 있어요. 로그인이 풀렸을 수 있으니 새로고침해 주세요.
    </p>
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
export function PrototypeFrame({ className = '', src = null }){
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
          <iframe src={src || '/prototype-preview.html'} title={src ? '프로토타입 화면' : '프로토타입 화면 예시'} sandbox="allow-scripts"
            style={{ width: PROTOTYPE_PAGE.w, height: PROTOTYPE_PAGE.h, border: 'none', transform: `scale(${scale})`, transformOrigin: 'top left' }}/>
        )}
      </div>
    </div>
  );
}

export function ResultPreview({kind,onClose,siteSrc=null,infoSrc=null}){
 const ref=useRef(null);
 useEffect(()=>{const d=ref.current;d?.showModal();return()=>d?.close()},[]);
 return <dialog ref={ref} className="result-preview-lightbox" onCancel={onClose}
   onClick={(e)=>{ if (e.target===ref.current) onClose(); }} aria-label="산출물 미리보기">
   <button onClick={onClose} aria-label="미리보기 닫기" className="result-preview-lightbox-close"><Icon name="close"/></button>
   {kind==='site'
     ? <PrototypeFrame className="result-preview-lightbox-frame" src={siteSrc}/>
     : <img src={infoSrc || '/infographic-preview.png'} alt={infoSrc ? '인포그래픽' : '인포그래픽 예시'} className="result-preview-lightbox-img"/>}
 </dialog>;
}

export function ArtifactResult({ announcement, itemInfo, onBack, onFinalize, scoreOutcome = 'fail', projectId, reworkCounts = {}, onRework, scores = null, reworkBudget = null, onScoresRefresh, artifact = null }){
  const [preview,setPreview]=useState(null);
  // 서버가 이미 정한 카테고리(artifact.category)가 있으면 그걸 쓴다 — 없으면(아직 생성
  // 전이라 artifact 자체가 없는 극히 드문 진입 경로에서만) itemInfo 텍스트로 추측한다.
  // 예전엔 항상 추측만 써서, 사용자가 입력한 문구가 onepage 키워드(매장/가게/카페 등)에
  // 안 걸리면 실제로는 onepage인데 실행 파일 카드가 있는 것처럼 잘못 보였다(사용자 지적).
  const category = artifact?.category || detectItemCategory(itemInfo && itemInfo.item);
  const hasExecutable = category !== 'onepage';
  const copy = ARTIFACT_CATEGORY_COPY[category];
  // 서버 채점이 끝났으면 그 값을, 아직이면 기존 고정 표를 쓴다(utils.js scoresFromResult).
  const artifactScore = scores?.artifactScore || ARTIFACT_SCORE_BY_OUTCOME[scoreOutcome];
  const codeCheckItems = scores?.codeCheckItems || buildCodeCheckItems(category, scoreOutcome);
  const passedItems = codeCheckItems.filter((item) => item.passed);
  const failedItems = codeCheckItems.filter((item) => !item.passed);
  const missingFeatures = artifactScore.crossCheck.reasons;
  const subtasks = ARTIFACT_SUBTASKS_BY_CATEGORY[category] || ARTIFACT_SUBTASKS_BY_CATEGORY.webdev;
  const [checkedTasks, setCheckedTasks] = useState([]);
  const [runningTasks, setRunningTasks] = useState([]);
  // 재작성 스피너가 끝나도 완료 표시가 없어 헷갈린다는 지적에 따라, 방금 재작성한
  // 항목을 완료 표시로 남긴다 — 같은 항목을 다시 체크하면 완료 표시는 지운다.
  const [completedTasks, setCompletedTasks] = useState([]);
  // 사업계획서 화면(PlanForm.jsx)과 같은 위치 구성 — 좌측에 산출물 점검, 접었다 펼 수
  // 있고, 박스(테두리 카드) 대신 구역만 나눈다(사용자 지적: 여백만 커지는 사이드바
  // 카드 말고 그냥 구역으로).
  const [panelOpen, setPanelOpen] = useState(true);
  // 서버가 만든 실제 산출물 파일. 없으면(아직 생성 전이거나 못 받으면) 예시 파일로 돌아간다.
  const [infoUrl, infoFailed] = useArtifactFile(artifact?.infographic_path, { expect: 'image' });
  const [siteUrl, siteFailed] = useArtifactFile(artifact?.executable_path);

  // 재작성 상한(RERUN_CAP = 항목마다 1회)에 닿은 항목은 고를 수 없다 — PlanForm과 같은 규칙.
  // 화면에 적는 상한값도 서버가 준 값을 쓴다(관리자가 바꾸면 같이 따라간다).
  const cap = reworkBudget?.cap ?? RERUN_CAP;
  const isCapped = (label) => isRerunCapped(reworkCounts, label, reworkBudget);
  const allCapped = subtasks.every(isCapped);

  const toggleTask = (label) => {
    if (isCapped(label)) return;
    setCheckedTasks((prev) => (prev.includes(label) ? prev.filter((t) => t !== label) : [...prev, label]));
    setCompletedTasks((prev) => prev.filter((t) => t !== label));
  };
  // POST /projects/{id}/retry-task 실제 호출(app/routers/projects.py retry_task) — 예전엔
  // setTimeout으로 스피너만 흉내 내고 서버 호출이 없어 artifacts 테이블이 안 바뀌었다.
  const handleRewrite = async () => {
    const picked = checkedTasks.filter((label) => !isCapped(label));
    if (picked.length === 0) return;
    setRunningTasks(picked);
    setCheckedTasks([]);
    const taskKeys = [...new Set(picked.map((label) => TASK_KEY_BY_LABEL[label]).filter(Boolean))];
    try {
      if (projectId) await Promise.all(taskKeys.map((key) => retryTask(projectId, key)));
      // 실제로 재시도가 나간 뒤에만 횟수를 센다 — 실패한 호출로 상한을 깎지 않는다.
      if (onRework) onRework(picked);
      if (onScoresRefresh) await onScoresRefresh();
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
    <section data-screen="artifact" className="max-w-6xl mx-auto px-6 py-16">
      <button onClick={onBack} className="mb-6 text-[13.5px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
        ‹ 사업계획서로 돌아가기
      </button>

      <div className={`grid gap-6 items-start transition-[grid-template-columns] duration-200 ${panelOpen ? 'md:grid-cols-[290px_1fr]' : 'md:grid-cols-[auto_1fr]'}`}>
        {/* 좌측 — 산출물 점검: 합격선은 물론 점수 자체도 표기하지 않는다(사용자 요청) —
            판정에 쓰일 숫자는 종합 평가에서만 보여주고, 여기서는 항목별 통과 여부만
            본다. 8항목을 2열로 접어 체크리스트 하나 때문에 세로로 길게 늘어지지 않게
            한다. 사업계획서 화면과 같은 위치·같은 방식(박스 아닌 구역, 접기/펼치기). */}
        {!panelOpen && (
          <button type="button" onClick={() => setPanelOpen(true)} aria-label="산출물 점검 펼치기"
            className="hidden md:flex flex-col items-center gap-3 w-11 py-5 md:sticky md:top-24 text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors">
            <Icon name="chevron" size={13} />
            <span className="font-display font-bold text-[13px] leading-none text-[var(--ok)]">{passedItems.length}</span>
          </button>
        )}
        {panelOpen && (
        <aside className="relative md:sticky md:top-24">
          <button type="button" onClick={() => setPanelOpen(false)} aria-label="산출물 점검 접기"
            className="hidden md:grid absolute -right-3.5 top-0 w-7 h-7 place-items-center rounded-full border border-[var(--border)] bg-white shadow-[0_2px_8px_-1px_rgba(15,23,42,.15)] hover:bg-[var(--muted)] transition-colors z-10">
            <Icon name="chevron" size={12} className="rotate-180 text-[var(--muted-fg)]" />
          </button>
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
            <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-1">다시 준비할 항목</p>
            <p className="text-[11px] text-[var(--muted-fg)] mb-3">항목마다 다시 만들기는 {cap}회까지만 가능해요</p>
            <div className="flex flex-col gap-2">
              {subtasks.map((label) => {
                const isRunning = runningTasks.includes(label);
                const isDone = !isRunning && completedTasks.includes(label);
                const left = rerunLeftOf(reworkCounts, label, reworkBudget);
                const capped = left <= 0;
                return (
                  <label key={label} className={`flex items-center gap-2.5 text-[13px] ${isRunning || capped ? 'text-[var(--muted-fg)]' : 'text-[var(--fg)] cursor-pointer'}`}>
                    {isRunning ? (
                      <span className="rewrite-indicator" aria-hidden="true"></span>
                    ) : (
                      <input type="checkbox" checked={checkedTasks.includes(label)} onChange={() => toggleTask(label)}
                        disabled={capped}
                        className="w-4 h-4 accent-[var(--primary)] disabled:cursor-not-allowed" />
                    )}
                    <span>
                      {isRunning ? `${label} 재작성 중…` : label}
                      {isDone && <span className="ml-1.5 text-[11.5px] font-semibold text-[var(--ok)]">✓ 재작성 완료</span>}
                      {!isRunning && <RerunLeftBadge left={left} />}
                    </span>
                  </label>
                );
              })}
            </div>
            <button onClick={handleRewrite} disabled={allCapped || checkedTasks.length === 0 || runningTasks.length > 0}
              className="w-full mt-3 rounded-lg border border-[var(--border)] py-2.5 text-[13.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              선택 항목 재작성
            </button>
          </div>
        </aside>
        )}

        <div className="flex flex-col">
          {(infoFailed || siteFailed) && <ArtifactLoadError />}
          <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">산출물</p>
          <p className="text-[14px] text-[var(--muted-fg)] leading-snug mb-1.5">『{announcement ? announcement.title : ''}』</p>
          <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">프로토타입이 준비됐어요</h1>
          <p className="text-[14.5px] text-[var(--muted-fg)] mb-8">
            {hasExecutable ? '사업계획서와 함께 제출할 실행 파일·인포그래픽입니다' : copy.note}
          </p>

          <div className={`flex-1 grid gap-6 ${hasExecutable ? 'sm:grid-cols-2' : 'sm:grid-cols-1 max-w-md'}`}>
            <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
              <div className="relative flex-1 aspect-[4/3] overflow-hidden">
                <InfographicMock src={infoUrl} />
              </div>
              <div className="p-4">
                <p className="font-bold text-[14.5px] mb-1">인포그래픽</p>
                <p className="text-[12.5px] text-[var(--muted-fg)] mb-3">사업계획서에 삽입할 요약 인포그래픽입니다</p>
                <div className="flex items-center justify-between text-[12px] font-mono text-[var(--muted-fg)]">
                  <span>{(artifact?.infographic_path||'infographic.png').split('/').pop()}</span>
                  <button onClick={()=>setPreview("info")} className="font-semibold text-[var(--primary)] hover:underline">미리보기</button>
                </div>
              </div>
            </div>

            {hasExecutable && (
              <div className="flex flex-col rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
                <div className="relative flex-1 aspect-[4/3] overflow-hidden">
                  <SiteMock src={siteUrl} />
                </div>
                <div className="p-4">
                  <p className="font-bold text-[14.5px] mb-1">{EXECUTABLE_COPY.title}</p>
                  <p className="text-[12.5px] text-[var(--muted-fg)] mb-3">{EXECUTABLE_COPY.desc}</p>
                  <div className="flex items-center justify-between text-[12px] font-mono text-[var(--muted-fg)]">
                    <span>{(artifact?.executable_path||'index.html').split('/').pop()}</span>
                    <button onClick={()=>setPreview("site")} className="font-semibold text-[var(--primary)] hover:underline">크게 보기</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
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
      {preview&&<ResultPreview kind={preview} onClose={()=>setPreview(null)} siteSrc={siteUrl} infoSrc={infoUrl}/>}
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
