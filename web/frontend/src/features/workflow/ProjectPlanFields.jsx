// 프로젝트 작성 화면(IntakeForm)의 "사업 계획" 입력 부품 — 프로젝트마다 달라서 마이페이지가
// 아니라 여기서 받는다(개발 기간·사업비·채용 계획·장비·협력 기관·사업비 집행 계획·추진 일정).
import React from 'react';
import { Check, Field, ListEditor, Select, TextInput, inputCls } from '../mypage/ui.jsx';
import { PRELIMINARY_BUDGET_CAP_MANWON } from '../mypage/derive.js';

// 공고마다 정부지원 비율·현금·현물 기준이 다르므로 사전 입력 단계에서는 정확한 부담액을
// 계산하지 않는다. 여기서는 자기부담금이 있는 공고를 검토할 수 있는지와 현금 여력만 받는다.
export const EMPTY_FUNDING = { available: null, cashLimit: '', inKindResources: '' };

const digitsOnly = (v) => v.replace(/\D/g, '');
const withCommas = (digits) => (digits ? Number(digits).toLocaleString('ko-KR') : '');

// max를 주면 그보다 큰 값은 그 자리에서 max로 자른다.
function MoneyInput({ label, value, onChange, unit = '원', placeholder, max }) {
  const change = (digits) => onChange(max != null && digits && Number(digits) > max ? String(max) : digits);
  return (
    <Field label={label}>
      <div className="relative">
        <input inputMode="numeric" value={withCommas(value)} placeholder={placeholder}
          onChange={(e) => change(digitsOnly(e.target.value))} className={`${inputCls} pr-12`} />
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
          <MoneyInput label="투입 가능한 현금 한도" value={value.cashLimit} placeholder="예) 10,000,000" onChange={set('cashLimit')} />
          <label className="block mt-4">
            <span className="block text-[13px] font-semibold text-[#4e5968] mb-1.5">현물로 활용 가능한 자원 <small className="font-normal text-[var(--muted-fg)]">(선택)</small></span>
            <textarea value={value.inKindResources} onChange={(e) => set('inKindResources')(e.target.value)} rows={3}
              placeholder="예) 대표자 인건비, 보유 장비, 사업장 등" className="w-full border border-[var(--border)] rounded-xl px-3.5 py-3 text-[15px] bg-white outline-none resize-none focus:border-[var(--primary)]" />
          </label>
        </div>
      )}
      <p className="funding-notice">지원 비율과 현금·현물 인정 기준은 공고마다 달라요. 아래 사업비 표의 금액이 고른 공고 기준에 맞는지 지원 전에 다시 확인해 주세요.</p>
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

// ── 사업비 집행 계획 · 추진 일정 ──────────────────────────────────────────────
// 계획서 양식의 사업비 표 · 일정 표 행은 이 입력이 원본이다(없으면 계획서 검증에서 막힌다).
// 양식은 신청자 유형으로 정해진다 — 예비창업자는 예비창업패키지(사업비 1 · 2단계, 일정은 협약기간 내 /
// 협약 이후 전체), 개인사업자 · 법인은 초기창업패키지(사업비 한 표, 일정은 실현가능성 / 성장전략).
// 조율 agents/form_defaults.py FORM_TABLE과 같은 기준이다. 저장 모양 · 검사 규칙은 백엔드(app/schemas.py BudgetItemIn ·
// ScheduleItemIn, SB-329 · 330)와 같다 — 단계는 phase('1단계' | '2단계' | 초기창업 null), 일정 section은 두 유형 모두
// feasibility · growth, 표마다 50줄, 금액은 원 단위 정수 999,999,999,999 이하.
export const BUDGET_PHASES = ['1단계', '2단계'];
export const EMPTY_BUDGET_ROW = { phase: '', category: '', plan: '', gov: '', cash: '', inKind: '' };
export const MAX_TABLE_ROWS = 50;
const MAX_AMOUNT_WON = 999_999_999_999;
// 자기부담 칸 — 상희 님 입력 양식대로 예비창업은 '자기부담금' 하나(현금으로 저장, 현물은 0), 초기창업은 현금 · 현물 둘.
// 금액 칸은 비워 둘 수 없다(0은 된다) — 빈 금액은 오케스트레이터가 '확인 필요'로 써서 검증-1에서 문제가 된다.
export const budgetAmountFields = (isPreliminary) => (isPreliminary
  ? [['gov', '정부지원사업비', '예) 30,000,000'], ['cash', '자기부담금', '없으면 0']]
  : [['gov', '정부지원사업비', '예) 30,000,000'], ['cash', '자기부담 현금', '없으면 0'], ['inKind', '자기부담 현물', '없으면 0']]);
