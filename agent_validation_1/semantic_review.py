"""F19 semantic-review pass: deterministic second opinion over model issues.

판정 문구는 prompts/reference에 두고 이 모듈은 분류 로직만 담당한다.
"""
from pathlib import Path

_REFERENCE = Path(__file__).parent / 'res' / 'prompts' / 'reference'
_persona_text = (_REFERENCE / 'validation_persona.md').read_text(encoding='utf-8-sig') if (_REFERENCE / 'validation_persona.md').exists() else '검증 1 판정 재검토자'
_checklist_text = (_REFERENCE / 'validation_checklist.md').read_text(encoding='utf-8-sig') if (_REFERENCE / 'validation_checklist.md').exists() else ''
REVIEW_PERSONA = '검증 1 판정 재검토자'
REVIEW_PROMPT = f'''{_persona_text}\n\n{_checklist_text}\n\nF19 의미 검증 결과를 재검토한다. 필수 구조·확정 사실·마감일·예산 상한 위반은 실패를 유지하고, 계획·제안·확인 필요·근거 보완·시험조건 미확정은 경고로 분류한다. 표현 차이만으로 실패시키지 않는다.'''

HARD_MARKERS = ('원본과 불일치','확정 fact 오류','마감일 이후','지원규모 상한','필수 표','필수 항목','이미지 nodes')
ADVISORY_MARKERS = ('근거','출처','제안','계획','확인 필요','미확정','시험','측정','표현','토큰','기능 목록','fact 경로','구체화','정합성')

def review_issues(issues):
    """Return (hard_failures, advisory_warnings) with duplicates removed."""
    hard=[]; warnings=[]
    for raw in issues or []:
        text=str(raw).strip()
        if not text: continue
        if any(marker in text for marker in HARD_MARKERS): target=hard
        elif any(marker in text for marker in ADVISORY_MARKERS): target=warnings
        else: target=hard
        if text not in target: target.append(text)
    return hard,warnings
