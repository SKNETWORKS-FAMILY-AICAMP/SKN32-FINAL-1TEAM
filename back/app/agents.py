"""에이전트 연동 인터페이스 — 기능정의서 cf. 요구사항 대응:

    "담당자가 작성한 기능을 바로 연동할 수 있도록 인터페이스 및 코드 구조 구현 /
     실제 기능이 연동되기 전까지는 예외 처리하여 더미 코드기반으로 진행"

지금은 오케스트레이터(실제 Agent 파이프라인)가 다른 팀원 작업이라 여기 없다. 대신 이 파일이
그 경계선(인터페이스) 역할을 한다 — app/routers/projects.py의 retry_task()는 여기 정의된
함수만 호출하고, 그 함수가 돌려주는 값의 "모양"만 알면 된다. 지금은 모든 함수가 무작위 더미
값을 만들어서 돌려주지만("더미 코드기반"), Agent 담당자가 실제 기능을 완성하면 이 파일 안의
구현부만 실제 LLM 호출/코드 실행으로 바꿔치면 되고, 호출부(projects.py)는 한 줄도 안 고쳐도
된다 — 함수 시그니처(입력 타입 → 출력 타입)가 곧 계약이다.

왜 SQLAlchemy 모델을 안 받고 (item_code, max_score) 같은 평범한 값만 받는가: Agent 담당자가
이 함수를 실제로 구현할 때 우리 DB 스키마(app/models.py)를 몰라도 되게 하려는 것 — 이것도
"바로 연동할 수 있는 인터페이스"의 일부다. DB 읽기/쓰기(트랜잭션, commit)는 여전히
projects.py 쪽 책임으로 남겨뒀다.

[Agent 7개 중 여기 6개만 있는 이유]
app/models.py의 FIXED_TASK_SEQUENCE엔 서로 다른 agent_name이 7개(조율/전략/작성/검증-1/
구현/검증-2/검수) 있다. '조율'(coordinate_intake, user_decision_doc, user_decision_final,
coordinate_finalize)은 콘텐츠를 만드는 게 아니라 사용자 판단을 기다리거나 다음 단계로 넘기는
오케스트레이션 체크포인트라서, "재시도하면 결과물이 바뀐다"는 개념 자체가 안 맞는다 — 그래서
재시도 인터페이스에서 뺐다. 나머지 6개는 각자 자기 테이블에 대응하는 더미 함수를 아래에 뒀다:

    전략(strategy)              -> plan_sections '3-1'(성장 전략) 섹션 본문
    작성(writing)                -> plan_sections '1-1'/'2-1'(문제인식/실현가능성) 섹션 본문
    검증-1 · rubric(verify1_rubric)   -> plan_score_reasons 점수
    검증-1 · evidence(verify1_evidence) -> plan_score_reasons의 evidence_locator
                                          (+ E-V1-EVIDENCE: 근거 없으면 감점 무효 처리)
    구현(implement_prototype/infographic) -> artifacts의 파일 경로
    검증-2 · static/crosscheck(verify2_static/crosscheck) -> artifact_score_reasons 점수
    검수 · expression(review_expression) -> format_findings (T-P1, 형식 검수)
    검수 · token_check(review_token_check) -> proofread_logs (T-P2, 윤문)
"""
import random
import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ScoreItemResult:
    """채점 항목 하나의 재채점 결과. plan_score_reasons/artifact_score_reasons 행 하나에 대응."""

    item_code: str
    score: Decimal
    max_score: Decimal
    evidence_locator: str | None
    reason_text: str


@dataclass
class SectionDraftResult:
    """plan_sections 행 하나의 재작성 결과."""

    tag: str
    title: str
    body: str


@dataclass
class ImplementArtifactResult:
    """구현 Agent 결과 — 새로 만들어진 파일. 채점은 검증-2 몫이라 여기 없다."""

    file_bytes: bytes
    file_ext: str  # 예: '.html' — UPLOAD_DIR에 저장할 때 확장자로 쓴다.


@dataclass
class FormatFindingResult:
    """format_findings(T-P1, 문장 형식 검수) 결과 — 지적만 하고 고치지는 않는다."""

    finding_type: str
    location: str | None
    message: str
    severity: str | None


@dataclass
class ProofreadResult:
    """proofread_logs(T-P2, 윤문) 결과 — 실제로 고친 문장.

    [2026-09-18 확장] passed=False면 보호 토큰(수치·날짜·고유명사·기능명) 위반으로
    이 시도가 반려됐다는 뜻이다 — 이때 corrected_text는 "실제로 반영된 교정문"이
    아니라 "반려된 시도안"이고, violation_type/violation_note가 왜 반려됐는지 담는다.
    호출부(projects.py)는 passed=False인 결과를 plan_sections 등 실제 계획서 본문에
    반영하지 않고 proofread_logs 이력에만 남긴다.

    score(0~100)는 재시도할수록 실제로 나아지는지 숫자로 보여달라는 요청(하정원님)으로
    추가했다 — business_plans.doc_score와 같은 형식."""

    corrected_text: str
    reason: str | None
    score: Decimal = Decimal('100')
    passed: bool = True
    violation_type: str | None = None
    violation_note: str | None = None


