import React, {useState,useRef,useEffect} from 'react';
import Preparation from '../components/Preparation.jsx';
import {Icon} from '../components/Icons.jsx';
import {getMatchCandidates,generatePipeline} from '../api.js';
import {downloadPlanDocx,downloadPrototypeZip,downloadVerificationPdf} from '../dummyDeliverables.js';
import {downloadPlanDocument} from '../api.js';
function FloatingInput({inputRef,type,value,onChange,label}){
  return <label className="block text-[14px] text-[var(--muted-fg)]"><span className="block mb-2">{label}</span><input ref={inputRef} type={type} value={value} onChange={onChange} onInput={onChange} onBlur={onChange} className="w-full border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--fg)]"/></label>;
}
function SiteMock(){
  return <div className="absolute inset-0 flex items-center justify-center p-5"><div className="w-full max-w-[350px] overflow-hidden rounded-xl border border-[var(--border)] bg-white shadow-lg"><div className="border-b border-[var(--border)] px-4 py-2 text-[12px] text-[var(--muted-fg)]">프로토타입 화면 예시</div><div className="p-5"><div className="font-bold text-[14px]">LOCALFIT</div><h3 className="mt-4 text-[19px] font-bold">오늘, 가까운 곳에서 시작.</h3><p className="mt-2 text-[12px] text-[var(--muted-fg)]">우리 동네 운동시설을 한 곳에서.</p><div className="mt-4 flex gap-2 text-[12px]">{['피트니스','필라테스','요가'].map(x=><span key={x} className="rounded bg-[var(--muted)] px-2 py-1">{x}</span>)}</div></div></div></div>;
}
function BackButton({ onClick, label = '이전 단계로 돌아가기' }){
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
const SIMILAR_ANNOUNCEMENT_ALERTS = [
  { id: 1, itemName: '동네 헬스장 예약 서비스', title: 'AI 서비스 실증지원 사업', org: '정보통신산업진흥원', similarity: 87, detectedAt: '2026-09-09' },
  { id: 2, itemName: '중고거래 안전결제 플랫폼', title: '생활밀착형 서비스 창업 지원사업', org: '중소벤처기업부', similarity: 81, detectedAt: '2026-09-07' },
];

// 이메일 발송은 이번 범위에서 제외(최종발표 이후 유료화 검토와 함께 진행) — 카카오
// 알림톡은 사업자등록이 있어야 보낼 수 있어 예비창업자 사용자를 못 받아 대상에서
// 제외했다. 그래서 여기선 "화면·등록 목록·페이지 내 알림"까지만 만들고, 이메일
// 항목은 흐리게 표시만 해서 로드맵은 보여주되 기능은 없다는 걸 분명히 한다.
function NotificationBell({ enabled, onToggle, alerts = [] }){
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
function FileAttach({ files, onAdd, onRemove }){
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
function IntakeForm({ onSubmit, onBack, backLabel = '처음으로 돌아가기' }){
  const itemRef = useRef(null);
  const ceoRef = useRef(null);
  const foundedRef = useRef(null);
  const [applicantType, setApplicantType] = useState(null); // 'preliminary' | 'individual' | 'corp'
  const [item, setItem] = useState('');
  const [files, setFiles] = useState([]);
  const [ceoName, setCeoName] = useState('');
  const [foundedAt, setFoundedAt] = useState('');
  const [team, setTeam] = useState([{ name: '', role: '', experience: '' }]);
  const [noTeam, setNoTeam] = useState(false);
  const [pricing, setPricing] = useState([{ item: '', price: '' }]);

  

  const addFiles = (added) => setFiles((prev) => [...prev, ...added]);
  const removeFile = (i) => setFiles((prev) => prev.filter((_, idx) => idx !== i));
  const updateRow = (list, setList, i, key, value) => {
    setList(list.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)));
  };
  const addRow = (list, setList, empty) => setList([...list, empty]);
  const removeRow = (list, setList, i) => setList(list.filter((_, idx) => idx !== i));

  const isPreliminary = applicantType === 'preliminary';
  const applicantValid = !!applicantType;
  const companyValid = isPreliminary || (ceoName.trim().length > 0 && !!foundedAt);
  const ideaValid = item.trim().length > 5;
  const teamValid = noTeam || team.every((r) => r.name.trim() && r.role.trim() && r.experience.trim());
  const pricingValid = pricing.every((r) => r.item.trim() && r.price.trim());
  const valid = applicantValid && companyValid && ideaValid && teamValid && pricingValid;

  // 실제 POST /projects 호출은 여기서 하지 않는다 — App.jsx의 handleIntakeSubmit이 이 폼
  // 정보를 받아서 만든다(project_id를 App 쪽 상태(projectId)로 들고 있어야 다음 화면들
  // (MatchResults 등)에 넘겨줄 수 있어서). 여기서는 유효성 검사만 하고 폼 값을 그대로 올려보낸다.
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!valid) return;
    onSubmit({
      applicantType, item, files,
      ceoName: isPreliminary ? '' : ceoName,
      foundedAt: isPreliminary ? '' : foundedAt,
      team: noTeam ? [] : team,
      pricing,
    });
  };

  return (
    <section data-screen="intake" className="max-w-2xl mx-auto px-6 py-16">
      <BackButton onClick={onBack} label={backLabel} />
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">사전 정보 입력</p>
      <h1 className="font-display font-bold text-[28px] md:text-[34px] mb-3">어떤 아이디어를 준비하고 있나요?</h1>
      <p className="text-[15px] text-[var(--muted-fg)] mb-10">아이템과 신청자 정보를 알려주시면 맞는 공고를 찾아드릴게요.</p>

      <form onSubmit={handleSubmit}>
        <div className="mb-10">
          <h2 className="font-bold text-[15px] mb-3">신청자 유형</h2>
          <div className="grid grid-cols-3 gap-3">
            {[['preliminary', '예비창업자'], ['individual', '개인사업자'], ['corp', '법인']].map(([val, label]) => (
              <button key={val} type="button" onClick={() => setApplicantType(val)} aria-pressed={applicantType === val}
                className={`rounded-xl border-2 py-3.5 text-[14px] font-semibold transition-[border-color,background-color,scale] duration-150 ease-out active:scale-[0.97] ${applicantType === val ? 'border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_6%,white)]' : 'border-[var(--border)] bg-white hover:border-[var(--muted-fg)]'}`}>
                {label}
              </button>
            ))}
          </div>

          {applicantType && !isPreliminary && (
            <div className="grid sm:grid-cols-2 gap-4 mt-4">
              <FloatingInput inputRef={ceoRef} type="text" value={ceoName} onChange={(e) => setCeoName(e.target.value)} label="대표자명" />
              <FloatingInput inputRef={foundedRef} type="date" value={foundedAt} onChange={(e) => setFoundedAt(e.target.value)} label="설립일자" />
            </div>
          )}
        </div>

        <div className="mb-10">
          <label htmlFor="idea" className="block text-[13.5px] font-semibold mb-2">아이디어 설명</label>
          <textarea id="idea" ref={itemRef} value={item} onChange={(e) => setItem(e.target.value)} rows={5}
            placeholder="예) 반려견 산책 도우미를 구해주는 매칭 플랫폼을 만들고 있어요"
            className="w-full border border-[var(--border)] rounded-xl p-4 text-[15px] bg-white focus:border-[var(--primary)] focus:border-2 outline-none resize-none transition-colors placeholder:text-[var(--muted-fg)]" />
          <FileAttach files={files} onAdd={addFiles} onRemove={removeFile} />
        </div>

        <div className="mb-10 pt-6 border-t border-[var(--border)]">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-[15px]">팀 구성원 경력</h2>
            {!noTeam && (
              <button type="button" onClick={() => addRow(team, setTeam, { name: '', role: '', experience: '' })}
                className="text-[13px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
                + 팀원 추가
              </button>
            )}
          </div>
          <label className="flex items-center gap-2 mb-3 text-[13px] font-semibold text-[var(--muted-fg)] cursor-pointer select-none">
            <input type="checkbox" checked={noTeam} onChange={(e) => setNoTeam(e.target.checked)}
              className="w-4 h-4 accent-[var(--primary)]" />
            팀원 없음 (1인 창업)
          </label>
          {noTeam ? (
            <p className="text-[13px] text-[var(--muted-fg)] bg-[var(--muted)] rounded-xl p-4">혼자 준비하고 계시는군요. 팀 정보는 입력하지 않아도 돼요.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {team.map((row, i) => (
                <RepeatableRow key={i} values={row} removable={team.length > 1}
                  onRemove={() => removeRow(team, setTeam, i)}
                  onChange={(key, value) => updateRow(team, setTeam, i, key, value)}
                  fields={[
                    { key: 'name', label: '이름', placeholder: '홍길동' },
                    { key: 'role', label: '역할', placeholder: '대표 · 개발' },
                    { key: 'experience', label: '경력', placeholder: '제빵 경력 8년' },
                  ]} />
              ))}
            </div>
          )}
        </div>

        <div className="mb-10">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-bold text-[15px]">수익모델 단가</h2>
            <button type="button" onClick={() => addRow(pricing, setPricing, { item: '', price: '' })}
              className="text-[13px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
              + 항목 추가
            </button>
          </div>
          <p className="text-[12px] text-[var(--muted-fg)] mb-3">매출을 예상하는 데 사용할 상품과 가격을 알려주세요.</p>
          <div className="flex flex-col gap-3">
            {pricing.map((row, i) => (
              <RepeatableRow key={i} values={row} removable={pricing.length > 1}
                onRemove={() => removeRow(pricing, setPricing, i)}
                onChange={(key, value) => updateRow(pricing, setPricing, i, key, value)}
                fields={[
                  { key: 'item', label: '상품·서비스', placeholder: '주문 1건당 수수료' },
                  { key: 'price', label: '단가', placeholder: '500원' },
                ]} />
            ))}
          </div>
        </div>

        <button type="submit" disabled={!valid}
          className="w-full rounded-xl bg-[var(--primary)] text-white py-3.5 text-[15px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
          맞는 공고 찾기
        </button>
        {!valid && (
          <p className="mt-2 text-[12.5px] text-[var(--muted-fg)] text-center">
            {!applicantValid ? '신청자 유형을 선택해주세요'
              : !companyValid ? '대표자명과 설립일자를 입력해주세요'
              : !ideaValid ? '아이디어 설명을 6자 이상 입력해주세요'
              : !teamValid ? '팀원 정보를 모두 입력하거나 팀원 없음을 선택해주세요'
              : '수익모델 단가 항목을 모두 입력해주세요'}
          </p>
        )}
      </form>
    </section>
  );
}