export const SCHEDULE_FIELDS = [
  { key: 'category', label: '구분', placeholder: '시제품 개발', required: true },
  { key: 'content', label: '추진 내용', placeholder: '예약 · 결제 화면 개발', required: true },
  { key: 'period', label: '추진 기간', placeholder: '2026.11 ~ 2027.01', required: true },
  { key: 'detail', label: '세부 내용 (선택)', placeholder: '외주 개발사와 첫 버전 완성' },
];
// 추진 기간에는 연도가 있어야 한다(백엔드 _PERIOD_YEAR_RE와 같다).
export const periodHasYear = (period) => /20\d{2}/.test(period || '');
const EMPTY_SCHEDULE_ROW = Object.fromEntries(SCHEDULE_FIELDS.map((f) => [f.key, '']));
// 일정 표 두 개. key는 저장 요청의 section 값(웹 DB project_schedule_items.section)이고 두 유형이 같다 —
// 제목만 유형별로 다르다. 협약 이후 일정이 필수인지는 상희 님 확인 중(2026-10-10).
const SCHEDULE_SECTIONS = [
  { key: 'feasibility', required: true, title: { preliminary: '협약기간 내 일정', business: '실현가능성 일정 · 협약기간 내' } },
  { key: 'growth', title: { preliminary: '협약 이후 전체 사업 일정', business: '성장전략 일정 · 전체 사업 단계' } },
];
export const scheduleSectionsFor = (isPreliminary) => SCHEDULE_SECTIONS
  .map((s) => ({ ...s, title: s.title[isPreliminary ? 'preliminary' : 'business'] }));
// 반드시 적어야 하는 표에는 빈 줄 하나를 미리 열어 둔다.
export const emptySchedule = () => Object.fromEntries(SCHEDULE_SECTIONS
  .map(({ key, required }) => [key, required ? [{ ...EMPTY_SCHEDULE_ROW }] : []]));

const amountOf = (v) => (v ? Number(v) : 0);
const won = (n) => `${n.toLocaleString('ko-KR')}원`;

// 자기부담 가능 범위(낼 수 있는 한도)와 사업비 집행 계획의 자기부담 금액(실제로 쓸 계획)이 어긋나면 안내 한 줄을 돌려준다.
// 둘은 다른 값이라 함께 받지만, 계획이 한도를 넘거나 "어려워요"인데 계획에 자기부담이 있으면 계획서가 스스로 앞뒤가 안 맞는다.
// 막지는 않는다 — 한도는 공고 범위를 정하는 참고값이라 계획을 다시 볼지는 사용자가 정한다. 개인사업자 · 법인만 쓴다.
export function selfFundingMismatch(funding, rows) {
  if (!funding || funding.available == null) return null;
  const cash = (rows || []).reduce((sum, r) => sum + amountOf(r.cash), 0);
  const inKind = (rows || []).reduce((sum, r) => sum + amountOf(r.inKind), 0);
  if (funding.available === false) {
    return cash + inKind > 0
      ? `위에서 자기부담금이 어렵다고 고르셨는데, 사업비 집행 계획에 자기부담 금액이 ${won(cash + inKind)} 있어요. 어느 쪽이 맞는지 확인해 주세요.`
      : null;
  }
  const limit = amountOf(funding.cashLimit);
  return limit > 0 && cash > limit
    ? `자기부담 현금 합계(${won(cash)})가 위에 적은 현금 한도(${won(limit)})보다 커요. 한도나 사업비 금액을 다시 확인해 주세요.`
    : null;
}
// 총사업비 = 정부지원사업비 + 자기부담 현금 + 자기부담 현물. 사용자가 고치지 않고 화면이 계산한다(백엔드도 불일치를 막는다).
// 예비창업은 현물 칸이 없으므로 현물을 0으로 본다(유형을 바꾸기 전에 적어 둔 현물이 섞이지 않게).
export const budgetRowTotal = (row, isPreliminary = false) => amountOf(row.gov) + amountOf(row.cash) + (isPreliminary ? 0 : amountOf(row.inKind));
const sumBy = (rows, pick) => rows.reduce((acc, r) => acc + pick(r), 0);
const amountsBlank = (row, isPreliminary) => budgetAmountFields(isPreliminary).some(([key]) => row[key] === '');

