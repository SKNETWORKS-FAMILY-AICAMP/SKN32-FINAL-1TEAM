import React,{useState} from 'react';
import {Brand,Icon} from './Icons.jsx';
import {UserPill} from './Login.jsx';
import {NotificationBell} from '../features/Workflow.jsx';
import LandingDepthGallery from './LandingDepthGallery.jsx';
export default function Landing({onStart,user,isAdmin,onOpenAdmin,onMyPage,onLogin,onLogout,notifyEnabled,onToggleNotify,onOpenProject}){
 const [tab,setTab]=useState(0);
 const [activeScene,setActiveScene]=useState(0);
 const [menuOpen,setMenuOpen]=useState(false);
 return <div className="landing"><header className="site-nav"><div className="site-container nav-inner"><Brand onClick={()=>setActiveScene(0)}/><nav aria-label="주 메뉴"><a href="#how" onClick={e=>{e.preventDefault();setActiveScene(1)}}>서비스 소개</a><a href="#outputs" onClick={e=>{e.preventDefault();setActiveScene(2)}}>결과물 보기</a><a href="#faq" onClick={e=>{e.preventDefault();setActiveScene(3)}}>자주 묻는 질문</a></nav>{user&&<NotificationBell enabled={notifyEnabled} onToggle={onToggleNotify} onOpenProject={onOpenProject} refreshKey="landing"/>}{user?<div className="relative flex-shrink-0"><button aria-haspopup="menu" aria-expanded={menuOpen} onClick={()=>setMenuOpen(v=>!v)} className="flex items-center gap-1 rounded-full pr-1.5 hover:bg-[var(--muted)]"><UserPill user={user}/><Icon name="chevron" size={14} className={'text-[var(--muted-fg)] transition-transform duration-150 '+(menuOpen?'rotate-90':'')}/></button>{menuOpen&&<><div className="fixed inset-0 z-40" onClick={()=>setMenuOpen(false)} aria-hidden="true"/><div role="menu" className="absolute right-0 top-full mt-2 z-50 min-w-[132px] rounded-xl border border-[var(--border)] bg-white py-1 shadow-[0_12px_32px_-12px_rgba(15,23,42,.35)]">{isAdmin&&<button role="menuitem" onClick={()=>{setMenuOpen(false);onOpenAdmin()}} className="flex w-full items-center gap-2 whitespace-nowrap px-3 py-2 text-[13.5px] text-[var(--fg)] hover:bg-[var(--muted)]"><Icon name="grid" size={16}/>관리자 화면</button>}<button role="menuitem" onClick={()=>{setMenuOpen(false);onMyPage()}} className="flex w-full items-center gap-2 whitespace-nowrap px-3 py-2 text-[13.5px] text-[var(--fg)] hover:bg-[var(--muted)]"><Icon name="file" size={16}/>마이페이지</button><button role="menuitem" onClick={()=>{setMenuOpen(false);onLogout()}} className="flex w-full items-center gap-2 whitespace-nowrap px-3 py-2 text-[13.5px] text-[var(--fg)] hover:bg-[var(--muted)]"><Icon name="logout" size={16}/>로그아웃</button></div></>}</div>:<button className="flex-shrink-0 text-[13.5px] font-semibold text-[var(--muted-fg)] hover:text-[var(--fg)]" onClick={onLogin}>로그인</button>}<button className="btn small flex-shrink-0" onClick={onStart}>시작하기</button></div></header><LandingDepthGallery onStart={onStart} tab={tab} setTab={setTab} active={activeScene} setActive={setActiveScene}/></div>
}

// 로그인한 계정이 마이페이지를 저장(완료)하기 전까지, 마이페이지가 아닌 다른 화면으로
// 갈 때마다 이 위에 뜬다(App.jsx의 onboarded 게이트). 닫기·바깥 클릭이 전혀 없다 — 자기
// 정보를 저장하기 전까진 예외 없이 이 화면으로 돌아오게 하려는 것.
export function MyPageNudge({open,onGo}){
 if(!open)return null;
 return <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
  <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" aria-hidden="true"/>
  <div role="dialog" aria-modal="true" aria-labelledby="mypage-nudge-title" className="relative w-full max-w-lg rounded-3xl bg-white p-12 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)] text-center">
   <span className="inline-flex items-center justify-center w-20 h-20 rounded-2xl mb-6 bg-[var(--primary)]"><img src="/symbol-white.png" alt="" className="w-16 h-auto"/></span>
   <h2 id="mypage-nudge-title" className="font-extrabold text-[26px] leading-snug">내 정보를 입력하면<br/>더 좋은 공고매칭을 해드려요</h2>
   <p className="text-[16px] text-[var(--muted-fg)] mt-3 leading-relaxed">대표자 정보·사업자등록번호·보유 인증 같은 항목을 마이페이지에 미리 채워두면 자격 확인과 공고 추천이 더 정확해져요.</p>
   <button onClick={onGo} className="w-full mt-8 rounded-xl bg-[var(--primary)] text-white py-4 text-[16.5px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">마이페이지에서 정보 입력하기</button>
  </div>
 </div>;
}
