import React,{useEffect,useState} from 'react';
import {Icon} from './Icons.jsx';
// progress를 넘기면(서버 진행률 0~100) 그 값으로 그리고, 안 넘기면 데모 타이머로 흉내 낸다.
// onLeave가 있으면 기다리는 동안 다른 화면으로 나갈 수 있다 — 생성은 서버에서 계속 돈다.
export default function Preparation({kind='plan',onComplete,compact=false,progress,onLeave}){
 const controlled=progress!==undefined;
 const [timerStage,setStage]=useState(0);
 const [reduce,setReduce]=useState(false);
 const descriptions={match:{title:'잘 맞는 공고를 찾고 있어요',done:'맞는 공고를 찾았어요',subtitle:'아이템과 신청 조건을 함께 살펴보고 있어요.',rows:['아이템의 지원 분야 확인','신청 가능한 공고 확인','추천할 공고 정리'],button:'매칭 결과 보기',object:'맞춤 공고'},plan:{title:'생각을 계획으로 옮기고 있어요',done:'사업계획서가 준비됐어요',subtitle:'선택한 공고의 작성 기준에 맞추고 있어요.',rows:['아이템과 공고 기준 연결','사업계획서·표·그래프 작성','내용과 근거 점검'],button:'계획서 확인하기',object:'사업계획서'},artifact:{title:'직접 보여줄 수 있게 만들어요',done:'프로토타입이 준비됐어요',subtitle:'사업계획서와 이어지는 결과물을 준비하고 있어요.',rows:compact?['핵심 내용 정리','인포그래픽 제작','결과물 확인']:['핵심 화면과 기능 구성','프로토타입·인포그래픽 제작','사업계획서와 결과물 확인'],button:'산출물 확인하기',object:compact?'인포그래픽':'프로토타입'}};
 const d=descriptions[kind];
 const stage=controlled?((progress??0)>=100?3:Math.min(2,Math.floor((progress??0)/34))):timerStage;
 const done=stage>=3;const percent=controlled?Math.max(0,Math.min(100,progress??0)):[12,42,76,100][Math.min(stage,3)];
 useEffect(()=>{if(controlled)return;const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;setReduce(reduced);if(reduced){setStage(3);return;}if(timerStage>=3)return;const t=setTimeout(()=>setStage(s=>s+1),1600);return()=>clearTimeout(t)},[timerStage,controlled]);
 useEffect(()=>{if(kind==='match'&&done){const t=setTimeout(onComplete,700);return()=>clearTimeout(t)}},[kind,done,onComplete]);
 return <section className={'preparation '+(done?'is-done':'')+(reduce?' reduced':'')}><div className="preparation-heading"><p>{d.object} 준비</p><h1>{done?d.done:d.title}</h1><span>{done?'준비된 내용을 확인해 주세요.':d.subtitle}</span></div><div className="preparation-stage"><div className="preparation-count" role="progressbar" aria-label={d.object+' 준비 진행률'} aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>{done?<span className="preparation-done"><Icon name="check" size={45}/></span>:<><strong key={percent}>{percent}</strong><span>%</span></>}</div><div className="preparation-status" role="status" aria-live="polite">{done?'준비 완료':d.rows[stage]}</div><ol className="preparation-rows">{d.rows.map((row,i)=><li key={row} className={stage>i?'finished':stage===i?'working':''}><span className="preparation-row-icon">{stage>i?<Icon name="check" size={17}/>:<Icon name={kind==='match'?'search':kind==='plan'?'file':'code'} size={18}/>}</span><span>{row}</span><small>{stage>i?'완료':stage===i?'진행 중':'대기'}</small></li>)}</ol></div>{done?<button className="btn preparation-action" onClick={onComplete}>{d.button}</button>:onLeave?<div className="preparation-leave"><p className="preparation-caption">시간이 조금 걸릴 수 있어요. 다른 화면으로 이동해도 계속 만들어지고, 끝나면 알림으로 알려드려요.</p><button type="button" className="btn btn-muted preparation-action" onClick={onLeave}>다른 작업 하고 올게요</button></div>:<p className="preparation-caption">잠시만 기다려 주세요. 이 화면은 생성 과정을 보여주는 데모예요.</p>}</section>
}
