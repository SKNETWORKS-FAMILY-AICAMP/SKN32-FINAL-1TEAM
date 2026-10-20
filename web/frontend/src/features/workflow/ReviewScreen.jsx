// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useEffect, useRef, useState} from 'react';
import {buildZip,downloadPlanDocx,downloadPrototypeZip,triggerDownload} from '../../dummyDeliverables.js';
import {downloadDeliverableZip,downloadPlanDocument,downloadPlanHwp,fetchUploadBlob} from '../../api.js';
import {buildCodeCheckItems,buildGeneralInfo,buildOverview,deliverableNoticesFrom,detectItemCategory,DOC_SCORE_BY_OUTCOME,projectNameOf,prototypeFilesOf,scoreInt,shortfallFrom} from './utils.js';
import {printVerificationReport} from './verificationReport.js';
import {ARTIFACT_SCORE_BY_OUTCOME,DOWNLOAD_FILES,FINAL_THRESHOLD,PLAN_DOCUMENT_SECTIONS_REWORKED} from './data.js';

// verdict: GET /result의 VerdictOut. 검증결과서의 "종합 판정"을 서버 점수로 찍기 위해 받는다
// (없으면 화면 값으로 계산 — verificationReport.js 참고).
// deliverable: GET /result의 DeliverableOut — 제출 안내 · 계획서 고지 문구(없으면 고정 문구).
export function ReviewScreen({ announcement, itemInfo, docOutcome = 'fail', artifactOutcome = 'fail', onGoDashboard, projectId, verdict = null, scores = null, plan = null, deliverable = null }){
  // 화면 점수와 내려받는 검증결과서 점수가 어긋나지 않도록, 둘 다 서버 값을 본다.
  const docScore = scores?.docScore || DOC_SCORE_BY_OUTCOME[docOutcome];
  const artifactScore = scores?.artifactScore || ARTIFACT_SCORE_BY_OUTCOME[artifactOutcome];
  const threshold = scores?.threshold ?? FINAL_THRESHOLD;
  const finalTotal = scores?.total ?? (docScore.raw + artifactScore.autoCheck.raw + artifactScore.crossCheck.raw);
  const passed = finalTotal >= threshold;
  const itemTitle = announcement ? announcement.title : '';
  // 아래 고지 4줄. 서버가 준 제출 안내 · 계획서 고지가 있으면 그 문구로(utils.js deliverableNoticesFrom).
  const notices = deliverableNoticesFrom(deliverable);
  // 제출 전에 보완하면 좋은 항목(deliverable.shortfall_items) — 없으면 null이라 칸을 그리지 않는다.
  const shortfall = shortfallFrom(deliverable);
  const [showAllShortfall, setShowAllShortfall] = useState(false);
  // 프로토타입 압축에 넣을 실제 파일(실행 파일 · 인포그래픽)을 화면이 열릴 때 미리 받아 둔다. 누른 뒤에 받으면 받는 동안
  // 브라우저가 '누른 다운로드'로 보지 않고 저장을 막는 경우가 있었다(10-13 — 파일은 받아졌는데 저장이 안 됨).
  // 미리 받아 두면 누르는 순간 바로 묶어 저장한다. 아직 받는 중이면 끝날 때까지 기다렸다가 저장한다.
  const prototypeFiles = projectId ? prototypeFilesOf(plan) : [];
  const prototypeKey = prototypeFiles.map((f) => f.path).join('|');
  const prototypeFetch = useRef(null);
  useEffect(() => {
    prototypeFetch.current = null;
    if (!prototypeKey) return;
    const pending = Promise.all(prototypeFiles.map(async ({ path, name }) => ({ name, data: new Uint8Array(await (await fetchUploadBlob(path)).arrayBuffer()) })));
    pending.then((entries) => { if (prototypeFetch.current?.pending === pending) prototypeFetch.current.entries = entries; }, () => {});
    prototypeFetch.current = { pending, entries: null };
  }, [prototypeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const planNotice = notices.find((n) => n.label === '계획서')?.text;
  // 받기 실패 안내 — 카드 이름(DOWNLOAD_FILES name, 전체 다운로드는 'all')마다 한 줄. 실제 프로젝트에서는 실패했을 때
  // 예시 파일로 몰래 바꿔 주지 않고 이 안내를 띄운다(예전엔 계획서 · 프로토타입이 예시 파일로 받아져 진짜인 줄 알았다).
  // 한글(.hwp)은 서버에 rhwp가 있어야만 만들어진다(RHWP_BIN) — 그래서 사유를 따로 적는다.
  const [downloadErrors, setDownloadErrors] = useState({});
  const setDownloadError = (name, message) => setDownloadErrors((errors) => ({ ...errors, [name]: message }));
  // 받는 중인 버튼('카드이름:형식', 전체는 'all') — 한글은 서버가 만드는 데 10초 넘게 걸려, 표시가 없으면 안 눌린 줄 안다.
  const [busy, setBusy] = useState({});
  const track = (key, promise) => {
    setBusy((b) => ({ ...b, [key]: true }));
    return promise.finally(() => setBusy((b) => ({ ...b, [key]: false })));
  };

  function handleDownload(file, format){
    // formats가 있는 항목은 어느 형식 버튼을 눌렀는지가 같이 온다 — '전체 다운로드'처럼
    // 형식을 안 넘기면 기본 형식(formats[0], 사업계획서는 docx)으로 받는다.
    const ext = format ?? file.formats?.[0]?.ext;
    setDownloadError(file.name, '');
    if (file.name === '사업계획서' && ext === 'hwp') {
      if (!projectId) {
        setDownloadError(file.name, '미리보기 화면에서는 한글 파일을 만들 수 없습니다 — 실제 프로젝트에서 내려받아 주세요.');
        return;
      }
      track('사업계획서:hwp', downloadPlanHwp(projectId)).catch((err) => {
        console.error('한글 사업계획서 다운로드 실패:', err);
        setDownloadError(file.name, '한글 파일을 만들지 못했습니다 — 서버에 한글 변환기(rhwp)가 설치돼 있는지 확인해 주세요. 워드(.docx)는 그대로 받을 수 있습니다.');
      });
      return;
    }
    if (file.name === '사업계획서') {
      // projectId가 있으면 서버가 신청자 유형별 공식 양식 구조로 채운 진짜 .docx를 내려준다(app/plan_document_export.py).
      // 실패하면 예시 문서로 바꿔 주지 않고 안내를 띄운다. projectId가 없는 미리보기 화면에서만 예시 문서를 만든다.
      if (projectId) {
        track('사업계획서:docx', downloadPlanDocument(projectId)).catch((err) => {
          console.error('사업계획서 다운로드 실패:', err);
          setDownloadError(file.name, '워드 파일을 받지 못했어요. 잠시 후 다시 시도해 주세요.');
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
        footer: planNotice,
      });
      return;
    }
    if (file.name === 'prototype.zip') {
      // 실제 프로젝트는 서버의 실행 파일 · 인포그래픽을 받아 한 압축 파일로 묶는다. 아래 예시 화면 압축은 미리보기 화면 전용.
      if (projectId) {
        const prefetched = prototypeFetch.current;
        if (!prototypeFiles.length || !prefetched) {
          setDownloadError(file.name, '프로토타입 파일이 아직 없어요. 종합 평가까지 마친 뒤 다시 시도해 주세요.');
          return;
        }
        const save = (entries) => triggerDownload(buildZip(entries), 'prototype.zip', 'application/zip');
        if (prefetched.entries) {
          save(prefetched.entries); // 누른 그 자리에서 바로 저장
          return;
        }
        track('prototype.zip:default', prefetched.pending.then(save)).catch((err) => {
          console.error('프로토타입 다운로드 실패:', err);
          // 실패한 받기는 다음에 누를 때 다시 받는다
          prototypeFetch.current = null;
          setDownloadError(file.name, '프로토타입 파일을 받지 못했어요. 화면을 새로 고친 뒤 다시 시도해 주세요.');
        });
        return;
      }
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
      // ArtifactResult.jsx와 같은 이유 — 서버가 정한 artifact.category를 우선 쓴다.
      const category = plan?.artifacts?.[0]?.category || detectItemCategory(itemInfo?.item);
      printVerificationReport({
        projectName: projectNameOf(itemInfo?.item),
        announcementTitle: itemTitle,
        category,
        docScore,
        codeCheckItems: scores?.codeCheckItems || buildCodeCheckItems(category, artifactOutcome),
        crossCheck: artifactScore.crossCheck,
        threshold,
        verdict,
      });
      return;
    }
  }

  // 전체 다운로드 — 실제 프로젝트는 서버가 묶은 결과물 한 파일(deliverable.zip: 계획서 워드 · 그림 · 실행 파일 · 인포그래픽).
  // 검증결과서는 화면이 그리는 문서라 묶음에 없고 아래 카드에서 따로 저장한다.
  // 미리보기 화면(projectId 없음)은 예전처럼 카드마다 받는다 — 브라우저가 같은 틱의 여러 다운로드를 막지 않게 간격을 둔다.
  const handleDownloadAll = () => {
    if (projectId) {
      setDownloadError('all', '');
      track('all', downloadDeliverableZip(projectId)).catch((err) => {
        console.error('결과물 묶음 다운로드 실패:', err);
        setDownloadError('all', err?.status === 404 ? '아직 내려받을 수 있는 결과물이 없어요.' : '결과물 묶음을 받지 못했어요. 잠시 후 다시 시도해 주세요.');
      });
      return;
    }
    DOWNLOAD_FILES.forEach((f, i) => setTimeout(() => handleDownload(f), i * 400));
  };
  // 미리보기 화면에서만 예시 파일이라는 표시를 단다(실제 프로젝트 파일에는 달지 않는다).
  const previewTitle = projectId ? undefined : '미리보기용 예시 파일입니다 — 형식만 실제와 같습니다';

  return (
    <section data-screen="review" className="max-w-3xl mx-auto px-6 py-16">
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">최종 결과물</p>
      {/* 공고 제목을 모르면(알림에서 연 프로젝트 · 공고 표에서 빠진 공고) 빈 『』를 그리지 않는다 */}
      {announcement?.title && <p className="text-[14px] text-[var(--muted-fg)] leading-snug mb-1.5">『{announcement.title}』</p>}
      <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">결과물이 준비됐어요</h1>
      {/* 조율 2026-10-15부터 검수(문장 다듬기)는 흐름에서 빠졌다 — 화면 9 '진행' 뒤 결과 통합만 돌고 바로 이 화면이다.
          예전엔 이 자리에 문단별 수정 전/후가 있었고, 검수 기록이 없으면 시연용 예시 문단을 대신 보였다. */}
      <p className="text-[14.5px] text-[var(--muted-fg)] mb-1">계획서 · 프로토타입 · 검증결과서를 아래에서 내려받을 수 있어요</p>
      <p className="text-[12.5px] text-[var(--muted-fg)] mb-8">이 단계부터는 이전 화면으로 돌아갈 수 없습니다</p>

      <div className="border-t border-[var(--border)] pt-6">
        <div className="flex items-center justify-between gap-4 flex-wrap mb-6 px-5">
          <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide">결과물</p>
          <button onClick={handleDownloadAll} title={previewTitle} disabled={!!busy.all}
            className="flex-shrink-0 text-[12.5px] font-semibold text-[var(--primary)] hover:underline disabled:opacity-60 disabled:no-underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
            {busy.all ? '받는 중…' : '전체 다운로드'}
          </button>
        </div>
        {projectId && (
          <p className="-mt-4 mb-5 px-5 text-[12px] text-[var(--muted-fg)] leading-relaxed">
            전체 다운로드는 계획서(워드) · 그림 · 실행 파일 · 인포그래픽을 압축 파일 하나로 받아요. 검증결과서는 아래에서 따로 저장해요.
          </p>
        )}
        {downloadErrors.all && <p role="alert" className="-mt-3 mb-5 px-5 text-[12.5px] leading-relaxed text-[var(--danger)]">{downloadErrors.all}</p>}
        {!passed && (
          <p className="text-[13px] text-[var(--fg)] mb-4">현재 {scoreInt(finalTotal)}점으로 저장됩니다 — 종합 평가에서 확인한 점수가 그대로 기록됩니다</p>
        )}

        {shortfall && (
          <div data-testid="shortfall" className="rounded-2xl border border-[var(--border)] bg-white p-5 mb-6">
            <p className="font-semibold text-[15px] mb-1">제출 전에 보완하면 좋은 항목</p>
            <p className="text-[12.5px] text-[var(--muted-fg)] leading-relaxed mb-3">검증에서 기준에 못 미쳤거나 지적된 항목이에요. 총점이 통과여도 제출 전에 직접 확인해 주세요.</p>
            {[['사업계획서', shortfall.document], ['프로토타입', shortfall.artifact]].filter(([, rows]) => rows.length).map(([title, rows]) => {
              // 묶음마다 처음 다섯 줄만 보이고 나머지는 펼쳐 본다 — 실제 실행 건은 계획서 줄이 열 줄 넘게 올 수 있다.
              const shown = showAllShortfall ? rows : rows.slice(0, 5);
              return (
                <div key={title} className="mt-3 first:mt-0">
                  <p className="text-[12px] font-bold text-[var(--muted-fg)] mb-1">{title}</p>
                  <ul className="flex flex-col gap-1.5">
                    {shown.map((row) => (
                      <li key={row.key} className="text-[13px] leading-relaxed text-[var(--fg)]">
                        {row.bundle && <span className="text-[var(--muted-fg)]">{row.bundle} · </span>}
                        <span className="font-semibold">{row.name}</span>
                        {row.points && <span className="ml-1 text-[12px] text-[var(--muted-fg)]">{row.points}</span>}
                        {row.inputError && <span className="ml-1.5 text-[11px] font-semibold text-[var(--warn)]">입력 확인</span>}
                        {row.reason && <span className="text-[var(--muted-fg)]"> — {row.reason}</span>}
                      </li>
                    ))}
                  </ul>
                  {rows.length > shown.length && (
                    <button type="button" onClick={() => setShowAllShortfall(true)} className="mt-1.5 text-[12px] font-semibold text-[var(--primary)] hover:underline">
                      외 {rows.length - shown.length}개 더 보기
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div className="flex flex-col gap-3 mb-6">
          {DOWNLOAD_FILES.map((f) => (
            <div key={f.name} className="rounded-2xl border border-[var(--border)] bg-white p-5">
              <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                  <p className="font-semibold text-[15px] mb-1">{f.title || f.name}</p>
                  <p className="text-[12.5px] text-[var(--muted-fg)]">{f.desc}</p>
                  {f.file && <p className="mt-1 text-[11.5px] font-mono text-[var(--muted-fg)]">{f.file}</p>}
                </div>
                {/* 형식이 여러 개인 항목(사업계획서: 워드/한글)은 버튼을 형식별로 나눠 그린다 —
                    받기 전에 어느 형식인지 보이게 하려고 드롭다운 대신 버튼을 둘 다 노출한다. */}
                <div className="flex-shrink-0 flex items-center gap-2 flex-wrap">
                  {(f.formats ?? [null]).map((fmt) => (
                    <button key={fmt?.ext ?? 'default'} onClick={() => handleDownload(f, fmt?.ext)}
                      title={previewTitle} disabled={!!busy[`${f.name}:${fmt?.ext ?? 'default'}`]}
                      className="rounded-lg border border-[var(--border)] px-4 py-2 text-[13px] font-semibold hover:bg-[var(--bg)] disabled:opacity-60 disabled:cursor-wait transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
                      {busy[`${f.name}:${fmt?.ext ?? 'default'}`] ? '만드는 중…' : fmt ? fmt.label : f.action || '다운로드'}
                    </button>
                  ))}
                </div>
              </div>
              {f.hint && <p className="mt-2 text-[11.5px] text-[var(--muted-fg)] leading-relaxed">{f.hint}</p>}
              {downloadErrors[f.name] && (
                <p role="alert" className="mt-3 text-[12.5px] leading-relaxed text-[var(--danger)]">{downloadErrors[f.name]}</p>
              )}
            </div>
          ))}
        </div>

        <ul className="flex flex-col gap-1.5 mb-8">
          {notices.map((n) => (
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
