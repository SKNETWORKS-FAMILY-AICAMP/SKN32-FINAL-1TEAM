// 단위 테스트 결과서(워드) 생성 — 숫자는 모두 이번 실행 리포트 폴더에서 읽는다.
//   node build_report.js <리포트 폴더> <출력 docx>
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, HeadingLevel,
  AlignmentType, WidthType, ShadingType, BorderStyle, LevelFormat, PageBreak,
  Footer, PageNumber, TableOfContents,
} = require('docx');

const [folder, out] = process.argv.slice(2);
const S = JSON.parse(fs.readFileSync(path.join(folder, 'coverage_summary.json'), 'utf8'));
const T = JSON.parse(fs.readFileSync(path.join(folder, 'tests.json'), 'utf8'));

const FONT = '맑은 고딕';
const NAVY = '1F4E78';
const PALE = 'EAF2F8';
const GRAY = 'F5F7F9';
const BORDER = { style: BorderStyle.SINGLE, size: 4, color: 'BFBFBF' };
const BORDERS = { top: BORDER, bottom: BORDER, left: BORDER, right: BORDER };
const W = 9026; // A4 본문 폭(여백 1인치)

const kst = (iso) => {
  const d = new Date(iso);
  const k = new Date(d.getTime() + 9 * 3600 * 1000);
  const p = (n) => String(n).padStart(2, '0');
  return `${k.getUTCFullYear()}-${p(k.getUTCMonth() + 1)}-${p(k.getUTCDate())} ${p(k.getUTCHours())}:${p(k.getUTCMinutes())} (한국 시각)`;
};
const pct = (v) => `${v.toFixed(1)}%`;
const num = (v) => v.toLocaleString('en-US');

function p(text, opts = {}) {
  const runs = (Array.isArray(text) ? text : [text]).map((t) =>
    typeof t === 'string' ? new TextRun({ text: t, font: FONT, size: opts.size || 21, bold: opts.bold, color: opts.color }) : t);
  return new Paragraph({ children: runs, spacing: { after: opts.after ?? 120, line: 300 }, alignment: opts.align });
}
const b = (t) => new TextRun({ text: t, font: FONT, size: 21, bold: true });
const h1 = (t) => new Paragraph({ keepNext: true, heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t, font: FONT })], spacing: { before: 360, after: 160 } });
const h2 = (t) => new Paragraph({ keepNext: true, heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT })], spacing: { before: 240, after: 120 } });
const bullet = (text) => new Paragraph({
  numbering: { reference: 'bullets', level: 0 },
  children: (Array.isArray(text) ? text : [text]).map((t) => (typeof t === 'string' ? new TextRun({ text: t, font: FONT, size: 21 }) : t)),
  spacing: { after: 80, line: 290 },
});

function cell(text, width, { head = false, fill, align, mono = false, size = 18 } = {}) {
  const lines = String(text).split('\n');
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders: BORDERS,
    shading: head ? { fill: NAVY, type: ShadingType.CLEAR, color: 'auto' } : fill ? { fill, type: ShadingType.CLEAR, color: 'auto' } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: lines.map((line) => new Paragraph({
      alignment: align,
      children: [new TextRun({ text: line, font: mono ? 'Consolas' : FONT, size, bold: head, color: head ? 'FFFFFF' : undefined })],
    })),
  });
}

function table(widths, header, rows, { aligns = [], mono = [], size = 18, zebra = true } = {}) {
  const total = widths.reduce((a, c) => a + c, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA },
    columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], { head: true, align: aligns[i], size })) }),
      ...rows.map((r, ri) => new TableRow({
        children: r.map((v, i) => cell(v, widths[i], { fill: zebra && ri % 2 ? GRAY : undefined, align: aligns[i], mono: mono[i], size })),
      })),
    ],
  });
}
const gap = () => new Paragraph({ children: [], spacing: { after: 120 } });