def _dummy_rescored_item(item_code: str, max_score: Decimal) -> ScoreItemResult:
    """더미 재채점 공통 로직 — max_score 범위 안에서 무작위로 점수를 다시 매긴다."""
    score = Decimal(str(round(random.uniform(0, float(max_score)), 2)))
    return ScoreItemResult(
        item_code=item_code,
        score=score,
        max_score=max_score,
        evidence_locator=f'dummy-agent:{item_code}:{uuid.uuid4().hex[:8]}',
        reason_text=f'(더미 재채점) {item_code}: {score}/{max_score}점 — 실제 Agent 연동 전 무작위 값',
    )


# ---------------------------------------------------------------------------
# 전략
# ---------------------------------------------------------------------------
def run_strategy_agent_retry(project_description: str) -> SectionDraftResult:
    """전략 Agent 재시도 — plan_sections의 '3-1'(성장 전략) 섹션 본문을 다시 쓴다.
    실제 연동 시: 시장 진입/확장 전략 분석 LLM 호출 결과를 SectionDraftResult로 돌려주면 된다."""
    return SectionDraftResult(
        tag='3-1',
        title='성장 전략',
        body=(
            f'(더미 재작성 {uuid.uuid4().hex[:8]}) {project_description} 기반 성장 전략 — '
            '시장 진입 및 확장 전략을 다시 서술한 문단입니다.'
        ),
    )


# ---------------------------------------------------------------------------
# 작성
# ---------------------------------------------------------------------------
def run_writing_agent_retry(project_description: str, tags: list[str]) -> list[SectionDraftResult]:
    """작성 Agent 재시도 — plan_sections의 문제인식('1-1')/실현가능성('2-1') 섹션 본문을
    다시 쓴다. tags에 실제로 존재하는(또는 만들어야 할) 섹션 태그 목록을 넘긴다."""
    titles = {'1-1': '문제 인식', '2-1': '실현 가능성'}
    return [
        SectionDraftResult(
            tag=tag,
            title=titles.get(tag, tag),
            body=(
                f'(더미 재작성 {uuid.uuid4().hex[:8]}) {project_description} 기반 '
                f'{titles.get(tag, tag)} — 본문을 다시 서술한 문단입니다.'
            ),
        )
        for tag in tags
    ]


# ---------------------------------------------------------------------------
# 검증-1
# ---------------------------------------------------------------------------
def run_verify1_rubric_retry(rubric_items: list[tuple[str, Decimal]]) -> list[ScoreItemResult]:
    """검증-1(rubric) 재시도 — 채점 기준표(rubric_items)에 따라 문서 채점 항목별 점수를
    다시 매긴다. rubric_items: [(item_code, max_score), ...]."""
    return [_dummy_rescored_item(item_code, max_score) for item_code, max_score in rubric_items]


def run_verify1_evidence_retry(items: list[tuple[str, Decimal]]) -> list[ScoreItemResult]:
    """검증-1(evidence) 재시도 — 항목별 근거 위치(evidence_locator)를 다시 찾는다.

    기능정의서 E-V1-EVIDENCE: "evidenceLocator 없는 감점은 무효 처리하고 점수를 복원한다" —
    더미 구현은 항목마다 대략 30% 확률로 "근거를 못 찾음"을 흉내내고, 그 경우 이 함수가 곧바로
    점수를 만점으로 돌려준다(무효 처리를 여기서 직접 구현해뒀다). 호출부(projects.py)는 이
    함수가 돌려준 score/evidence_locator를 그대로 반영하기만 하면 된다."""
    results = []
    for item_code, max_score in items:
        found_evidence = random.random() > 0.3
        if found_evidence:
            score = Decimal(str(round(random.uniform(0, float(max_score)), 2)))
            evidence = f'dummy-agent:{item_code}:{uuid.uuid4().hex[:8]}'
            reason = f'(더미 근거 재확인) {item_code}: 근거 위치 {evidence} 확인 — {score}/{max_score}점'
        else:
            # E-V1-EVIDENCE: 근거 없는 감점은 무효 처리 -> 만점 복원
            score = max_score
            evidence = None
            reason = f'(더미 근거 재확인) {item_code}: 근거 위치를 못 찾아 감점 무효 처리 — 만점({max_score}) 복원'
        results.append(ScoreItemResult(
            item_code=item_code, score=score, max_score=max_score,
            evidence_locator=evidence, reason_text=reason,
        ))
    return results


