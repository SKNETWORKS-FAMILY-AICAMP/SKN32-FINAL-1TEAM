"""산출물층 '코드 기준 자동 검증'(기획서 5-4) — 구현 Agent가 만든 HTML·SVG를 정적 파싱으로 판정한다. LLM·브라우저 없음.

HTML(웹개발·AI API) 배점 3/2/2/1/2/2/1/2:
  1 진입 파일(파싱 성공 + 외부 CDN·빌드 도구 의존 없음) 2 대체 텍스트 3 input label 연결 4 html lang 5 명도 대비 4.5:1
  6 제목 계층 7 실행 안내 문서(규칙 모듈이 만든다 → 모델 몫이 아니라 자동 만점) 8 하드코딩된 비밀값
SVG(원페이지·인포그래픽) 배점 3/2/2/2/2/2/1/1:
  1 진입 파일(루트 파싱 성공) 2 title·desc 3 핵심 정보 6항목(부분 점수) 4 명도 대비 5 정보 계층(글자 크기 3단 이상)
  6 텍스트 실재성(래스터 <image> 없음) 7 최소 글자 크기 8 열람 안내(규칙 모듈 → 자동 만점)
1번이 미충족이면 코드 점수 전체를 0으로 한다. 계획서 대조(기능 목록 실재)는 15점, 기능 하나 누락마다 4점 감점.
CSS는 단순 선택자(태그·클래스·아이디, :root 변수)만 읽는 근사 판정이다. 판정 못 하는 요소는 세지 않는다.
"""
from __future__ import annotations

import colorsys
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

HTML_WEIGHTS = [3, 2, 2, 1, 2, 2, 1, 2]
HTML_NAMES = ['진입 파일', '대체 텍스트', 'label 연결', 'html lang', '명도 대비', '제목 계층', '실행 안내(규칙)', '비밀값']
SVG_WEIGHTS = [3, 2, 2, 2, 2, 2, 1, 1]
SVG_NAMES = ['진입 파일', 'title·desc', '핵심 정보 6항목', '명도 대비', '정보 계층', '텍스트 실재성', '최소 글자 크기', '열람 안내(규칙)']
MIN_FONT = 12                                  # 최소 글자 크기(px, 잠정: 기획서에 값이 없다)
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_NAMED = {'white': '#ffffff', 'black': '#000000', 'red': '#ff0000', 'blue': '#0000ff', 'green': '#008000', 'gray': '#808080',
          'grey': '#808080', 'orange': '#ffa500', 'yellow': '#ffff00', 'purple': '#800080', 'navy': '#000080', 'teal': '#008080',
          'silver': '#c0c0c0', 'transparent': None, 'currentcolor': None, 'inherit': None, 'none': None}
_SECRET = re.compile(r'(sk-[A-Za-z0-9_\-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}|ghp_[A-Za-z0-9]{30,}|'
                     r'(?:api[_-]?key|secret|token|password|passwd)["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-/+=]{12,}["\'])', re.I)


# ── 색·대비 ────────────────────────────────────────────────
def parse_color(v: str | None, variables: dict | None = None) -> tuple[int, int, int] | None:
    """CSS 색 → (r, g, b). 해석하지 못하면 None(그라데이션·url·투명 포함)."""
    if not v:
        return None
    v = v.strip().lower()
    for _ in range(3):
        m = re.match(r'var\(\s*(--[\w-]+)\s*(?:,\s*(.+))?\)', v)
        if not m:
            break
        v = (variables or {}).get(m.group(1)) or (m.group(2) or '')
        v = v.strip().lower()
    if v in _NAMED:
        v = _NAMED[v] or ''
    if v.startswith('#'):
        h = v[1:]
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h[:3])
        if len(h) in (6, 8) and re.fullmatch(r'[0-9a-f]+', h):
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return None
    m = re.match(r'rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)', v)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r'hsla?\(\s*([\d.]+)[,\s]+([\d.]+)%[,\s]+([\d.]+)%', v)
    if m:
        r, g, b = colorsys.hls_to_rgb(float(m.group(1)) / 360, float(m.group(3)) / 100, float(m.group(2)) / 100)
        return round(r * 255), round(g * 255), round(b * 255)
    return None


