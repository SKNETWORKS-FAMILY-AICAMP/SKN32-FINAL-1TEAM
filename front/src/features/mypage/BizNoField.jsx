import React, { useState } from 'react';
import { checkBizNo } from '../../api.js';
import { useMyPageStore } from '../../store/useMyPageStore.js';
import { formatBizNo } from './derive.js';
import { Badge, Field, inputCls } from './ui.jsx';

const STATUS_TONE = { '01': 'ok', '02': 'warn', '03': 'danger' };
const STATUS_HINT = {
  '02': '휴업 중이면 지원이 제한되는 공고가 있어요.',
  '03': '폐업한 번호예요. 새로 사업체를 냈다면 그 사업자등록번호를 입력해 주세요.',
};

export default function BizNoField({ value, onChange }) {
  const bizStatus = useMyPageStore((s) => s.profiles[s.activeIndex].bizStatus);
  const profileId = useMyPageStore((s) => s.profiles[s.activeIndex].profileId);
  const setBizStatus = useMyPageStore((s) => s.setBizStatus);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 번호를 고치면 이전 조회 결과는 더 이상 이 번호의 것이 아니다.
  const result = bizStatus?.checkedNo === value ? bizStatus : null;
  const ready = value.replace(/\D/g, '').length === 10;

  const lookup = async () => {
    setLoading(true);
    setError('');
    try {
      // profileId가 아직 없으면(이 슬롯을 한 번도 저장한 적 없으면) 서버는 조회 결과를
      // 어느 슬롯에도 저장하지 않는다(back/app/routers/biz_check.py) — 화면엔 그래도
      // 결과가 뜨지만, 슬롯을 먼저 저장해야 새로고침 후에도 남는다.
      const res = await checkBizNo(value, profileId);
      setBizStatus({ ...res, checkedNo: value });
    } catch (err) {
      setError(err.status === 401 ? '로그인이 끊겼어요. 다시 로그인해 주세요.' : '지금은 조회할 수 없어요. 잠시 후 다시 시도해 주세요.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Field label="사업자등록번호">
        <div className="flex gap-2">
          <input value={value} inputMode="numeric" placeholder="000-00-00000" className={inputCls}
            onChange={(e) => { onChange(formatBizNo(e.target.value)); setError(''); }}
            onKeyDown={(e) => { if (e.key === 'Enter' && ready) { e.preventDefault(); lookup(); } }} />
          <button type="button" onClick={lookup} disabled={!ready || loading}
            className="shrink-0 h-11 px-4 rounded-xl bg-[#e8f1ff] text-[var(--primary-dim)] text-[14px] font-semibold hover:bg-[#dbe9ff] disabled:bg-[var(--muted)] disabled:text-[#b0b8c1] transition-colors">
            {loading ? '조회 중…' : result ? '다시 조회' : '국세청 조회'}
          </button>
        </div>
      </Field>
      <div className="mt-2 min-h-7" aria-live="polite">
        {error && <p className="text-[13px] text-[var(--danger)]">{error}</p>}
        {!error && !result && <p className="text-[12.5px] text-[var(--muted-fg)]">조회하면 영업상태와 과세유형을 자동으로 확인해요.</p>}
        {!error && result && !result.valid && <Badge tone="danger">국세청에 등록되지 않은 번호예요</Badge>}
        {!error && result?.valid && (
          <>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone={STATUS_TONE[result.b_stt_cd] || 'muted'}>{result.label}</Badge>
              {result.tax_type && <Badge tone="muted">{result.tax_type}</Badge>}
            </div>
            {STATUS_HINT[result.b_stt_cd] && <p className="text-[12.5px] text-[var(--muted-fg)] mt-1.5">{STATUS_HINT[result.b_stt_cd]}</p>}
          </>
        )}
      </div>
    </div>
  );
}