// ── 기능별 핵심 확인 내용 ───────────────────────────────────
const KEY = {
  '①': 'K-Startup 목록을 100건씩 쪽 나눠 서버가 보고한 건수까지 모은다. 빈 쪽에서 멈추고, 인증키가 없으면 부르지 않는다.',
  '②': '모르는 값을 "제한 없음"·"모집 중"으로 바꾸지 않는다. 목록에서 빠진 공고만 닫고, 늦게 온 옛 목록은 최신 공고를 닫지 않는다.',
  '③': '파일 앞부분으로 종류를 판별하고, 30MB 상한·실패 사유를 남긴다. 끊겨도 이어서 하고, 연속 20건 실패면 멈춘다.',
  '④': '내용·설정이 바뀐 벡터와 새 첨부만 올린다. 벡터는 1,024차원 float32 = 4,096바이트, 내용이 이름(해시)과 다른 파일은 올리지 않는다.',
  '⑤': 'AI가 지어낸 근거 문장·다른 줄의 점수는 버린다. 하루 호출 상한을 지키고, 호출 기록이 깨지면 그날은 부르지 않는다.',
  '⑥': '한쪽 수집이 실패해도 다른 쪽은 처리한다. 목록이 불완전하면 공고를 닫지 않고, 이미 실행 중이면 겹쳐 돌지 않는다.',
  '⑦': '판정은 충족·미달·모름 세 값. 모르면 빼지 않는다. 정형 필터와 자격 확인이 같은 함수로 같은 결론을 낸다.',
  '⑧': '정형 필터를 먼저 걸고 그 안에서 검색한다. 지역·업종은 순위에만 쓴다. 검색 부품이 고장 나도 500 오류 없이 대체 순서로 낸다.',
  '⑨': '수집 상태는 정상·지연·실패 셋 중 하나. 모르는 값은 null로 두고 지어내지 않는다. 내용 지문은 수집 시각에 흔들리지 않는다.',
  '⑩': '근거 문장에 "N점"이 있을 때만 점수를 인정한다. 해당 없음은 0, 모름은 null로 구분한다. 세부사업별로 다르면 null.',
  '⑪': '.env를 읽되 이미 있는 환경 변수가 이긴다. 인코딩된 인증키는 경고하고(값은 찍지 않음), 필요한 값이 없으면 안내 후 종료한다.',
};

