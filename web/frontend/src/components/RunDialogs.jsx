// 실행(Run) 관련 안내 두 가지 — 둘 다 백엔드가 2026-09-27에 새로 내려주기 시작한 정보를
// 화면으로 옮긴 것이다(공식 기능정의서 v1.9).
//   - RunBlockedDialog: 계정당 동시 실행 1건 제한(E-RUN-CONCURRENT). POST /projects가 409와
//     함께 진행 중인 실행 정보를 구조화해서 준다(app/routers/projects.py create_project).
//   - NoticeClosedBanner: 이어하기로 돌아왔는데 고른 공고가 그새 마감된 경우(E-RUN-CLOSED).
//     GET /projects/{id}/status의 notice_closed — 실행을 막지 않고 알리기만 한다.
import React from 'react';

const STAGE_LABEL = {
  plan_writing: '사업계획서 작성',
  plan_review_pending: '사업계획서 확인 대기',
  prototype_building: '프로토타입 제작',
  artifact_review: '산출물 검증',
  final_review_pending: '최종 확인 대기',
  reviewing: '문장 다듬기',
  done: '완료',
};

export function RunBlockedDialog({ detail, onResume, onRestart, onClose, busy }){
  if (!detail) return null;
  const stageLabel = STAGE_LABEL[detail.active_stage] || (detail.active_stage ? '진행 중' : '공고 고르는 중');
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" aria-hidden="true" onClick={busy ? undefined : onClose} />
      <div role="dialog" aria-modal="true" aria-labelledby="run-blocked-title" className="relative w-full max-w-md rounded-3xl bg-white p-8 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)]">
        <h2 id="run-blocked-title" className="font-extrabold text-[20px] leading-snug mb-2">이미 진행 중인 작업이 있어요</h2>
        <p className="text-[14px] text-[var(--muted-fg)] leading-relaxed mb-5">
          한 번에 하나씩만 진행할 수 있어요. 지금 작업은 <span className="font-semibold text-[var(--fg)]">{stageLabel}</span> 단계까지 와 있습니다.
        </p>
        <div className="rounded-xl bg-[var(--muted)] px-4 py-3 text-[12.5px] text-[var(--muted-fg)] leading-relaxed mb-6">
          중단하고 새로 시작하면 지금까지 만든 계획서·프로토타입을 다시 볼 수 없습니다.
        </div>
        <button onClick={onResume} disabled={busy}
          className="w-full rounded-xl bg-[var(--primary)] text-white py-3 text-[14.5px] font-semibold disabled:opacity-40 hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
          이어서 진행하기
        </button>
        <button onClick={onRestart} disabled={busy}
          className="w-full mt-2.5 rounded-xl border border-[var(--border)] py-3 text-[14.5px] font-semibold text-[var(--danger)] disabled:opacity-40 hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
          {busy ? '처리 중…' : '중단하고 새로 시작하기'}
        </button>
        <button onClick={onClose} disabled={busy}
          className="w-full mt-2.5 py-2 text-[13px] font-semibold text-[var(--muted-fg)] disabled:opacity-40 hover:text-[var(--fg)]">
          닫기
        </button>
      </div>
    </div>
  );
}

export function NoticeClosedBanner({ onClose }){
  return (
    <div role="status" className="mx-auto mt-6 mb-2 max-w-3xl px-6">
      <div className="flex items-start gap-3 rounded-2xl border border-[#f4c9c9] bg-[#fff1f1] px-4 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-[13.5px] font-semibold text-[#bb3434] mb-0.5">고른 공고의 모집이 마감됐어요</p>
          <p className="text-[12.5px] text-[#874b4b] leading-relaxed">작성은 그대로 이어서 할 수 있지만, 이 공고에는 제출할 수 없어요. 다른 공고를 고르려면 새 프로젝트를 시작해 주세요.</p>
        </div>
        <button onClick={onClose} aria-label="닫기" className="flex-shrink-0 px-1.5 text-[13px] font-semibold text-[#bb3434] hover:opacity-70">✕</button>
      </div>
    </div>
  );
}
