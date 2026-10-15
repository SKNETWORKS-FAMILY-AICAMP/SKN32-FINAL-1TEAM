// 프로젝트 작성 화면(IntakeForm)의 "사업 계획" 입력 부품 — 프로젝트마다 달라서 마이페이지가
// 아니라 여기서 받는다(개발 기간·사업비·채용 계획·장비·협력 기관).
import React from 'react';
import { Check, Field, ListEditor, inputCls } from '../mypage/ui.jsx';
import { PRELIMINARY_BUDGET_CAP_MANWON } from '../mypage/derive.js';

// 공고마다 정부지원 비율·현금·현물 기준이 다르므로 사전 입력 단계에서는 정확한 부담액을
// 계산하지 않는다. 여기서는 자기부담금이 있는 공고를 검토할 수 있는지와 현금 여력만 받는다.
export const EMPTY_FUNDING = { available: null, cashLimit: '', inKindResources: '' };

const digitsOnly = (v) => v.replace(/\D/g, '');
const withCommas = (digits) => (digits ? Number(digits).toLocaleString('ko-KR') : '');

function MoneyInput({ label, value, onChange, unit = '원', placeholder }) {
  return (
    <Field label={label}>
      <div className="relative">
        <input inputMode="numeric" value={withCommas(value)} placeholder={placeholder}
          onChange={(e) => onChange(digitsOnly(e.target.value))} className={`${inputCls} pr-12`} />
        <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[14px] text-[var(--muted-fg)]">{unit}</span>
      </div>
    </Field>
  );
}

export function DevPeriodField({ value, onChange }) {
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const reversed = value.start && value.end && value.start > value.end;
  return (
    <div>
      <div className="grid gap-3 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-end">
        <Field label="시작"><input type="month" value={value.start} onChange={set('start')} className={inputCls} /></Field>
        <span className="pb-3 text-[var(--muted-fg)]">~</span>
        <Field label="종료"><input type="month" value={value.end} onChange={set('end')} className={inputCls} /></Field>
      </div>
      {reversed && <p className="text-[12.5px] mt-1.5 text-[var(--danger)]">종료월이 시작월보다 빨라요.</p>}
    </div>
  );
}

// 예비창업자 — 희망 사업 규모(만원). 2,000만원을 넘지 못하게 그 자리에서 자른다.
export function BudgetScaleField({ value, onChange }) {
  const clamp = (digits) => (digits ? String(Math.min(PRELIMINARY_BUDGET_CAP_MANWON, parseInt(digits, 10))) : '');
  return (
    <div>
      <MoneyInput label="희망 사업 규모" unit="만원" value={value} placeholder="예) 1,500" onChange={(d) => onChange(clamp(d))} />
      <p className="text-[12.5px] text-[var(--muted-fg)] mt-1.5">
        예비창업자는 첫창업 기준으로 접수돼요. 최대 2,000만원까지 입력할 수 있고, 실제 상한은 공고마다 다르니 지원 전 다시 확인해 주세요.
      </p>
    </div>
  );
}

export function SelfFundingField({ value, onChange }) {
  const choose = (available) => onChange({ ...value, available });
  const set = (key) => (next) => onChange({ ...value, [key]: next });

  return (
    <div className="funding-panel">
      <div>
        <p className="text-[14px] font-semibold text-[var(--fg)] mb-2">자기부담금이 있는 공고도 검토할 수 있나요?</p>
        <p className="text-[12.5px] text-[var(--muted-fg)] mb-3">공고마다 부담 비율과 현금·현물 인정 기준이 달라요. 여기서는 신청 가능한 공고의 범위를 정하기 위한 정보만 받아요.</p>
        <div className="funding-choice" role="radiogroup" aria-label="자기부담금 공고 검토 가능 여부">
          <button type="button" role="radio" aria-checked={value.available === true}
            className={value.available === true ? 'selected' : ''} onClick={() => choose(true)}>
            가능해요
            <small>자기부담금이 필요한 공고도 함께 찾아요</small>
          </button>
          <button type="button" role="radio" aria-checked={value.available === false}
            className={value.available === false ? 'selected' : ''} onClick={() => choose(false)}>
            어려워요
            <small>자기부담금이 없는 공고를 우선 확인해요</small>
          </button>
        </div>
      </div>
      {value.available === true && (
        <div className="funding-capacity">
          <MoneyInput label="투입 가능한 현금 규모" value={value.cashLimit} placeholder="예) 10,000,000" onChange={set('cashLimit')} />
          <label className="block mt-4">
            <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">현물로 활용 가능한 자원 <small className="font-normal text-[var(--muted-fg)]">(선택)</small></span>
            <textarea value={value.inKindResources} onChange={(e) => set('inKindResources')(e.target.value)} rows={3}
              placeholder="예) 대표자 인건비, 보유 장비, 사업장 등" className="w-full border border-[var(--border)] rounded-xl px-3.5 py-3 text-[15px] bg-white outline-none resize-none focus:border-[var(--primary)]" />
          </label>
        </div>
      )}
      <p className="funding-notice">정확한 자기부담 현금·현물 금액은 공고를 선택한 뒤, 해당 공고의 지원 비율과 지역 기준을 적용해 안내해야 합니다.</p>
    </div>
  );
}

// 목록 입력 + "없음" 체크. 없음을 고르면 목록을 숨기고, 그 자체로 작성한 것으로 친다.
export function ListOrNone({ items, onChange, none, onNoneChange, noneLabel, fields, cols, addLabel }) {
  return (
    <div>
      <div className="mb-3"><Check checked={none} onChange={onNoneChange}>{noneLabel}</Check></div>
      {!none && <ListEditor items={items} onChange={onChange} cols={cols} addLabel={addLabel} fields={fields} />}
    </div>
  );
}

// 목록이 1행 이상이고, 체크박스를 뺀 모든 칸이 채워졌는지.
export const rowsFilled = (rows, fields) => rows.length > 0
  && rows.every((r) => fields.filter((f) => f.type !== 'check').every((f) => String(r[f.key] ?? '').trim()));

export const fundingFilled = (f) => f.available === false || (f.available === true && !!f.cashLimit);
export const periodFilled = (p) => !!p.start && !!p.end && p.start <= p.end;
