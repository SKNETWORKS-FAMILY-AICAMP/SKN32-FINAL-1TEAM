// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
import React, {useState,useRef} from 'react';
import {BackButton,FileAttach,FloatingInput,RepeatableRow} from './shared.jsx';

export function IntakeForm({ onSubmit, onBack, backLabel = '처음으로 돌아가기' }){
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
