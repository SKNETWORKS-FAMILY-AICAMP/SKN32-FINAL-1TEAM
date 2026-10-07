"""T-B1: 실행 파일 HTML 제작 진입점.

카테고리가 '웹개발'/'AI_API'일 때만 Supervisor가 호출한다(호출자 책임 — 여기서는
카테고리 값을 검증하지 않고 프롬프트 문구만 갈라 쓴다).
산출물은 외부 빌드 도구 없이 동작하는 단일 HTML 실행 파일이다.
README는 조율 단계 G-04가 생성한다.
"""
import re
import uuid

from engineering_agent import gates
from engineering_agent.file_writer import parse_code_blocks, save_files

# 진입 파일명. 프론트가 사용자에게 이 이름으로 보여주고(verificationReport.js의
# 검증 대상 target, 산출물 ZIP 설명), 압축을 풀어 열 때의 관례적 진입점이기도 하다.
_ENTRY_FILENAME = "index.html"

# LLM이 자기가 실제로 구현한 기능을 자기신고하도록 HTML 최상단에 남기게 하는 마커.
# implementedFeatures는 채점 근거가 아니다. 마커가 없으면 빈 목록으로 둔다.
_IMPLEMENTED_FEATURES_RE = re.compile(r'<!--\s*IMPLEMENTED_FEATURES:\s*(.*?)-->', re.DOTALL)


# 프롬프트에 싣는 계획서 본문 길이 상한.
_PLAN_CHARS = 12000


def feature_notes(feature_list: list[str], plan_text: str) -> dict[str, str]:
    """기능마다 계획서가 그 기능을 정의한 줄(기능 이름이 그대로 들어간 줄). 없으면 빈 문자열.

    기능 이름만 주면 모델은 계획서가 말한 입력 항목 · 표시 정보를 알 수 없다. "고장 신고 접수"만 받으면
    증상 입력 화면을 만들지만, 계획서는 "사진과 증상을 올리면"이라고 적었다. 검증-2는 계획서를 기준으로
    대조하므로 그 차이가 그대로 감점이 됐다(실측: 기능 4개 중 2~2.5개 인정).
    """
    lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
    notes = {}
    for feature in feature_list:
        whole = feature.replace(" ", "").casefold()
        found = [line for line in lines
                 if whole in line.replace(" ", "").casefold() and line.replace(" ", "").casefold() != whole]
        notes[feature] = " ".join(found[:3])
    return notes


