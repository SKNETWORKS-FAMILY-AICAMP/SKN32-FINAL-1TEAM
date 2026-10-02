import React,{useEffect,useRef} from 'react';
import {Brand,Icon} from './Icons.jsx';

const SCENES=[
 {id:'hero',label:'시작'},
 {id:'match',label:'맞춤 공고'},
 {id:'outputs',label:'결과물'},
 {id:'faq',label:'FAQ'},
 {id:'closing',label:'프로젝트 시작'},
];

function HeroScene({onStart}){
 return <section className="landing-scene scene-hero" aria-labelledby="scene-hero-title">
  <div className="scene-hero-inner">
   <p className="hero-label">아이디어는 있는데 시작이 막막하다면</p>
   <h1 id="scene-hero-title">지원사업 준비<br/><span>이제 한곳에서</span></h1>
   <p className="hero-description">나에게 맞는 공고를 찾는 일부터<br/>사업계획서와 프로토타입을 준비하는 일까지.</p>
   <button className="btn hero-cta" onClick={onStart}>내 아이디어로 시작하기</button>
   <div className="hero-summary" aria-label="지원사업 준비 과정"><div className="summary-input"><span className="service-symbol"><span>S</span></span><div><small>이런 아이디어를 준비하고 있어요</small><p>동네 운동시설을 쉽게 예약하는 서비스</p></div></div><div className="summary-results"><div><span className="summary-number">01</span><span>맞는 공고 찾기</span><b>공고 3건</b></div><div><span className="summary-number">02</span><span>계획서와 프로토타입</span><b>함께 준비</b></div><div><span className="summary-number">03</span><span>제출 전 점검</span><b>빠짐없이</b></div></div><small className="sample-label">서비스 이용 과정 예시</small></div>
  </div>
 </section>;
}

function MatchScene({onStart}){
 const notices=[{title:'초기창업패키지',org:'창업진흥원',fit:92,amount:'최대 1억원'},{title:'예비창업패키지',org:'창업진흥원',fit:81,amount:'최대 5천만원'},{title:'스마트상점 기술보급',org:'중소벤처기업부',fit:68,amount:'최대 3천만원'}];
 return <section className="landing-scene scene-match" aria-labelledby="scene-match-title">
  <div className="scene-intro"><h2 id="scene-match-title">찾고 쓰고 확인하는 일<br/>따로 하지 않아도 괜찮아요</h2><p>지원사업 준비에 필요한 과정을 연결했어요.<br/>지금 내게 필요한 일부터 차근차근 시작해 보세요.</p></div>
  <div className="scene-match-content"><div className="section-copy"><span className="section-label">맞춤 공고</span><h2>수많은 공고 중에서<br/>나에게 맞는 것만</h2><p>아이템과 기업 정보를 알려주면<br/>신청할 수 있는 공고와 지원 조건을<br/>한눈에 확인할 수 있어요.</p><button className="text-link" onClick={onStart}>맞는 공고 찾아보기 <Icon name="chevron" size={17}/></button></div><div className="notice-preview"><div className="notice-preview-heading"><h3>이런 공고가 잘 맞아요</h3><span>예시</span></div>{notices.map((x,i)=><div className="notice-preview-row" key={x.title}><span className={'notice-icon tone-'+i}><Icon name="file" size={23}/></span><div><h4>{x.title}</h4><p>{x.org} · {x.amount}</p></div><span className="fit-number">{x.fit}<small>%</small></span></div>)}</div></div>
 </section>;
}

function OutputsScene({tab,setTab}){
 return <section className="landing-scene scene-outputs" aria-labelledby="scene-outputs-title"><div className="scene-outputs-inner"><div className="document-preview"><div className="document-top"><span>S-Brain</span><span>초안</span></div><div className="document-title">{['사업계획서','프로토타입','검증 리포트'][tab]}</div>{tab===0?<><h3>동네의 운동을<br/>더 가깝게 만드는 방법</h3><div className="document-outline">{['문제 인식','실현 가능성','성장 전략','팀 구성'].map((x,i)=><div key={x}><span>0{i+1}</span><b>{x}</b><Icon name="check" size={17}/></div>)}</div></>:tab===1?<><h3>아이디어를<br/>직접 보여줄 수 있도록</h3><div className="product-preview"><b>로컬핏</b><h4>오늘은 어떤 운동을 할까요?</h4><div><span>피트니스</span><span>필라테스</span><span>요가</span></div><p>핵심 화면과 기능을 확인하는 프로토타입</p></div></>:<><h3>제출 전에<br/>한 번 더 꼼꼼하게</h3><div className="review-preview"><div><span>문서 구성</span><b>확인 완료</b></div><div><span>프로토타입 연결</span><b>확인 완료</b></div><div><span>시장 규모 출처</span><b className="warning-text">보완 필요</b></div></div><small>예시 결과이며 실제 심사 점수가 아니에요.</small></>}</div><div className="section-copy"><span className="section-label">계획부터 실행까지</span><h2 id="scene-outputs-title">머릿속에 있던 생각을<br/>보여줄 수 있는 결과로</h2><p>공고에 맞춘 사업계획서와<br/>아이디어를 설명할 프로토타입.<br/>서로 잘 맞는지도 함께 점검해요.</p><div className="output-tabs" role="tablist" aria-label="결과물 종류">{['사업계획서','프로토타입','검증 리포트'].map((x,i)=><button role="tab" aria-selected={tab===i} key={x} onClick={()=>setTab(i)} className={tab===i?'active':''}>{x}</button>)}</div></div></div></section>;
}

