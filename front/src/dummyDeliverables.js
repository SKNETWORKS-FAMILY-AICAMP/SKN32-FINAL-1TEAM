// ReviewScreen(검수 화면)의 "실제 생성 후 다운로드" 버튼용 더미 파일 생성기.
//
// [2026-09-15, 프론트 통합 임시 구현] 실제 산출물 생성(Task #14, PlanForm/ArtifactResult/
// FinalVerdict 실데이터 연동)은 아직 백엔드에 붙기 전이라, 화면 하단 세 파일
// (사업계획서.docx / prototype.zip / 검증결과.pdf)을 실제로 "그 확장자로 열리는" 더미
// 파일로 브라우저에서 즉석 생성해 내려준다. 새 npm 의존성(JSZip/jsPDF 등)을 추가하지
// 않고 — 무압축(store) ZIP과 최소 유효 OOXML/PDF를 순수 JS로 직접 만든다.
//
// docx/zip 쪽 텍스트는 UTF-8 XML/HTML이라 한글이 그대로 렌더링된다. PDF 쪽은 표준
// 14종 내장 폰트(Helvetica)에 한글 글리프가 없어서(임베딩하려면 CJK 폰트 파일이 수
// MB 필요 — 더미 파일 취지에 안 맞음) 영문 라벨로만 작성한다.