def _build_system_prompt(feature_list: list[str], item_spec: dict, category: str,
                         plan_text: str = "") -> str:
    """카테고리별로 요구되는 흐름(화면 전환 vs 입력→처리→출력)을 갈라 지시한다.
    plan_text(사업계획서 본문)가 있으면 기능마다 계획서의 설명을 붙이고 본문도 함께 싣는다."""
    if category == "웹개발":
        flow_instruction = (
            "이 프로토타입은 '웹개발' 카테고리다. 최소 2개 이상의 화면(또는 화면 상태)을 "
            "JavaScript로 전환하며 보여주는 화면 전환 흐름을 중심으로 구현하라."
        )
    else:  # AI_API
        flow_instruction = (
            "이 프로토타입은 'AI_API' 카테고리다. 사용자가 입력을 넣고 → 처리 과정을 "
            "시각적으로 확인하고 → 결과를 출력받는 입력→처리→출력 흐름을 명확히 보여주도록 "
            "구현하라. 실제 외부 API를 호출하지 말고(외부 네트워크 의존 금지), 처리 로직은 "
            "더미/시뮬레이션(예: setTimeout으로 처리 중 상태를 보여준 뒤 규칙 기반 결과 출력)으로 구현하라. "
            "버튼 하나로 처리 전체를 돌리더라도, 기능 목록의 기능마다 그 기능만 실행하거나 그 기능의 결과를 "
            "보여 주는 버튼을 따로 하나씩 두고(예: '담당 부서 자동 분류' 버튼, '처리 기한 안내' 버튼) 규칙 9대로 "
            "data-feature와 id를 붙여 직접 연결하라. 처리 흐름의 한 단계로 결과만 나오고 그 기능의 버튼이 없으면 "
            "그 기능은 동작하지 않는 것으로 본다."
        )

    notes = feature_notes(feature_list, plan_text) if plan_text.strip() else {}
    feature_lines = "\n".join(
        f"- {f}" + (f"\n  계획서의 설명: {notes[f]}" if notes.get(f) else "") for f in feature_list)
    plan_rule = plan_section = ""
    if plan_text.strip():
        plan_rule = (
            "\n14. 기능마다 '계획서의 설명'에 적힌 것을 화면에 빠짐없이 넣어라. 설명에 나온 입력 항목"
            "(예: 사진, 증상, 비용)은 각각 입력칸으로, 표시 정보(예: 요일별 판매량, 폐기량, 후보 순위)는 "
            "각각 화면에 보이는 값으로, 조건(예: 30분 단위, 5개 이하)은 그 조건대로 동작하게 만들어라. "
            "화면의 낱말은 계획서의 낱말을 그대로 써라. 서버 저장 · 실제 발송 · 결제 · 실제 AI 처리는 "
            "더미 데이터와 간단한 규칙으로 흉내 내되, 그 결과가 계획서가 말한 모양으로 화면에 보여야 한다. "
            "계획서가 보여 준다고 한 정보인데 계획서에 실제 값이 없으면(예: 민원 종류별 처리 기한, 요일별 판매량) "
            "그 자리를 비우거나 '연결되지 않아 표시하지 않는다'고 적지 마라. 그럴듯한 값을 더미 데이터로 넣어 "
            "화면에 보이게 하고, 그 값이 있는 영역에 '시연용 예시 값'이라고 표시하라. 계획서에 값이 있으면 그 값을 그대로 써라."
        )
        plan_section = ("\n\n## 사업계획서 본문 (기능 설명의 근거. 여기에 없는 기능을 지어내지 마라. "
                        "계획서의 수치는 그대로 쓰고, 계획서에 없는 값은 규칙 14대로 '시연용 예시 값'으로 표시해 넣어라)\n"
                        + plan_text.strip()[:_PLAN_CHARS])

    return f"""너는 정부지원사업 신청용 프로토타입을 만드는 엔지니어다.
사업계획서의 "준비 정도"를 뒷받침할, 동작을 확인할 수 있는 수준의 실행 파일을 만든다.
완성된 제품이 아니라 "동작 확인 가능한 수준"이면 충분하다.

## 절대 규칙
1. 결과물은 단일 HTML 파일 하나(`{_ENTRY_FILENAME}`)로만 동작해야 한다.
   외부 CDN 스크립트(<script src="https://...">), 외부 스타일시트
   (<link rel="stylesheet" href="https://...">), 외부 이미지(<img src="https://...">),
   외부 @import, CSS 안의 외부 url(...)(배경 그림 · 웹 글꼴 포함), npm/webpack 등 어떤 빌드 도구도 쓰지 마라. CSS는 <style> 태그 안에,
   JS는 <script> 태그 안에 전부 인라인으로 작성하라. 이미지가 필요하면 data: URI나
   SVG/CSS로 대체하라.
   API 키 · 토큰 · 비밀번호 값을 코드에 적지 마라(`apiKey: "…"`, `password: "…"`, `sk-…` 같은 줄 금지).
   외부 서비스 호출은 더미 함수로 흉내 내고, 로그인 시연은 비밀번호를 코드에 두고 비교하지 말고
   빈칸이 아니면 무엇이든 받아들이게 하라.
2. `<html lang="ko">`를 반드시 명시하라.
3. 제목 계층을 지켜라: `<h1>`은 문서에 정확히 하나만 두고, h1→h2→h3 순서를 건너뛰지 마라.
4. 폼 요소(input, textarea, select)가 있으면 반드시 `<label for="...">`로 연결하라.
5. 이미지가 있으면(data: URI 포함) 반드시 의미를 설명하는 `alt` 속성을 채워라.
6. 파일명은 항상 정확히 `{_ENTRY_FILENAME}`로 하라. 다른 이름을 쓰지 마라.
7. HTML 파일 맨 위쪽(<head> 시작 직후 등)에 다음 형식의 주석을 정확히 한 줄 추가하라.
   이 주석에는 아래 기능 목록 중 네가 실제로 구현에 반영한 것만, 표현 그대로 적어라:
   `<!-- IMPLEMENTED_FEATURES: 기능명1 | 기능명2 | ... -->`
8. 글자색과 배경색은 **같은 셀렉터 블록 안에** `color`와 `background-color` 두 속성으로
   나란히 선언하라(`background` 단축 속성이나 CSS 변수로 흘리지 마라). 배경색은 `transparent`가 아닌
   실제 색으로 적어라. 그 짝의 명도 대비는
   4.5:1 이상이어야 한다. 최소한 `body`와 버튼·카드 등 글자가 놓이는 주요 셀렉터에 적용하라.
   예: `body {{ color:#0F172A; background-color:#FFFFFF; }}`
   이 기준은 `color`와 `background-color`를 함께 적은 **모든** 셀렉터에 적용된다. 자주 틀리는 곳:
   - 보조 글자 · 안내 문구 · 날짜 · 배지: 흐리게 보이려고 옅은 회색 글자를 쓰지 마라.
     흰색 · 옅은 배경 위 글자는 `#475569`보다 어둡게 쓰고, 덜 중요한 글은 색 대신 글자 크기 · 굵기로 구분하라.
   - 비활성(`:disabled`) · 선택 안 됨 · 지난 날짜 같은 상태: 이때도 글자가 읽혀야 한다. 대비 4.5:1을 지켜라.
   - 색 배경(버튼 · 배지 · 띠) 위 흰 글자: 배경을 충분히 진하게 써라(예: `#1D4ED8`, `#15803D`, `#B91C1C`).
     밝은 주황 · 노랑 · 하늘색 배경에는 흰 글자 대신 진한 글자를 써라.
   - 점 · 막대 · 구분선처럼 글자가 없는 장식 요소: `background-color`만 적고 `color`는 적지 마라.
   - 색 값에 `!important`를 붙이지 마라.
9. 각 기능을 실행하는 버튼·입력·폼에는 해당 기능명을 `data-feature` 속성으로 붙이고
   고유한 `id`도 붙여라. 이벤트는 **그 요소에 직접** 연결하라:
   `document.getElementById('그 id').addEventListener('click', ...)` 또는
   `const btn = document.getElementById('그 id'); btn.addEventListener(...)`.
   document 하나에 리스너를 달고 대상을 가려내는 이벤트 위임, querySelectorAll 반복문으로
   한꺼번에 다는 방식은 쓰지 마라. id를 배열에 담아 for · forEach 반복문으로 연결하는 것도
   쓰지 마라 — 메뉴 · 탭 버튼도 버튼마다 `getElementById('그 id')`로 한 줄씩 연결하라.
   화면의 모든 버튼은 실제로 무언가를 하게 연결하라. 기능명은 화면에도 글자로 표시하라.
   파일 · 사진 · 녹음처럼 보는 사람이 따로 준비해야 하는 입력이 있으면, 그 옆에 '예시로 실행'
   버튼을 두고 파일 안에 넣어 둔 예시 데이터로 처리부터 결과까지 바로 돌게 하라.
   파일을 올리지 않아도 모든 기능을 끝까지 시연할 수 있어야 한다.
10. 이 파일은 `sandbox="allow-scripts"`만 허용된 iframe 안에서 돌아간다. 다음을 쓰면
    스크립트가 통째로 멈추거나 조용히 무시되어 화면이 동작하지 않는다. 절대 쓰지 마라.
    - `localStorage`, `sessionStorage`, `document.cookie`, `indexedDB`
      (origin이 opaque라 접근하는 순간 예외가 난다. 상태는 JS 변수에만 담아라)
    - `alert()`, `confirm()`, `prompt()` (차단된다. 화면 안 토스트나 모달로 대체하라)
    - `<form>`의 submit이나 페이지 이동(`location.href=`, `window.open`)으로 동작하는 흐름
      (막힌다. 버튼 `onclick`과 `event.preventDefault()`로 처리하라)
11. 레이아웃은 데스크톱 폭 1440px 기준으로 만들어라. 화면이 이 폭에 맞게 보이도록
    고정 폭 컨테이너를 쓰고, 가로 스크롤이 생기지 않게 하라. `width`·`min-width`에
    1440px보다 큰 값을 쓰지 마라.
12. 스크립트에서 `getElementById`·`querySelector('#...')`로 찾는 id는 전부 문서에 실제로
    있어야 한다.
13. 화면에 lorem ipsum, TODO:, FIXME, TBD, "샘플 텍스트", "여기에 내용" 같은 임시 문구를
    남기지 마라. 화면의 글은 이 아이템에 맞는 실제 문장으로 채워라.{plan_rule}

## 카테고리 지시
{flow_instruction}

## 반드시 구현해야 하는 기능 목록 (전부 실제로 동작하게 구현할 것)
{feature_lines}

## 산출물 스펙(item_spec)
{item_spec}{plan_section}

## 출력 형식
아래 코드블록 하나만 출력하라. README는 별도 규칙 단계에서 생성한다.

```html:{_ENTRY_FILENAME}
(여기에 완성된 단일 HTML 파일 전체)
```

"""


