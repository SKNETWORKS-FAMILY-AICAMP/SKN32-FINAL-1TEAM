// 마이페이지 전용 입력 부품. 색·모서리·포커스 규칙은 IntakeForm과 맞춘다.
import React, { useEffect, useRef, useState } from 'react';
import { INDUSTRY_OPTIONS, SIDO } from './derive.js';

const fieldBase = 'w-full border border-[var(--border)] rounded-xl px-3.5 text-[15px] bg-white outline-none focus:border-[var(--primary)] transition-colors placeholder:text-[#b0b8c1] disabled:bg-[var(--muted)]';
export const inputCls = `${fieldBase} h-11`;
// 여러 줄 입력칸 — inputCls에 h-auto를 덧붙이면 CSS 생성 순서상 h-11이 이겨서 한 줄 높이로
// 눌리므로 높이 클래스 없이 따로 둔다. 크기는 rows로 정하고 사용자가 늘리지 못하게 막는다.
export const textareaCls = `${fieldBase} py-3 resize-none leading-relaxed`;

const TONES = {
  ok: 'bg-[#e8f7f1] text-[var(--ok)]',
  info: 'bg-[#e8f1ff] text-[var(--primary-dim)]',
  warn: 'bg-[#fff4e0] text-[var(--warn)]',
  danger: 'bg-[#fff0f0] text-[var(--danger)]',
  muted: 'bg-[var(--muted)] text-[var(--muted-fg)]',
};

export function Badge({ tone = 'info', children }) {
  return <span className={`inline-flex items-center h-7 px-2.5 rounded-lg text-[12.5px] font-semibold ${TONES[tone]}`}>{children}</span>;
}

export function Badges({ items }) {
  const list = items.filter(Boolean);
  if (!list.length) return null;
  return <div className="flex flex-wrap gap-1.5 mt-3">{list.map((b) => <Badge key={b.text} tone={b.tone}>{b.text}</Badge>)}</div>;
}

// <section>이 아니라 <div>인 이유: styles.css의 레거시 규칙
// ".workflow-content section input{background:#f2f4f6}"(IntakeForm용)이 태그명만
// 보고 걸리는 바람에, 여기서도 <section>을 쓰면 흰 배경으로 짜둔 inputCls를 회색으로
// 덮어써 버렸다(포커스 때만 잠깐 흰색으로 바뀌었다 풀리는 것도 그 규칙의 :focus 예외 때문).
// 레거시 규칙은 그대로 두고, 여기 태그만 바꿔서 그 선택자에 안 걸리게 한다.
export function Section({ title, desc, children }) {
  return (
    <div className="py-8 border-t border-[var(--border)] first:border-t-0 first:pt-0">
      <h2 className="font-bold text-[17px]">{title}</h2>
      {desc && <p className="text-[13.5px] text-[var(--muted-fg)] mt-1">{desc}</p>}
      <div className="mt-5">{children}</div>
    </div>
  );
}

export function Field({ label, children }) {
  return (
    <label className="block min-w-0">
      <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">{label}</span>
      {children}
    </label>
  );
}

export function TextInput({ label, value, onChange, type = 'text', placeholder }) {
  return <Field label={label}><input type={type} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={inputCls} /></Field>;
}