// 사업비: 1 ~ 50줄, 줄마다 비목 · 집행 계획 · 금액 칸 모두(0 허용, 총사업비 1원 이상 · 상한 이하). 예비창업은 줄마다 단계,
// 1 · 2단계 각 1줄 이상.
export const budgetFilled = (rows, isPreliminary) => rows.length > 0 && rows.length <= MAX_TABLE_ROWS
  && rows.every((r) => {
    const total = budgetRowTotal(r, isPreliminary);
    return r.category.trim() && r.plan.trim() && !amountsBlank(r, isPreliminary) && total > 0 && total <= MAX_AMOUNT_WON && (!isPreliminary || r.phase);
  })
  && (!isPreliminary || BUDGET_PHASES.every((p) => rows.some((r) => r.phase === p)));

const scheduleRowFilled = (r) => SCHEDULE_FIELDS.every((f) => !f.required || String(r[f.key] ?? '').trim()) && periodHasYear(r.period);
// 일정: 반드시 적을 표는 1줄 이상, 두 표 합쳐 50줄까지, 적은 줄은 구분 · 추진 내용 · 추진 기간(연도 포함).
export const scheduleFilled = (schedule, isPreliminary) => {
  const sections = scheduleSectionsFor(isPreliminary);
  if (sumBy(sections, ({ key }) => (schedule[key] || []).length) > MAX_TABLE_ROWS) return false;
  return sections.every(({ key, required }) => {
    const rows = schedule[key] || [];
    return (!required || rows.length > 0) && rows.every(scheduleRowFilled);
  });
};

function RowCard({ onRemove, children }) {
  return (
    <div className="relative rounded-2xl bg-white border border-[var(--border)] p-4 pr-12">
      {children}
      <button type="button" aria-label="삭제" onClick={onRemove}
        className="absolute top-3 right-3 w-8 h-8 grid place-items-center rounded-lg text-[#b0b8c1] hover:text-[var(--danger)] hover:bg-[var(--muted)] transition-colors">
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>
  );
}

const addBtnCls = 'h-11 rounded-xl border border-dashed border-[#d1d6db] text-[14px] font-semibold text-[var(--primary)] hover:bg-[#f5f9ff] transition-colors';

function SumLine({ label, value, strong }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className={strong ? 'font-semibold text-[var(--fg)]' : ''}>{label}</dt>
      <dd className={strong ? 'text-[16px] font-bold text-[var(--primary-dim)]' : 'font-semibold text-[#4e5968]'}>{won(value)}</dd>
    </div>
  );
}

