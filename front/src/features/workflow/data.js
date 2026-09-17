// features/Workflow.jsx(2235줄)에서 분리 — 원본 로직/주석은 그대로 옮김.
export const SIMILAR_ANNOUNCEMENT_ALERTS = [
  { id: 1, itemName: '동네 헬스장 예약 서비스', title: 'AI 서비스 실증지원 사업', org: '정보통신산업진흥원', similarity: 87, detectedAt: '2026-09-09' },
  { id: 2, itemName: '중고거래 안전결제 플랫폼', title: '생활밀착형 서비스 창업 지원사업', org: '중소벤처기업부', similarity: 81, detectedAt: '2026-09-07' },
];

// 이메일 발송은 이번 범위에서 제외(최종발표 이후 유료화 검토와 함께 진행) — 카카오
// 알림톡은 사업자등록이 있어야 보낼 수 있어 예비창업자 사용자를 못 받아 대상에서
// 제외했다. 그래서 여기선 "화면·등록 목록·페이지 내 알림"까지만 만들고, 이메일
// 항목은 흐리게 표시만 해서 로드맵은 보여주되 기능은 없다는 걸 분명히 한다.
export const AI_SUMMARY_SOURCE_NOTICE = '본 AI 요약 정보는 K-Startup 공고 내용을 바탕으로 생성되었습니다.';