def _format_error(message: str) -> Exception:
    """tools가 재시도 대상으로 인식하는 FormatError를 만든다.

    import을 실패 시점으로 미루는 이유: 정상 경로에서는 Orchestration 패키지를
    건드리지 않아야 이 모듈을 단독으로 검사할 수 있다.
    """
    from sbrain.orchestrator.errors import FormatError

    return FormatError(message)


def _parse_llm_files(llm_output: str) -> dict[str, str]:
    """LLM 응답에서 코드블록을 꺼낸다.

    "응답 자체가 쓸 수 없는 경우"(빈 응답, 코드블록 0개)는 품질 문제가 아니라 호출이
    사실상 실패한 것이므로 FormatError를 올려 tools가 재시도하게 한다. 재시도를 다
    쓰면 tools가 ToolCallExhausted로 바꿔 올리고 조율이 완전 실패로 판정한다.
    반대로 코드는 왔는데 게이트를 위반한 경우(파일명 틀림,
    외부 CDN)는 품질 실패이므로 여기서 다루지 않고 CheckResult로 정상 반환한다.
    """
    if not llm_output or not llm_output.strip():
        raise _format_error("T-B1 응답이 비어 있음")
    files = parse_code_blocks(llm_output)
    if not files:
        raise _format_error("T-B1 응답에 ```lang:filename 코드블록이 없음")
    return files