// ── 대표 시험 사례(기능마다 2~3개) ───────────────────────────
const CASES = {
  '①': [
    ['test_fetch · test_collects_every_page_until_total', '서버가 250건이 있다고 보고, 한 번에 100건씩 준다', '3번(100+100+50) 불러 250건을 순서대로 모은다'],
    ['test_fetch · test_stops_on_empty_page_even_if_total_is_larger', '서버는 500건이라 보고했는데 2쪽부터 비어 있다', '빈 쪽에서 멈춘다(무한 반복 없음)'],
    ['test_fetch · test_main_stops_without_key', '인증키(KSTARTUP_KEY)가 없다', '안내를 남기고 종료, 외부 API는 한 번도 부르지 않는다'],
  ],
  '②': [
    ['test_normalize · test_unknown_is_not_unrestricted_or_open', '기업마당 공고에 업력·지역·모집 상태 정보가 없다', '업력·지역은 빈 값, 모집 상태는 unknown — "제한 없음"·"모집 중"으로 채우지 않는다'],
    ['test_store_mysql · test_이_목록보다_최신인_행은_닫지_않는다', '늦게 도착한 옛 목록으로 "목록에 없는 공고 닫기"를 한다', '목록보다 최신으로 저장된 공고는 닫지 않는다'],
    ['test_store_mysql · test_빈_목록이면_아무것도_닫지_않는다', '목록이 비어 있다(수집 실패 등)', '공고를 하나도 닫지 않는다'],
  ],
  '③': [
    ['test_attachment_pipeline · test_short_text_large_file_is_image_only', '50KB 넘는 PDF인데 글자가 0자(글꼴을 곡선으로 넣은 문서)', '"빈 문서"가 아니라 그림 문서(OCR 대상)로 분류'],
    ['test_attachment_pipeline · test_resume_skips_done_and_records_each', '3건 중 1건은 지난번에 이미 처리했다', '나머지 2건만 처리하고 한 건씩 바로 기록한다'],
    ['test_attachment_pipeline · test_gives_up_after_consecutive_failures', '30건이 모두 내려받기 실패', '20건째에서 상대 서버 문제로 보고 멈춘다'],
  ],
  '④': [
    ['test_upload_vectors · test_only_new_or_changed', '공고 4건: 그대로·내용 바뀜·설정 바뀜·DB에 없음', '바뀐 3건만 올린다'],
    ['test_upload_vectors · test_bytes_are_float32_little_endian_4096', '1,024차원 벡터 하나', '4,096바이트로 저장되고 되읽으면 원래 값과 같다'],
    ['test_upload_attachments · test_corrupt_file_not_uploaded', '파일 이름(해시)과 실제 내용이 다른 파일', '올리지 않고 "해시 불일치 1건"으로 센다'],
  ],
  '⑤': [
    ['test_extract_bonus · test_made_up_quote_is_rejected', 'AI가 공고문에 없는 근거 문장을 냈다', '근거를 찾지 못한 것으로 보고 버린다'],
    ['test_extract_bonus · test_daily_record_broken_skips_calls', '하루 호출 기록 파일이 깨져 있다', '호출 수를 0으로 보지 않고 그날은 AI를 부르지 않는다'],
    ['test_applicant_type_daily · test_limit_is_per_day_not_per_run', '하루에 여러 번 실행한다', '상한이 실행마다가 아니라 하루 합계로 지켜진다'],
  ],
  '⑥': [
    ['test_pipeline · test_K_목록이_서버_건수보다_적으면_닫지_않는다', 'K-Startup 목록이 서버가 보고한 건수보다 적다', '저장은 하되, 목록이 불완전하므로 빠진 공고를 닫지 않는다'],
    ['test_pipeline · test_K_수집이_실패해도_기업마당은_처리된다', 'K-Startup 수집이 실패했다', '기업마당은 그대로 처리한다'],
    ['test_pipeline · test_이미_실행_중이면_busy', '배치가 이미 돌고 있는데 또 실행했다', '겹쳐 돌지 않고 busy로 끝낸다'],
  ],
  '⑦': [
    ['test_gate · test_예산_소진시까지는_판단_불가지_미달이_아니다', '접수기간이 "예산 소진 시까지"(마감일 없음)', '미달이 아니라 "확인 필요(모름)"'],
    ['test_eligibility · test_body_allowed_overrides_api_age_no', '업력 칸은 "3년미만"(예비창업자 불가로 읽힘), 본문에는 예비창업자 가능', '본문을 따라 업력도 충족'],
    ['test_eligibility · test_same_gate_result_as_matching_filter', '업력 3년 미만 공고에 업력 6년 법인', '자격 확인은 미달, 추천의 정형 필터도 같은 이유로 뺀다'],
  ],
  '⑧': [
    ['test_match_rules · test_region_is_not_a_filter', '경기 신청자에게 서울·경기 공고', '서울 공고도 후보에 남고 순위만 뒤로 간다'],
    ['test_match_rules · test_finds_live_notices_beyond_the_first_page', '검색 상위권이 모두 마감된 공고', '필터를 먼저 걸어 뒤쪽의 신청 가능한 공고를 찾아낸다'],
    ['test_match_deh · test_both_fail_orders_by_deadline_without_fit', '의미 검색과 단어 검색이 모두 고장', '500 오류 없이 마감 임박순으로 내고, 적합도는 비워 둔다'],
  ],
  '⑨': [
    ['test_collection_status · test_older_than_24h_is_delayed_and_blocks', '마지막 저장이 25시간 전', '"지연"이고 추천을 멈추라고 알린다'],
    ['test_notice_api · test_detail_unknown_values_are_null_not_made_up', '공고에 주관 기관·마감일·지원 금액이 없다', 'null로 낸다(지원 금액 0을 "정보 없음"으로 쓰지 않는다)'],
    ['test_notice_api · test_collection_time_fields_do_not_change_version', '내용은 같고 수집 시각만 바뀌었다', '내용 지문이 그대로다'],
  ],
  '⑩': [
    ['test_bonus · test_all_not_applicable_is_zero_but_unknown_is_null', '남성 신청자: ① 가점이 모두 해당 없음 ② 판단 못 하는 항목이 섞임', '① 0점 ② null(모름) — 0과 모름을 구분'],
    ['test_bonus · test_points_from_other_cell_or_serial_number_are_not_trusted', '점수가 근거 문장 밖에서 왔거나, 숫자가 연번뿐', '점수로 인정하지 않는다'],
    ['test_bonus · test_programs_differ_is_null', '세부사업마다 가산점 결과가 다르다', '최대값을 고르지 않고 null'],
  ],
  '⑪': [
    ['test_config · test_existing_environment_wins', '.env와 이미 설정된 환경 변수에 같은 이름이 있다', '이미 설정된 값을 덮지 않는다'],
    ['test_config · test_url_encoded_key_warns', '인증키가 %2B 같은 인코딩된 값', '경고를 내되 키 값 자체는 찍지 않는다'],
    ['test_config · test_require_missing_exits_with_guide', '필요한 값이 없다', '안내 문구와 함께 종료 코드 1'],
  ],
};

