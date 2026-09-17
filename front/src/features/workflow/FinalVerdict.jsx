// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef,useEffect} from 'react';
import {Icon} from '../../components/Icons.jsx';
import {DiffText} from './shared.jsx';
import {GeneralInfoBlock,PlanExtrasBlock} from './PlanForm.jsx';
import {PrototypeFrame,ResultPreview} from './ArtifactResult.jsx';
import {detectItemCategory,diffSentences,taskReasons,DOC_SCORE_BY_OUTCOME} from './utils.js';
import {ARTIFACT_SCORE_BY_OUTCOME,ARTIFACT_SUBTASKS_BY_CATEGORY,FINAL_THRESHOLD,PLAN_AI_NOTICE,PLAN_DOCUMENT_SECTIONS,PLAN_DOCUMENT_SECTIONS_REWORKED,PSST_OFFICIAL_HEADERS,SCORE_DISCLAIMER,TASK_REWORK_SUMMARY,WRITING_SUBTASKS} from './data.js';

export function PlanCompareColumns({ itemInfo, announcement }){
  const diffs = PLAN_DOCUMENT_SECTIONS.map((s, i) => diffSentences(s.body, PLAN_DOCUMENT_SECTIONS_REWORKED[i].body));
  return (
    <div className="flex flex-col gap-6">
      {/* 일반현황·개요는 재작성 전/후로 갈리지 않는 값이라 좌우로 나누지 않고 위에 한 번만 둔다. */}
      <div className="pb-5 border-b border-[var(--border)]">
        <GeneralInfoBlock itemInfo={itemInfo} itemTitle={announcement ? announcement.title : ''} sections={PLAN_DOCUMENT_SECTIONS_REWORKED} />
      </div>
      {/* 재작성 전/후를 컬럼 두 개로 나란히 보여주면 같은 문단이 거의 그대로 두 번 반복돼
          문서가 길어진다(사용자 지적) — 코드 검증 화면처럼 한 줄에 합쳐서 빠진 부분은
          빨간 취소선, 새로 들어간 부분은 초록 배경으로만 표시한다. */}
      <p className="text-[11px] font-semibold text-[var(--muted-fg)]">
        <span className="text-[var(--danger)] line-through">빨간 취소선</span>은 빠지거나 바뀐 부분, <span className="text-[var(--ok)]">초록 배경</span>은 새로 들어간 부분이에요
      </p>
      {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
        <div key={s.title} className="pt-5 border-t border-[var(--border)] first:pt-0 first:border-t-0">
          <h2 className="font-display font-bold text-[14px] mb-1">{PSST_OFFICIAL_HEADERS[i]}</h2>
          <DiffText parts={diffs[i]} />
        </div>
      ))}
      {/* 재작성 대조 화면에서 표·그래프가 빠져 있었다(사용자 지적: "재작성하면 자꾸
          그래프가 사라진다") — 계획서 열람 모달과 똑같이 여기도 포함시킨다. */}
      <div className="pt-5 border-t border-[var(--border)]">
        <PlanExtrasBlock size="compact" />
      </div>
    </div>
  );
}

// 제출 전 점검(ArtifactCarousel)과 같은 슬라이드 방식으로, "재작성 전" 카드 전체와
// "재작성 후" 카드 전체를 두 파트로 나눠 옆으로 넘겨보게 한다(사용자 요청) — 나란히
// 두 칸으로 늘어놓지 않아 화면이 좁을 때도 카드 하나씩 온전한 크기로 보인다.
function CompareCarousel({ before, after, prevAriaLabel = '재작성 전 보기', nextAriaLabel = '재작성 후 보기', draggable = true }){
  const [slide, setSlide] = useState(0);
  const dragRef = useRef(null);
  const go = (next) => setSlide(Math.max(0, Math.min(1, next)));

  const onPointerDown = (e) => { if (!draggable) return; dragRef.current = { startX: e.clientX, pointerId: e.pointerId }; };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d) return;
    try { e.currentTarget.setPointerCapture(d.pointerId); } catch { /* 캡처 실패는 무시 */ }
  };
  const endDrag = (e) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d) return;
    const dx = e.clientX - d.startX;
    if (dx < -60) go(slide + 1);
    else if (dx > 60) go(slide - 1);
  };

  return (
    <div className="relative">
      <div className="overflow-hidden">
        <div className="flex transition-transform duration-300 ease-out" style={{ width: '200%', transform: `translateX(-${slide * 50}%)` }}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}>
          <div className="w-1/2 flex-shrink-0 px-1">{before}</div>
          <div className="w-1/2 flex-shrink-0 px-1">{after}</div>
        </div>
      </div>
      {/* 화살표를 컨테이너 전체 높이의 50%(=아래로 스크롤해야 보이는 위치)가 아니라
          지금 보이는 화면 가운데에 계속 떠 있게 한다(사용자 지적: "스크롤 내리기 전에도
          보이고, 내려서도 유동적으로 움직이게") — 높이 0짜리 sticky 앵커 안에서
          버튼만 위로 절반 당겨 중앙에 놓는, 스크롤 컨테이너 안에서 흔히 쓰는 방식이다. */}
      <div className="sticky top-1/2 h-0 overflow-visible pointer-events-none z-10">
        {slide > 0 && (
          <button onClick={() => go(slide - 1)} aria-label={prevAriaLabel}
            className="pointer-events-auto absolute left-2 -translate-y-1/2 w-9 h-9 rounded-full bg-white shadow-lg flex items-center justify-center text-[var(--fg)] hover:bg-[var(--muted)]">
            <Icon name="chevron" size={16} style={{ transform: 'rotate(180deg)' }}/>
          </button>
        )}
        {slide < 1 && (
          <button onClick={() => go(slide + 1)} aria-label={nextAriaLabel}
            className="pointer-events-auto absolute right-2 -translate-y-1/2 w-9 h-9 rounded-full bg-white shadow-lg flex items-center justify-center text-[var(--fg)] hover:bg-[var(--muted)]">
            <Icon name="chevron" size={16}/>
          </button>
        )}
      </div>
      <div className="flex items-center justify-center gap-1.5 mt-3">
        {[0, 1].map((i) => (
          <button key={i} onClick={() => go(i)} aria-label={i === 0 ? prevAriaLabel : nextAriaLabel}
            className={`w-1.5 h-1.5 rounded-full ${i === slide ? 'bg-[var(--fg)]' : 'bg-[var(--border)]'}`}/>
        ))}
      </div>
    </div>
  );
}