export function BudgetEditor({ rows, onChange, isPreliminary }) {
  const update = (i, key, value) => onChange(rows.map((r, idx) => (idx === i ? { ...r, [key]: value } : r)));
  const amountFields = budgetAmountFields(isPreliminary);
  const totalOf = (r) => budgetRowTotal(r, isPreliminary);
  // 쓰기 시작한 줄에서 금액 칸이 비어 있으면 그 줄 아래에 알린다(새로 연 빈 줄에는 띄우지 않는다).
  const startedButBlank = (r) => (r.category.trim() || r.plan.trim() || amountFields.some(([key]) => r[key] !== '')) && amountsBlank(r, isPreliminary);
  return (
    <div className="flex flex-col gap-3">
      {rows.map((r, i) => (
        <RowCard key={i} onRemove={() => onChange(rows.filter((_, idx) => idx !== i))}>
          <div className={`grid gap-3 ${isPreliminary ? 'sm:grid-cols-[8rem_minmax(0,1fr)_minmax(0,2fr)]' : 'sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]'}`}>
            {isPreliminary && <Select label="단계" value={r.phase} options={BUDGET_PHASES} onChange={(v) => update(i, 'phase', v)} />}
            <TextInput label="비목" value={r.category} placeholder="재료비" onChange={(v) => update(i, 'category', v)} />
            <TextInput label="집행 계획" value={r.plan} placeholder="시제품 부품 구입" onChange={(v) => update(i, 'plan', v)} />
          </div>
          <div className={`grid gap-3 mt-3 ${isPreliminary ? 'sm:grid-cols-2' : 'sm:grid-cols-3'}`}>
            {amountFields.map(([key, label, placeholder]) => (
              <MoneyInput key={key} label={label} value={r[key]} placeholder={placeholder} max={MAX_AMOUNT_WON} onChange={(v) => update(i, key, v)} />
            ))}
          </div>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {startedButBlank(r) && <p className="text-[12px] text-[var(--danger)]">금액 칸을 모두 채워 주세요. 없으면 0을 적어요.</p>}
            <p className="ml-auto text-[13px] text-[var(--muted-fg)]">총사업비 <b className="ml-1 text-[15px] text-[var(--fg)]">{won(totalOf(r))}</b></p>
          </div>
        </RowCard>
      ))}
      {rows.length < MAX_TABLE_ROWS
        ? <button type="button" onClick={() => onChange([...rows, { ...EMPTY_BUDGET_ROW }])} className={addBtnCls}>+ 비목 추가</button>
        : <p className="text-[12.5px] text-[var(--muted-fg)]">사업비는 {MAX_TABLE_ROWS}줄까지 적을 수 있어요.</p>}
      {rows.length > 0 && (
        <dl className="flex flex-col gap-1.5 rounded-xl bg-[#f5f7fa] px-4 py-3.5 text-[13.5px] text-[var(--muted-fg)]">
          {isPreliminary && BUDGET_PHASES.map((p) => <SumLine key={p} label={`${p} 소계`} value={sumBy(rows.filter((r) => r.phase === p), totalOf)} />)}
          {amountFields.map(([key, label]) => <SumLine key={key} label={label} value={sumBy(rows, (r) => amountOf(r[key]))} />)}
          <div className="border-t border-[#e5e8eb] mt-1 pt-2"><SumLine label="총사업비 합계" value={sumBy(rows, totalOf)} strong /></div>
        </dl>
      )}
    </div>
  );
}

export function ScheduleEditor({ value, onChange, isPreliminary }) {
  const sections = scheduleSectionsFor(isPreliminary);
  const totalRows = sumBy(sections, ({ key }) => (value[key] || []).length);
  return (
    <div className="flex flex-col gap-6">
      {sections.map(({ key, title, required }) => {
        const rows = value[key] || [];
        const yearMissing = rows.some((r) => String(r.period || '').trim() && !periodHasYear(r.period));
        return (
          <div key={key}>
            <p className="text-[14px] font-semibold text-[var(--fg)] mb-2">
              {title} <small className="font-normal text-[var(--muted-fg)]">{required ? '(1건 이상)' : '(선택)'}</small>
            </p>
            {/* 두 표를 합쳐 50줄까지 — 다 차면 추가 버튼을 숨긴다. */}
            <ListEditor items={rows} onChange={(next) => onChange({ ...value, [key]: next })} cols={2} addLabel="일정 추가" fields={SCHEDULE_FIELDS}
              max={rows.length + MAX_TABLE_ROWS - totalRows} />
            {yearMissing && <p className="mt-2 text-[12px] text-[var(--danger)]">추진 기간에 연도를 넣어 주세요. 예) 2026.11 ~ 2027.01</p>}
          </div>
        );
      })}
    </div>
  );
}