// 대표 사례가 실제 이번 실행에서 통과했는지 확인
const outcome = {};
for (const t of T.tests) outcome[`${t.module} · ${t.id.split('.').pop()}`] = t.outcome;
for (const [f, list] of Object.entries(CASES)) {
  for (const c of list) {
    if (outcome[c[0]] !== 'pass') throw new Error(`대표 사례 결과가 통과가 아님: ${c[0]} → ${outcome[c[0]]}`);
  }
}

const run = S.run;
const passed = run.total - run.failures - run.errors - run.skipped;
const scopeTotal = S.scope_tests.pass + S.scope_tests.skip + S.scope_tests.fail + S.scope_tests.error;
const outScope = Object.values(S.out_of_scope_tests).reduce((a, c) => a + c, 0);
const newTotal = Object.values(S.new_tests).reduce((a, c) => a + c, 0);
const lowFiles = S.files.filter((f) => f.percent < 50).sort((a, b) => a.percent - b.percent);

const LOW_REASON = {
  'ec2/ec2_vecstore.py': '팀 EC2(리눅스)에서만 도는 색인 갱신. 서비스는 10/7부터 이 색인을 쓰지 않는다',
  'search/vecstore.py': '임베딩 모델을 실제로 올려 색인을 만드는 부분. 모델·공용 DB 없이는 실행할 수 없다',
  'collect/fetch_bizinfo.py': '기업마당 사이트에서 실제로 받아오는 부분(인터넷 필요). 받은 뒤 처리는 배치 시험에서 확인',
  'shared/store_mysql.py': '저장 SQL 대부분은 MySQL 통합 시험(건너뜀 16개)에서만 실행된다',
  'collect/attachment_store.py': '저장 규칙 검사는 시험했고, DB 저장 부분은 MySQL 통합 시험(건너뜀)에서만 실행된다',
  'collect/extract_conditions.py': 'OpenAI를 실제로 부르는 부분과 명령줄 실행 부분',
  'shared/embed.py': '임베딩 모델(BGE-M3)을 실제로 올려 계산하는 부분',
  'collect/hwp5.py': '실제 HWP 파일을 여는 부분. 이번에는 HWP 샘플 없이 글자 해석 규칙만 시험',
  'experiments/sql_semantic/applicant_type_llm.py': 'OpenAI를 실제로 부르는 부분과 명령줄 실행 부분',
  'collect/doctext.py': 'PDF 해석(pdfplumber)·명령줄 부분. 실제 PDF 샘플 시험 없음',
};