// InfographicMock은 박스 가운데에 이미지를 여백과 함께 띄우는 카드용 컴포넌트라, 이
// 비교 박스(고정 aspect-[4/3])에 그대로 넣으면 인포그래픽 원본 비율과 안 맞아 위아래로
// 빈 여백이 남는다(사용자 지적) — 프로토타입과 같은 방식으로, 이미지가 박스 너비에
// 꽉 차게 채우고 세로로 넘치는 만큼은 스크롤하게 한다.
function InfographicPreviewFill(){
  return (
    <div className="soft-scroll absolute inset-0 overflow-y-auto overflow-x-hidden bg-[#f2f4f6]">
      <img src="/infographic-preview.png" alt="인포그래픽 예시" className="block w-full h-auto"/>
    </div>
  );
}

// 웹페이지(프로토타입)와 인포그래픽은 둘 중 하나만 재작성될 수도 있다 — 안 고른 쪽까지
// 자리를 만들어두면 빈 칸만 남는다(사용자 지적) — reworkedParts로 실제 체크했던 항목만
// 렌더링한다. showPrototype/showInfographic이 둘 다 false로 들어오면(레거시 호출 등)
// hasExecutable 기준으로 기본값을 잡는다.
function ArtifactPartCompare({ label, render, reasons }){
  return (
    <div>
      {label && <p className="text-[13px] font-semibold mb-3">{label}</p>}
      <CompareCarousel
        before={
          <div>
            <p className="text-[11px] font-semibold text-[var(--muted-fg)] mb-3">재작성 전</p>
            <div className="relative aspect-[4/3] rounded-xl overflow-hidden border border-[var(--border)] mb-3">
              {render()}
            </div>
            <ul className="flex flex-col gap-1">
              {reasons.map((r) => (
                <li key={r} className="text-[12px] text-[var(--danger)] leading-relaxed">✕ {r}</li>
              ))}
            </ul>
          </div>
        }
        after={
          <div>
            <p className="text-[11px] font-semibold text-[var(--ok)] mb-3">재작성 후</p>
            <div className="relative aspect-[4/3] rounded-xl overflow-hidden border border-[var(--primary)] mb-3">
              {render()}
            </div>
            <ul className="flex flex-col gap-1">
              {reasons.map((r) => (
                <li key={r} className="text-[12px] text-[var(--ok)] leading-relaxed">✓ 해결됨 — {r}</li>
              ))}
            </ul>
          </div>
        }
      />
    </div>
  );
}

// 재작성 대조 모달 전용 책장 넘기기. 페이지 넘기기(이 컴포넌트)와 페이지 안의 "재작성
// 전/후" 넘기기(CompareCarousel)가 둘 다 드래그면 제스처가 겹치므로, 여기는 버튼으로만
// 넘긴다 — next/prev를 누르면 페이지가 반쯤(90도) 접히듯 사라졌다가 새 내용으로 펼쳐진다.
function BookCompare({ pages }){
  const [index, setIndex] = useState(0);
  const [flipping, setFlipping] = useState(false);
  const safeIndex = Math.min(index, Math.max(pages.length - 1, 0));
  const go = (delta) => {
    const next = safeIndex + delta;
    if (next < 0 || next >= pages.length || flipping) return;
    setFlipping(true);
    setTimeout(() => { setIndex(next); setFlipping(false); }, 260);
  };
  if (pages.length === 0) return null;
  const page = pages[safeIndex];
  return (
    <div>
      {pages.length > 1 && (
        <div className="flex items-center justify-between mb-4">
          <button onClick={() => go(-1)} disabled={safeIndex === 0} aria-label="이전 페이지"
            className="w-8 h-8 rounded-full flex items-center justify-center text-[var(--fg)] disabled:opacity-30 hover:bg-[var(--muted)] transition-colors">
            <Icon name="chevron" size={16} style={{ transform: 'rotate(180deg)' }}/>
          </button>
          <div className="flex items-center gap-3">
            {pages.map((p, i) => (
              <span key={p.key} className={`text-[12px] font-semibold ${i === safeIndex ? 'text-[var(--fg)]' : 'text-[var(--muted-fg)]'}`}>{p.label}</span>
            ))}
          </div>
          <button onClick={() => go(1)} disabled={safeIndex === pages.length - 1} aria-label="다음 페이지"
            className="w-8 h-8 rounded-full flex items-center justify-center text-[var(--fg)] disabled:opacity-30 hover:bg-[var(--muted)] transition-colors">
            <Icon name="chevron" size={16}/>
          </button>
        </div>
      )}
      <div style={{ perspective: '1800px' }}>
        {/* key를 안 주면 페이지를 넘겨도 인포그래픽/웹페이지가 내부적으로 같은
            ArtifactPartCompare > CompareCarousel 컴포넌트를 재사용해서, "재작성 후"
            상태로 넘겨봤던 페이지의 슬라이드 위치(slide state)가 다음 페이지에도
            그대로 남는다(사용자 지적) — key로 페이지마다 새로 마운트시켜 항상
            "재작성 전"부터 다시 보이게 한다. */}
        <div key={page.key} className="transition-transform duration-[260ms] ease-in"
          style={{ transform: flipping ? 'rotateY(90deg)' : 'rotateY(0deg)', transformOrigin: 'left center' }}>
          <p className="font-display font-bold text-[15px] mb-4">{page.label}</p>
          {page.content}
        </div>
      </div>
    </div>
  );
}

