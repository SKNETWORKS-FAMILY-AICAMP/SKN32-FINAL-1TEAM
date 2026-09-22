// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState} from 'react';
import {Icon} from '../../components/Icons.jsx';
import {downloadPlanDocx,downloadPrototypeZip} from '../../dummyDeliverables.js';
import {downloadPlanDocument} from '../../api.js';
import {buildCodeCheckItems,buildGeneralInfo,buildOverview,detectItemCategory,DOC_SCORE_BY_OUTCOME} from './utils.js';
import {printVerificationReport} from './verificationReport.js';
import {ARTIFACT_SCORE_BY_OUTCOME,DELIVERABLE_NOTICES,DOWNLOAD_FILES,FINAL_THRESHOLD,PLAN_DOCUMENT_SECTIONS_REWORKED,REVIEW_PARAGRAPHS} from './data.js';

export function ReviewScreen({ announcement, itemInfo, docOutcome = 'fail', artifactOutcome = 'fail', onGoDashboard, projectId }){
  const docScore = DOC_SCORE_BY_OUTCOME[docOutcome];
  const artifactScore = ARTIFACT_SCORE_BY_OUTCOME[artifactOutcome];
  const finalTotal = docScore.raw + artifactScore.autoCheck.raw + artifactScore.crossCheck.raw;
  const passed = finalTotal >= FINAL_THRESHOLD;
  const itemTitle = announcement ? announcement.title : '';
  // 문장 다듬기 항목별 수정 내역(p-02, p-09...)은 대부분의 사용자가 신경 안 쓰는
  // 세부 정보라, 기본은 접어두고 보고 싶은 사람만 눌러서 펼친다(사용자 지적) —
  // 항목별로 따로따로 펼치는 게 아니라 토글 하나로 전부 한 번에 나온다.
  const [showDetails, setShowDetails] = useState(false);

  function handleDownload(file){
    if (file.name === '사업계획서.docx') {
      // [2026-09-15] projectId가 있으면 실제 백엔드가 초기창업패키지(일반형) 공식 양식(별첨1)
      // 구조로 채운 진짜 .docx를 내려준다(app/plan_document_export.py). projectId가 없는
      // 경우(데모 화면을 프로젝트 없이 미리보기로 연 경우 등)에만 예전 클라이언트 더미로
      // 폴백한다 — 실패 시에도 마찬가지로 폴백해서 다운로드 버튼 자체가 죽지 않게 한다.
      if (projectId) {
        downloadPlanDocument(projectId).catch((err) => {
          console.error('실제 사업계획서 다운로드 실패, 더미로 대체합니다:', err);
          downloadPlanDocx({
            title: `${itemTitle || '사업계획서'} 사업계획서`,
            sections: PLAN_DOCUMENT_SECTIONS_REWORKED,
            footer: DELIVERABLE_NOTICES.find((n) => n.label === '계획서')?.text,
          });
        });
        return;
      }
      // 실제로 아는 값(아이템 설명·대표자명·설립일자 등)만 채우고, 모르는 칸(기업명 등
      // 폼에서 아예 안 받는 값)은 서식 원본의 자리표시자 관례를 그대로 쓴다 — 지어낸
      // 값을 넣지 않는다.
      downloadPlanDocx({
        title: '초기창업패키지 창업기업 사업계획서',
        generalInfo: buildGeneralInfo(itemInfo),
        overview: buildOverview(itemTitle, PLAN_DOCUMENT_SECTIONS_REWORKED),
        sections: PLAN_DOCUMENT_SECTIONS_REWORKED,
        footer: DELIVERABLE_NOTICES.find((n) => n.label === '계획서')?.text,
      });
      return;
    }
    if (file.name === 'prototype.zip') {
      const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"/><title>${itemTitle || '프로토타입'}</title>
<style>body{font-family:system-ui,sans-serif;background:#f2f4f6;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
.card{width:350px;background:#fff;border:1px solid #e5e8eb;border-radius:12px;box-shadow:0 8px 24px rgba(20,23,31,.12);overflow:hidden}
.bar{border-bottom:1px solid #e5e8eb;padding:8px 16px;font-size:12px;color:#6b7684}
.body{padding:20px}
.tag{border-radius:4px;background:#f2f4f6;padding:4px 8px;font-size:12px;margin-right:6px}</style>
</head><body>
<div class="card">
  <div class="bar">프로토타입 화면 예시</div>
  <div class="body">
    <div style="font-weight:700;font-size:14px">LOCALFIT</div>
    <h3 style="margin-top:16px;font-size:19px;font-weight:700">오늘, 가까운 곳에서 시작.</h3>
    <p style="margin-top:8px;font-size:12px;color:#6b7684">우리 동네 운동시설을 한 곳에서.</p>
    <div style="margin-top:16px">${['피트니스','필라테스','요가'].map((x) => `<span class="tag">${x}</span>`).join('')}</div>
  </div>
</div>
</body></html>`;
      downloadPrototypeZip({ itemName: itemTitle, html });
      return;
    }
    if (file.name === '검증결과.pdf') {
      // 원페이지형 검증결과서 양식을 인쇄 창으로 연다 — "PDF로 저장"을 고르면 PDF가 된다.
      const category = detectItemCategory(itemInfo?.item);
      printVerificationReport({
        projectName: itemInfo?.item,
        announcementTitle: itemTitle,
        category,
        docScore,
        codeCheckItems: buildCodeCheckItems(category, artifactOutcome),
        crossCheck: artifactScore.crossCheck,
        threshold: FINAL_THRESHOLD,
      });
      return;
    }
  }

  // 파일마다 따로 눌러야 했던 걸 한 번에 — 브라우저가 같은 틱에 여러 다운로드를
  // 팝업 차단처럼 막는 경우가 있어(사용자 지적: 산출물 한번에 받게) 살짝 간격을 둔다.
  const handleDownloadAll = () => {
    DOWNLOAD_FILES.forEach((f, i) => setTimeout(() => handleDownload(f), i * 400));
  };

  return (
    <section data-screen="review" className="max-w-3xl mx-auto px-6 py-16">
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">문장 다듬기</p>
      <p className="text-[14px] text-[var(--muted-fg)] leading-snug mb-1.5">『{announcement ? announcement.title : ''}』</p>
      <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">문장을 다듬었어요</h1>
      <p className="text-[14.5px] text-[var(--muted-fg)] mb-1">사업계획서 문장 형식과 한국어 표현만 다듬는 단계라 점수는 바뀌지 않습니다</p>
      <p className="text-[12.5px] text-[var(--muted-fg)] mb-8">이 단계부터는 이전 화면으로 돌아갈 수 없습니다</p>

      <button type="button" onClick={() => setShowDetails((v) => !v)} aria-expanded={showDetails}
        className="flex items-center gap-1.5 text-[13.5px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors mb-10">
        <Icon name="chevron" size={14} className={`transition-transform duration-150 ${showDetails ? 'rotate-90' : ''}`} />
        수정한 문장 {REVIEW_PARAGRAPHS.length}건 {showDetails ? '접기' : '보기'}
      </button>

      {/* 이 div는 접혀있어도(showDetails=false) DOM에 항상 존재해야 한다 — styles.css의
          레거시 규칙(.workflow-content [data-screen="review"]>div:first-of-type>div)이
          "몇 번째 div 자식인지"로 문단 카드를 스타일링하는데, 이 div 자체를 통째로
          안 그리면 그 자리를 "결과물" 감싸는 div가 대신 차지해서 엉뚱하게 padding:28px가
          거기 먹혀버린다(사용자 지적: 전체 다운로드가 계속 삐져나옴 — 실제로 이게 원인이었다).
          그래서 바깥 div는 그대로 두고 안쪽 map만 조건부로 비운다. */}
      <div className={`flex flex-col gap-4 ${showDetails ? 'mb-10' : ''}`}>
        {showDetails && REVIEW_PARAGRAPHS.map((p) => (
          <div key={p.id} className={`rounded-2xl border bg-white p-5 ${p.spotlight ? 'border-[var(--primary)]' : 'border-[var(--border)]'}`}>
            <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
              <p className="text-[11px] font-bold text-[var(--muted-fg)] tracking-wide font-mono">{p.id}</p>
              {!p.spotlight && (
                <span className="flex-shrink-0 text-[11px] font-semibold text-[var(--ok)] bg-[color-mix(in_srgb,var(--ok)_12%,white)] rounded-full px-2.5 py-1">표현 반영됨</span>
              )}
            </div>

            {p.spotlight ? (
              <React.Fragment>
                <p className="text-[11px] font-semibold text-[var(--muted-fg)] mb-1.5">원문</p>
                <p className="text-[13px] leading-relaxed text-[var(--muted-fg)] mb-4">{p.before}</p>
                <div className="flex flex-col gap-3">
                  {p.attempts.map((a) => (
                    <div key={a.try} className={`rounded-xl p-4 ${a.passed ? 'bg-[color-mix(in_srgb,var(--ok)_8%,white)]' : 'bg-[color-mix(in_srgb,var(--danger)_6%,white)]'}`}>
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${a.passed ? 'text-[var(--ok)] bg-[color-mix(in_srgb,var(--ok)_16%,white)]' : 'text-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_12%,white)]'}`}>
                          {a.try}차 시도 · {a.passed ? '핵심 정보 보존 확인' : '핵심 정보 변경 발견'}
                        </span>
                      </div>
                      <p className="text-[13.5px] leading-relaxed text-[var(--fg)]">{a.after}</p>
                      {a.issue && <p className="mt-1.5 text-[12px] text-[var(--danger)] leading-relaxed">{a.issue}</p>}
                    </div>
                  ))}
                </div>
              </React.Fragment>
            ) : (
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <p className="text-[11px] font-semibold text-[var(--muted-fg)] mb-1.5">수정 전</p>
                  <p className="text-[13px] leading-relaxed text-[var(--muted-fg)]">{p.before}</p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold text-[var(--primary-dim)] mb-1.5">수정 후</p>
                  <p className="text-[13.5px] leading-relaxed text-[var(--fg)]">{p.after}</p>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="border-t border-[var(--border)] pt-6">
        <div className="flex items-center justify-between gap-4 flex-wrap mb-6 px-5">
          <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide">결과물</p>
          <button onClick={handleDownloadAll} title="더미 데이터로 만든 파일입니다 — 형식만 실제와 같습니다"
            className="flex-shrink-0 text-[12.5px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
            전체 다운로드
          </button>
        </div>
        {!passed && (
          <p className="text-[13px] text-[var(--fg)] mb-4">현재 {finalTotal}점으로 저장됩니다 — 검수는 표현만 다듬으므로 종합 평가에서 확인한 점수가 그대로 기록됩니다</p>
        )}

        <div className="flex flex-col gap-3 mb-6">
          {DOWNLOAD_FILES.map((f) => (
            <div key={f.name} className="rounded-2xl border border-[var(--border)] bg-white p-5 flex items-center justify-between gap-4 flex-wrap">
              <div>
                <p className="font-semibold text-[14px] font-mono mb-1">{f.name}</p>
                <p className="text-[12.5px] text-[var(--muted-fg)]">{f.desc}</p>
              </div>
              <button onClick={() => handleDownload(f)} title="더미 데이터로 만든 파일입니다 — 형식만 실제와 같습니다" className="flex-shrink-0 rounded-lg border border-[var(--border)] px-4 py-2 text-[13px] font-semibold hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
                다운로드
              </button>
            </div>
          ))}
        </div>

        <ul className="flex flex-col gap-1.5 mb-8">
          {DELIVERABLE_NOTICES.map((n) => (
            <li key={n.label} className="text-[12px] text-[var(--muted-fg)] leading-relaxed">
              <span className="font-semibold text-[var(--fg)]">［{n.label}］</span> {n.text}
            </li>
          ))}
        </ul>

        <button onClick={onGoDashboard}
          className="w-full rounded-xl border border-[var(--border)] py-3 text-[14.5px] font-semibold hover:bg-[var(--bg)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
          내 프로젝트로 돌아가기
        </button>
      </div>
    </section>
  );
}