function MatchProgress({onComplete}){return <Preparation kind="match" onComplete={onComplete}/>;}

const MOCK_TODAY = new Date('2026-09-08');

function yearsSince(dateStr){
  const then = new Date(dateStr);
  let years = MOCK_TODAY.getFullYear() - then.getFullYear();
  const m = MOCK_TODAY.getMonth() - then.getMonth();
  if (m < 0 || (m === 0 && MOCK_TODAY.getDate() < then.getDate())) years--;
  return years;
}

// R-2(신청 자격 확인) 요약: 구조화 필드 비교만으로 통과·불통과를 정한다. LLM을 호출하지
// 않으므로 같은 입력에 항상 같은 결과가 나온다. COMP-ID-002: 설립일자 미입력 = 예비창업자.
function evaluateEligibility(rule, company){
  const isPreFounding = !company.foundedAt;
  const ageYears = isPreFounding ? null : yearsSince(company.foundedAt);

  const typeOk =
    rule.applicantType === '제한없음' ? true :
    rule.applicantType === '예비창업자' ? isPreFounding :
    !isPreFounding && (rule.ageLimitYears == null || ageYears <= rule.ageLimitYears);

  const ageOk = rule.ageLimitYears == null ? true : isPreFounding ? true : ageYears <= rule.ageLimitYears;
  const deadlineOk = MOCK_TODAY <= new Date(rule.deadline);

  const rows = [
    {
      label: '지원대상 유형',
      criterion: rule.applicantType,
      actual: isPreFounding ? '예비창업자' : `업력 ${ageYears}년 기업`,
      passed: typeOk,
    },
    {
      label: '업력 상한',
      criterion: rule.ageLimitYears == null ? '제한없음' : `${rule.ageLimitYears}년 이내`,
      actual: isPreFounding ? '해당없음 (예비창업자)' : `${ageYears}년`,
      passed: ageOk,
    },
    {
      label: '접수기간',
      criterion: `${rule.deadline} 마감`,
      actual: deadlineOk ? '접수 중' : '마감 지남',
      passed: deadlineOk,
    },
  ];

  return { rows, passed: rows.every((r) => r.passed) };
}

// 목업 수정 요청서 v3 §4: reason(매칭 사유)은 모델이 생성한 요약이라 기획서 6-1이
// 출처 표기 + 원문 링크를 함께 요구한다. sourceNotice는 시연 로그(steps[2].data.
// candidates[].sourceNotice)와 동일하게 모든 공고에 같은 문구를 쓰고, originalUrl은
// 공고별로 다르다(초기창업패키지·예비창업패키지·창업도약패키지 3건은 시연 로그의
// 실제 K-Startup 공고 ID를 그대로 썼다).
const AI_SUMMARY_SOURCE_NOTICE = '본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.';

