"""Generate a verified 2026 web-design trend list; no crawler, RAG, or statistics."""
import json
from pathlib import Path

TITLE = "Figma — Top Web design trends for 2026"
URL = "https://www.figma.com/resource-library/web-design-trends/"
TYPE = "2026_web_design_report"
# name|description|web example|Second Brain example|keywords|direct source text
ROWS = '''3D and immersive elements|정적 이미지 대신 입체 모델과 몰입형 상호작용으로 제품·공간을 보여준다|3D 제품 회전 미리보기|문서 미리보기의 3D 커버|3D,WebGL,immersive|Designers are leaning into depth and interaction, moving beyond static images to immersive, 3D-driven experiences.
Interactive 3D models|사용자가 화면 안의 대상을 직접 회전·탐색한다|가구 360도 뷰|프로젝트 아티팩트 3D 뷰|3D,model,interaction|Using technologies like WebGL, sites now feature interactive models, scroll-triggered animations, and AR previews.
Scroll-triggered animation|스크롤을 콘텐츠 진행 신호로 쓰는 애니메이션|스크롤 기반 제품 스토리|프로젝트 단계 전환|scroll,animation,storytelling|Using technologies like WebGL, sites now feature interactive models, scroll-triggered animations, and AR previews.
AR previews|실제 맥락에서 대상을 확인하는 증강현실 미리보기|공간 배치 AR|회의실 레이아웃 AR|AR,preview,spatial|Using technologies like WebGL, sites now feature interactive models, scroll-triggered animations, and AR previews.
Experimental navigation|탐색 경험 자체를 차별화하는 비선형 내비게이션|탐색형 브랜드 사이트|프로젝트 맵 탐색|navigation,exploration,nonlinear|Designers are experimenting with layouts that feel more like exploration than navigation.
Radial menus|선택지를 방사형으로 배치해 탐색 동선을 압축한다|원형 도구 메뉴|빠른 작업 메뉴|radial,menu,navigation|Think radial menus, hidden drawers, interactive maps, or nonlinear journeys.
Interactive maps|장소·주제·관계를 지도형 화면으로 탐색한다|매장 지도|지식·프로젝트 관계 지도|map,interactive,navigation|Think radial menus, hidden drawers, interactive maps, or nonlinear journeys.
Vibrant color palettes|밝고 채도 높은 색상으로 강한 첫인상을 만든다|고대비 Hero 섹션|프로젝트 상태 색상 체계|color,vibrant,palette|Bright, saturated color palettes are making a comeback, fueled by Y2K nostalgia, retro patterns, and “dopamine design” aesthetics.
Neon gradients|네온 계열 그라데이션으로 디지털 인상을 만든다|그라데이션 배경|AI 실행 상태 배경|neon,gradient,color|Neon gradients, high-contrast pairings, and playful hues are replacing minimal or muted tones.
High-contrast pairings|색상 간 강한 대비로 주목도와 구분을 높인다|강조 CTA|우선순위 알림|contrast,color,CTA|Neon gradients, high-contrast pairings, and playful hues are replacing minimal or muted tones.
Bold typography|큰 제목과 독자적 서체로 텍스트를 스토리텔링 수단으로 쓴다|대형 Hero 제목|프로젝트 핵심 목표 제목|typography,headline,variable-font|Typography is taking center stage in 2026, moving beyond legibility into storytelling.
Kinetic lettering|움직이는 글자로 진입과 상태 변화를 강조한다|인트로 타이틀 모션|작업 완료 타이틀 모션|kinetic,type,motion|Hero sections now often feature kinetic lettering, dynamic font pairings, and variable fonts that respond to interaction or context.
Variable fonts|상황과 상호작용에 반응하는 가변 서체를 쓴다|반응형 헤드라인|확대 가능한 문서 제목|variable-font,responsive,type|Hero sections now often feature kinetic lettering, dynamic font pairings, and variable fonts that respond to interaction or context.
Dark mode personalization|라이트·다크 전환을 개인화와 접근성의 일부로 제공한다|테마 토글|업무 공간 테마 설정|dark-mode,theme,accessibility|Many well-known brands like YouTube, X, and Slack offer a toggle for switching between light and dark modes.
Motion design and animation|상태와 흐름을 설명하는 모션을 사용한다|버튼 상태 모션|Agent 진행 상태 모션|motion,animation,microinteraction|Motion design adds rhythm and storytelling to Web experiences.
Scrollytelling|스크롤 진행을 정보 공개의 순서로 활용한다|제품 기능 스토리|프로젝트 타임라인|scrollytelling,scroll,narrative|From subtle hover effects to full scroll-based narratives (“scrollytelling”), motion helps guide attention and build immersion.
Micro animations|작은 애니메이션으로 입력·전환·완료를 알린다|버튼 리플|작업 완료 체크 모션|microanimation,feedback,state|Brands use micro animations—scroll triggers, button ripples, animated states—to enhance the user journey without slowing performance.
Gamified design|포인트·레벨·보상으로 참여와 동기를 높인다|온보딩 체크리스트|작업 목표·배지|gamification,progress,badge|Think points, levels, badges, progress bars, leaderboards, challenges, and micro-rewards woven into the user journey to boost engagement and motivation.
Neumorphism|부드러운 그림자와 미세한 그라데이션으로 촉각적 표면을 만든다|입체 카드|노트·태스크 카드|neumorphism,tactile,shadow|Soft shadows and subtle gradients create raised or inset elements that look almost touchable.
Retrofuturism|레트로한 미래 이미지와 현대 웹 인터랙션을 결합한다|크롬·네온 랜딩|AI 실험 공간 테마|retrofuturism,neon,chrome|Retrofuturism fuses nostalgia with optimism, bringing vintage visions of the future into modern Web design.
Maximalism|강한 색·중첩 시각물·굵은 글자로 에너지 높은 화면을 만든다|캠페인 랜딩|중요 프로젝트 발표 화면|maximalism,layering,bold|Rich colors, overlapping visuals, bold fonts, and dense compositions are key ingredients in this high-energy trend.
Collage|스티커·찢어진 질감·컷아웃 사진으로 스크랩북 개성을 만든다|크리에이터 포트폴리오|프로젝트 무드보드|collage,scrapbook,texture|Collage Web design brings scrapbook-style creativity into digital experiences.
Neo-brutalism|거칠고 비정형적인 표현으로 강한 개성을 만든다|실험적 브랜드 페이지|실험 기능 베타 화면|neo-brutalism,anti-design,raw|Neo-brutalism embraces raw, unpolished visuals that stand out in a sea of sleek, minimalist templates.
Sustainable web design|가벼운 코드와 최적화 자산으로 환경 부담을 줄인다|최적화 이미지 랜딩|가벼운 문서 목록 화면|sustainable,performance,images|Leaner code, optimized images, and low-impact hosting help reduce the carbon footprint of digital products.
Accessible and inclusive design|고대비·스크린리더·키보드 흐름을 함께 고려한다|접근성 설정|키보드 중심 Command Palette|accessibility,screen-reader,keyboard|Designers are also prioritizing accessibility and inclusion: high contrast color palettes, screen reader support, voice navigation, and keyboard-only flows are becoming standard.
AI chatbots|대화형 AI가 다단계 작업과 사용자 요구 예측을 수행한다|고객 지원 챗봇|Second Brain Chat Workspace|AI,chatbot,agentic|Today’s AI chatbots are proactive, conversational, and often agentic—capable of handling multi-step tasks and anticipating user needs.
Voice-activated interfaces|음성으로 기능 제어·메뉴 탐색·도움 요청을 수행한다|음성 검색|음성 기반 노트 추가|voice,hands-free,navigation|It now goes beyond search, letting you control site features, talk to helpful chatbots, or browse menus naturally.
Progressive lead nurturing|상호작용에 맞춰 폼과 추천을 조정한다|단계형 가입 폼|점진적 프로젝트 설정|forms,personalization,progressive|Instead of overwhelming users, AI tailors form questions, follow-ups, and product recommendations based on each interaction.
AI-driven personalization|AI가 개인화된 웹 경험을 만든다|맞춤 추천|개인화된 작업 시작 화면|AI,personalization,recommendation|AI is shaking up Web design, making sites smarter and more personalized.
Responsive components|반응형 컴포넌트로 여러 화면에서 일관된 경험을 만든다|반응형 카드 그리드|반응형 사이드바·패널|responsive,components,interaction|Launch your next website through Figma Sites, complete with its own CMS plus responsive components and preset interactions like marquee scrolling, custom cursors, and hover effects.'''