// ---------- 공통: 다운로드 트리거 ----------
export function triggerDownload(bytes, filename, mime) {
  const blob = new Blob([bytes], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function utf8(str) {
  return new TextEncoder().encode(str);
}

function concatBytes(arrays) {
  const total = arrays.reduce((s, a) => s + a.length, 0);
  const out = new Uint8Array(total);
  let o = 0;
  for (const a of arrays) {
    out.set(a, o);
    o += a.length;
  }
  return out;
}

// ---------- 공통: 최소 ZIP(무압축 store) 작성기 ----------
const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();
function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function dosDateTime(d = new Date()) {
  const time = ((d.getHours() & 0x1f) << 11) | ((d.getMinutes() & 0x3f) << 5) | ((Math.floor(d.getSeconds() / 2)) & 0x1f);
  const date = (((d.getFullYear() - 1980) & 0x7f) << 9) | (((d.getMonth() + 1) & 0xf) << 5) | (d.getDate() & 0x1f);
  return { time, date };
}

// entries: [{ name: string, data: Uint8Array }]
export function buildZip(entries) {
  const { time, date } = dosDateTime();
  const localChunks = [];
  const centralChunks = [];
  let offset = 0;

  for (const { name, data } of entries) {
    const nameBytes = utf8(name);
    const crc = crc32(data);

    const local = new Uint8Array(30 + nameBytes.length);
    const lv = new DataView(local.buffer);
    lv.setUint32(0, 0x04034b50, true);
    lv.setUint16(4, 20, true);
    lv.setUint16(6, 0x0800, true); // UTF-8 filename flag
    lv.setUint16(8, 0, true); // method: store(무압축)
    lv.setUint16(10, time, true);
    lv.setUint16(12, date, true);
    lv.setUint32(14, crc, true);
    lv.setUint32(18, data.length, true);
    lv.setUint32(22, data.length, true);
    lv.setUint16(26, nameBytes.length, true);
    lv.setUint16(28, 0, true);
    local.set(nameBytes, 30);
    localChunks.push(local, data);

    const central = new Uint8Array(46 + nameBytes.length);
    const cv = new DataView(central.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0x0800, true);
    cv.setUint16(10, 0, true);
    cv.setUint16(12, time, true);
    cv.setUint16(14, date, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, data.length, true);
    cv.setUint32(24, data.length, true);
    cv.setUint16(28, nameBytes.length, true);
    cv.setUint16(30, 0, true);
    cv.setUint16(32, 0, true);
    cv.setUint16(34, 0, true);
    cv.setUint16(36, 0, true);
    cv.setUint32(38, 0, true);
    cv.setUint32(42, offset, true);
    central.set(nameBytes, 46);
    centralChunks.push(central);

    offset += local.length + data.length;
  }

  const centralSize = centralChunks.reduce((s, c) => s + c.length, 0);
  const centralOffset = offset;
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, entries.length, true);
  ev.setUint16(10, entries.length, true);
  ev.setUint32(12, centralSize, true);
  ev.setUint32(16, centralOffset, true);

  return concatBytes([...localChunks, ...centralChunks, end]);
}

// ---------- 사업계획서.docx ----------
function escapeXml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// sections: [{ tag, title, body }]
export function buildPlanDocx({ title, sections, footer }) {
  const paras = [];
  paras.push(
    `<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:b/><w:sz w:val="40"/></w:rPr>` +
      `<w:t xml:space="preserve">${escapeXml(title)}</w:t></w:r></w:p>`
  );
  paras.push('<w:p/>');
  sections.forEach((s, i) => {
    paras.push(
      `<w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr>` +
        `<w:t xml:space="preserve">［${escapeXml(s.tag)}］ ${String(i + 1).padStart(2, '0')}. ${escapeXml(s.title)}</w:t></w:r></w:p>`
    );
    paras.push(`<w:p><w:r><w:t xml:space="preserve">${escapeXml(s.body)}</w:t></w:r></w:p>`);
    paras.push('<w:p/>');
  });
  if (footer) {
    paras.push(
      `<w:p><w:r><w:rPr><w:i/><w:color w:val="888888"/><w:sz w:val="16"/></w:rPr>` +
        `<w:t xml:space="preserve">${escapeXml(footer)}</w:t></w:r></w:p>`
    );
  }

  const documentXml = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
${paras.join('\n')}
<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1417" w:left="1417"/></w:sectPr>
</w:body>
</w:document>`;

  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>`;

  const rels = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>`;

  return buildZip([
    { name: '[Content_Types].xml', data: utf8(contentTypes) },
    { name: '_rels/.rels', data: utf8(rels) },
    { name: 'word/document.xml', data: utf8(documentXml) },
  ]);
}

export function downloadPlanDocx({ title, sections, footer }) {
  const bytes = buildPlanDocx({ title, sections, footer });
  triggerDownload(
    bytes,
    '사업계획서.docx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  );
}

// ---------- prototype.zip ----------
export function buildPrototypeZip({ itemName, html }) {
  const readme = `prototype.zip
==============
이 파일은 S-Brain이 생성한 프로토타입 초안입니다. 실제 서비스 코드가 아니며,
index.html을 브라우저로 열면 화면 예시를 확인할 수 있습니다.

항목: ${itemName || ''}
생성 시각: ${new Date().toISOString()}
`;
  return buildZip([
    { name: 'index.html', data: utf8(html) },
    { name: 'README.txt', data: utf8(readme) },
  ]);
}

export function downloadPrototypeZip({ itemName, html }) {
  const bytes = buildPrototypeZip({ itemName, html });
  triggerDownload(bytes, 'prototype.zip', 'application/zip');
}

// ---------- 검증결과.pdf ----------
// lines: [{ text, size? }]
export function buildVerificationPdf({ lines }) {
  const esc = (s) => String(s).replace(/([()\\])/g, '\\$1');
  const contentParts = lines.map((l, i) => {
    const size = l.size || 12;
    const y = 750 - i * 20;
    return `BT /F1 ${size} Tf 56 ${y} Td (${esc(l.text)}) Tj ET`;
  });
  const content = contentParts.join('\n');

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ];

  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((obj, i) => {
    offsets.push(pdf.length);
    pdf += `${i + 1} 0 obj\n${obj}\nendobj\n`;
  });
  const xrefStart = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i <= objects.length; i++) {
    pdf += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;

  return utf8(pdf);
}

export function downloadVerificationPdf({ lines }) {
  const bytes = buildVerificationPdf({ lines });
  triggerDownload(bytes, '검증결과.pdf', 'application/pdf');
}
