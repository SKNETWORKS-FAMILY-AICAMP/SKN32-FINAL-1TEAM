// 서버 시각 → 화면 표시(한국 시간).
// 서버 시각은 전부 UTC다. Orchestrator 함수 결과는 끝에 `Z`가 붙어 오고, 웹 백엔드가 자기 표에서
// 읽어 내보내는 값(utcnow)은 시간대 표시 없이 온다. 시간대 표시가 없는 문자열을 그대로
// `new Date()`에 넣으면 브라우저가 한국 시각으로 읽어 9시간 어긋나고, ISO 문자열을 잘라(slice)
// 보여 주면 UTC 시각이 그대로 보인다 — 그래서 여기서 UTC로 읽어 한국 시간으로 바꾼다
// (웹연동_변경사항_웹팀전달.md 11.1).

const HAS_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

// 문자열 · Date → Date (읽을 수 없으면 null). 시간대 표시가 없는 시각 문자열은 UTC로 본다.
export function parseServerTime(value){
  if (value == null || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const text = String(value).trim();
  if (DATE_ONLY.test(text)) return null; // 날짜만 있는 값은 시각이 아니다 — formatKstDate가 그대로 쓴다
  const at = new Date(HAS_ZONE.test(text) ? text : text.replace(' ', 'T') + 'Z');
  return Number.isNaN(at.getTime()) ? null : at;
}

const KST_PARTS = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function kstParts(value){
  const at = parseServerTime(value);
  if (!at) return null;
  const parts = {};
  for (const {type, value: v} of KST_PARTS.formatToParts(at)) parts[type] = v;
  return parts;
}

// 'YYYY-MM-DD'. 날짜만 있는 값은 그대로 돌려준다.
export function formatKstDate(value){
  if (typeof value === 'string' && DATE_ONLY.test(value.trim())) return value.trim();
  const p = kstParts(value);
  return p ? `${p.year}-${p.month}-${p.day}` : '';
}

// 'YYYY-MM-DD HH:mm'
export function formatKstDateTime(value){
  const p = kstParts(value);
  return p ? `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}` : '';
}

// 'MM-DD HH:mm' — 관리자 표처럼 칸이 좁은 곳
export function formatKstShort(value){
  const p = kstParts(value);
  return p ? `${p.month}-${p.day} ${p.hour}:${p.minute}` : '';
}