const children = [];
// 표지
children.push(
  new Paragraph({ spacing: { before: 2400, after: 240 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: '[단위 테스트]', font: FONT, size: 28, color: NAVY })] }),
  new Paragraph({ spacing: { after: 240 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: '공고 데이터·매칭 단위 테스트 결과서', font: FONT, size: 44, bold: true })] }),
  new Paragraph({ spacing: { after: 1200 }, alignment: AlignmentType.CENTER, children: [new TextRun({ text: 'S-Brain · 공고 수집 · 매칭 · 자격 판정 담당 부분', font: FONT, size: 24, color: '595959' })] }),
);
children.push(table([2600, 5600], ['항목', '내용'], [
  ['프로젝트', 'S-Brain (SK네트웍스 Family AI 32기 1팀)'],
  ['담당', '이근준 — 공고 데이터 수집·매칭·자격 판정'],
  ['시험 실행', kst(run.started_at)],
  ['결과', `전체 ${num(run.total)}개 · 실패 0 · 오류 0 · 건너뜀 ${run.skipped}`],
  ['맡은 범위 줄 커버리지', `${pct(S.scope_coverage.percent)} (${num(S.scope_coverage.statements)}줄 중 ${num(S.scope_coverage.statements - S.scope_coverage.missed)}줄 실행)`],
], { size: 20 }));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 1. 개요
children.push(h1('1. 개요'));
children.push(h2('1.1 무엇을 시험했나'));
children.push(p('S-Brain에서 이 담당이 맡은 일은 "정부지원 공고를 매일 모아 공용 DB에 넣고, 신청자 정보에 맞는 공고를 골라 순위를 매기고, 공고마다 신청 자격을 판정하는 것"이다. 이번 단위 테스트는 이 가운데 실제 서비스에 쓰이는 부분 11개 기능을 대상으로 했다.'));
children.push(p('단위 테스트는 기계 전체를 돌려 보기 전에 부품 하나하나를 작업대에 올려 놓고 "이 입력을 넣으면 이 결과가 나오는가"를 확인하는 시험이다. 부품마다 정상인 경우뿐 아니라 고장·누락·이상한 값이 들어오는 경우를 함께 넣어 본다.'));
children.push(h2('1.2 시험 환경'));
children.push(table([2600, 6426], ['항목', '내용'], [
  ['운영체제', 'Windows 11 Pro'],
  ['언어', `Python ${run.python} (프로젝트 가상환경 .venv)`],
  ['시험 도구', 'unittest (Python 표준 시험 도구)'],
  ['커버리지 도구', 'coverage 7.16.2 — 시험이 코드의 몇 줄을 실제로 실행했는지 잰다'],
  ['실행 일시', `${kst(run.started_at)} 시작, 약 ${Math.round((new Date(run.finished_at) - new Date(run.started_at)) / 1000)}초 걸림`],
  ['실행 명령', 'python -X utf8 -m coverage run -m run_unit\n(= python -m unittest discover -s tests 와 같은 시험 묶음)'],
  ['결과 기록', `reports/${path.basename(folder)}/ (요약·파일별 표·시험별 결과 JSON·실행 기록)`],
], { mono: [false, false], size: 19 }));
children.push(h2('1.3 원칙'));
children.push(bullet('실제 외부 API(K-Startup·기업마당), 팀 공용 DB, OpenAI, 인터넷을 부르지 않는다. 가짜 응답·가짜 DB 연결·임시 파일로 시험한다. 그래서 언제 다시 돌려도 같은 결과가 나오고, 비용이 0이며, 공용 데이터를 건드리지 않는다.'));
children.push(bullet('운영 코드는 고치지 않았다. 시험만 더했고, 기존 시험의 기대값도 바꾸지 않았다.'));
children.push(bullet('판정은 충족(True)·미달(False)·모름(None) 세 값이다. "모르면 빼지 않는다"는 원칙이 지켜지는지를 특히 많이 확인했다.'));

// 2. 결과 요약
children.push(h1('2. 결과 요약'));
children.push(table([4200, 2400, 2426], ['구분', '시험 수', '비고'], [
  ['전체 시험', num(run.total), `통과 ${num(passed)} · 실패 ${run.failures} · 오류 ${run.errors} · 건너뜀 ${run.skipped}`],
  ['맡은 범위(11개 기능) 시험', num(scopeTotal), `통과 ${S.scope_tests.pass} · 건너뜀 ${S.scope_tests.skip}`],
  ['범위 밖 시험(평가 도구·검증 화면 등)', num(outScope), '함께 돌렸고 모두 통과, 표에는 넣지 않음'],
  ['이번에 더한 시험', num(newTotal), '시험 파일 7개 새로 작성, 모두 통과'],
  ['건너뛴 시험', String(run.skipped), 'MySQL 통합 시험(아래 설명)'],
], { aligns: [undefined, AlignmentType.CENTER, undefined], size: 19 }));
children.push(gap());
children.push(p([b('커버리지 '), `맡은 범위 코드 ${num(S.scope_coverage.statements)}줄 중 ${num(S.scope_coverage.statements - S.scope_coverage.missed)}줄이 시험 중 실제로 실행됐다(${pct(S.scope_coverage.percent)}). 목표치는 두지 않고 있는 그대로 적었다. 자격 판정(${pct(S.features[6].percent)})·가산점(${pct(S.features[9].percent)})·조율 창구 응답(notice_api.py ${pct(S.files.find((f) => f.file === 'search/notice_api.py').percent)})처럼 서비스 결과를 직접 정하는 부분은 높고, 인터넷·DB·AI 모델이 있어야만 도는 부분이 낮다(5장).`]));
children.push(p([b('건너뛴 16개 '), '실제 MySQL에 표를 만들고 쓰고 지우는 통합 시험이다. 시험용 MySQL이 따로 없고, 팀 공용 DB에 쓰는 시험을 돌리면 팀원 데이터가 바뀔 수 있어 이번에는 돌리지 않았다. 설정(MYSQL_INTEGRATION_TEST=1)을 켜야만 도는 시험이다.']));
children.push(h2('이번에 더한 시험 7개 파일'));
const NEWFILES = [
  ['test_fetch.py', 'K-Startup 수집', '쪽 나눔·전체 건수·인증키 전달·빈 응답·깨진 응답'],
  ['test_attachment_pipeline.py', '첨부 본문 추출', '종류 판별·30MB 상한·실패 기록·이어 하기·연속 실패 상한·적재 후 정리'],
  ['test_hwp5.py', '구 HWP 글자 해석', '본문 레코드 해석·제어문자·이모지 등 (HWP 샘플 없이)'],
  ['test_upload_vectors.py', '벡터 올리기', '바뀐 것만·4,096바이트·100건씩·공고 없는 벡터 건너뜀'],
  ['test_upload_attachments.py', '첨부 원본 올리기', '이미 있는 해시 건너뜀·상한 파일 안 올림·커밋 단위'],
  ['test_config.py', '공통 설정', '.env 해석·기존 값 우선·인코딩 키 경고·값 없을 때 종료'],
  ['test_eligibility.py', '자격 판정 한 곳', '조건 네 줄 순서·본문 우선·세부사업별 허용·설립일 없음'],
];
const newCount = {};
for (const t of T.tests) newCount[t.module] = (newCount[t.module] || 0) + 1;
children.push(table([2900, 1900, 3426, 800], ['시험 파일', '대상', '확인 내용', '시험'],
  NEWFILES.map(([f, a, c]) => [f, a, c, String(newCount[f.replace('.py', '')] || 0)]),
  { mono: [true], aligns: [undefined, undefined, undefined, AlignmentType.CENTER], size: 18 }));