function FaqScene(){
 const faqs=[['아이디어만 있어도 시작할 수 있나요?','네. 준비 중인 아이템과 신청자 정보를 입력하면 공고 매칭부터 시작할 수 있어요. 아직 창업 전이라면 예비창업자를 선택해 주세요.'],['만든 문서를 바로 제출해도 되나요?','사업계획서는 AI가 작성한 초안이에요. 사실 관계와 근거, 공고의 제출 양식을 직접 확인하고 수정한 뒤 제출해 주세요.'],['입력한 아이디어나 첨부한 자료는 안전하게 관리되나요?','네. 첨부한 원본 파일은 텍스트를 추출한 직후 바로 파기하고, 입력하신 정보는 회원 탈퇴 시 함께 삭제돼요. 학습 데이터 활용 동의는 선택 사항이라 언제든 껐다 켤 수 있어요.']];
 return <section className="landing-scene scene-faq" aria-labelledby="scene-faq-title"><div className="scene-faq-inner"><h2 id="scene-faq-title">궁금한 점이 있나요?</h2><div>{faqs.map(([q,a])=><details key={q}><summary>{q}<Icon name="plus" size={19}/></summary><p>{a}</p></details>)}</div></div></section>;
}

function ClosingScene({onStart}){
 return <section className="landing-scene scene-closing" aria-labelledby="scene-closing-title"><div className="scene-closing-main"><span className="scene-closing-symbol"><img src="/symbol-white.png" alt=""/></span><p>S-Brain과 함께 다음 단계로</p><h2 id="scene-closing-title">생각만 해왔던 아이디어<br/>이제 시작해 볼까요?</h2><button className="btn" onClick={onStart}>첫 프로젝트 만들기</button></div><footer className="scene-footer"><Brand/><p>정부지원사업 준비를 더 쉽게</p><small>© 2026 S-Brain · 서비스 시연용 데모</small></footer></section>;
}

export default function LandingDepthGallery({onStart,tab,setTab,active,setActive}){
 const activeRef=useRef(0);
 const wheelRef=useRef({sum:0,lockedUntil:0});
 const dragRef=useRef(null);
 const rootRef=useRef(null);
 const count=SCENES.length;
 const go=next=>{const value=(next+count)%count;activeRef.current=value;setActive(value)};
 const move=direction=>go(activeRef.current+direction);

 useEffect(()=>{
  activeRef.current=active;
 },[active]);

 useEffect(()=>{
  const root=rootRef.current;
  if(!root)return;
  const onKey=event=>{
   if(event.key==='ArrowDown'||event.key==='PageDown'||event.key==='ArrowRight'){event.preventDefault();move(1)}
   if(event.key==='ArrowUp'||event.key==='PageUp'||event.key==='ArrowLeft'){event.preventDefault();move(-1)}
  };
  root.addEventListener('keydown',onKey);
  return()=>root.removeEventListener('keydown',onKey);
 },[]);

 const handleWheel=event=>{
  const now=performance.now();
  if(now<wheelRef.current.lockedUntil)return;
  wheelRef.current.sum+=event.deltaY;
  if(Math.abs(wheelRef.current.sum)>48){move(wheelRef.current.sum>0?1:-1);wheelRef.current.sum=0;wheelRef.current.lockedUntil=now+520}
 };
 const handlePointerDown=event=>{
  if(event.target.closest('button,a,summary,details'))return;
  dragRef.current={id:event.pointerId,y:event.clientY};
  event.currentTarget.setPointerCapture?.(event.pointerId);
 };
 const handlePointerUp=event=>{const drag=dragRef.current;if(!drag||drag.id!==event.pointerId)return;const dy=event.clientY-drag.y;if(Math.abs(dy)>50)move(dy<0?1:-1);dragRef.current=null};
 const position=index=>{let delta=(index-active+count)%count;if(delta>count/2)delta-=count;return delta};

 return <main className="landing-depth" ref={rootRef} tabIndex="-1" onWheel={handleWheel} onPointerDown={handlePointerDown} onPointerUp={handlePointerUp} onPointerCancel={()=>{dragRef.current=null}}>
  <div className="landing-scene-stack">
   {[<HeroScene onStart={onStart}/>,<MatchScene onStart={onStart}/>,<OutputsScene tab={tab} setTab={setTab}/>,<FaqScene/>,<ClosingScene onStart={onStart}/>].map((scene,index)=>{
    const pos=position(index);
    return <div key={SCENES[index].id} className={`landing-scene-plate${pos===0?' is-active':''}`} style={{'--scene-position':pos,'--scene-distance':Math.abs(pos),zIndex:30-Math.abs(pos)}} aria-hidden={pos!==0}>{scene}</div>;
   })}
  </div>
  <nav className="scene-pagination" aria-label="랜딩페이지 장면 선택">{SCENES.map((scene,index)=><button key={scene.id} className={index===active?'active':''} onClick={()=>go(index)} aria-label={`${index+1}. ${scene.label}`} aria-current={index===active?'step':undefined}><span>{String(index+1).padStart(2,'0')}</span><b>{scene.label}</b></button>)}</nav>
 </main>;
}