// 모든 드롭다운(성별·시/도·역량 탭의 구분·상태 선택 등)이 같은 모양을 쓰도록 여기 하나로
// 통일한다 — 네이티브 select는 펼쳤을 때 옵션 목록이 OS 기본 모양(각진 사각형)으로 나와
// CSS로 못 고치므로, 버튼 + 커스텀 목록으로 직접 그린다.
export function Select({ label, value, onChange, options, placeholder = '선택' }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <Field label={label}>
      <div className="relative" ref={ref}>
        <button type="button" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}
          className={`${inputCls} flex items-center justify-between gap-2 text-left ${value ? '' : 'text-[#b0b8c1]'}`}>
          <span className="truncate">{value || placeholder}</span>
          <svg className={`w-4 h-4 text-[#8b95a1] shrink-0 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
            viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
        {open && (
          <ul role="listbox" className="absolute z-20 left-0 right-0 mt-1.5 max-h-60 overflow-auto rounded-xl border border-[var(--border)] bg-white shadow-lg py-1.5">
            {options.map((o) => (
              <li key={o}>
                <button type="button" role="option" aria-selected={value === o}
                  onClick={() => { onChange(o); setOpen(false); }}
                  className={`w-full text-left px-3.5 py-2.5 text-[14.5px] transition-colors ${value === o ? 'bg-[#eef4fe] text-[var(--primary-dim)] font-semibold' : 'text-[var(--fg)] hover:bg-[#f5f7fa]'}`}>
                  {o}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Field>
  );
}

export function Segmented({ options, value, onChange }) {
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` }}>
      {options.map(([val, label, sub]) => (
        <button key={val} type="button" aria-pressed={value === val} onClick={() => onChange(val)}
          className={`rounded-xl border-2 px-3 py-3 text-left transition-[border-color,background-color,scale] duration-150 active:scale-[0.98] ${value === val ? 'border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_6%,white)]' : 'border-[var(--border)] bg-white hover:border-[#d1d6db]'}`}>
          <span className={`block text-[14.5px] font-semibold ${value === val ? 'text-[var(--primary-dim)]' : ''}`}>{label}</span>
          {sub && <span className="block text-[12.5px] text-[var(--muted-fg)] mt-0.5">{sub}</span>}
        </button>
      ))}
    </div>
  );
}

export function Check({ checked, onChange, children }) {
  return (
    <label className="inline-flex items-center gap-2 text-[14px] text-[#4e5968] cursor-pointer select-none">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="w-4 h-4 accent-[var(--primary)]" />
      {children}
    </label>
  );
}

// 개인사업자·법인은 이미 사업자등록증에 업종이 정해져 있어 정부지원사업 신청서
// 표준 목록(지원 분야/전문기술분야) 중에서만 고르게 한다. 예비창업자는 아직 업종이
// 굳어지지 않은 경우가 많아 자유 입력을 그대로 둔다.
// 자유입력↔선택형 경계를 넘나들 때 값을 안 지우면, 예비창업자에서 자유롭게 쓴 텍스트가
// 선택형 쪽엔 없는 항목인데도 "선택된 값"처럼 보이거나(또는 그 반대) 남아 있는 버그가
// 났었다 — 개인/법인끼리는 같은 목록을 쓰니 유지하고, 그 경계를 넘을 때만 비운다.
export function IndustryField({ label = '주업종', applicantType, value, onChange }) {
  const selectable = applicantType === 'individual' || applicantType === 'corp';
  const prevSelectable = useRef(selectable);
  useEffect(() => {
    if (prevSelectable.current !== selectable && value) onChange('');
    prevSelectable.current = selectable;
  }, [selectable]);
  if (selectable) return <Select label={label} value={value} options={INDUSTRY_OPTIONS} onChange={onChange} />;
  return <TextInput label={label} value={value} placeholder="예) 응용 소프트웨어 개발" onChange={onChange} />;
}