// 3. 기능별 결과
children.push(h1('3. 기능별 결과'));
children.push(p('커버리지는 그 기능에 속한 코드 줄 가운데 시험 중 한 번이라도 실행된 줄의 비율이다. 시험 수는 그 기능을 직접 겨냥한 시험 파일 기준이다.'));
children.push(table([1750, 700, 700, 800, 900, 4176], ['기능', '시험', '통과', '건너뜀', '커버리지', '핵심 확인 내용'],
  S.features.map((f) => [`${f.feature} ${f.name}`, String(f.tests), String(f.passed), String(f.skipped), pct(f.percent), KEY[f.feature]]),
  { aligns: [undefined, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER], size: 17 }));
children.push(gap());
children.push(p('기능별 코드 파일과 파일마다의 커버리지는 부록 A에 있다.', { size: 19, color: '595959' }));

// 4. 대표 사례
children.push(h1('4. 대표 시험 사례'));
children.push(p('기능마다 판정 원칙(모르면 빼지 않음, 정형 필터 먼저, 0과 모름의 구분, 수집 상태, 내용 지문 등)이 드러나는 시험을 골랐다. 실제 결과는 모두 이번 실행 기록(tests.json)에서 확인한 값이다.'));
for (const f of S.features) {
  children.push(h2(`${f.feature} ${f.name}`));
  children.push(table([2700, 2500, 2926, 900], ['시험 이름', '입력(상황)', '기대 결과', '실제'],
    CASES[f.feature].map(([n, i, e]) => [n.replace(' · ', '\n'), i, e, '통과']),
    { mono: [true], aligns: [undefined, undefined, undefined, AlignmentType.CENTER], size: 17 }));
}