// 기획서 4-7 유스케이스 표: 종합 평가(9)는 80점 이상이면 바로, 미만이면 확인 절차를
// 거쳐 항상 문장 다듬기(10)로 이어진다 — "제출 파일 내려받기"가 아니다. 다운로드는
// 검수 화면에 함께 있다(목업 수정 요청서 v3 §3 — 화면을 쪼갤 이유가 없다).
// 목업 수정 요청서 v3 §2: "선택한 층에 따라 뒤에서 도는 게 다르다... 고르지 않은
// 층의 점수는 그대로 승계된다. 화면에서는 갱신된 총점만 보이면 된다." docOutcome·
// artifactOutcome은 App 레벨 상태다 — FinalVerdict 안에 지역 상태로 두면 재작성한
// 뒤 문장 다듬기 화면으로 넘어갈 때(App이 그 상태를 모르니) 갱신된 값이 사라진다.
// ARTIFACT_SCORE_BY_OUTCOME.pass가 시연 로그의 실제 재작성 후 값(26/30)과 같아서,
// 이 방식이 곧 시연 로그의 진행(71→79→86)을 그대로 재현한다(문서층만 재작성:
// 52+19=71→60+19=79, 둘 다 재작성: →60+26=86).
// 2026-09-16: "프로토타입 열기" 모달 — 인포그래픽과 프로토타입이 둘 다 있는
// 카테고리(hasExecutable)는 한 화면에 욱여넣지 않고, 인포그래픽이 먼저 보이고
// 옆으로 밀면 프로토타입(스크롤 가능한 실제 화면)이 나오는 슬라이드 2장으로 보여준다
// (사용자 요청 — 페이지를 여러 구간으로 쪼개는 게 아니라 "인포그래픽 먼저, 넘기면
// 그냥 전체 페이지 스크롤"). 드래그는 양쪽 슬라이드 어디서 시작해도 양방향으로 반응한다
// — 단, 프로토타입 슬라이드는 세로 스크롤도 있어서 첫 움직임이 가로인지 세로인지 보고
// (방향 결정 전엔 아무것도 안 함) 가로일 때만 슬라이드를 옆으로 밀고, 세로면 그대로
// 둬서 원래 하던 세로 스크롤이 방해받지 않게 한다. 화살표 버튼은 항상 양쪽에서 다 쓸
// 수 있다. 산출물이 하나뿐인 카테고리(원페이지)는 넘길 게 없으니 그냥 인포그래픽만 보여준다.
export function ArtifactCarousel({ hasExecutable }){
  const [slide, setSlide] = useState(0);
  const trackRef = useRef(null);
  const dragRef = useRef(null);

  if (!hasExecutable) {
    return (
      <div className="flex items-center justify-center py-2">
        <img src="/infographic-preview.png" alt="인포그래픽 예시" className="max-w-full max-h-[90vh] object-contain rounded-lg shadow-lg"/>
      </div>
    );
  }

  const go = (next) => setSlide(Math.max(0, Math.min(1, next)));

  // 첫 pointermove에서 가로/세로 중 어느 쪽으로 더 움직였는지로 방향을 "잠근다" — 세로로
  // 잠기면 이후 이 제스처 동안은 아무것도 안 해서, 프로토타입 슬라이드의 세로 스크롤이
  // 그대로 살아있다. 가로로 잠겨야만 트랙을 옆으로 밀고 포인터를 캡처한다.
  const onPointerDown = (e) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, mode: null, pointerId: e.pointerId };
  };
  const onPointerMove = (e) => {
    const d = dragRef.current;
    if (!d || !trackRef.current) return;
    const dx = e.clientX - d.startX;
    const dy = e.clientY - d.startY;
    if (!d.mode) {
      if (Math.abs(dx) < 6 && Math.abs(dy) < 6) return;
      d.mode = Math.abs(dx) > Math.abs(dy) ? 'h' : 'v';
      // 포인터가 이미 놓였거나(취소된 제스처 등) 캡처할 수 없는 상태면 예외가 난다 —
      // 캡처는 요소 밖으로 끌고 나가도 계속 추적하려는 보조 장치일 뿐이라, 실패해도
      // 드래그 자체는 그대로 진행되게 둔다.
      if (d.mode === 'h') { try { e.currentTarget.setPointerCapture(d.pointerId); } catch { /* 캡처 실패는 무시 */ } }
    }
    if (d.mode !== 'h') return;
    e.preventDefault();
    trackRef.current.style.transition = 'none';
    trackRef.current.style.transform = `translateX(calc(-${slide * 50}% + ${dx}px))`;
  };
  const endDrag = (e) => {
    const d = dragRef.current;
    dragRef.current = null;
    if (!d || d.mode !== 'h') return;
    const dx = e.clientX - d.startX;
    if (trackRef.current) { trackRef.current.style.transition = ''; trackRef.current.style.transform = ''; }
    if (dx < -60) go(slide + 1);
    else if (dx > 60) go(slide - 1);
  };

  // 산출물 확인 화면의 미리보기(ResultPreview) 라이트박스와 크기를 맞춘다(사용자 지적:
  // "프로토타입 열기했을때 사이즈 너무 작음 ... 미리보기 눌렀을때랑 사이즈 동일시하게").
  const stageHeight = 'min(90vh, 760px)';
  return (
    <div className="relative">
      {/* 트랙 자체는 클리핑 용도일 뿐 아무 장식도 없다 — 사진/화면 각각에만 그림자를 줘서
          "박스에 담겼다"는 인상 없이 그냥 사진·화면이 떠 있는 것처럼 보이게 한다(사용자
          지적: 미리보기랑 똑같이, 옆으로 넘기는 것만 추가). */}
      <div className="overflow-hidden">
        <div ref={trackRef} className="flex transition-transform duration-300 ease-out" style={{ width: '200%', transform: `translateX(-${slide * 50}%)` }}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}>
          <div className="w-1/2 flex-shrink-0 flex items-center justify-center p-2" style={{ height: stageHeight }}>
            <img src="/infographic-preview.png" alt="인포그래픽 예시" className="max-w-full max-h-full object-contain rounded-lg shadow-2xl" draggable={false}/>
          </div>
          <div className="w-1/2 flex-shrink-0 flex flex-col items-center justify-center p-2" style={{ height: stageHeight }}>
            {/* 화면이 카드를 꽉 채우도록 배율은 PrototypeFrame이 상자 너비를 재서 계산한다 —
                고정 배율이면 남는 폭만큼 카드의 흰 배경이 옆에 띠처럼 보인다(사용자 지적). */}
            <div className="relative w-full h-full rounded-xl shadow-2xl bg-white overflow-hidden">
              <PrototypeFrame className="w-full h-full"/>
              {/* 프로토타입 화면은 iframe이라 그 위에서 시작한 드래그는 부모로 안 올라온다
                  (다른 문서라 브라우저가 막음). 드래그로 되돌아갈 수 있게 iframe 밖의 손잡이를
                  하나 두되, 줄(row)로 쌓으면 위쪽에 흰 띠가 생기므로 화면 위에 떠 있게 한다. */}
              <div className="absolute top-2 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-full bg-black/35 backdrop-blur-sm cursor-grab active:cursor-grabbing">
                <div className="w-8 h-1 rounded-full bg-white/70"/>
              </div>
            </div>
          </div>
        </div>
      </div>
      {slide > 0 && (
        <button onClick={() => go(slide - 1)} aria-label="이전 화면(인포그래픽)"
          className="absolute left-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-white shadow-lg flex items-center justify-center text-[var(--fg)] hover:bg-[var(--muted)]">
          <Icon name="chevron" size={16} style={{ transform: 'rotate(180deg)' }}/>
        </button>
      )}
      {slide < 1 && (
        <button onClick={() => go(slide + 1)} aria-label="다음 화면(프로토타입)"
          className="absolute right-2 top-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-white shadow-lg flex items-center justify-center text-[var(--fg)] hover:bg-[var(--muted)]">
          <Icon name="chevron" size={16}/>
        </button>
      )}
      <div className="flex items-center justify-center gap-1.5 mt-3">
        {[0, 1].map((i) => (
          <span key={i} className={`w-1.5 h-1.5 rounded-full ${i === slide ? 'bg-white' : 'bg-white/40'}`}/>
        ))}
      </div>
    </div>
  );
}

