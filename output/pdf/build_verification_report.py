from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'S-Brain_산출물검증결과서_원페이지형_개선안.pdf'
pdfmetrics.registerFont(TTFont('Body', 'C:/Windows/Fonts/malgun.ttf'))
pdfmetrics.registerFont(TTFont('Bold', 'C:/Windows/Fonts/malgunbd.ttf'))
W, H = 595.276, 841.89
c = canvas.Canvas(str(OUT), pagesize=(W,H))
c.setTitle('S-Brain 산출물 검증결과서 | 원페이지형 개선안')
c.setAuthor('S-Brain')
INK, MUTED, LINE, BLUE = '#202A35', '#647080', '#D8DEE5', '#23547A'
L, R = 42, W-42

def text(x,y,s,size=9,bold=False,color=INK,align='left'):
    c.setFont('Bold' if bold else 'Body',size); c.setFillColor(HexColor(color))
    fn = c.drawRightString if align=='right' else c.drawString
    fn(x,H-y,s)

def line(y,color=LINE,width=.5):
    c.setStrokeColor(HexColor(color)); c.setLineWidth(width); c.line(L,H-y,R,H-y)

def box(x,y,w,h,color):
    c.setFillColor(HexColor(color)); c.rect(x,H-y-h,w,h,stroke=0,fill=1)

def para(x,y,s,w,size=8.4,color=INK,leading=13):
    p=Paragraph(s,ParagraphStyle('body',fontName='Body',fontSize=size,leading=leading,textColor=HexColor(color),wordWrap='CJK'))
    _,h=p.wrap(w,1000); p.drawOn(c,x,H-y-h); return h

def section(y,n,title,note=''):
    text(L,y,n,9,True,BLUE); text(L+24,y,title,11,True)
    if note:text(R,y,note,8,False,MUTED,'right')
    line(y+9,INK,.7)

text(L,35,'S-Brain',11,True)
text(R,35,'검증결과서  /  원페이지형 산출물',8,False,MUTED,'right')
line(47,INK,1)
text(L,80,'산출물 검증결과서',23,True)
text(L,101,'사업계획서 및 인포그래픽 검증 결과',9,False,MUTED)
text(R,100,'양식 적용 예시',8,False,BLUE,'right')

line(118)
for y,label,value in [(137,'프로젝트명','동네 헬스장 예약 서비스'),(157,'검증 대상','gym-booking-infographic.svg')]:
    text(L,y,label,8,False,MUTED); text(L+77,y,value,9,True if y==137 else False)
text(L,177,'산출물 유형',8,False,MUTED); text(L+77,177,'원페이지형 / 인포그래픽',9)
text(330,177,'원본 생성 일시',8,False,MUTED); text(R,177,'2026-09-16 15:42',8.5,False,INK,'right')
line(189)

box(L,201,R-L,64,'#F3F6F9')
text(L+14,222,'종합 판정',8,False,MUTED)
text(L+14,247,'통과',17,True,BLUE)
text(L+104,244,'86',27,True); text(L+146,244,'/ 100점',9,False,MUTED)
text(330,225,'사업계획서',8.5); text(R-14,225,'60 / 70',10,True,INK,'right')
text(330,243,'산출물',8.5); text(R-14,243,'26 / 30',10,True,INK,'right')
text(L,282,'판정 기준  80점 이상   |   총점 통과와 별개로 미충족 항목의 보완이 필요합니다.',8,False,MUTED)

section(308,'01','사업계획서 평가','획득 점수 / 배점')
for x,label,score in [(L,'문제 인식','13 / 15'),(L+132,'실현 가능성','17 / 20'),(L+264,'성장 전략','17 / 20'),(L+396,'팀 구성','13 / 15')]:
    text(x,337,label,8.5,False,MUTED); text(x,358,score,13,True)
line(370)

section(396,'02','산출물 자동 점검','13 / 15점')
box(L,406,R-L,23,'#F3F6F9')
text(L+9,422,'점검 항목',8,True); text(386,422,'배점',8,True); text(437,422,'결과',8,True); text(R-9,422,'획득',8,True,INK,'right')
rows=[('진입 파일 존재',3,True),('이미지·SVG 대체 텍스트',2,True),('SVG viewBox 유효성',1,True),('명도 대비 4.5:1',2,True),('카테고리 배지 표기',1,True),('필수 섹션 제목 존재',2,True),('데이터 완전성',2,False),('하드코딩된 비밀값 없음',2,True)]
for i,(label,score,ok) in enumerate(rows):
    top=429+i*20
    if not ok: box(L,top,R-L,20,'#FAF5F0')
    text(L+9,top+14,label,8.3,bold=not ok)
    text(396,top+14,str(score),8.3,align='right')
    text(437,top+14,'충족' if ok else '미충족',8,bold=not ok,color=INK if ok else '#865629')
    text(R-9,top+14,str(score if ok else 0),8.3,align='right')
    line(top+20)

section(614,'03','교차 검증 의견 및 보완 사항','13 / 15점')
text(L,643,'검증 의견',8.3,True)
para(L+76,632,'인포그래픽과 사업계획서의 수치·주요 지표는 일치합니다. 일부 근거는 인포그래픽에 단순화되어 표현되어 있습니다.',R-L-76)
text(L,682,'보완 사항',8.3,True)
para(L+76,671,'데이터 완전성 미충족 항목을 확인하고 누락 정보를 보완하십시오. 단순화된 주장에는 사업계획서의 근거 위치 또는 출처를 연결하는 것을 권고합니다.',R-L-76)
text(L,721,'근거 기록',8.3,True)
para(L+76,710,'원본에 누락 데이터의 항목명·위치가 기재되어 있지 않습니다. 실제 발급 시 검증 로그와 대조 문서의 페이지·섹션을 함께 기재해야 합니다.',R-L-76,8,MUTED,12)

line(750,INK,.7)
para(L,760,'본 문서는 제공된 예시의 점수와 판정을 재구성한 양식이며, 실제 프로젝트를 재검증한 결과가 아닙니다.<br/>평가는 S-Brain 내부 참고용으로 공식 심사 결과를 의미하지 않습니다. 적용 정책에 따라 항목·배점은 달라질 수 있습니다.',R-L,7.2,MUTED,11)
text(L,814,'S-Brain  |  산출물 검증결과서',7,False,MUTED)
text(R,814,'1 / 1',7,False,MUTED,'right')
c.save()
print(OUT)