const ANNOUNCEMENTS = [
  {
    title: '초기창업패키지',
    org: '창업진흥원',
    deadline: '2026-10-15 마감',
    amount: '최대 1억원',
    fit: 92,
    reason: '제조·서비스 기반 창업 아이템과 지원 분야가 일치합니다',
    eligibility: { applicantType: '창업 3년 이내 기업', ageLimitYears: 3, deadline: '2026-10-15' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
  {
    title: '예비창업패키지',
    org: '창업진흥원',
    deadline: '2026-09-30 마감',
    amount: '최대 5천만원',
    fit: 81,
    reason: '예비창업자 대상 지원 요건과 일치합니다',
    eligibility: { applicantType: '예비창업자', ageLimitYears: null, deadline: '2026-09-30' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
  {
    title: '지역특화 스마트상점 기술보급 지원사업',
    org: '중소벤처기업부',
    deadline: '2026-11-01 마감',
    amount: '최대 3천만원',
    fit: 68,
    reason: '오프라인 매장 디지털 전환 지원 항목과 부합합니다',
    eligibility: { applicantType: '제한없음', ageLimitYears: null, deadline: '2026-11-01' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
  {
    title: '창업도약패키지',
    org: '창업진흥원',
    deadline: '2026-10-30 마감',
    amount: '최대 3억원',
    fit: 64,
    reason: '업력 3~7년차 성장기 창업기업 지원 요건과 유사합니다',
    eligibility: { applicantType: '창업 3년 이내 기업', ageLimitYears: 7, deadline: '2026-10-30' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
  {
    title: '소상공인 디지털전환 지원사업',
    org: '소상공인시장진흥공단',
    deadline: '2026-12-01 마감',
    amount: '최대 2천만원',
    fit: 58,
    reason: '소상공인 대상 디지털 전환 지원 항목과 유사합니다',
    eligibility: { applicantType: '제한없음', ageLimitYears: null, deadline: '2026-12-01' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
  {
    title: '여성기업 창업경진대회',
    org: '여성기업종합지원센터',
    deadline: '2026-09-20 마감',
    amount: '최대 3천만원',
    fit: 51,
    reason: '창업 경진대회형 지원사업으로 심사 방식이 다릅니다',
    eligibility: { applicantType: '예비창업자', ageLimitYears: null, deadline: '2026-09-20' },
    originalUrl: 'https://www.k-startup.go.kr/',
  },
];

// 자격 판정은 미리 화면에 뿌리지 않는다(사용자 요청) — 추천 사유가 있어서 보여준
// 공고인데 미리 비활성화해버리면 "왜 추천했는지" 납득이 안 된다. 대신 사용자가
// 직접 눌러서 신청 자격 확인까지 갔다가 불통과를 확인하고 "다른 공고 다시 보기"로
// 돌아왔을 때만 그 공고를 비활성화한다(disabledTitles, App state) — 즉 비활성화는
// 사용자 자신의 확인 행동에서 나온다.
// 기획서 4-1/4-2②: 공고는 매칭 결과로만 등장하고, 전체 목록을 보여주지 않는다 —
// 적합도 상위 3건만 카드로 제시한다("더 보기"로 나머지를 펼치지 않는다). 공고를
// 먼저 훑어보고 거기 맞춰 아이템을 지어내는 흐름이 되지 않도록 하는 게 목적이다.
const RESULTS_SHOWN_COUNT = 3;

// [2026-09-15, 프론트 통합 임시 구현] 예전엔 ANNOUNCEMENTS(하드코딩 6건)를 그대로 3건
// 잘라 보여줬는데, 이제 마운트 시 GET /projects/{id}/match-candidates(api.js
// getMatchCandidates)로 실제 후보를 받아온다 — 백엔드가 아직 아무것도 저장하지 않은 채
// 후보만 계산해서 보여주는 단계라(app/routers/projects.py get_match_candidates 주석 참고),
// 사용자가 "신청 자격 확인하기"를 누르는 순간에만 POST /generate(generatePipeline)를 호출해
// 실제 매칭·자격판정·계획서·산출물·최종판정을 한 번에 만든다.
function MatchResults({projectId,onBack,onCheckEligibility,disabledTitles=[],backLabel='아이템 정보 다시 입력하기'}){
 const [selected,setSelected]=useState(null);
 const [results,setResults]=useState([]);
 const [loading,setLoading]=useState(true);
 const [loadError,setLoadError]=useState(false);
 const [confirming,setConfirming]=useState(false);
 const [confirmError,setConfirmError]=useState('');

 useEffect(()=>{
  if(!projectId)return;
  let cancelled=false;
  setLoading(true);setLoadError(false);
  getMatchCandidates(projectId).then(rows=>{
   if(cancelled)return;
   setResults(rows.slice(0,RESULTS_SHOWN_COUNT));
   setLoading(false);
  }).catch(err=>{
   console.error('매칭 후보를 불러오지 못했어요',err);
   if(!cancelled){setLoadError(true);setLoading(false);}
  });
  return ()=>{cancelled=true};
 },[projectId]);

 const confirm=async(r)=>{
  setConfirming(true);setConfirmError('');
  try{
   const generateResult=await generatePipeline(projectId,r.notice_id);
   onCheckEligibility(r,generateResult);
  }catch(err){
   console.error('신청 자격을 확인하지 못했어요',err);
   setConfirmError(err.message||'신청 자격을 확인하지 못했어요. 다시 시도해 주세요.');
   setConfirming(false);
  }
 };

 return <section data-screen="matches" className="matches-page">
  <p className="section-label">공고 찾기</p>
  <h1>이런 공고가 잘 맞아요</h1>
  <p>아이템과 잘 맞는 순서로 {RESULTS_SHOWN_COUNT}건을 골랐어요. 신청 자격을 확인해 보세요.</p>
  {loading&&<p className="matched-note">공고를 찾는 중이에요…</p>}
  {loadError&&<p className="matched-note">공고를 불러오지 못했어요. 새로고침해 주세요.</p>}
  {!loading&&!loadError&&results.length===0&&<p className="matched-note">지금은 모집 중인 공고가 없어요.</p>}
  <div className="matched-list">
   {results.map((r,i)=>{
    const disabled=disabledTitles.includes(r.title);
    return <article key={r.notice_id} className={'matched-row '+(selected===r.notice_id?'selected':'')+(disabled?'disabled':'')}>
     <button className="matched-select" disabled={disabled} aria-pressed={selected===r.notice_id} onClick={()=>setSelected(r.notice_id)}>
      <span className="match-rank">{i+1}</span>
      <div><span className="match-org">{r.org||'주관기관 정보 없음'}</span><h3>{r.title}</h3><p>{r.apply_end?`${r.apply_end} 마감`:'마감일 정보 없음'}</p></div>
      <span className="match-fit"><b>{r.fit_score}<small>%</small></b><span>아이템 적합도</span></span>
     </button>
     <div className="matched-detail">
      <p>{disabled?'신청 자격에 맞지 않는 공고예요. 다른 공고를 선택해 주세요.':<React.Fragment>{r.reason}<br/><span className="match-source-notice">{AI_SUMMARY_SOURCE_NOTICE}</span></React.Fragment>}</p>
      {r.url&&<a href={r.url} target="_blank" rel="noopener noreferrer">공고 사이트 확인 <Icon name="chevron" size={14}/></a>}
     </div>
     {selected===r.notice_id&&!disabled&&<div className="matched-action">
      <span>{confirming?'신청 자격을 확인하는 중이에요…':'이 공고의 신청 조건을 확인할까요?'}</span>
      <button className="btn" disabled={confirming} onClick={()=>confirm(r)}>{confirming?'확인 중…':'신청 자격 확인하기'}</button>
     </div>}
     {selected===r.notice_id&&confirmError&&<p className="matched-note">{confirmError}</p>}
    </article>;
   })}
  </div>
  <p className="matched-note">AI가 임시로 생성한 공고와 적합도예요. 실제 접수 여부는 공고 사이트에서 확인해 주세요.</p>
  <button className="text-link back-link" onClick={onBack}>{backLabel}</button>
 </section>;
}

function GeneratingOverlay({children}){
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
function EligibilityGate({announcement,eligibility,onProceed,onLeave}){
 const passed=eligibility?.passed??false;
 const undecidable=eligibility?.undecidable??false;
 const failedConditions=eligibility?.failed_conditions||[];
 const missingInputs=eligibility?.missing_inputs||[];
 const [generating,setGenerating]=useState(false);
 const leave=()=>onLeave(announcement.title,!passed);
 return <><section data-screen="eligibility" className="eligibility-page">
  <BackButton onClick={leave} label="매칭 결과로 돌아가기"/>
  <div className={'eligibility-symbol '+(passed?'':'failed')}><Icon name={passed?'check':'file'} size={32}/></div>
  <p className="section-label">{announcement.title}</p>
  <h1>{passed?'신청 조건을 충족해요':undecidable?'자격 판정을 확정하지 못했어요':'확인이 필요한 조건이 있어요'}</h1>
  <p>{passed?'입력한 정보로 확인했어요. 이제 사업계획서를 준비해 볼까요?':undecidable?'입력한 정보만으로는 판단하기 어려운 항목이 있어요.':'이 공고의 조건과 맞지 않는 항목이 있어요. 다른 공고를 확인해 주세요.'}</p>
  {(failedConditions.length>0||missingInputs.length>0)&&<div className="eligibility-list">
   {failedConditions.map((c,i)=><div className="eligibility-row" key={'fail-'+i}><div><b>충족하지 않는 조건</b><p>{typeof c==='string'?c:JSON.stringify(c)}</p></div><div><small className="fail-text">미충족</small></div></div>)}
   {missingInputs.map((m,i)=><div className="eligibility-row" key={'missing-'+i}><div><b>추가로 필요한 정보</b><p>{typeof m==='string'?m:JSON.stringify(m)}</p></div><div><small className="fail-text">확인 필요</small></div></div>)}
  </div>}
  <div className="eligibility-action"><p>등록하신 정보를 기준으로 AI가 확인한 결과예요.</p><button className="btn" onClick={()=>passed?setGenerating(true):leave()}>{passed?'사업계획서 작성하기':'다른 공고 다시 보기'}</button></div>
 </section>{generating&&<GeneratingOverlay><PipelineProgress onComplete={onProceed}/></GeneratingOverlay>}</>;
}

function RepeatableRow({ values, fields, onChange, onRemove, removable }){
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
const PLAN_STAGE_TASKS = [
  { agent: '전략', task: '요구사항 분석' },
  { agent: '전략', task: '목표 시장 분석' },
  { agent: '작성', task: '사업계획서 본문 작성' },
  { agent: '작성', task: '그래프 생성' },
  { agent: '작성', task: '표 생성' },
  { agent: '검증-1', task: '사업계획서 검증' },
];

// 실제로는 본문·표·그래프가 한 Task 안에서 같이 만들어지지만, 진행률 %만 보고는
// "지금 뭘 하는지" 감이 안 온다는 피드백에 따라 이 세 가지를 작게 순환시켜 보여준다
// — 스피너가 도는 항목이 "지금" 진행 중인 것이라는 신호다.
const WRITING_SUBTASKS = ['사업계획서 본문 작성', '그래프 생성', '표 생성'];

// PRJ-ID-009: 진행률만 보여준다 — Agent별 단계를 다 나열하면 사용자가 볼 필요 없는
// 내부 구현이 드러난다. 기다리는 동안 볼 거리로 유사 공고 목록을 함께 두되(3건만 —
// 매칭 결과 화면의 전체 목록과 헷갈리지 않게), 점수·자격 표기는 뺀다. 완료돼도
// 자동으로 넘어가지 않는다 — 공고를 읽던 중에 화면이 갑자기 바뀌면 사용자 입장에서
// 당황스럽다, 확인 버튼을 직접 눌러야 계획서로 이동한다. 목록은 완료 후에도 그대로
// 남겨두고 그 아래에 "계획서 확인하기" 버튼을 덧붙인다 — 다 읽던 걸 안 끊는다.
// 기획서 4-2④: 진행률은 Task 목록이 아니라 프로그레스 바+백분율로만 보여주고,
// 바 아래엔 지금 하는 일을 한 줄만 표시한다 — Agent별 단계를 다 나열하면 사용자가
// 볼 필요 없는 내부 구현이 드러난다.
function PipelineProgress({onComplete}){return <Preparation kind="plan" onComplete={onComplete} similarAnnouncements={ANNOUNCEMENTS.slice(0,3)}/>;}

// 사업계획서 표준 4대 항목(PSST: Problem·Solution·Scale-up·Team) — 정부지원사업 사업계획서의
// 실제 목차 구조를 그대로 예시 본문에 쓴다. 표·그래프 예시도 같이 넣어서 "구현 Task가
// 실제로 뭘 만드는지" 목업만 보고도 감이 오게 한다.
// 내용은 시연 로그(sbrain_demo_run.json)의 실제 아이템 — "동네 헬스장 회원 관리·예약
// 서비스"(대표 김서준, 법인, steps[1].data.formInput) — 그대로다. 이전엔 점수만 이
// 시나리오에 맞추고 본문은 옛 예시(반려견 산책 대행)로 남아 있었다 — 프로젝트를 열면
// 점수·이름은 헬스장인데 계획서 내용은 완전히 다른 얘기가 나오는 불일치였다(사용자 지적).
// 각 섹션은 DOC_ITEMS_FAIL의 미달 사유를 실제로 "보여주는" 서술이 되도록 썼다 — 예:
// 문제인식은 "수치가 1건뿐"이라는 지적대로 근거 수치를 하나만("12개소") 담았다.
const PLAN_DOCUMENT_SECTIONS = [
  { tag: 'P', title: '문제인식', body: '동네 헬스장은 대부분 수기 장부와 전화로 예약을 받아 운영 부담이 크고, 회원권 잔여 횟수 관리도 수작업에 의존합니다. 인근 헬스장 12개소를 조사한 결과 대부분 같은 문제를 겪고 있었습니다' },
  { tag: 'S', title: '실현가능성', body: '회원 등록·조회, 수업 예약, 회원권 결제 기능을 갖춘 통합 관리 서비스를 만들 계획입니다. 회원권 잔여 횟수는 자동으로 차감되도록 구현할 예정입니다' },
  { tag: 'S', title: '성장전략', body: '월 회원권 단가 35,000원을 기준으로 매출을 추정했습니다. 이후 지역 내 다른 헬스장으로 서비스를 확장할 계획입니다' },
  { tag: 'T', title: '팀 구성', body: '대표 김서준은 피트니스 센터를 4년간 운영하며 지점 2곳을 관리하였고, 개발은 웹 프론트엔드 경력 3년의 이하늘이 담당하며, 결제 연동은 외부 개발사와 협력합니다' },
];

// 종합 평가에서 "사업계획서 본문 작성"을 재작성했을 때 열리는 비교 모달용 — 같은
// 4개 섹션을 재작성 후 버전으로 다시 쓴다. DOC_ITEMS_PASS의 평가 코멘트(시장 수치
// 출처 2건으로 보강·구현 예정 기능 구체화·고객 확보 경로 3단계화·역할 분담+외부 협력)를
// 실제 문장으로 풀어썼다 — 점수 코멘트를 그대로 보여주는 대신 "문서가 실제로 어떻게
// 바뀌는지"를 사용자가 알아볼 수 있는 형태로 둔다(사용자 요청: 모달이 전/후 두
// 문서를 나란히 보여줘야 한다).
const PLAN_DOCUMENT_SECTIONS_REWORKED = [
  { tag: 'P', title: '문제인식', body: '동네 헬스장은 대부분 수기 장부와 전화로 예약을 받아 운영 부담이 크고, 회원권 잔여 횟수 관리도 수작업에 의존합니다. 인근 헬스장 12개소 조사 결과와 회원 300명 이하 소규모 헬스장 대상 커뮤니티 반응을 종합하면, 같은 문제를 겪는 곳이 다수였습니다' },
  { tag: 'S', title: '실현가능성', body: '회원 등록·조회, 수업 예약, 회원권 결제, 출석 알림, 매출 대시보드까지 다섯 기능을 프로토타입으로 구현할 예정이며, 회원권 잔여 횟수는 결제 즉시 자동으로 차감되도록 설계했습니다' },
  { tag: 'S', title: '성장전략', body: '월 회원권 단가 35,000원을 기준으로 매출을 추정했으며, 1단계 대표가 운영해온 피트니스 센터 기존 회원 전환, 2단계 인근 헬스장 12개소 대상 입점 제안, 3단계 지역 커뮤니티 제휴 순으로 고객을 확보합니다' },
  { tag: 'T', title: '팀 구성', body: '대표 김서준은 피트니스 센터를 4년간 운영하며 지점 2곳을 관리해 왔고, 개발은 웹 프론트엔드 경력 3년의 이하늘이 맡습니다. 결제 연동은 외부 개발사와 협력하며, 결원 발생에 대비해 외부 파트너사와 백업 계약도 함께 마련해뒀습니다' },
];

const PLAN_TABLE_EXAMPLE = {
  title: '수익모델 단가표', columns: ['상품·서비스', '단가'],
  rows: [['월 회원권', '35,000원 / 월'], ['1회 이용권', '8,000원']],
};

const PLAN_CHART_EXAMPLE = {
  title: '연도별 예상 매출', bars: [
    { label: '1년차', value: 30 }, { label: '2년차', value: 55 }, { label: '3년차', value: 100 },
  ],
};

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
function sumScores(items){ return items.reduce((s, it) => s + it.score, 0); }
function reasonsFromItems(items){
  return items.filter((it) => it.score < it.max).map((it) => `${it.name} ${it.score}/${it.max} — ${it.comment}`);
}

const DOC_ITEMS_FAIL = [
  { name: '문제인식', score: 12, max: 15, comment: '문제 규모를 뒷받침하는 수치가 1건뿐입니다.' },
  { name: '실현가능성', score: 13, max: 20, comment: '준비 정도 서술이 계획 수준에 머물러 있습니다.' },
  { name: '성장전략', score: 15, max: 20, comment: '매출 추정 단가 근거는 있으나 고객 확보 경로 서술이 없습니다.' },
  { name: '팀 구성', score: 12, max: 15, comment: '역할 분담은 명확하나 결원 시 대응 계획이 없습니다.' },
];
const DOC_ITEMS_PASS = [
  { name: '문제인식', score: 13, max: 15, comment: '시장 수치 출처가 2건으로 보강되었습니다.' },
  { name: '실현가능성', score: 17, max: 20, comment: '구현 예정 기능을 근거로 준비 정도를 구체화했습니다.' },
  { name: '성장전략', score: 17, max: 20, comment: '고객 확보 경로가 3단계로 구체화되었습니다.' },
  { name: '팀 구성', score: 13, max: 15, comment: '역할 분담과 외부 협력 계획이 함께 제시되었습니다.' },
];

const DOC_SCORE_BY_OUTCOME = {
  fail: { raw: sumScores(DOC_ITEMS_FAIL), max: 70, items: DOC_ITEMS_FAIL, reasons: reasonsFromItems(DOC_ITEMS_FAIL) },
  pass: { raw: sumScores(DOC_ITEMS_PASS), max: 70, items: DOC_ITEMS_PASS, reasons: reasonsFromItems(DOC_ITEMS_PASS) },
};
const FINAL_THRESHOLD = 80;

// 기획서 6-8: "검증 결과 문서와 화면 양쪽에 이 성격을 표기한다" — 지금까지는
// 표현검수/다운로드 화면에만 있었다. 점수가 실제로 뜨는 화면(문서 평가·종합 평가)
// 에도 같은 문구를 단다. 다운로드 화면 고지(DELIVERABLE_NOTICES)와 문구를 맞춘다.
const SCORE_DISCLAIMER = '이 점수는 서비스 내부 기준에 따른 값이며 실제 심사 점수가 아닙니다. 80점을 넘었다고 선정을 보장하지 않고, 밑돌았다고 탈락을 뜻하지도 않습니다.';
// 기획서 6-8: "사업계획서 — 첫 장에 AI 초안 생성 사실과 검토 필요를 표기." 계획서
// 미리보기(PlanForm, FinalVerdict의 열람 모달)가 실제로 이 문서의 "첫 장"에 해당한다.
const PLAN_AI_NOTICE = '본 문서는 AI가 생성한 초안입니다 — 제출 전 작성자 본인의 확인과 수정이 필요합니다.';

// 이 화면에 도달했다는 건 신청 자격 확인를 통과해 공고가 이미 고정됐다는 뜻이다
// (기획서 4-1: 공고를 고르면 이후 작업이 그 공고 기준으로 고정된다) — 매칭 결과로
// 돌아가는 경로를 두면 다른 공고를 다시 고를 수 있게 돼 이 계획서 자체가 무의미해
// 진다. 그래서 이 화면부터는(사용자 요청) 뒤로가기 버튼을 두지 않는다.
function PlanForm({ announcement, onGenerate, scoreOutcome = 'fail', itemInfo }){
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
  const [generating, setGenerating] = useState(false);

  const handleGenerateClick = () => {
    if (!passed) { setConfirmProceed(true); return; }
    setGenerating(true);
  };

  const toggleTask = (label) => {
    setCheckedTasks((prev) => (prev.includes(label) ? prev.filter((t) => t !== label) : [...prev, label]));
    setCompletedTasks((prev) => prev.filter((t) => t !== label));
  };

  // 실제 재생성 파이프라인은 없는 목업이라, 체크한 항목을 잠깐 "재작성 중"으로
  // 보여준 뒤 다시 대기 상태로 되돌린다 — 어떤 조작인지 감만 준다. 끝나면 완료
  // 표시로 남긴다(재작성 중 → 완료, 무반응으로 끝나지 않도록).
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
    <React.Fragment>
    <section data-screen="plan" className={`max-w-6xl mx-auto px-6 py-12 transition-[filter] duration-300 ${generating ? 'blur-sm pointer-events-none select-none' : ''}`}>
      <div className="grid md:grid-cols-[1fr_340px] gap-6 items-start">
        {/* 좌측 — 작성된 사업계획서 미리보기 */}
        <div className="rounded-2xl border border-[var(--border)] bg-white overflow-hidden">
          <div className="border-b border-[var(--border)] px-8 py-6 flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="text-[12.5px] font-semibold text-[var(--primary-dim)] tracking-wide mb-1">사업계획서</p>
              <h1 className="font-display font-bold text-[21px] mb-1.5">『{announcement ? announcement.title : ''}』 사업계획서</h1>
              <p className="text-[11.5px] text-[var(--muted-fg)]">{PLAN_AI_NOTICE}</p>
            </div>
          </div>

          <div className="px-8 py-8 flex flex-col gap-8">
            {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
              <div key={s.title}>
                <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［{s.tag}］</p>
                <h2 className="font-display font-bold text-[17px] mb-2">{String(i + 1).padStart(2, '0')}. {s.title}</h2>
                <p className="text-[14px] leading-relaxed text-[var(--fg)]">{s.body}</p>
              </div>
            ))}

            <div>
              <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［표］</p>
              <h2 className="font-display font-bold text-[17px] mb-3">05. {PLAN_TABLE_EXAMPLE.title}</h2>
              <div className="rounded-lg border border-[var(--border)] overflow-hidden">
                <div className="grid grid-cols-2 text-[12.5px] font-semibold text-[var(--muted-fg)] bg-[var(--muted)]">
                  {PLAN_TABLE_EXAMPLE.columns.map((c) => <div key={c} className="p-3">{c}</div>)}
                </div>
                {PLAN_TABLE_EXAMPLE.rows.map((row, i) => (
                  <div key={i} className={`grid grid-cols-2 text-[13.5px] ${i !== PLAN_TABLE_EXAMPLE.rows.length - 1 ? 'border-b border-[var(--border)]' : ''}`}>
                    {row.map((cell, j) => <div key={j} className="p-3">{cell}</div>)}
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="text-[12px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［그래프］</p>
              <h2 className="font-display font-bold text-[17px] mb-3">06. {PLAN_CHART_EXAMPLE.title}</h2>
              <div className="flex items-stretch gap-6 h-28 px-2">
                {PLAN_CHART_EXAMPLE.bars.map((b) => (
                  <div key={b.label} className="flex flex-col items-center justify-end gap-2 flex-1 h-full">
                    <div className="w-full max-w-[52px] rounded-t-md" style={{ height: `${b.value}%`, backgroundColor: '#90bfff' }}></div>
                    <span className="text-[11.5px] text-[var(--muted-fg)]">{b.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 우측 — 문서 평가: 문서층 70점을 100점 만점으로 환산해 표시 (기획서 4-5) */}
        <aside className="rounded-2xl border border-[var(--border)] bg-white p-6 md:sticky md:top-24">
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

          <div className="flex flex-col gap-2 mt-4">
            <button onClick={handleGenerateClick}
              className="w-full rounded-xl bg-[var(--primary)] text-white py-3 text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">
              프로토타입 생성
            </button>
          </div>

          {confirmProceed && (
            <div className="mt-4 rounded-xl border border-[var(--danger)] bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-4">
              <p className="text-[13px] font-semibold text-[var(--danger)] mb-3">점수 미달입니다 — 그래도 진행하시겠습니까</p>
              <div className="flex items-center gap-4">
                <button onClick={() => setConfirmProceed(false)}
                  className="text-[13px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-[color,scale] duration-150 ease-out active:scale-[0.96]">
                  취소
                </button>
                <button onClick={() => setGenerating(true)} className="text-[13px] font-semibold text-[var(--primary)] hover:underline transition-[scale] duration-150 ease-out active:scale-[0.96]">
                  그래도 진행하기
                </button>
              </div>
            </div>
          )}
        </aside>
      </div>
    </section>
    {generating && (
      <GeneratingOverlay>
        <ArtifactProgress itemInfo={itemInfo} onComplete={onGenerate} />
      </GeneratingOverlay>
    )}
    </React.Fragment>
  );
}

// PRJ-ID-008/구현 Agent 스펙: 카테고리(원페이지/웹개발/AI API)는 내부 판정값이라
// 사용자에게 선택 UI로 노출하지 않는다 — 아이템 설명 텍스트에서 휴리스틱으로
// 추정한다(실제로는 조율 Agent가 판정). 원페이지는 실행 파일 Task 자체가 생략되므로
// "빈 슬롯"을 보여주는 대신 그 카드를 아예 렌더링하지 않는다 — 없는 걸 없다고
// 티내면 카테고리 로직이 사용자에게 역으로 드러난다.
function detectItemCategory(itemText){
  const text = itemText || '';
  if (/매장|오프라인|가게|매점|제조|공장|카페|식당/.test(text)) return 'onepage';
  if (/AI|인공지능|API|챗봇|추천\s*엔진|이미지\s*생성|모델(?!링)/i.test(text)) return 'aiapi';
  return 'webdev';
}

const ARTIFACT_CATEGORY_COPY = {
  onepage: {
    note: '이 아이템은 인포그래픽 중심으로 준비했습니다 — 오프라인 매장·제조업처럼 "동작 화면"보다 사업 구조를 한눈에 보여주는 게 더 적합해요.',
  },
};

// 웹개발과 AI API 모두 "HTML 실행 파일"이라는 산출물 형태는 같다 — 아이템 성격에
// 따라 내부적으로 다르게 만들어지더라도, 사용자에게 보여주는 미리보기 디자인·명칭은
// 하나로 통일한다(카테고리별로 다른 카드를 보여주면 카테고리 판정이 화면에 드러난다).
const EXECUTABLE_COPY = {
  title: '화면 흐름 미리보기',
  desc: '핵심 화면의 구성과 요소를 크게 확인할 수 있어요.',
};

function InfographicMock(){
  return (
    <div className="absolute inset-0 flex items-center justify-center p-6" style={{ background:'#f2f4f6' }}>
      <div className="w-[52%] max-w-[160px] aspect-[3/4] bg-[#fff] rounded-sm shadow-xl p-3 flex flex-col gap-2.5">
        <div className="h-2.5 w-1/2 bg-[var(--primary)] rounded-sm"></div>
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-md p-2.5" style={{ background:'color-mix(in srgb, var(--primary) 12%, white)' }}>
            <div className="h-3 w-3 rounded-full mb-1.5" style={{ background:'var(--primary)' }}></div>
            <div className="h-1.5 w-full bg-[#e5e8eb] rounded-sm"></div>
          </div>
          <div className="rounded-md p-2.5" style={{ background:'color-mix(in srgb, var(--primary) 12%, white)' }}>
            <div className="h-3 w-3 rounded-full mb-1.5" style={{ background:'var(--primary)' }}></div>
            <div className="h-1.5 w-full bg-[#e5e8eb] rounded-sm"></div>
          </div>
        </div>
        <div className="h-1.5 w-full bg-[#e5e8eb] rounded-sm"></div>
        <div className="h-1.5 w-[80%] bg-[#e5e8eb] rounded-sm"></div>
        <div className="flex items-end gap-1.5 h-10 mt-auto">
          <div className="flex-1 rounded-t-sm" style={{ height:'40%', backgroundColor:'#90bfff' }}></div>
          <div className="flex-1 rounded-t-sm" style={{ height:'70%', backgroundColor:'#90bfff' }}></div>
          <div className="flex-1 rounded-t-sm" style={{ height:'55%', backgroundColor:'#90bfff' }}></div>
          <div className="flex-1 rounded-t-sm" style={{ height:'95%', backgroundColor:'#90bfff' }}></div>
        </div>
      </div>
    </div>
  );
}

// 구현 Agent 산출 Task도 카테고리별로 다르다 — 원페이지는 실행 파일 Task 자체가
// 생략되므로 "지금 하는 일" 목록도 인포그래픽 제작 하나만 보여준다(사업계획서 작성
// 진행 화면과 같은 패턴, 없는 Task를 나열하지 않는다는 원칙도 동일하게 적용).
const ARTIFACT_SUBTASKS_BY_CATEGORY = {
  onepage: ['인포그래픽 제작'],
  webdev: ['실행 파일 제작', '인포그래픽 제작'],
  aiapi: ['실행 파일 제작', '인포그래픽 제작'],
};

function ArtifactProgress({onComplete,itemInfo}){return <Preparation kind="artifact" compact={detectItemCategory(itemInfo?.item)==='onepage'} onComplete={onComplete}/>;}

// 목업 수정 요청서 v3 §12: 산출물층 30점 = 코드 기준 자동 검증 15 + 계획서 대조 15.
// 값은 시연 로그 steps[9]/steps[10](산출물 확인·종합 평가 1차, 자동검증 12/15·대조
// 7/15)와 steps[11]/steps[13](재작성 후, 자동검증 15/15·대조 11/15)을 그대로 옮겼다.
// 대조 사유(누락 기능 2건)도 시연 로그 featureMatch.findings 그대로다 — 계획서
// 한 벌만으로는 나올 수 없는, 두 산출물을 독립적으로 대조해야만 나오는 지적이다.
const ARTIFACT_SCORE_BY_OUTCOME = {
  fail: {
    autoCheck: {
      raw: 12, max: 15,
      reasons: [
        'html 태그에 lang 속성이 없습니다.',
        '예약 버튼의 전경/배경 명도 대비가 2.9:1로 기준(4.5:1) 미만입니다.',
      ],
    },
    crossCheck: {
      raw: 7, max: 15,
      reasons: [
        "계획서의 '회원권 결제' 기능이 프로토타입에 존재하지 않습니다.",
        "계획서의 '출석 알림' 기능이 프로토타입에 존재하지 않습니다.",
      ],
    },
  },
  pass: {
    autoCheck: { raw: 15, max: 15, reasons: [] },
    crossCheck: { raw: 11, max: 15, reasons: [] },
  },
};

// verification_agent/score.py의 R-4 8항목 배점표(이름·weight)를 그대로 옮긴다 — 웹개발·AI API는
// prototype.html을 검사하는 8항목(_ITEM_DEFS), 원페이지는 인포그래픽 SVG를 검사하는 별도
// 8항목(_ONEPAGE_ITEM_DEFS)을 쓴다. 합계는 두 쪽 다 15점. standard 쪽 이름은 시연 로그
// steps[9].data.codeCheck.checks의 표기를 그대로 따랐다(원 소스 파일의 긴 이름과 다름).
const CODE_CHECK_ITEMS_BY_CATEGORY = {
  standard: [
    { id: 1, name: '진입 파일 존재', weight: 3 },
    { id: 2, name: '대체 텍스트', weight: 2 },
    { id: 3, name: 'label 연결', weight: 2 },
    { id: 4, name: 'html lang', weight: 1 },
    { id: 5, name: '명도 대비', weight: 2 },
    { id: 6, name: '제목 계층', weight: 2 },
    { id: 7, name: '실행 안내', weight: 1 },
    { id: 8, name: '비밀값 하드코딩 없음', weight: 2 },
  ],
  onepage: [
    { id: 1, name: '진입 파일 존재', weight: 3 },
    { id: 2, name: 'img·svg 대체 텍스트', weight: 2 },
    { id: 3, name: 'viewBox 유효성', weight: 1 },
    { id: 4, name: '명도 대비 4.5:1', weight: 2 },
    { id: 5, name: '카테고리 배지 표기', weight: 1 },
    { id: 6, name: '필수 섹션 제목 존재', weight: 2 },
    { id: 7, name: '데이터 완전성', weight: 2 },
    { id: 8, name: '하드코딩된 비밀값 없음', weight: 2 },
  ],
};

// outcome('fail'/'pass')별로 미달 처리할 항목 id·사유만 지정한다 — 나머지는 자동 통과.
// standard 쪽은 시연 로그 steps[9].data.codeCheck.checks를 그대로 옮겼다: fail은
// 4(html lang)·5(명도 대비)만 미달(weight 1+2=3, raw 12/15), pass는 전부 통과(15/15,
// steps[11].data.reworkDiff의 "코드 15/15"). onepage는 시연 로그에 없어 이전 값 유지.
const CODE_CHECK_FAILS_BY_OUTCOME = {
  fail: {
    standard: { 4: 'html 태그에 lang 속성이 없습니다.', 5: '예약 버튼의 전경/배경 명도 대비가 2.9:1로 기준(4.5:1) 미만입니다.' },
    onepage: { 3: 'viewBox 속성 값 형식이 올바르지 않음', 4: '명도 대비 4.5:1 기준 미달 2건',
      5: '카테고리 배지 텍스트 누락', 7: '매출 추정 표의 일부 항목 데이터 누락' },
  },
  pass: {
    standard: {},
    onepage: { 5: '카테고리 배지 텍스트 누락' },
  },
};

function buildCodeCheckItems(category, scoreOutcome){
  const itemCategory = category === 'onepage' ? 'onepage' : 'standard';
  const fails = CODE_CHECK_FAILS_BY_OUTCOME[scoreOutcome][itemCategory];
  return CODE_CHECK_ITEMS_BY_CATEGORY[itemCategory].map((item) => ({
    ...item, passed: !(item.id in fails), evidence: fails[item.id] || null,
  }));
}

// 기획서 4-5: "산출물 확인" 화면은 합격선을 표기하지 않는다 — 코드 검증 8항목과 계획서
// 대조 누락 기능을 항목별로 보여주고, 판정(통과 여부)은 종합 평가에서 한 번만 말한다.
function ResultPreview({kind,onClose}){
 const ref=useRef(null);
 useEffect(()=>{const d=ref.current;d?.showModal();return()=>d?.close()},[]);
 return <dialog ref={ref} className="result-preview-dialog" onCancel={onClose} aria-label="산출물 미리보기"><header><h2>{kind==='site'?'프로토타입 화면':'인포그래픽'} 미리보기</h2><button onClick={onClose} aria-label="미리보기 닫기"><Icon name="close"/></button></header><p>아이템을 설명하기 위한 예시 화면이에요.</p><div className="result-preview-stage">{kind==='site'?<SiteMock/>:<InfographicMock/>}</div><button className="btn" onClick={onClose}>확인했어요</button></dialog>;
}

function ArtifactResult({ announcement, itemInfo, onBack, onFinalize, scoreOutcome = 'fail' }){
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
          <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">『{announcement ? announcement.title : ''}』 프로토타입이 준비됐어요</h1>
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
function taskReasons(label, docScore, artifactScore){
  if (label === '사업계획서 본문 작성') return docScore.reasons.map((r) => `［문서층］ ${r}`);
  if (label === '실행 파일 제작') {
    return [...artifactScore.autoCheck.reasons, ...artifactScore.crossCheck.reasons].map((r) => `［산출물층］ ${r}`);
  }
  return [];
}

// 재작성 완료 후 "변경 내역"에 쓸 항목별 전/후 요약. 실행 파일 제작의 값은 시연
// 로그(steps[11].data.reworkDiff)를 그대로 옮겼다 — 나머지는 같은 결의 더미 값.
const TASK_REWORK_SUMMARY = {
  '사업계획서 본문 작성': { before: '실현가능성 13/20', after: '실현가능성 17/20' },
  '그래프 생성': { before: '매출 추정 근거 부족', after: '매출 추정 근거 보강' },
  '표 생성': { before: '단가 출처 미표기', after: '단가 출처 표기' },
  '실행 파일 제작': { before: '코드 12/15 · 대조 7/15', after: '코드 15/15 · 대조 11/15' },
  '인포그래픽 제작': { before: '대체 텍스트 누락', after: '대체 텍스트 보강' },
};

// FinalVerdict의 재작성-비교 모달에서 쓰는 두 블록 — 계획서 쪽과 프로토타입 쪽을
// 각각 컴포넌트로 빼서, 두 층을 함께 재작성했을 때(viewerOpen==='both') 모달 하나
// 안에서 둘 다 이어서 보여줄 수 있게 한다(중복 인라인 JSX 대신).
// 전/후 문단이 통째로 같은 색이면 어디가 달라졌는지 직접 찾아 읽어야 해서, 코드 비교 도구처럼
// 바뀐 곳을 짚어준다. 낱말 단위로 가르면 조사만 달라진 자리까지 잘게 칠해져 읽기 어려워서
// 문장 단위로 비교한다 — 최장 공통 부분수열로 유지/삭제/추가를 가른다.
function diffSentences(before, after){
  const a = before.split(/(?<=[.!?])\s+/).filter(Boolean), b = after.split(/(?<=[.!?])\s+/).filter(Boolean);
  const m = a.length, n = b.length;
  const lcs = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const parts = [];
  const push = (type, text) => {
    const last = parts[parts.length - 1];
    if (last && last.type === type) last.text += ' ' + text; else parts.push({ type, text });
  };
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { push('same', a[i]); i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) { push('removed', a[i]); i++; }
    else { push('added', b[j]); j++; }
  }
  while (i < m) { push('removed', a[i]); i++; }
  while (j < n) { push('added', b[j]); j++; }
  return parts;
}

function DiffText({ parts, side }){
  const hidden = side === 'before' ? 'added' : 'removed';
  return (
    <p className="text-[12.5px] leading-relaxed text-[var(--fg)]">
      {parts.filter((p) => p.type !== hidden).map((p, i) => (
        <React.Fragment key={i}>
          {i > 0 ? ' ' : ''}
          {p.type === 'same'
            ? <span>{p.text}</span>
            : <mark className={`rounded px-1 ${side === 'before'
              ? 'bg-[color-mix(in_srgb,var(--danger)_14%,white)] text-[var(--danger)] line-through'
              : 'bg-[color-mix(in_srgb,var(--primary)_14%,white)] text-[var(--primary-dim)]'}`}>{p.text}</mark>}
        </React.Fragment>
      ))}
    </p>
  );
}

function PlanCompareColumns(){
  const diffs = PLAN_DOCUMENT_SECTIONS.map((s, i) => diffSentences(s.body, PLAN_DOCUMENT_SECTIONS_REWORKED[i].body));
  return (
    <div className="grid sm:grid-cols-2 gap-6">
      <div>
        <p className="text-[11px] font-semibold text-[var(--muted-fg)] mb-3">재작성 전 <span className="font-normal">— 빨간색은 빠지거나 바뀐 부분</span></p>
        <div className="flex flex-col gap-5">
          {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
            <div key={s.title}>
              <p className="text-[11px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［{s.tag}］</p>
              <h2 className="font-display font-bold text-[14px] mb-1">{String(i + 1).padStart(2, '0')}. {s.title}</h2>
              <DiffText parts={diffs[i]} side="before" />
            </div>
          ))}
        </div>
      </div>
      <div>
        <p className="text-[11px] font-semibold text-[var(--primary-dim)] mb-3">재작성 후 <span className="font-normal text-[var(--muted-fg)]">— 파란색은 새로 들어간 부분</span></p>
        <div className="flex flex-col gap-5">
          {PLAN_DOCUMENT_SECTIONS_REWORKED.map((s, i) => (
            <div key={s.title}>
              <p className="text-[11px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［{s.tag}］</p>
              <h2 className="font-display font-bold text-[14px] mb-1">{String(i + 1).padStart(2, '0')}. {s.title}</h2>
              <DiffText parts={diffs[i]} side="after" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ArtifactCompareColumns({ hasExecutable }){
  const before = [...ARTIFACT_SCORE_BY_OUTCOME.fail.autoCheck.reasons, ...ARTIFACT_SCORE_BY_OUTCOME.fail.crossCheck.reasons];
  return (
    <div className="grid sm:grid-cols-2 gap-6">
      <div>
        <p className="text-[11px] font-semibold text-[var(--muted-fg)] mb-3">재작성 전</p>
        <div className="relative aspect-[4/3] rounded-xl overflow-hidden border border-[var(--border)] mb-3">
          {hasExecutable ? <SiteMock /> : <InfographicMock />}
        </div>
        <ul className="flex flex-col gap-1">
          {before.map((r) => (
            <li key={r} className="text-[12px] text-[var(--danger)] leading-relaxed">✕ {r}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-[11px] font-semibold text-[var(--primary-dim)] mb-3">재작성 후</p>
        <div className="relative aspect-[4/3] rounded-xl overflow-hidden border border-[var(--primary)] mb-3">
          {hasExecutable ? <SiteMock /> : <InfographicMock />}
        </div>
        <ul className="flex flex-col gap-1">
          {before.map((r) => (
            <li key={r} className="text-[12px] text-[var(--ok)] leading-relaxed">✓ 해결됨 — {r}</li>
          ))}
        </ul>
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
function FinalVerdict({ announcement, itemInfo, onBack, onProceed, docOutcome, artifactOutcome, setDocOutcome, setArtifactOutcome }){
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
      <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">『{announcement ? announcement.title : ''}』 제출 전 점검 결과예요</h1>
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
      {viewerOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={() => setViewerOpen(null)}></div>
          <div className={`soft-scroll relative bg-white rounded-2xl w-full max-h-[85vh] overflow-y-auto p-6 shadow-2xl ${viewerCompare ? 'max-w-4xl' : 'max-w-2xl'}`}>
            <div className="flex items-center justify-between mb-5">
              <p className="font-display font-bold text-[18px]">
                {viewerOpen === 'both' ? '사업계획서 · 프로토타입' : viewerOpen === 'plan' ? '사업계획서' : '프로토타입'}
                {viewerCompare ? ' — 재작성 전/후 비교' : ''}
              </p>
              <button onClick={() => setViewerOpen(null)} aria-label="닫기"
                className="text-[13px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)] transition-colors">닫기 ✕</button>
            </div>

            {(viewerOpen === 'plan' || viewerOpen === 'both') && (
              <p className="text-[11px] text-[var(--muted-fg)] mb-4 pb-4 border-b border-[var(--border)]">{PLAN_AI_NOTICE}</p>
            )}

            {!viewerCompare && (
              viewerOpen === 'plan' ? (
                <div className="flex flex-col gap-6">
                  {PLAN_DOCUMENT_SECTIONS.map((s, i) => (
                    <div key={s.title}>
                      <p className="text-[11px] font-bold text-[var(--muted-fg)] tracking-wide mb-1">［{s.tag}］</p>
                      <h2 className="font-display font-bold text-[15px] mb-1.5">{String(i + 1).padStart(2, '0')}. {s.title}</h2>
                      <p className="text-[13px] leading-relaxed text-[var(--fg)]">{s.body}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="relative aspect-[4/3] rounded-xl overflow-hidden border border-[var(--border)]">
                  {hasExecutable ? <SiteMock /> : <InfographicMock />}
                </div>
              )
            )}

            {/* 두 층을 함께 재작성했으면(viewerOpen==='both') 모달 하나에 계획서·프로토타입
                비교를 위아래로 둘 다 보여준다 — 프로토타입만 보여주고 바로 종합 판정으로
                넘어가면 계획서 쪽 대조 결과를 놓친다(사용자 지적). */}
            {viewerCompare && viewerOpen === 'plan' && <PlanCompareColumns />}
            {viewerCompare && viewerOpen === 'artifact' && <ArtifactCompareColumns hasExecutable={hasExecutable} />}
            {viewerCompare && viewerOpen === 'both' && (
              <div className="flex flex-col gap-8">
                <div>
                  <p className="font-display font-bold text-[15px] mb-4">사업계획서</p>
                  <PlanCompareColumns />
                </div>
                <div className="pt-8 border-t border-[var(--border)]">
                  <p className="font-display font-bold text-[15px] mb-4">프로토타입</p>
                  <ArtifactCompareColumns hasExecutable={hasExecutable} />
                </div>
              </div>
            )}
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
const REVIEW_PARAGRAPHS = [
  {
    id: 'p-02',
    before: '회원 300명 이하 소규모 헬스장은 기존 통합 관리 솔루션의 도입 비용을 감당하기 어렵다.',
    after: '회원 300명 이하 소규모 헬스장은 기존 통합 관리 솔루션의 도입 비용을 부담하기 어려운 실정이다.',
  },
  {
    id: 'p-09', spotlight: true,
    before: '본 사업은 2026년 10월 16일 접수 마감 기준으로 사업화자금 1억원 한도 내에서 집행하며, 수업 예약 기능을 최우선으로 구현한다.',
    attempts: [
      {
        try: 1, passed: false,
        after: '본 사업은 10월 중순 마감에 맞추어 사업화자금 100,000,000원 한도 내에서 집행하며, 수업 예약 기능을 우선 구현한다.',
        issue: "중요 정보가 변경되었어요 — '2026년 10월 16일' 누락, '1억원'이 '100,000,000원'으로 표기 변경됨",
      },
      {
        try: 2, passed: true,
        after: '본 사업은 2026년 10월 16일 접수 마감을 기준으로 사업화자금 1억원 한도 내에서 집행하며, 수업 예약 기능을 최우선으로 구현한다.',
      },
    ],
  },
  {
    id: 'p-11',
    before: '대표 김서준은 피트니스 센터를 4년간 운영하며 지점 2곳을 관리하였고, 개발은 웹 프론트엔드 경력 3년의 이하늘이 담당하며, 결제 연동은 외부 개발사와 협력한다.',
    after: '대표 김서준은 피트니스 센터를 4년간 운영하며 지점 2곳을 관리해 왔고, 개발은 웹 프론트엔드 경력 3년의 이하늘이 맡으며, 결제 연동은 외부 개발사와 협력한다.',
  },
];

// 산출물 3종 + 제출 안내 4개 고지(기획서 6-8, 목업 수정 요청서 v3 §5). 문구는
// 시연 로그 steps[13].data.deliverable을 그대로 옮겼다.
const DELIVERABLE_NOTICES = [
  { label: '계획서', text: '본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다.' },
  { label: '프로토타입', text: '본 프로토타입은 S-Brain이 생성한 초안입니다. 실제 서비스 코드가 아닙니다.' },
  { label: '검증 결과', text: '본 점수는 서비스 내부 기준에 따른 값이며 실제 심사 점수가 아닙니다. 80점을 넘었다고 선정을 보장하지 않고, 밑돌았다고 탈락을 뜻하지도 않습니다.' },
  { label: '제출 안내', text: '공고에 따라 AI로 작성한 문서의 제출을 제한하거나 명시를 요구할 수 있습니다. 해당 공고의 제출 요건을 확인해 주세요.' },
];

const DOWNLOAD_FILES = [
  { name: '사업계획서.docx', desc: '문장 다듬기까지 마친 최종 사업계획서' },
  { name: 'prototype.zip', desc: '실행 파일(index.html)과 인포그래픽을 담은 압축 파일' },
  { name: '검증결과.pdf', desc: '문서층·산출물층 검증 내역과 대조 결과' },
];

// 실제 산출물 생성(Task #14)이 아직 안 붙어서, 이 세 파일은 화면에 이미 있는 더미
// 데이터(PLAN_DOCUMENT_SECTIONS_REWORKED/ARTIFACT_SCORE_BY_OUTCOME 등)를 그대로 옮겨
// 그 확장자로 실제 열리는 더미 파일을 즉석 생성해 내려준다(dummyDeliverables.js).
// 검증결과.pdf만 표준 내장 폰트 한계로 영문 라벨을 쓴다 — 아래는 그 번역표.
const EN_DOC_ITEM_LABEL = {
  '문제인식': 'Problem Recognition',
  '실현가능성': 'Feasibility',
  '성장전략': 'Growth Strategy',
  '팀 구성': 'Team Composition',
};

// 검수 단계 진입은 되돌릴 수 없다(기획서 4-7) — 종합 평가로 돌아가는 경로를 두지
// 않는다. 그래서 이 화면에는 뒤로가기 버튼이 없다(다른 모든 파이프라인 화면과의
// 유일한 차이). 다운로드도 이 화면 하단에 함께 둔다 — 목업 수정 요청서 v3 §3:
// "검수와 내려받기를 별도 단계로 세지만 화면을 쪼갤 이유는 없다."
// 점수는 다시 표시하지 않는다 — 검수가 점수를 바꾼 것처럼 보이면 안 되기 때문에,
// 종합 평가에서 본 점수가 최종이라는 사실이 화면에서도 드러나야 한다(v3 §3).
function ReviewScreen({ announcement, docOutcome = 'fail', artifactOutcome = 'fail', onGoDashboard, projectId }){
  const docScore = DOC_SCORE_BY_OUTCOME[docOutcome];
  const artifactScore = ARTIFACT_SCORE_BY_OUTCOME[artifactOutcome];
  const finalTotal = docScore.raw + artifactScore.autoCheck.raw + artifactScore.crossCheck.raw;
  const passed = finalTotal >= FINAL_THRESHOLD;
  const itemTitle = announcement ? announcement.title : '';

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
      downloadPlanDocx({
        title: `${itemTitle || '사업계획서'} 사업계획서`,
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
      const lines = [
        { text: 'S-Brain Verification Result (Demo)', size: 16 },
        { text: `Item: ${itemTitle || '-'}`, size: 10 },
        { text: `Generated: ${new Date().toISOString()}`, size: 10 },
        { text: '' },
        { text: `[Document Layer] ${docScore.raw} / ${docScore.max}`, size: 13 },
        ...docScore.items.map((it) => ({ text: `  - ${EN_DOC_ITEM_LABEL[it.name] || it.name}: ${it.score} / ${it.max}` })),
        { text: '' },
        { text: `[Artifact Layer] Auto-check ${artifactScore.autoCheck.raw}/${artifactScore.autoCheck.max}, Cross-check ${artifactScore.crossCheck.raw}/${artifactScore.crossCheck.max}`, size: 13 },
        ...artifactScore.autoCheck.reasons.map((r, i) => ({ text: `  - Auto-check issue ${i + 1}` })),
        ...artifactScore.crossCheck.reasons.map((r, i) => ({ text: `  - Cross-check issue ${i + 1}` })),
        { text: '' },
        { text: `Final Score: ${finalTotal} / 100 (threshold ${FINAL_THRESHOLD})`, size: 14 },
        { text: `Result: ${passed ? 'PASS' : 'BELOW THRESHOLD'}`, size: 14 },
        { text: '' },
        { text: 'This score is an internal reference score, not an official screening score.', size: 9 },
      ];
      downloadVerificationPdf({ lines });
      return;
    }
  }

  return (
    <section data-screen="review" className="max-w-3xl mx-auto px-6 py-16">
      <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">문장 다듬기</p>
      <h1 className="font-display font-bold text-[26px] md:text-[30px] mb-3">『{announcement ? announcement.title : ''}』 문장을 다듬었어요</h1>
      <p className="text-[14.5px] text-[var(--muted-fg)] mb-1">사업계획서 문장 형식과 한국어 표현만 다듬는 단계라 점수는 바뀌지 않습니다</p>
      <p className="text-[12.5px] text-[var(--muted-fg)] mb-8">이 단계부터는 이전 화면으로 돌아갈 수 없습니다</p>

      <div className="flex flex-col gap-4 mb-10">
        {REVIEW_PARAGRAPHS.map((p) => (
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

      <div className="border-t border-[var(--border)] pt-8">
        <p className="text-[13px] font-semibold text-[var(--primary-dim)] tracking-wide mb-2">결과물</p>
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


const MY_PROJECTS = [
  { id: 1, name: '동네 헬스장 예약 서비스', announcementTitle: '초기창업패키지', status: '사업계획서 작성중', progress: 65, updatedAt: '2026-09-08', view: 'plan-form' },
  { id: 5, name: '중고거래 안전결제 플랫폼', announcementTitle: '예비창업패키지', status: '제출 완료', progress: 100, updatedAt: '2026-08-20', view: 'review', scoreOutcome: 'pass' },
];

const PROJECT_PAGE_SIZE = 5;
const PROJECT_STATUS_TONE = {
  ok: { color: '#3D7A4F', bg: 'rgba(61,122,79,.12)' },
  danger: { color: '#A8342A', bg: 'rgba(168,52,42,.1)' },
  neutral: { color: '#6b7684', bg: '#f2f4f6' },
};
function projectStatusTone(status){
  if (/완료|통과/.test(status)) return PROJECT_STATUS_TONE.ok;
  if (/미달|불통과/.test(status)) return PROJECT_STATUS_TONE.danger;
  return PROJECT_STATUS_TONE.neutral;
}

// 기획서 4-7 + 목업 수정 요청서 v3 §8: 실행은 계정당 1건이다. 완료 건("제출 완료")은
// 제한 대상이 아니고, 그 외 상태는 전부 "진행 중"으로 본다.
const COMPLETED_PROJECT_STATUS = '제출 완료';

// 완전히 처음 로그인한 유저는 등록한 프로젝트가 하나도 없다 — 기존에 만든
// 대시보드는 전부 MY_PROJECTS(더미 7건)를 전제로 하고 있어서 그 빈 상태를 보여줄
// 방법이 없었다. 실제 신규가입 절차를 또 만드는 대신(로그인 자체는 목업이라 계정을
// 여러 개 둘 이유가 없다), 대시보드 진입 시점에 "어느 페르소나로 볼지"만 전환하는
// 가벼운 토글을 둔다 — 발표자가 그 자리에서 신규/기존 화면을 바로 오가며 보여줄 수 있다.

export { IntakeForm, MatchProgress, MatchResults, EligibilityGate, PlanForm, ArtifactResult, FinalVerdict, ReviewScreen, NotificationBell, SIMILAR_ANNOUNCEMENT_ALERTS, ANNOUNCEMENTS, MY_PROJECTS };

export { PipelineProgress, ArtifactProgress };