// 펼치기/접기. "불러온 정보를 다 보여주되 한꺼번에 펼쳐두면 혼잡하다"는 요구에 맞춰
// IntakeForm의 "불러온 정보" 묶음에 쓴다. 기본은 펼친 상태(불러온 직후엔 바로 보이게).
export function Collapsible({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-[var(--border)] overflow-hidden">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="w-full flex items-center justify-between gap-3 px-5 py-4 bg-[#f9fafb] hover:bg-[#f2f4f6] transition-colors">
        <span className="text-[14.5px] font-bold">{title}</span>
        <svg className={`w-4 h-4 text-[#8b95a1] shrink-0 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && <div className="p-5 flex flex-col gap-6">{children}</div>}
    </div>
  );
}

export function RegionInput({ label, value, onChange }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
      <Select label={`${label} 시/도`} value={value.sido} options={SIDO} onChange={(sido) => onChange({ ...value, sido })} />
      <TextInput label="시/군/구" value={value.sigungu} placeholder="예) 강남구" onChange={(sigungu) => onChange({ ...value, sigungu })} />
    </div>
  );
}

// 칩 토글 + 목록에 없는 항목 직접 추가
export function ChipSelect({ options, values, onChange }) {
  const [custom, setCustom] = useState('');
  const toggle = (v) => onChange(values.includes(v) ? values.filter((x) => x !== v) : [...values, v]);
  const all = [...options, ...values.filter((v) => !options.includes(v))];
  const add = () => {
    const v = custom.trim();
    if (v && !values.includes(v)) onChange([...values, v]);
    setCustom('');
  };
  return (
    <div className="flex flex-wrap items-center gap-2">
      {all.map((o) => (
        <button key={o} type="button" aria-pressed={values.includes(o)} onClick={() => toggle(o)}
          className={`h-9 px-3.5 rounded-full text-[14px] font-medium border transition-colors ${values.includes(o) ? 'bg-[var(--primary)] border-[var(--primary)] text-white' : 'bg-white border-[var(--border)] text-[#4e5968] hover:border-[#d1d6db]'}`}>
          {o}
        </button>
      ))}
      <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="+ 직접 입력"
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} onBlur={add}
        className="h-9 w-28 px-3 rounded-full border border-dashed border-[#d1d6db] text-[14px] outline-none focus:border-[var(--primary)] focus:w-40 transition-[width,border-color]" />
    </div>
  );
}

// 행 추가/삭제형 목록. fields: [{key,label,type:'text'|'date'|'month'|'select'|'check',options,placeholder}]
const COLS = { 2: 'sm:grid-cols-2', 3: 'sm:grid-cols-3', 4: 'sm:grid-cols-2 md:grid-cols-4' };

export function ListEditor({ items, onChange, fields, cols = 3, addLabel, emptyText, extra }) {
  const blank = Object.fromEntries(fields.map((f) => [f.key, f.type === 'check' ? false : '']));
  const update = (i, key, value) => onChange(items.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)));
  return (
    <div className="flex flex-col gap-3">
      {items.length === 0 && emptyText && <p className="text-[13.5px] text-[var(--muted-fg)] bg-white border border-[var(--border)] rounded-xl px-4 py-3.5">{emptyText}</p>}
      {items.map((row, i) => (
        <div key={i} className="relative rounded-2xl bg-white border border-[var(--border)] p-4 pr-12">
          <div className={`grid gap-3 ${COLS[cols]}`}>
            {fields.map((f) => {
              const set = (v) => update(i, f.key, v);
              if (f.type === 'select') return <Select key={f.key} label={f.label} value={row[f.key]} options={f.options} onChange={set} />;
              if (f.type === 'check') return <div key={f.key} className="flex items-end pb-2.5"><Check checked={!!row[f.key]} onChange={set}>{f.label}</Check></div>;
              return <TextInput key={f.key} label={f.label} type={f.type || 'text'} value={row[f.key]} placeholder={f.placeholder} onChange={set} />;
            })}
          </div>
          {extra && extra(row)}
          <button type="button" aria-label="삭제" onClick={() => onChange(items.filter((_, idx) => idx !== i))}
            className="absolute top-3 right-3 w-8 h-8 grid place-items-center rounded-lg text-[#b0b8c1] hover:text-[var(--danger)] hover:bg-[var(--muted)] transition-colors">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...items, blank])}
        className="h-11 rounded-xl border border-dashed border-[#d1d6db] text-[14px] font-semibold text-[var(--primary)] hover:bg-[#f5f9ff] transition-colors">
        + {addLabel}
      </button>
    </div>
  );
}