export const ANNOUNCEMENTS = [
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
export const RESULTS_SHOWN_COUNT = 3;

// 적합도(fit_score) 하나를 원형 게이지로 보여준다 — 백엔드가 실제로 내려주는 숫자가
// 이것뿐이라(항목별 세부 점수는 없음), 없는 근거를 지어내서 막대 여러 개로 쪼개는
// 대신 정직하게 이 값 하나만 크게 시각화한다.
export const PLAN_STAGE_TASKS = [
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
export const WRITING_SUBTASKS = ['사업계획서 본문 작성', '그래프 생성', '표 생성'];

// PRJ-ID-009: 진행률만 보여준다 — Agent별 단계를 다 나열하면 사용자가 볼 필요 없는
// 내부 구현이 드러난다. 기다리는 동안 볼 거리로 유사 공고 목록을 함께 두되(3건만 —
// 매칭 결과 화면의 전체 목록과 헷갈리지 않게), 점수·자격 표기는 뺀다. 완료돼도
// 자동으로 넘어가지 않는다 — 공고를 읽던 중에 화면이 갑자기 바뀌면 사용자 입장에서
// 당황스럽다, 확인 버튼을 직접 눌러야 계획서로 이동한다. 목록은 완료 후에도 그대로
// 남겨두고 그 아래에 "계획서 확인하기" 버튼을 덧붙인다 — 다 읽던 걸 안 끊는다.
// 기획서 4-2④: 진행률은 Task 목록이 아니라 프로그레스 바+백분율로만 보여주고,
// 바 아래엔 지금 하는 일을 한 줄만 표시한다 — Agent별 단계를 다 나열하면 사용자가
// 볼 필요 없는 내부 구현이 드러난다.
export const PSST_OFFICIAL_HEADERS = ['1. 문제 인식 (Problem)', '2. 실현 가능성 (Solution)', '3. 성장전략 (Scale-up)', '4. 팀 구성 (Team)'];

export const PLAN_DOCUMENT_SECTIONS = [
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
export const PLAN_DOCUMENT_SECTIONS_REWORKED = [
  { tag: 'P', title: '문제인식', body: '동네 헬스장은 대부분 수기 장부와 전화로 예약을 받아 운영 부담이 크고, 회원권 잔여 횟수 관리도 수작업에 의존합니다. 인근 헬스장 12개소 조사 결과와 회원 300명 이하 소규모 헬스장 대상 커뮤니티 반응을 종합하면, 같은 문제를 겪는 곳이 다수였습니다' },
  { tag: 'S', title: '실현가능성', body: '회원 등록·조회, 수업 예약, 회원권 결제, 출석 알림, 매출 대시보드까지 다섯 기능을 프로토타입으로 구현할 예정이며, 회원권 잔여 횟수는 결제 즉시 자동으로 차감되도록 설계했습니다' },
  { tag: 'S', title: '성장전략', body: '월 회원권 단가 35,000원을 기준으로 매출을 추정했으며, 1단계 대표가 운영해온 피트니스 센터 기존 회원 전환, 2단계 인근 헬스장 12개소 대상 입점 제안, 3단계 지역 커뮤니티 제휴 순으로 고객을 확보합니다' },
  { tag: 'T', title: '팀 구성', body: '대표 김서준은 피트니스 센터를 4년간 운영하며 지점 2곳을 관리해 왔고, 개발은 웹 프론트엔드 경력 3년의 이하늘이 맡습니다. 결제 연동은 외부 개발사와 협력하며, 결원 발생에 대비해 외부 파트너사와 백업 계약도 함께 마련해뒀습니다' },
];

// 2026-09-16: "이 양식이 쓰이는게 사업계획서 작성하고 나왔을때랑 계획서 보기...비교할때"
// (사용자 지적) — 다운로드 파일(dummyDeliverables.js)만 "□ 일반현황"/"□ 창업 아이템
// 개요(요약)"을 갖추고 화면(PlanForm/계획서 보기 모달/비교 모달)은 PSST 4개 섹션만
// 보여주고 있었다. 세 화면이 같은 값을 쓰도록 여기 한 곳에 모은다 — ReviewScreen의
// handleDownload도 이 함수를 그대로 쓴다(값이 두 곳에서 따로 어긋날 일이 없게).
export const APPLICANT_TYPE_LABEL = { preliminary: '예비창업자(개업 전)', individual: '개인사업자', corp: '법인사업자' };
export const PLAN_TABLE_EXAMPLE = {
  title: '수익모델 단가표', columns: ['상품·서비스', '단가'],
  rows: [['월 회원권', '35,000원 / 월'], ['1회 이용권', '8,000원']],
};

export const PLAN_CHART_EXAMPLE = {
  title: '연도별 예상 매출', bars: [
    { label: '1년차', value: 30 }, { label: '2년차', value: 55 }, { label: '3년차', value: 100 },
  ],
};

// 2026-09-16: 계획서 본문 뒤에 붙는 표(05)·그래프(06). 사업계획서 작성 화면에만 있고
// "계획서 보기"에는 없어서, 열어보면 4. 팀 구성에서 문서가 그냥 끝나 버렸다(사용자 지적:
// "밑에 그래프 막대는 잘린다" — 잘려 보인 게 아니라 아예 빠져 있었다). 두 화면이 다시
// 어긋나지 않게 한 컴포넌트로 빼서 양쪽이 같은 걸 쓴다.
// size='full'은 작성 화면(넓은 카드), 'compact'는 모달용으로 글자만 한 단계 작게 쓴다.
export const DOC_ITEMS_FAIL = [
  { name: '문제인식', score: 12, max: 15, comment: '문제 규모를 뒷받침하는 수치가 1건뿐입니다.' },
  { name: '실현가능성', score: 13, max: 20, comment: '준비 정도 서술이 계획 수준에 머물러 있습니다.' },
  { name: '성장전략', score: 15, max: 20, comment: '매출 추정 단가 근거는 있으나 고객 확보 경로 서술이 없습니다.' },
  { name: '팀 구성', score: 12, max: 15, comment: '역할 분담은 명확하나 결원 시 대응 계획이 없습니다.' },
];
export const DOC_ITEMS_PASS = [
  { name: '문제인식', score: 13, max: 15, comment: '시장 수치 출처가 2건으로 보강되었습니다.' },
  { name: '실현가능성', score: 17, max: 20, comment: '구현 예정 기능을 근거로 준비 정도를 구체화했습니다.' },
  { name: '성장전략', score: 17, max: 20, comment: '고객 확보 경로가 3단계로 구체화되었습니다.' },
  { name: '팀 구성', score: 13, max: 15, comment: '역할 분담과 외부 협력 계획이 함께 제시되었습니다.' },
];

export const FINAL_THRESHOLD = 80;

// 기획서 6-8: "검증 결과 문서와 화면 양쪽에 이 성격을 표기한다" — 지금까지는
// 표현검수/다운로드 화면에만 있었다. 점수가 실제로 뜨는 화면(문서 평가·종합 평가)
// 에도 같은 문구를 단다. 다운로드 화면 고지(DELIVERABLE_NOTICES)와 문구를 맞춘다.
export const SCORE_DISCLAIMER = '이 점수는 서비스 내부 기준에 따른 값이며 실제 심사 점수가 아닙니다. 80점을 넘었다고 선정을 보장하지 않고, 밑돌았다고 탈락을 뜻하지도 않습니다.';
// 기획서 6-8: "사업계획서 — 첫 장에 AI 초안 생성 사실과 검토 필요를 표기." 계획서
// 미리보기(PlanForm, FinalVerdict의 열람 모달)가 실제로 이 문서의 "첫 장"에 해당한다.
export const PLAN_AI_NOTICE = '본 문서는 AI가 생성한 초안입니다 — 제출 전 작성자 본인의 확인과 수정이 필요합니다.';

// 이 화면에 도달했다는 건 신청 자격 확인를 통과해 공고가 이미 고정됐다는 뜻이다
// (기획서 4-1: 공고를 고르면 이후 작업이 그 공고 기준으로 고정된다) — 매칭 결과로
// 돌아가는 경로를 두면 다른 공고를 다시 고를 수 있게 돼 이 계획서 자체가 무의미해
// 진다. 그래서 이 화면부터는(사용자 요청) 뒤로가기 버튼을 두지 않는다.
export const ARTIFACT_CATEGORY_COPY = {
  onepage: {
    note: '이 아이템은 인포그래픽 중심으로 준비했습니다 — 오프라인 매장·제조업처럼 "동작 화면"보다 사업 구조를 한눈에 보여주는 게 더 적합해요.',
  },
};

// 웹개발과 AI API 모두 "HTML 실행 파일"이라는 산출물 형태는 같다 — 아이템 성격에
// 따라 내부적으로 다르게 만들어지더라도, 사용자에게 보여주는 미리보기 디자인·명칭은
// 하나로 통일한다(카테고리별로 다른 카드를 보여주면 카테고리 판정이 화면에 드러난다).
export const EXECUTABLE_COPY = {
  title: '화면 흐름 미리보기',
  desc: '핵심 화면의 구성과 요소를 크게 확인할 수 있어요.',
};

// 2026-09-16: 팀원이 실제로 만든 인포그래픽 예시(Main@1x.png)를 그대로 쓴다 — 위
// SiteMock과 같은 이유로, 실제 산출물이 나올 때까지의 자리표시자다. 카드 안 작은
// 미리보기용이라 회색 배경 박스 안에 축소해 담는다. "미리보기" 팝업(ResultPreview)은
// 이 컴포넌트를 쓰지 않고 라이트박스로 사진만 직접 띄운다.
export const ARTIFACT_SUBTASKS_BY_CATEGORY = {
  onepage: ['인포그래픽 제작'],
  webdev: ['실행 파일 제작', '인포그래픽 제작'],
  aiapi: ['실행 파일 제작', '인포그래픽 제작'],
};

export const ARTIFACT_SCORE_BY_OUTCOME = {
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
export const CODE_CHECK_ITEMS_BY_CATEGORY = {
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
export const CODE_CHECK_FAILS_BY_OUTCOME = {
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

export const PROTOTYPE_PAGE = { w: 1440, h: 3770 };
export const TASK_REWORK_SUMMARY = {
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
export const REVIEW_PARAGRAPHS = [
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
export const DELIVERABLE_NOTICES = [
  { label: '계획서', text: '본 문서는 S-Brain이 생성한 초안입니다. 제출 전 작성자 본인의 확인과 수정이 필요합니다.' },
  { label: '프로토타입', text: '본 프로토타입은 S-Brain이 생성한 초안입니다. 실제 서비스 코드가 아닙니다.' },
  { label: '검증 결과', text: '본 점수는 서비스 내부 기준에 따른 값이며 실제 심사 점수가 아닙니다. 80점을 넘었다고 선정을 보장하지 않고, 밑돌았다고 탈락을 뜻하지도 않습니다.' },
  { label: '제출 안내', text: '공고에 따라 AI로 작성한 문서의 제출을 제한하거나 명시를 요구할 수 있습니다. 해당 공고의 제출 요건을 확인해 주세요.' },
];

export const DOWNLOAD_FILES = [
  { name: '사업계획서.docx', desc: '문장 다듬기까지 마친 최종 사업계획서' },
  { name: 'prototype.zip', desc: '실행 파일(index.html)과 인포그래픽을 담은 압축 파일' },
  { name: '검증결과.pdf', desc: '문서층·산출물층 검증 내역과 대조 결과' },
];

// 실제 산출물 생성(Task #14)이 아직 안 붙어서, 이 세 파일은 화면에 이미 있는 더미
// 데이터(PLAN_DOCUMENT_SECTIONS_REWORKED/ARTIFACT_SCORE_BY_OUTCOME 등)를 그대로 옮겨
// 그 확장자로 실제 열리는 더미 파일을 즉석 생성해 내려준다(dummyDeliverables.js).
// 검증결과.pdf만 표준 내장 폰트 한계로 영문 라벨을 쓴다 — 아래는 그 번역표.
export const EN_DOC_ITEM_LABEL = {
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
export const MY_PROJECTS = [
  { id: 1, name: '동네 헬스장 예약 서비스', announcementTitle: '초기창업패키지', status: '사업계획서 작성중', progress: 65, updatedAt: '2026-09-08', view: 'plan-form' },
  { id: 5, name: '중고거래 안전결제 플랫폼', announcementTitle: '예비창업패키지', status: '제출 완료', progress: 100, updatedAt: '2026-08-20', view: 'review', scoreOutcome: 'pass' },
];

export const PROJECT_PAGE_SIZE = 5;
export const PROJECT_STATUS_TONE = {
  ok: { color: '#3D7A4F', bg: 'rgba(61,122,79,.12)' },
  danger: { color: '#A8342A', bg: 'rgba(168,52,42,.1)' },
  neutral: { color: '#6b7684', bg: '#f2f4f6' },
};
export const COMPLETED_PROJECT_STATUS = '제출 완료';

// 완전히 처음 로그인한 유저는 등록한 프로젝트가 하나도 없다 — 기존에 만든
// 대시보드는 전부 MY_PROJECTS(더미 7건)를 전제로 하고 있어서 그 빈 상태를 보여줄
// 방법이 없었다. 실제 신규가입 절차를 또 만드는 대신(로그인 자체는 목업이라 계정을
// 여러 개 둘 이유가 없다), 대시보드 진입 시점에 "어느 페르소나로 볼지"만 전환하는
// 가벼운 토글을 둔다 — 발표자가 그 자리에서 신규/기존 화면을 바로 오가며 보여줄 수 있다.