export function FinalVerdict({ announcement, itemInfo, onBack, onProceed, docOutcome, artifactOutcome, setDocOutcome, setArtifactOutcome }){
  const docScore = DOC_SCORE_BY_OUTCOME[docOutcome];
  const artifactScore = ARTIFACT_SCORE_BY_OUTCOME[artifactOutcome];
  const artifactRawTotal = artifactScore.autoCheck.raw + artifactScore.crossCheck.raw;
  const finalTotal = docScore.raw + artifactRawTotal;
  const passed = finalTotal >= FINAL_THRESHOLD;
  // E9: 산출물층을 이미 최선까지 재작성했는데도(더 오를 여지가 없는데도) 총점이
  // 기준에 못 미치면, 프로토타입만 다시 만들어선 기준에 이를 수 없다 — 버튼을
  // 막지는 않되 계획서 항목도 함께 고르라고 안내한다.
  const showE9Hint = !passed && artifactOutcome === 'pass';
  // 되돌릴 수 없음 확인 절차(시연 로그 steps[10].data.choices[1].confirm)에 쓸 짧은
  // 항목별 미달 요약 — "실현가능성 13/20"처럼 항목명+점수로 간결하게 늘어놓는다.
  const remainingShortfalls = [
    ...docScore.items.filter((it) => it.score < it.max).map((it) => `${it.name} ${it.score}/${it.max}`),
    ...artifactScore.autoCheck.reasons,
    ...artifactScore.crossCheck.reasons,
  ];

  const category = detectItemCategory(itemInfo && itemInfo.item);
  const hasExecutable = category !== 'onepage';
  const allTasks = [
    ...WRITING_SUBTASKS.map((label) => ({ label, layer: '계획서' })),
    ...(ARTIFACT_SUBTASKS_BY_CATEGORY[category] || ARTIFACT_SUBTASKS_BY_CATEGORY.webdev).map((label) => ({ label, layer: '프로토타입' })),
  ];

  const [checkedTasks, setCheckedTasks] = useState([]);
  const [runningTasks, setRunningTasks] = useState([]);
  const [viewerOpen, setViewerOpen] = useState(null); // null | 'plan' | 'artifact'
  // 상단 "계획서 보기"/"프로토타입 열기" 버튼은 지금 상태 하나만 보여주면 되지만,
  // 재작성 직후에 여는 모달은 "뭐가 바뀌었는지" 보여주는 자리라 전/후를 나란히
  // 비교해야 한다(사용자 요청) — 같은 모달을 두 모드로 쓴다.
  const [viewerCompare, setViewerCompare] = useState(false);
  const [confirmProceed, setConfirmProceed] = useState(false);
  const [reworkDiff, setReworkDiff] = useState(null); // null 이전엔 한 번도 재작성 안 함
  const [diffExpanded, setDiffExpanded] = useState(false);
  const [reworkFromTotal, setReworkFromTotal] = useState(null); // 변경 내역 헤더의 "X → Y" 중 X
  // 웹페이지(프로토타입)·인포그래픽 중 실제로 체크했던 쪽만 대조 화면에 보여주기 위한
  // 기록 — 둘 다 "프로토타입" 층으로 묶여 있어(ARTIFACT_SUBTASKS_BY_CATEGORY) 어느 걸
  // 골랐는지 따로 남겨두지 않으면 구분이 안 된다(사용자 지적: 안 고른 쪽은 여백만 남음).
  const [reworkedParts, setReworkedParts] = useState({ plan: false, infographic: false, prototype: false });

  useEffect(() => {
    if (!viewerOpen) return;
    const onKey = (e) => { if (e.key === 'Escape') setViewerOpen(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [viewerOpen]);

  const toggleTask = (label) => {
    setCheckedTasks((prev) => (prev.includes(label) ? prev.filter((t) => t !== label) : [...prev, label]));
  };
  // 실제 재생성 파이프라인은 없는 목업이라, 체크한 항목을 잠깐 "재작성 중"으로
  // 보여준 뒤 되돌린다 — PlanForm/ArtifactResult와 같은 국소 시뮬레이션 패턴. 완료되면
  // "변경 내역"을 채운다(고른 항목만이 아니라 전체 Task를 넣어, 승계된(고르지 않은)
  // 항목도 "변경 없음"으로 함께 보여준다). 목업 수정 요청서 v3 §2가 정확히 "바뀐
  // 항목을 접힌 형태로 제시하고 펼치면 전후 대비가 나오게 한다"고 못 박아서,
  // 여기서 자동으로 펼치지 않는다 — 접힌 채로 두고 사용자가 직접 펼쳐야 한다.
  // 재작성된 층의 결과물은 곧바로 모달로 띄운다(사용자 요청) — 다시 만든 결과가
  // 실제로 뭐가 나왔는지 계획서·프로토타입 화면으로 바로 보여준다. 두 층을 함께
  // 골랐을 때 하나만(프로토타입) 보여주고 종합 판정으로 넘어가 버리면 계획서 쪽
  // 대조 결과를 놓친다(사용자 지적) — viewerOpen을 'both'로 두고, 모달 안에서
  // 계획서·프로토타입 비교를 위아래로 둘 다 보여준다.
  const handleRewrite = () => {
    if (checkedTasks.length === 0) return;
    const picked = checkedTasks;
    const pickedLayers = new Set(allTasks.filter((t) => picked.includes(t.label)).map((t) => t.layer));
    const fromTotal = finalTotal; // 재작성 전 총점 — 변경 내역 헤더의 "X → Y" 중 X
    setRunningTasks(picked);
    setCheckedTasks([]);
    setTimeout(() => {
      setRunningTasks([]);
      setReworkDiff(allTasks.map(({ label, layer }) => {
        const changed = picked.includes(label);
        const summary = TASK_REWORK_SUMMARY[label] || { before: '변경 없음', after: '변경 없음' };
        return changed
          ? { label, layer, before: summary.before, after: summary.after, changed: true }
          : { label, layer, before: '변경 없음', after: '변경 없음', changed: false };
      }));
      setReworkFromTotal(fromTotal);
      setReworkedParts({
        plan: pickedLayers.has('계획서'),
        infographic: picked.includes('인포그래픽 제작'),
        prototype: picked.includes('실행 파일 제작'),
      });
      // 고른 층만 점수를 올린다 — 고르지 않은 층은 그대로 승계된다(v3 §2). ARTIFACT_
      // SCORE_BY_OUTCOME.pass/DOC_SCORE_BY_OUTCOME.pass가 시연 로그의 실제 재작성-후
      // 값이라, 이 전환이 곧 시연 로그가 보여준 점수 진행 그 자체가 된다.
      if (pickedLayers.has('계획서')) setDocOutcome('pass');
      if (pickedLayers.has('프로토타입')) setArtifactOutcome('pass');
      setViewerCompare(true);
      setViewerOpen(
        pickedLayers.has('계획서') && pickedLayers.has('프로토타입') ? 'both'
          : pickedLayers.has('프로토타입') ? 'artifact' : 'plan'
      );
    }, 1600);
  };

  // 기준 이상이면 곧장 검수로, 미달이면 되돌릴 수 없음을 확인받은 뒤에만 검수로 넘어간다(E4).
  const handleProceedClick = () => {
    if (passed) { onProceed(); return; }
    setConfirmProceed(true);
  };

  // 재작성 대조 모달의 책장 페이지 — 순서는 사업계획서 → 인포그래픽 → 실행 파일 고정,
  // 실제로 재작성한 항목만 페이지로 만든다(reworkedParts, 사용자 지적: 안 고른 항목까지
  // 페이지를 만들면 빈 페이지만 남는다).
  const artifactReasons = [...ARTIFACT_SCORE_BY_OUTCOME.fail.autoCheck.reasons, ...ARTIFACT_SCORE_BY_OUTCOME.fail.crossCheck.reasons];
  const comparePages = [];
  if (reworkedParts.plan) {
    comparePages.push({ key: 'plan', label: '사업계획서', content: <PlanCompareColumns itemInfo={itemInfo} announcement={announcement} /> });
  }
  if (reworkedParts.infographic) {
    comparePages.push({ key: 'infographic', label: '인포그래픽', content: <ArtifactPartCompare reasons={artifactReasons} render={() => <InfographicPreviewFill />} /> });
  }
  if (reworkedParts.prototype) {
    comparePages.push({ key: 'prototype', label: '웹페이지(프로토타입)', content: <ArtifactPartCompare reasons={artifactReasons} render={() => <PrototypeFrame className="absolute inset-0"/>} /> });
  }

  return (
    <section data-screen="final" className="max-w-3xl mx-auto px-6 py-16">
      <div className="flex items-center justify-between gap-4 flex-wrap mb-6">
        <button onClick={onBack} className="text-[13.5px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
          ‹ 산출물로 돌아가기
        </button>
        <div className="flex items-center gap-4">
          <button onClick={() => { setViewerCompare(false); setViewerOpen('plan'); }} className="text-[13px] font-semibold text-[var(--fg)] hover:text-[var(--primary)] transition-colors">계획서 보기</button>
          {hasExecutable && (
            <button onClick={() => { setViewerCompare(false); setViewerOpen('artifact'); }} className="text-[13px] font-semibold text-[var(--fg)] hover:text-[var(--primary)] transition-colors">프로토타입 열기</button>
          )}
        </div>
      </div>

      <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">종합 평가</p>
      <p className="text-[14px] text-[var(--muted-fg)] leading-snug mb-1.5">『{announcement ? announcement.title : ''}』</p>
      <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">제출 전 점검 결과예요</h1>
      <p className="text-[14.5px] text-[var(--muted-fg)] mb-8">사업계획서(문서층 70점)와 프로토타입(산출물층 30점)을 합친 총점입니다</p>

      <div className={`rounded-2xl p-6 flex items-center justify-between gap-4 flex-wrap mb-6 ${passed ? 'bg-[color-mix(in_srgb,var(--ok)_8%,white)] border border-[var(--border)]' : 'bg-[color-mix(in_srgb,var(--danger)_6%,white)] border border-[var(--danger)]'}`}>
        <div>
          <p className="text-[12px] font-semibold text-[var(--muted-fg)] mb-1">종합 판정</p>
          <p className={`font-display font-bold text-[20px] ${passed ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}`}>
            {passed ? '내부 점검 기준을 충족했어요' : '조금 더 보완하면 좋아요'}
          </p>
        </div>
        <div className="flex items-end gap-1.5">
          <p className={`font-display font-bold text-[32px] leading-none ${passed ? 'text-[var(--ok)]' : 'text-[var(--danger)]'}`}>{finalTotal}</p>
          <p className="text-[13px] text-[var(--muted-fg)] mb-0.5">/ 100점 (내부 기준 {FINAL_THRESHOLD})</p>
        </div>
      </div>

      <div className="grid sm:grid-cols-2 gap-4 mb-6">
        <div className="rounded-2xl border border-[var(--border)] bg-white p-5">
          <p className="text-[12.5px] font-semibold text-[var(--muted-fg)] mb-3">사업계획서 점검</p>
          <p className="font-display font-bold text-[24px] leading-none mb-1">{docScore.raw} <span className="text-[13px] font-semibold text-[var(--muted-fg)]">/ {docScore.max}점</span></p>
          <p className="text-[12px] text-[var(--muted-fg)]">공고의 평가항목을 얼마나 충족하는지 확인했어요.</p>
        </div>
        <div className="rounded-2xl border border-[var(--border)] bg-white p-5">
          <p className="text-[12.5px] font-semibold text-[var(--muted-fg)] mb-3">프로토타입 점검</p>
          <p className="font-display font-bold text-[24px] leading-none mb-1">{artifactRawTotal} <span className="text-[13px] font-semibold text-[var(--muted-fg)]">/ 30점</span></p>
          <p className="text-[12px] text-[var(--muted-fg)]">자동 검증 {artifactScore.autoCheck.raw}/{artifactScore.autoCheck.max} · 계획서 대조 {artifactScore.crossCheck.raw}/{artifactScore.crossCheck.max}</p>
        </div>
      </div>

      <p className="text-[11px] text-[var(--muted-fg)] leading-relaxed mb-6">{SCORE_DISCLAIMER}</p>

      {showE9Hint && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--muted)] p-4 mb-6">
          <p className="text-[12.5px] text-[var(--fg)] leading-relaxed">산출물층은 이미 최선까지 재작성했습니다 — 아래 목록에서 계획서 항목도 함께 선택해야 기준에 이릅니다.</p>
        </div>
      )}

      {!passed && (
        <div className="rounded-2xl border border-[var(--border)] p-5 mb-6">
          <p className="text-[12.5px] font-bold text-[var(--danger)] mb-3">보완이 필요한 항목</p>
          <div className="flex flex-col gap-2.5 mb-4">
            {allTasks.map(({ label, layer }) => {
              const isRunning = runningTasks.includes(label);
              // 재작성 대조 모달을 X로 닫고 나면, 방금 체크했던 항목이 실제로 반영됐는지
              // 구분할 UI가 없었다(사용자 지적) — 가장 최근 재작성에서 바뀐 항목(reworkDiff의
              // changed:true)에 "방금 재작성함" 배지를 달아준다. 다음 재작성을 돌리면
              // reworkDiff가 통째로 갱신되니, 배지도 항상 가장 최근 결과만 보여준다.
              const justReworked = reworkDiff?.find((d) => d.label === label)?.changed;
              const reasons = taskReasons(label, docScore, artifactScore);
              return (
                <label key={label} className={`flex items-start gap-2.5 text-[13px] ${isRunning ? 'text-[var(--muted-fg)]' : 'text-[var(--fg)] cursor-pointer'}`}>
                  {isRunning ? (
                    <span className="rewrite-indicator" aria-hidden="true"></span>
                  ) : (
                    <input type="checkbox" checked={checkedTasks.includes(label)} onChange={() => toggleTask(label)}
                      className="flex-shrink-0 mt-0.5 w-4 h-4 accent-[var(--primary)]" />
                  )}
                  <span>
                    <span className="flex-shrink-0 text-[11px] font-semibold text-[var(--muted-fg)] mr-1.5">［{layer}］</span>
                    {isRunning ? `${label} 재작성 중…` : label}
                    {!isRunning && justReworked && (
                      <span className="inline-flex items-center gap-0.5 ml-1.5 text-[11px] font-semibold text-[var(--ok)]">
                        <Icon name="check" size={12}/> 방금 재작성함
                      </span>
                    )}
                    {!isRunning && reasons.map((r) => (
                      <span key={r} className="block text-[12px] text-[var(--muted-fg)] mt-0.5">{r}</span>
                    ))}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <button onClick={handleRewrite} disabled={checkedTasks.length === 0 || runningTasks.length > 0}
              className="rounded-lg border border-[var(--border)] px-4 py-2.5 text-[13.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              선택 항목 다시 만들기
            </button>
            <button onClick={handleProceedClick}
              className="rounded-lg px-4 py-2.5 text-[13.5px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
              이대로 진행하기
            </button>
          </div>
        </div>
      )}

      {/* 변경 내역은 재작성으로 기준을 넘겨 !passed 카드가 사라진 뒤에도 계속 보여야
          한다 — v3 §2 예시가 "86점 · 통과 (79 → 86)"처럼 통과 상태에서도 방금 무엇이
          바뀌었는지 보여주므로, passed 여부와 무관하게 reworkDiff가 있으면 렌더링한다. */}
      {reworkDiff && (
        <div className="rounded-2xl border border-[var(--border)] p-5 mb-6">
          <p className="text-[13px] font-semibold mb-3">
            {finalTotal}점 · {passed ? '통과' : '미달'}
            {reworkFromTotal !== null && reworkFromTotal !== finalTotal && (
              <span className="text-[var(--muted-fg)] font-normal"> ({reworkFromTotal} → {finalTotal})</span>
            )}
          </p>
          <button onClick={() => setDiffExpanded((v) => !v)}
            className="text-[12.5px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors">
            {diffExpanded ? '▾' : '▸'} 변경 내역 — {reworkDiff.filter((d) => d.changed).length}개 항목 변경됨
          </button>
          {diffExpanded && (
            <ul className="mt-2 flex flex-col gap-1.5">
              {reworkDiff.map((d) => (
                <li key={d.label} className="text-[12.5px] text-[var(--fg)] leading-relaxed">
                  <span className="text-[11px] font-semibold text-[var(--muted-fg)] mr-1.5">［{d.layer}］</span>
                  {d.label} — {d.changed ? <React.Fragment><span className="text-[var(--muted-fg)]">{d.before}</span> → {d.after}</React.Fragment> : <span className="text-[var(--muted-fg)]">변경 없음</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {confirmProceed && (
        <div className="rounded-2xl border border-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-5 mb-6">
          <p className="text-[13px] font-bold text-[var(--danger)] mb-3">기준 미달 상태로 진행합니다 — 이 단계부터는 되돌릴 수 없습니다</p>
          <ul className="flex flex-col gap-1.5 mb-4">
            <li className="text-[12.5px] text-[var(--fg)] leading-relaxed">· 현재 점수 — 총점 {finalTotal}점 · 기준 {FINAL_THRESHOLD}점 미달</li>
            <li className="text-[12.5px] text-[var(--fg)] leading-relaxed">· 남는 미달 항목 — {remainingShortfalls.join(', ')}</li>
            <li className="text-[12.5px] text-[var(--fg)] leading-relaxed">· 진행 후에는 다시 만들 수 없습니다. 검수 단계로 넘어가면 이 점수가 그대로 확정됩니다.</li>
          </ul>
          <div className="flex items-center gap-4">
            <button onClick={() => setConfirmProceed(false)}
              className="text-[13px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-[color,scale] duration-150 ease-out active:scale-[0.96]">
              취소
            </button>
            <button onClick={onProceed}
              className="text-[13px] font-semibold text-[var(--danger)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
              그래도 진행하기
            </button>
          </div>
        </div>
      )}

      {passed && (
        <button onClick={handleProceedClick}
          className="w-full rounded-xl bg-[var(--primary)] text-white py-3.5 text-[15px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
          검수하기
        </button>
      )}

      {/* 재작성 직후 자동으로 여는 모달은 "지금 상태" 하나만 보여주면 뭐가 바뀌었는지
          알 수 없다(사용자 지적) — viewerCompare가 true면 재작성 전/후 문서를 나란히
          보여준다. "전" 쪽은 항상 원본 고정값(PLAN_DOCUMENT_SECTIONS, ARTIFACT_SCORE_
          BY_OUTCOME.fail)을 쓴다 — 재작성 후엔 실제 docOutcome/artifactOutcome이
          이미 'pass'로 바뀌어 있어서 라이브 상태로는 "전" 모습을 더 이상 알 수 없다. */}
      {/* 2026-09-16: "지금 상태 하나만" 보는 경우(재작성 비교가 아닌 그냥 열람)는 카드
          제목표시줄·테두리 없이 사진/화면만 뜨는 라이트박스(ResultPreview와 같은 방식)로
          보여준다 — 사용자 지적: "박스 안에 들어가있지 말고 미리보기 식으로". 재작성
          전/후를 나란히 비교하는 경우는 라벨(사업계획서/프로토타입, 재작성 전/후)이
          꼭 있어야 알아볼 수 있어서, 그 경우만 기존 흰 카드+제목표시줄 구조를 그대로 쓴다. */}
      {viewerOpen && !viewerCompare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6"
          onClick={(e) => { if (e.target === e.currentTarget) setViewerOpen(null); }}
          role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/70"></div>
          <button onClick={() => setViewerOpen(null)} aria-label="닫기"
            className="fixed top-6 right-6 z-10 w-10 h-10 rounded-full bg-white shadow-lg flex items-center justify-center text-[var(--fg)] hover:bg-[var(--muted)] transition-colors">
            <Icon name="close" size={18}/>
          </button>
          {viewerOpen === 'plan' ? (
            <div className="soft-scroll relative bg-white rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-y-auto p-8 shadow-2xl">
              <p className="text-[11px] text-[var(--muted-fg)] mb-4 pb-4 border-b border-[var(--border)]">{PLAN_AI_NOTICE}</p>
              <div className="flex flex-col gap-6">
                <GeneralInfoBlock itemInfo={itemInfo} itemTitle={announcement ? announcement.title : ''} sections={PLAN_DOCUMENT_SECTIONS} />
                {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
                  <div key={s.title}>
                    <h2 className="font-display font-bold text-[15px] mb-1.5">{PSST_OFFICIAL_HEADERS[i]}</h2>
                    <p className="text-[13px] leading-relaxed text-[var(--fg)]">{s.body}</p>
                  </div>
                ))}
                <PlanExtrasBlock size="compact" />
              </div>
            </div>
          ) : (
            <div className="relative" style={{ width: 'min(92vw, 900px)' }}>
              <ArtifactCarousel hasExecutable={hasExecutable} />
            </div>
          )}
        </div>
      )}

      {/* 재작성 직후 자동으로 여는 모달은 "지금 상태" 하나만 보여주면 뭐가 바뀌었는지
          알 수 없다(사용자 지적) — 재작성 전/후 문서를 나란히 보여준다. "전" 쪽은 항상
          원본 고정값(PLAN_DOCUMENT_SECTIONS, ARTIFACT_SCORE_BY_OUTCOME.fail)을 쓴다 —
          재작성 후엔 실제 docOutcome/artifactOutcome이 이미 'pass'로 바뀌어 있어서 라이브
          상태로는 "전" 모습을 더 이상 알 수 없다. */}
      {viewerOpen && viewerCompare && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={() => setViewerOpen(null)}></div>
          <div className="soft-scroll relative bg-white rounded-2xl w-full max-h-[85vh] overflow-y-auto p-6 shadow-2xl max-w-4xl">
            <div className="sticky -top-6 -mx-6 -mt-6 px-6 pt-6 pb-5 mb-5 bg-white/95 backdrop-blur-sm border-b border-[var(--border)] flex items-center justify-between z-10">
              <p className="font-display font-bold text-[18px]">
                {comparePages.map((p) => p.label).join(' · ')}
                {' — 재작성 전/후 비교'}
              </p>
              <button onClick={() => setViewerOpen(null)} aria-label="닫기"
                className="text-[16px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors">✕</button>
            </div>

            {reworkedParts.plan && (
              <p className="text-[11px] text-[var(--muted-fg)] mb-4 pb-4 border-b border-[var(--border)]">{PLAN_AI_NOTICE}</p>
            )}

            {/* 재작성한 항목이 여럿이면(사업계획서·인포그래픽·실행 파일 중 몇 개든) 책장처럼
                한 페이지씩 넘겨보게 한다(사용자 요청) — 순서는 사업계획서 → 인포그래픽 →
                실행 파일 고정, 재작성 안 한 항목은 페이지 자체를 안 만들어 여백이 안 남는다.
                각 페이지 안의 "재작성 전/후" 비교는 기존 캐러셀(CompareCarousel)을 그대로 쓴다 —
                페이지 넘기기와 전/후 넘기기가 같은 드래그를 쓰면 제스처가 겹치므로, 책장
                넘기기는 버튼으로만(드래그 없이) 동작한다. */}
            <BookCompare pages={comparePages} />
          </div>
        </div>
      )}
    </section>
  );
}

// 기획서 4-4/4-7 + 목업 수정 요청서 v3 §3: 검수는 채점 이후 단계라 문단별 전/후
// 대비만 보여주고 점수는 바꾸지 않는다. 문단 내용은 시연 로그(sbrain_demo_run.json
// steps[12].data.paragraphs)를 그대로 옮겼다 — p-09가 "강조" 대상으로, 1차 시도가
// 중요 정보가 변경되었어요(접수 마감일 누락·지원금액 표기 변경)으로 반려되고 2차에서 두 값을
// 그대로 보존한 채 통과하는 과정을 보여준다.