# ---------------------------------------------------------------------------
# 구현
# ---------------------------------------------------------------------------
def run_implement_agent_retry(*, artifact_kind: str, project_description: str) -> ImplementArtifactResult:
    """구현 Agent 재시도 — artifact_kind='prototype'|'infographic' 파일을 새로 만든다
    (채점은 검증-2 몫이라 여기서 하지 않는다). 실제 연동 시: 실제 코드/이미지 생성 파이프라인
    결과 파일의 바이트와 확장자를 이 반환 타입 그대로 돌려주면 된다 — 저장 위치(UPLOAD_DIR)는
    여전히 projects.py가 결정한다."""
    label = '프로토타입' if artifact_kind == 'prototype' else '인포그래픽'
    html = (
        f'<!doctype html><html><body><h1>{label} 재시도 결과물 (더미)</h1>'
        f'<p>{project_description}</p>'
        f'<p>generated: {uuid.uuid4().hex[:8]}</p></body></html>'
    ).encode()
    return ImplementArtifactResult(file_bytes=html, file_ext='.html')


# ---------------------------------------------------------------------------
# 검증-2
# ---------------------------------------------------------------------------
def run_verify2_retry(rubric_items: list[tuple[str, Decimal]], *, check_kind: str) -> list[ScoreItemResult]:
    """검증-2 재시도 — check_kind='static'(진입 파일 존재 등 정적 검사) 또는 'crosscheck'
    (계획서 대비 기능 대조)에 해당하는 산출물 채점 항목만 다시 매긴다. 어느 항목이 어느
    check_kind에 속하는지는 호출부(projects.py)가 item_code로 미리 걸러서 넘겨준다 —
    이 함수는 check_kind를 몰라도 동작하지만, 실제 연동 시 검사 종류별로 다른 로직을
    타야 한다면 이 값을 참고하면 된다."""
    return [_dummy_rescored_item(item_code, max_score) for item_code, max_score in rubric_items]


# ---------------------------------------------------------------------------
# 검수
# ---------------------------------------------------------------------------
def run_review_expression_retry(project_description: str) -> FormatFindingResult:
    """검수(표현, T-P1) 재시도 — 문장 형식(띄어쓰기/문체 불일치 등) 문제를 다시 찾아
    지적만 한다(고치지는 않음 — 실제로 고친 결과는 run_review_token_check_retry 쪽)."""
    finding_type = random.choice(['spacing', 'punctuation', 'tone_mismatch'])
    return FormatFindingResult(
        finding_type=finding_type,
        location=f're-review:{uuid.uuid4().hex[:8]}',
        message=f'(더미 재검수) {project_description} 대상 {finding_type} 문제 {random.randint(1, 3)}건 발견',
        severity=random.choice(['info', 'warning']),
    )


_PROTECTED_TOKEN_TYPES = ('날짜', '수치·금액', '고유명사', '기능명')


def run_review_token_check_retry(project_description: str, attempt_no: int = 1) -> ProofreadResult:
    """검수(윤문, T-P2) 재시도 — 문장을 다시 교정한 전/후 텍스트 쌍을 만들고, 그 시도가
    보호 토큰(수치·날짜·고유명사·기능명)을 훼손했는지도 함께 판정한다.

    [2026-09-18 확장] 더미 판정 규칙: 위반 확률이 attempt_no가 늘수록 낮아진다
    (1차 시도 40% -> 2차 20% -> 3차 이상 0%) — "재시도할수록 안정화된다"는 재수행의
    취지를 흉내낸 것으로, 실제 검수 모델이 붙으면 이 함수 내부만 실제 판정 로직으로
    바꾸면 된다(계약은 동일하게 유지: 위반이면 passed=False + violation_type/note).

    score도 같은 취지로 attempt_no가 늘수록 기본점이 올라가고(60 -> 70 -> 80 -> ...,
    최대 100), 그 시도에서 위반이 나면 20점을 깎는다 — "재시도할수록 나아지되, 위반이
    나오면 그 시도는 확실히 낮게 나온다"를 눈으로 보이게 하기 위함(하정원님 지적)."""
    violation_chance = max(0.0, 0.4 - (attempt_no - 1) * 0.2)
    base_score = min(100, 60 + (attempt_no - 1) * 10)
    if random.random() < violation_chance:
        violation_type = random.choice(_PROTECTED_TOKEN_TYPES)
        return ProofreadResult(
            corrected_text=f'(더미 재윤문 시도안 {uuid.uuid4().hex[:8]}) {project_description} — 문장을 다시 교정했습니다.',
            reason='재검수 교정 시도 (더미) — 보호 토큰 위반으로 반려',
            score=Decimal(max(0, base_score - 20)),
            passed=False,
            violation_type=violation_type,
            violation_note=f'보호 토큰({violation_type}) 훼손 감지 (더미) — 원문의 {violation_type} 표기가 변경되었거나 누락되었습니다.',
        )
    return ProofreadResult(
        corrected_text=f'(더미 재윤문 {uuid.uuid4().hex[:8]}) {project_description} — 문장을 다시 교정했습니다.',
        reason='재검수 교정 (더미)',
        score=Decimal(base_score),
        passed=True,
    )