def _extract_implemented_features(html_content: str) -> list[str]:
    """HTML 안의 자기 신고 마커를 파싱한다. 없으면 빈 목록이다.

    이 값은 LLM 자기신고일 뿐 채점 근거가 아니므로, 파싱 실패를 게이트 실패로 다루지 않는다.
    """
    match = _IMPLEMENTED_FEATURES_RE.search(html_content)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    return [f.strip() for f in raw.split('|') if f.strip()]


def user_message(instruction: str, previous_html: str = "") -> str:
    """지시문. 재실행에 이전 HTML이 오면 처음부터 새로 만들지 않고 그 HTML을 고치게 한다.

    처음부터 다시 만들면 버튼 하나만 고치면 될 때도 화면 전체가 바뀌어, 잘 되던 부분이 달라지고
    재작성 전후 비교에서 점수가 떨어질 수 있다. 문제 내용은 조율이 지시문 끝에 이미 붙여 보낸다."""
    if not previous_html.strip():
        return instruction
    # 이전 HTML은 코드블록이 아니라 표시 태그로 감싼다. 출력 형식은 ```html:index.html인데, 여기서
    # ```html을 보여 주면 모델이 파일 이름 없이 따라 써서 코드블록을 못 찾는(형식 오류 → 재시도) 일이 생긴다.
    return (f"{instruction}\n\n## 이전 HTML (고칠 대상)\n"
            "<이전HTML> 안의 HTML에서 위 지시문의 문제 내용만 고쳐라. 문제와 관계없는 화면 · 문구 · 동작 · "
            "디자인은 그대로 둬라. 고친 뒤에도 '절대 규칙'을 모두 지키고, 시스템 지시의 출력 형식"
            f"(html:{_ENTRY_FILENAME} 코드블록 하나)대로 파일 전체를 다시 출력하라.\n\n"
            f"<이전HTML>\n{previous_html.strip()}\n</이전HTML>")


