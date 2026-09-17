// 마이페이지 전용 입력 부품. 색·모서리·포커스 규칙은 IntakeForm과 맞춘다.
import React, { useState } from 'react';
import { SIDO } from './derive.js';

export const inputCls = 'w-full h-11 border border-[var(--border)] rounded-xl px-3.5 text-[15px] bg-white outline-none focus:border-[var(--primary)] transition-colors placeholder:text-[#b0b8c1] disabled:bg-[var(--muted)]';

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

export function Section({ title, desc, children }) {
  return (
    <section className="py-8 border-t border-[var(--border)] first:border-t-0 first:pt-0">
      <h2 className="font-bold text-[17px]">{title}</h2>
      {desc && <p className="text-[13.5px] text-[var(--muted-fg)] mt-1">{desc}</p>}
      <div className="mt-5">{children}</div>
    </section>
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

export function Select({ label, value, onChange, options, placeholder = '선택' }) {
  return (
    <Field label={label}>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={`${inputCls} ${value ? '' : 'text-[#b0b8c1]'}`}>
        <option value="">{placeholder}</option>
        {options.map((o) => <option key={o} value={o} className="text-[var(--fg)]">{o}</option>)}
      </select>
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
      {items.length === 0 && emptyText && <p className="text-[13.5px] text-[var(--muted-fg)] bg-[#f9fafb] rounded-xl px-4 py-3.5">{emptyText}</p>}
      {items.map((row, i) => (
        <div key={i} className="relative rounded-2xl bg-[#f9fafb] p-4 pr-12">
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
            className="absolute top-3 right-3 w-8 h-8 grid place-items-center rounded-lg text-[#b0b8c1] hover:text-[var(--danger)] hover:bg-white transition-colors">
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