def trends():
    result=[]
    for rank, row in enumerate(ROWS.splitlines(), 1):
        name, description, web, brain, keywords, quote=row.split("|")
        result.append({"rank":rank,"trendId":f"WD-2026-{rank:03d}","trendName":name,"description":description,"webApplicationExample":web,"secondBrainApplication":brain,"keywords":keywords.split(","),"evidence":[{"sourceTitle":TITLE,"sourceUrl":URL,"sourceType":TYPE,"supportingText":quote}]})
    return result

def markdown(items):
    lines=["# 2026 웹디자인 트렌드 TOP 30",""]
    for item in items:
        evidence=item["evidence"][0]
        lines += [f"## {item['rank']}. {item['trendName']} ({item['trendId']})","",f"- description: {item['description']}",f"- webApplicationExample: {item['webApplicationExample']}",f"- secondBrainApplication: {item['secondBrainApplication']}",f"- keywords: {', '.join(item['keywords'])}",f"- sourceTitle: {evidence['sourceTitle']}",f"- sourceUrl: {evidence['sourceUrl']}",f"- sourceType: {evidence['sourceType']}",f"- supportingText: {evidence['supportingText']}",""]
    return "\n".join(lines)

def write(output="output"):
    output=Path(output); output.mkdir(exist_ok=True)
    items=trends()
    (output/"web_design_trends_2026.json").write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"web_design_trends_2026.md").write_text(markdown(items),encoding="utf-8")
if __name__ == "__main__": write()