def build_prototype_html(
    feature_list: list[str], item_spec: dict, category: str, instruction: str, tools,
    plan_text: str = "", previous_html: str = "",
) -> dict:
    """T-B1 진입점: LLM 생성 → 코드블록 파싱 → 자체 게이트(E-B1-ENTRY, E-B1-DEP,
    E-B1-SANDBOX, E-B1-SECRET) → 저장.

    재시도 루프는 상위 Supervisor 몫이라 여기서는 게이트 실패 시 status="failed"로
    사유만 담아 한 번 반환한다. 다만 응답이 비었거나 코드블록이 없는 "호출 자체의
    실패"는 예외로 올려 tools의 재시도·완전 실패 경로를 타게 한다(_parse_llm_files).
    """
    if category not in ("웹개발", "AI_API"):
        raise ValueError("T-B1은 웹개발/AI_API 카테고리만 지원합니다")
    run_id = uuid.uuid4().hex

    system_prompt = _build_system_prompt(feature_list, item_spec, category, plan_text)
    files = tools.llm(
        [{"role": "system", "content": system_prompt},
         {"role": "user", "content": user_message(instruction, previous_html)}],
        parse=_parse_llm_files, purpose="T-B1 HTML 생성",
    )

    entry_ok, entry_reason = gates.check_entry_file_gate(files, _ENTRY_FILENAME)
    if not entry_ok:
        return {
            "status": "failed",
            "entryFilePath": None,
            "readmePath": None,
            "implementedFeatures": [],
            "gate_failures": {"entry": entry_reason, "dependency": [], "sandbox": [], "secret": None},
            "summary": f"E-B1-ENTRY 게이트 실패: {entry_reason}",
        }

    entry_content = files[_ENTRY_FILENAME]
    dep_ok, violations = gates.check_external_dependency_gate(entry_content)
    if not dep_ok:
        return {
            "status": "failed",
            "entryFilePath": None,
            "readmePath": None,
            "implementedFeatures": [],
            # 저장하지는 않지만 원문은 돌려준다 — 조율이 재수행 때 previous_source_text로 돌려줘 고쳐 만든다.
            "sourceText": entry_content,
            "gate_failures": {"entry": None, "dependency": violations, "sandbox": [], "secret": None},
            "summary": f"E-B1-DEP 게이트 실패: 외부 의존성 {len(violations)}건 발견",
        }

    sandbox_ok, sandbox_violations = gates.check_sandbox_api_gate(entry_content)
    if not sandbox_ok:
        return {
            "status": "failed",
            "entryFilePath": None,
            "readmePath": None,
            "implementedFeatures": [],
            "sourceText": entry_content,
            "gate_failures": {"entry": None, "dependency": [],
                              "sandbox": sandbox_violations, "secret": None},
            "summary": ("E-B1-SANDBOX 게이트 실패: sandbox iframe에서 동작하지 않는 API "
                        f"{len(sandbox_violations)}건 — {', '.join(sandbox_violations)}"),
        }

    secret_ok, secret = gates.check_secret_gate(entry_content)
    if not secret_ok:
        return {
            "status": "failed",
            "entryFilePath": None,
            "readmePath": None,
            "implementedFeatures": [],
            "sourceText": entry_content,
            "gate_failures": {"entry": None, "dependency": [], "sandbox": [], "secret": secret},
            "summary": (f"E-B1-SECRET 게이트 실패: 코드에 API 키 · 토큰 · 비밀번호 값이 있음({secret}). "
                        "값을 지우고 더미 함수 · 빈칸 아니면 통과하는 로그인으로 바꿀 것"),
        }

    saved_paths = save_files({_ENTRY_FILENAME: entry_content}, run_id)
    implemented = _extract_implemented_features(entry_content)

    return {
        "status": "success",
        "entryFilePath": saved_paths[_ENTRY_FILENAME],
        "readmePath": None,
        "sourceText": entry_content,
        "implementedFeatures": implemented,
        "gate_failures": {"entry": None, "dependency": [], "sandbox": [], "secret": None},
        "summary": f"run_id={run_id}: {_ENTRY_FILENAME} 생성 및 자체 게이트 통과",
    }