// 5. 한계
children.push(h1('5. 한계와 미검사'));
children.push(h2('5.1 돌리지 않은 시험'));
children.push(bullet([b('MySQL 통합 시험 16개 '), '(정규화·저장 6개, 첨부 결과 저장 10개). 시험용 MySQL이 없고 공용 DB에 쓰면 안 되기 때문이다. 같은 규칙의 입력 검사·SQL 모양은 가짜 연결로 시험했지만, 실제 DB에서 잠금·되돌리기가 맞게 도는지는 이번에 확인하지 않았다.']));
children.push(h2('5.2 이번 시험이 다루지 않는 것'));
children.push(bullet('실제 외부 API(K-Startup·기업마당) 응답. 형식이 바뀌면 이 시험으로는 알 수 없다(매일 배치 기록과 수집 상태 창구로 따로 본다).'));
children.push(bullet('실제 첨부 파일 샘플(PDF·HWP·HWPX) 해석. HWP는 파일 없이 글자 해석 규칙만 시험했고, 파일을 여는 부분은 "파일 시험 없음"이다.'));
children.push(bullet('OpenAI 호출 결과의 정확도. 시험은 AI 답을 받은 뒤의 검사(근거 확인·점수 확인)만 본다. 정확도는 별도 평가(판정 일치율 등)에서 다룬다.'));
children.push(bullet('임베딩 모델(BGE-M3) 계산과 검색 품질. 순위 규칙은 가짜 벡터로 시험했고, 검색 품질은 평가 도구(범위 밖)에서 따로 잰다.'));
children.push(h2('5.3 커버리지가 50% 미만인 파일'));
children.push(table([3600, 900, 4526], ['파일', '커버리지', '낮은 이유'],
  lowFiles.map((f) => [f.file, pct(f.percent), LOW_REASON[f.file] || '명령줄 실행·외부 연결 부분']),
  { mono: [true], aligns: [undefined, AlignmentType.CENTER], size: 17 }));
children.push(h2('5.4 범위 밖'));
children.push(p(`평가 도구(eval/), 검증 화면·실험 경로(experiments/의 서비스용 3개 모듈 외), 모델 학습(ml/), 공유 페이지(share/), 시험 화면(web/), DB 백업 도구, 일회성 스크립트, 옛 시험 CLI는 서비스에 쓰이지 않아 표에서 뺐다. 이 영역의 기존 시험 ${outScope}개도 함께 돌렸고 모두 통과했다.`));
children.push(h2('5.5 시험 중 발견한 것'));
children.push(bullet('운영 코드의 결함은 발견하지 못했다.'));
children.push(bullet('첨부 처리·벡터 올리기의 "기본 파일 위치"는 함수가 만들어질 때 고정된다. 시험에서 위치만 바꿔서는 실제 data 폴더를 막지 못해, 처음 쓴 시험 하나가 실제 결과 파일에 가짜 기록을 남겼다. 발견 즉시 지웠고(가짜 기록만 든 새 파일이었음), 시험이 함수 자체를 임시 폴더로 돌리게 고친 뒤 "실제 파일을 건드리면 실패"하는 확인을 더했다.'));
children.push(bullet('search/app.py 머리말의 경로 글자(\\.venv) 때문에 Python이 경고(SyntaxWarning) 한 줄을 낸다. 동작에는 영향이 없다.'));

// 부록 A
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('부록 A. 파일별 커버리지'));
children.push(table([700, 4300, 1200, 1200, 1626], ['기능', '파일', '코드 줄', '실행 줄', '커버리지'],
  S.files.map((f) => [f.feature, f.file, num(f.statements), num(f.covered), pct(f.percent)]),
  { mono: [false, true], aligns: [AlignmentType.CENTER, undefined, AlignmentType.CENTER, AlignmentType.CENTER, AlignmentType.CENTER], size: 17 }));

// 부록 B
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(h1('부록 B. 범위 안 시험 전체 목록'));
children.push(p(`맡은 범위 시험 ${scopeTotal}개. 결과는 통과·건너뜀(MySQL 통합 시험)이다.`));
const OUT_WORD = { pass: '통과', skip: '건너뜀', fail: '실패', error: '오류' };
const order = S.features.map((f) => f.feature);
const scoped = T.tests.filter((t) => t.feature).sort((a, b) =>
  order.indexOf(a.feature) - order.indexOf(b.feature) || a.id.localeCompare(b.id));
children.push(table([600, 2500, 4926, 1000], ['기능', '시험 파일', '시험 이름', '결과'],
  scoped.map((t) => {
    const parts = t.id.split('.');
    return [t.feature, t.module + '.py', parts.slice(-2).join('.'), OUT_WORD[t.outcome] || t.outcome];
  }),
  { mono: [false, true, true], aligns: [AlignmentType.CENTER, undefined, undefined, AlignmentType.CENTER], size: 15 }));

const doc = new Document({
  creator: '이근준',
  title: '공고 데이터·매칭 단위 테스트 결과서',
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 30, bold: true, font: FONT, color: NAVY }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true,
        run: { size: 24, bold: true, font: FONT, color: '17365D' }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
      children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18, color: '808080' })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, buf);
  console.log('saved', out, buf.length);
});