def luminance(c: tuple[int, int, int]) -> float:
    def f(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def contrast(a, b) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _norm(s: str) -> str:
    return re.sub(r'[\s\W_]+', '', s)


def _bigrams(s: str) -> set:
    s = _norm(s)
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def coverage(needle: str, hay: str) -> float:
    n = _bigrams(needle)
    return len(n & _bigrams(hay)) / len(n) if n else 0.0


# ── 코드 추출 ──────────────────────────────────────────────
def extract_code(text: str, kind: str) -> str | None:
    """모델 응답에서 코드를 꺼낸다. kind: 'html' | 'svg'. 없으면 None(형식 오류)."""
    m = re.search(r'```(?:html|svg|xml)?\s*\n(.*?)```', text, re.S | re.I)
    body = m.group(1) if m else text
    if kind == 'svg':
        m = re.search(r'<svg\b.*</svg>', body, re.S | re.I)
        return m.group(0).strip() if m else None
    m = re.search(r'(<!doctype html.*|<html\b.*)', body, re.S | re.I)
    if not m:
        return None
    out = m.group(1)
    end = re.search(r'</html\s*>', out, re.I)
    return (out[:end.end()] if end else out).strip()


# ── 미니 DOM ──────────────────────────────────────────────
class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children, self.texts = tag, attrs, parent, [], []

    def text(self) -> str:
        parts = list(self.texts)
        for c in self.children:
            if c.tag not in ('script', 'style'):
                parts.append(c.text())
        return ' '.join(p for p in parts if p.strip())

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def ancestors(self):
        n = self
        while n is not None:
            yield n
            n = n.parent


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node('#root', {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or '') for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        n = Node(tag, {k: (v or '') for k, v in attrs}, self.cur)
        self.cur.children.append(n)

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data.strip():
            self.cur.texts.append(data.strip())


def parse_html(src: str) -> Node:
    b = _Builder()
    b.feed(src)
    return b.root


# ── CSS (단순 선택자) ──────────────────────────────────────
def _decls(block: str) -> dict:
    out = {}
    for part in block.split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_css(root: Node) -> tuple[list, dict]:
    """(규칙 목록[(선택자, 우선순위, 선언)], :root 변수)."""
    css = '\n'.join(' '.join(n.texts) for n in root.walk() if n.tag == 'style')
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules, variables = [], {}
    for m in re.finditer(r'([^{}@]+)\{([^{}]*)\}', css):
        decl = _decls(m.group(2))
        for sel in (s.strip() for s in m.group(1).split(',')):
            if sel in (':root', 'html', 'html,:root'):
                variables.update({k: v for k, v in decl.items() if k.startswith('--')})
            if re.fullmatch(r'\*|[a-z][a-z0-9]*|[a-z0-9]*(?:[.#][\w-]+)+', sel, re.I) and ':' not in sel:
                spec = 100 * sel.count('#') + 10 * sel.count('.') + (1 if re.match(r'[a-z]', sel, re.I) else 0)
                rules.append((sel, spec, decl))
    return rules, variables


def _matches(sel: str, n: Node) -> bool:
    if sel == '*':
        return True
    m = re.fullmatch(r'([a-z0-9]*)((?:[.#][\w-]+)*)', sel, re.I)
    if not m:
        return False
    if m.group(1) and m.group(1).lower() != n.tag:
        return False
    classes = n.attrs.get('class', '').split()
    for t in re.findall(r'[.#][\w-]+', m.group(2)):
        if t[0] == '.' and t[1:] not in classes:
            return False
        if t[0] == '#' and t[1:] != n.attrs.get('id', ''):
            return False
    return True


def style_of(n: Node, rules: list, prop: str) -> str | None:
    """이 요소에 직접 적용되는 속성 값(우선순위 반영). 없으면 None."""
    best, val = -1, None
    for sel, spec, decl in rules:
        if _matches(sel, n):
            v = decl.get(prop)
            if v is None and prop == 'background-color':
                v = decl.get('background')
            if v is not None and spec >= best:
                best, val = spec, v
    inline = _decls(n.attrs.get('style', ''))
    v = inline.get(prop) or (inline.get('background') if prop == 'background-color' else None)
    return v if v is not None else val


# ── HTML 검사 ─────────────────────────────────────────────
_CONTROLS = {'input', 'textarea', 'select'}
_NO_LABEL_INPUT = {'hidden', 'submit', 'button', 'reset', 'image'}


def html_checks(src: str, case: dict) -> dict:
    root = parse_html(src)
    nodes = [n for n in root.walk() if n.tag != '#root']
    tags = {n.tag for n in nodes}
    rules, variables = parse_css(root)
    detail = {}

    # 1 진입 파일: 파싱 성공(html·body와 내용) + 외부 의존 없음
    external = []
    for n in nodes:
        if n.tag == 'script' and n.attrs.get('src', '').lower().startswith(('http', '//')):
            external.append(n.attrs['src'])
        if n.tag == 'link' and n.attrs.get('href', '').lower().startswith(('http', '//')) and 'stylesheet' in n.attrs.get('rel', '').lower():
            external.append(n.attrs['href'])
    for st in (n for n in nodes if n.tag == 'style'):
        external += re.findall(r'@import\s+(?:url\()?["\']?(https?://[^"\')\s]+)', ' '.join(st.texts))
    body_text = next((n.text() for n in nodes if n.tag == 'body'), '')
    parsed = 'html' in tags and 'body' in tags and len(body_text) >= 20
    ok1 = parsed and not external
    detail[1] = (ok1, '파싱 %s · 외부 의존 %d건%s' % ('성공' if parsed else '실패', len(external), (' (' + external[0][:60] + ')') if external else ''))

    # 2 대체 텍스트
    bad = 0
    for n in nodes:
        if n.tag == 'img' and 'alt' not in n.attrs:
            bad += 1
        if n.tag == 'input' and n.attrs.get('type') == 'image' and not n.attrs.get('alt'):
            bad += 1
        if n.tag == 'svg' and not (any(c.tag == 'title' for c in n.children) or n.attrs.get('aria-label') or n.attrs.get('aria-hidden') == 'true'
                                   or n.attrs.get('role') in ('presentation', 'none')):
            bad += 1
    detail[2] = (bad == 0, '대체 텍스트 없는 img·svg %d개' % bad)

    # 3 label 연결
    label_for = {n.attrs.get('for') for n in nodes if n.tag == 'label' and n.attrs.get('for')}
    total = bad3 = 0
    for n in nodes:
        if n.tag in _CONTROLS and n.attrs.get('type', 'text') not in _NO_LABEL_INPUT:
            total += 1
            linked = (n.attrs.get('id') in label_for and n.attrs.get('id')) or any(a.tag == 'label' for a in n.ancestors()) \
                or n.attrs.get('aria-label') or n.attrs.get('aria-labelledby') or n.attrs.get('title')
            if not linked:
                bad3 += 1
    detail[3] = (bad3 == 0, '입력 %d개 중 label 미연결 %d개' % (total, bad3))

    # 4 lang
    html_node = next((n for n in nodes if n.tag == 'html'), None)
    detail[4] = (bool(html_node and html_node.attrs.get('lang', '').strip()), 'lang=%r' % (html_node.attrs.get('lang') if html_node else None))

    # 5 명도 대비
    ok = fail = 0
    worst = None
    for n in nodes:
        if n.tag in ('script', 'style', 'head', 'title', 'meta', 'link', 'html', 'body') and n.tag not in ('body',):
            continue
        if not n.texts or n.tag in ('script', 'style', 'title'):
            continue
        fg = bg = None
        fg_known = bg_known = False
        for a in n.ancestors():
            if not fg_known:
                v = style_of(a, rules, 'color')
                if v is not None:
                    fg, fg_known = parse_color(v, variables), True
            if not bg_known:
                v = style_of(a, rules, 'background-color')
                if v is not None and v.strip().lower() not in ('transparent', 'inherit', 'initial', 'none'):
                    bg, bg_known = parse_color(v, variables), True
                    if bg is None:
                        bg_known = 'unknown'
        if bg_known == 'unknown' or (fg_known and fg is None):
            continue                                               # 그라데이션·해석 못 한 색은 판정하지 않는다
        fg = fg or (0, 0, 0)
        bg = bg or (255, 255, 255)
        ratio = contrast(fg, bg)
        if ratio >= 4.5:
            ok += 1
        else:
            fail += 1
            worst = min(worst, ratio) if worst else ratio
    measurable = ok + fail
    detail[5] = (measurable == 0 or fail / measurable <= 0.05,
                 '판정 가능 %d개 중 4.5:1 미만 %d개%s' % (measurable, fail, (' (최저 %.1f:1)' % worst) if worst else ''))

    # 6 제목 계층
    levels = [int(n.tag[1]) for n in nodes if re.fullmatch(r'h[1-6]', n.tag)]
    order_ok = bool(levels) and levels[0] == 1 and all(levels[i] <= levels[i - 1] + 1 for i in range(1, len(levels)))
    detail[6] = (order_ok, '제목 순서 %s' % ('→'.join('h%d' % x for x in levels[:8]) or '없음'))

    # 7 실행 안내 문서: 규칙 모듈이 만든다 → 자동 충족
    detail[7] = (True, '규칙 모듈이 생성(모델 몫 아님)')

    # 8 비밀값
    hits = _SECRET.findall(src)
    detail[8] = (not hits, '비밀값 패턴 %d건' % len(hits))

    return _assemble(detail, HTML_WEIGHTS, HTML_NAMES, external=external, features=_html_features(nodes, case))


def _html_features(nodes: list[Node], case: dict) -> dict:
    segs = []
    for n in nodes:
        if n.tag in ('script', 'style'):
            continue
        t = n.text()
        if t and len(t) <= 240:
            segs.append(t)
        for a in ('placeholder', 'aria-label', 'title', 'alt', 'value'):
            if n.attrs.get(a):
                segs.append(n.attrs[a])
    return _feature_match(segs, case['item_spec']['core_features'])


def _feature_match(segments: list[str], features: list[str]) -> dict:
    missing = [f for f in features if not any(coverage(f, s) >= 0.8 for s in segments)]
    return {'missing': missing, 'score': max(0, 15 - 4 * len(missing)), 'total': len(features)}


def _assemble(detail: dict, weights: list, names: list, **extra) -> dict:
    checks = []
    for i, (w, nm) in enumerate(zip(weights, names), 1):
        ok, note = detail[i][0], detail[i][1]
        earned = detail[i][2] if len(detail[i]) > 2 else (w if ok else 0)
        checks.append({'no': i, 'name': nm, 'weight': w, 'earned': earned, 'ok': bool(ok) if len(detail[i]) <= 2 else earned >= w, 'note': note})
    code = 0.0 if not checks[0]['ok'] else sum(c['earned'] for c in checks)
    return dict({'checks': checks, 'code': code}, **extra)


# ── SVG 검사 ──────────────────────────────────────────────
def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1]


def _size(v: str | None) -> float | None:
    m = re.match(r'\s*([\d.]+)', v or '')
    return float(m.group(1)) if m else None


def _svg_font_size(el, parents) -> float:
    for e in [el] + list(reversed(parents)):
        st = _decls(e.attrib.get('style', ''))
        v = st.get('font-size') or e.attrib.get('font-size')
        if v and _size(v):
            return _size(v)
    return 16.0


def _svg_paint(el, parents, prop='fill'):
    for e in [el] + list(reversed(parents)):
        st = _decls(e.attrib.get('style', ''))
        v = st.get(prop) or e.attrib.get(prop)
        if v is not None:
            return v
    return None


def _translate(parents) -> tuple[float, float]:
    tx = ty = 0.0
    for e in parents:
        m = re.search(r'translate\(\s*([-\d.]+)[,\s]+([-\d.]+)?', e.attrib.get('transform', ''))
        if m:
            tx += float(m.group(1))
            ty += float(m.group(2) or 0)
    return tx, ty


def svg_checks(src: str, case: dict, category: str) -> dict:
    detail = {}
    try:
        root = ET.fromstring(src)
        ok1 = _strip_ns(root.tag) == 'svg'
    except ET.ParseError as exc:
        root, ok1 = None, False
        detail[1] = (False, 'XML 파싱 실패: %s' % str(exc)[:60])
    if root is None:
        for i in range(2, 9):
            detail[i] = (False, '판정 불가')
        return _assemble(detail, SVG_WEIGHTS, SVG_NAMES, features={'missing': case['item_spec']['core_features'], 'score': 0, 'total': len(case['item_spec']['core_features'])}, info=[])
    if 1 not in detail:
        detail[1] = (ok1, '루트 %s' % _strip_ns(root.tag))

    # 요소 목록 (부모 경로 포함)
    items = []

    def walk(el, parents):
        items.append((el, parents))
        for c in el:
            walk(c, parents + [el])
    walk(root, [])
    texts = []
    for el, parents in items:
        if _strip_ns(el.tag) == 'text':
            s = ''.join(el.itertext()).strip()
            if s:
                texts.append((el, parents, s))
    all_text = ' '.join(s for _, _, s in texts)

    tags = [_strip_ns(el.tag) for el, _ in items]
    detail[2] = ('title' in tags[1:] and 'desc' in tags, 'title %s · desc %s' % ('있음' if 'title' in tags[1:] else '없음', '있음' if 'desc' in tags else '없음'))

    # 3 핵심 정보 6항목
    spec, co = case['item_spec'], case['company']
    price_ok = any(abs(x['value'] - co['revenue_unit_price']) <= 0.01 * co['revenue_unit_price'] for x in _numbers(all_text))
    dev = re.search(r'\d+', co['development_period'])
    sched_ok = bool((dev and re.search(r'%s\s*개월' % dev.group(0), all_text)) or case['announcement']['apply_end'] in all_text
                    or re.search(r'11\s*월\s*30\s*일', all_text))
    info = [
        ('아이템명', _norm(spec['item_name']) in _norm(all_text)),
        ('목표 고객', _has_target(texts, spec, all_text)),
        ('문제 정의', _has_problem(texts, spec)),
        ('해결 방안', any(coverage(f, all_text) >= 0.7 for f in spec['core_features'])),
        ('수익모델 단가', price_ok),
        ('추진 일정 기준선', sched_ok)]
    got = sum(1 for _, ok in info if ok)
    detail[3] = (got == 6, '6항목 중 %d개: 없음 = %s' % (got, ', '.join(n for n, ok in info if not ok) or '-'), round(2 * got / 6, 2))

    # 4 명도 대비 (글자 색 대 그 위치를 덮는 가장 작은 사각형, 없으면 전체 배경)
    rects = []
    for el, parents in items:
        if _strip_ns(el.tag) == 'rect':
            tx, ty = _translate(parents)
            try:
                x, y, w, h = (float(el.attrib.get(k, 0)) for k in ('x', 'y', 'width', 'height'))
            except ValueError:
                continue
            fill = parse_color(_svg_paint(el, parents, 'fill'))
            rects.append((x + tx, y + ty, w, h, fill))                     # 그라데이션 등 읽지 못한 색은 fill=None으로 남긴다
    vb = [float(v) for v in re.split(r'[ ,]+', root.attrib.get('viewBox', '').strip())] if root.attrib.get('viewBox') else None
    page_bg = (255, 255, 255)
    page_unknown = False
    if vb and rects:
        big = [r for r in rects if r[2] * r[3] >= 0.9 * vb[2] * vb[3]]
        if big:
            page_bg = big[0][4] or (255, 255, 255)
            page_unknown = big[0][4] is None
    ok4 = fail4 = 0
    for el, parents, s in texts:
        fill_raw = _svg_paint(el, parents, 'fill')
        fg = parse_color(fill_raw) if fill_raw is not None else (0, 0, 0)
        if fg is None:
            continue
        tx, ty = _translate(parents)
        try:
            px, py = float(el.attrib.get('x', 0)) + tx, float(el.attrib.get('y', 0)) + ty - 0.3 * _svg_font_size(el, parents)
        except ValueError:
            continue
        cover = [r for r in rects if r[0] - 1 <= px <= r[0] + r[2] + 1 and r[1] - 1 <= py <= r[1] + r[3] + 1 and not (r[2] * r[3] >= 0.9 * (vb[2] * vb[3] if vb else 1e18))]
        bg = min(cover, key=lambda r: r[2] * r[3])[4] if cover else (None if page_unknown else page_bg)
        if bg is None:                                                     # 그라데이션 배경 위 글자는 판정하지 않는다
            continue
        if contrast(fg, bg) >= 4.5:
            ok4 += 1
        else:
            fail4 += 1
    m4 = ok4 + fail4
    detail[4] = (m4 == 0 or fail4 / m4 <= 0.05, '판정 가능 %d개 중 4.5:1 미만 %d개' % (m4, fail4))

    # 5 정보 계층, 7 최소 글자 크기
    sizes = sorted({round(_svg_font_size(el, parents)) for el, parents, _ in texts})
    detail[5] = (len(sizes) >= 3, '글자 크기 %d단계 %s' % (len(sizes), sizes[:6]))

    # 6 텍스트 실재성
    images = sum(1 for t in tags if t == 'image')
    detail[6] = (images == 0 and len(texts) >= 3, '래스터 <image> %d개 · 글자 요소 %d개' % (images, len(texts)))
    detail[7] = (bool(sizes) and min(sizes) >= MIN_FONT, '최소 글자 크기 %s' % (min(sizes) if sizes else '없음'))
    detail[8] = (True, '규칙 모듈이 생성(모델 몫 아님)')
    feats = _feature_match([s for _, _, s in texts] + [all_text], case['item_spec']['core_features'])
    return _assemble(detail, SVG_WEIGHTS, SVG_NAMES, features=feats, info=[{'name': n, 'ok': ok} for n, ok in info])


def _labeled(strs: list[str], key: str, window: int = 6) -> bool:
    """이름표(짧은 글자에 key 포함) 뒤 window개 안에 내용 글자(10자 이상)가 이어지거나, 이름표와 내용을 한 글자 요소에 함께 쓴 경우."""
    for i, s in enumerate(strs):
        if key in s and len(s) > 18:
            return True
        if key in s and any(len(t) >= 10 for t in strs[i + 1:i + 1 + window]):
            return True
    return False


def _has_problem(texts: list, spec: dict) -> bool:
    """문제 정의: '문제' 이름표 + 내용이 이어지거나, 한 줄 설명과 비슷한 글이 있으면 인정한다."""
    strs = [s for _, _, s in texts]
    return _labeled(strs, '문제') or any(coverage(spec['one_line_summary'], s) >= 0.35 for s in strs)


def _has_target(texts: list, spec: dict, all_text: str) -> bool:
    """목표 고객: 원문과 글자가 40% 이상 겹치거나, '고객' 이름표 + 내용이 이어지면 인정한다(줄여 써도 인정)."""
    strs = [s for _, _, s in texts]
    return any(coverage(spec['target_customer'], s) >= 0.4 for s in strs) or coverage(spec['target_customer'], all_text) >= 0.6 or _labeled(strs, '고객')


def _numbers(text: str) -> list[dict]:
    """글 속 금액·수치(만·천 단위 포함)를 값으로 바꾼다."""
    out = []
    unit = {'만': 1e4, '천': 1e3, '억': 1e8}
    for m in re.finditer(r'(\d[\d,]*\.?\d*)\s*(억|만|천)?\s*(\d[\d,]*)?\s*(천)?', text):
        v = float(m.group(1).replace(',', '')) * unit.get(m.group(2), 1)
        if m.group(3) and m.group(4):
            v += float(m.group(3).replace(',', '')) * unit[m.group(4)]
        out.append({'value': v})
    return out
