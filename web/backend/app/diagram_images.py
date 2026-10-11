"""계획서(planDoc)의 그림(서비스 흐름도 · 서비스 구조도, SVG) → 내려받기 문서에 넣을 PNG (SB-340).

그림 항목(예비창업자 2.3.6 · 개인사업자 · 법인 3.3.6)의 그림은 오케스트레이터 파일 저장소의 SVG 파일이다(`planDoc.diagrams[].imageFile`,
`FileRef`). Word · 한글은 SVG를 안정적으로 열지 못해 PNG로 바꿔 docx와 hwp에 넣는다. 원본 SVG는 결과물 압축(zip)에 따로 넣는다.

- 변환은 `resvg-py`(순수 휠 — cairo 같은 시스템 라이브러리가 필요 없다)로 한다.
- 글자: SVG는 `font-family="sans-serif"`로만 쓰여 서버 글꼴에 따라 모양이 달라진다. 그래서 나눔스퀘어라운드를 묶어 두고 sans-serif로 쓴다.
  시스템 글꼴도 함께 읽는다 — 나눔스퀘어라운드에는 화살표(→) 글리프가 없어, 있는 시스템 글꼴이 대신 그린다(없는 서버에서는 화살표만 빠진다).
- 그림 하나를 못 받거나 못 바꾸면 그 그림만 빼고 로그를 남긴다 — 그림 하나 때문에 계획서 내려받기 전체가 실패하지 않게 한다.
"""
import logging
import os
import re
from dataclasses import dataclass

from app.orch import OrchError

logger = logging.getLogger('sbrain.web')

_FONT_DIR = os.path.join(os.path.dirname(__file__), 'assets', 'fonts')
_FONT_FILES = [os.path.join(_FONT_DIR, 'NanumSquareRoundR.ttf'), os.path.join(_FONT_DIR, 'NanumSquareRoundB.ttf')]
_SANS_FAMILY = 'NanumSquareRound'

PNG_WIDTH_PX = 1710          # 그림 viewBox 1140 폭의 1.5배 — 문서 폭(약 16cm)에서 270dpi 안팎
MAX_SVG_BYTES = 2 * 1024 * 1024
# 문서에 들어가는 순서와 제목 — 서비스 흐름도 다음에 서비스 구조도
FLOW_TITLES = {'USER_FLOW': '서비스 흐름도', 'SERVICE_ARCHITECTURE': '서비스 구조도'}
_FLOW_ORDER = list(FLOW_TITLES)

# 담당자 그리기 코드는 외부 참조를 쓰지 않는다(그림은 파일 하나로 열린다). 그래도 파일 · 주소를 부르는 요소가 있으면 그리지 않는다.
_EXTERNAL_REFERENCE = re.compile(rb'<image|<use|<foreignObject|href\s*=|@import|url\(\s*[\'"]?(?!#)', re.IGNORECASE)


@dataclass
class DiagramPicture:
    title: str      # 문서에 쓰는 이름(서비스 흐름도 · 서비스 구조도)
    png: bytes
    svg: bytes      # 원본 — 결과물 압축에 넣는다
    svg_name: str   # 원본 파일 이름(userflow.svg · architecture.svg)

    @property
    def size_px(self) -> tuple[int, int]:
        """PNG의 (가로, 세로) 픽셀 — PNG 머리말(IHDR)에서 읽는다."""
        return int.from_bytes(self.png[16:20], 'big'), int.from_bytes(self.png[20:24], 'big')


def svg_to_png(svg: bytes) -> bytes:
    """SVG 바이트 → PNG 바이트. 외부 참조가 있으면 ValueError."""
    if _EXTERNAL_REFERENCE.search(svg):
        raise ValueError('SVG에 외부 참조(이미지 · 링크)가 있어 그리지 않는다')
    import resvg_py

    return bytes(resvg_py.svg_to_bytes(
        svg_string=svg.decode('utf-8'), width=PNG_WIDTH_PX, font_files=_FONT_FILES, sans_serif_family=_SANS_FAMILY))


def diagram_pictures(gateway, project_id: int, plan_doc) -> list[DiagramPicture]:
    """계획서의 그림 목록 → 문서에 넣을 그림(서비스 흐름도, 서비스 구조도 순). 못 받거나 못 바꾼 그림은 뺀다."""
    if plan_doc is None:
        return []
    diagrams = sorted(getattr(plan_doc, 'diagrams', None) or [],
                      key=lambda d: _FLOW_ORDER.index(d.flow_type) if d.flow_type in _FLOW_ORDER else len(_FLOW_ORDER))
    pictures: list[DiagramPicture] = []
    for diagram in diagrams:
        ref = diagram.image_file
        if int(getattr(ref, 'size', 0) or 0) > MAX_SVG_BYTES:
            logger.warning('그림 %s: SVG가 너무 커서 문서에 넣지 않았다(%s바이트)', diagram.diagram_id, ref.size)
            continue
        try:
            file = gateway.read_artifact_file(project_id, ref.key)
        except OrchError as exc:
            logger.warning('그림 %s: 파일을 받지 못해 문서에 넣지 않았다(%s)', diagram.diagram_id, exc.code)
            continue
        try:
            png = svg_to_png(file.data)
        except Exception:  # 깨진 SVG · 렌더러 오류 — 그림만 뺀다
            logger.warning('그림 %s: PNG로 바꾸지 못해 문서에 넣지 않았다', diagram.diagram_id, exc_info=True)
            continue
        pictures.append(DiagramPicture(
            title=FLOW_TITLES.get(diagram.flow_type, diagram.flow_type), png=png, svg=file.data, svg_name=ref.name))
    return pictures
