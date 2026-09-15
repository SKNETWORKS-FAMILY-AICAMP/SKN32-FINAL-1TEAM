import React,{useState,useRef,useEffect} from 'react';
import {Icon} from './Icons.jsx';
import {api,ApiError} from '../api.js';

const GOOGLE_CLIENT_ID=import.meta.env.VITE_GOOGLE_CLIENT_ID;

// Decoded only to show the name/email — the backend must verify the token's signature.
function decodeIdToken(token){
  const b64=token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/');
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(b64),c=>c.charCodeAt(0))));
}

// The GSI script loads async, so the modal can open before window.google exists.
function whenGoogleReady(cb){
  if(window.google?.accounts?.id){cb();return()=>{}}
  const script=document.getElementById('google-gsi');
  script?.addEventListener('load',cb);
  return()=>script?.removeEventListener('load',cb);
}

function StepMethod({onCredential}){
  const btnRef=useRef(null);
  const cbRef=useRef(onCredential);
  cbRef.current=onCredential;
  useEffect(()=>{
    if(!GOOGLE_CLIENT_ID)return;
    return whenGoogleReady(()=>{
      window.google.accounts.id.initialize({client_id:GOOGLE_CLIENT_ID,callback:r=>cbRef.current(r.credential)});
      window.google.accounts.id.renderButton(btnRef.current,{theme:'outline',size:'large',text:'continue_with',shape:'rectangular',locale:'ko',width:btnRef.current.offsetWidth});
    });
  },[]);
  return (
    <React.Fragment>
      <p className="font-extrabold text-[14px] text-[var(--primary)] text-center mb-2">S-Brain</p>
      <h2 id="login-title" className="text-center font-extrabold text-[20px] mb-2">시작하려면 로그인하세요</h2>
      <p className="text-center text-[13.5px] text-[var(--muted-fg)] mb-7">구글 계정 하나면 충분합니다</p>
      {GOOGLE_CLIENT_ID
        ?<div ref={btnRef} className="flex justify-center min-h-[44px]"/>
        :<p className="rounded-xl bg-[var(--muted)] px-4 py-3 text-[13px] text-[var(--muted-fg)] text-center leading-relaxed">구글 로그인 설정이 필요해요<br/>front/.env에 VITE_GOOGLE_CLIENT_ID를 넣어 주세요</p>}
      <p className="mt-6 text-[11.5px] text-[var(--muted-fg)] leading-relaxed">
        로그인 시 이메일과 프로필 이름(필수)을 수집하며 회원 탈퇴 시까지 보관합니다.
        계속 진행하면 개인정보 수집·이용에 동의하는 것으로 간주합니다.
      </p>
    </React.Fragment>
  );
}

function StepSuccess({account}){
  return (
    <div className="text-center py-4">
      <span className="inline-flex items-center justify-center w-14 h-14 rounded-full mb-4 bg-[color-mix(in_srgb,var(--primary)_12%,white)] text-[var(--primary)]"><Icon name="check" size={28}/></span>
      <h2 id="login-title" className="font-extrabold text-[18px]">{account?`${account.name}님 환영해요`:'로그인되었어요'}</h2>
      <p className="text-[13px] text-[var(--muted-fg)] mt-1">잠시 후 S-Brain으로 돌아갑니다…</p>
    </div>
  );
}

function StepLoading(){
  return (
    <div className="text-center py-10">
      <span className="inline-block w-6 h-6 rounded-full border-2 border-[var(--muted)] border-t-[var(--primary)] animate-spin"/>
      <p className="text-[13px] text-[var(--muted-fg)] mt-4">로그인 확인 중…</p>
    </div>
  );
}

function StepError({message,onRetry}){
  return (
    <div className="text-center py-4">
      <span className="inline-flex items-center justify-center w-14 h-14 rounded-full mb-4 bg-[color-mix(in_srgb,#dc2626_10%,white)] text-[#dc2626]"><Icon name="close" size={28}/></span>
      <h2 id="login-title" className="font-extrabold text-[18px]">로그인에 실패했어요</h2>
      <p className="text-[13px] text-[var(--muted-fg)] mt-1 leading-relaxed">{message}</p>
      <button onClick={onRetry} className="w-full mt-6 rounded-xl bg-[var(--primary)] text-white py-3 text-[14.5px] font-semibold hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">다시 시도하기</button>
    </div>
  );
}

// 최초 로그인 시 이용약관·개인정보 수집이용은 필수 동의, 학습데이터 편입·알림 수신은
// 선택 동의로 분리한다. 구글 인증이 끝난 뒤(=구글의 몫은 여기서 끝) S-Brain 자체
// 동의를 받는 단계라, 구글 화면이 아니라 우리 사이트 자체의 작은 카드로 되돌아온다.
const CONSENT_TERMS={
  terms:{title:'이용약관',body:[
    '제1조(목적) 이 약관은 S-Brain(이하 "회사")이 제공하는 정부지원사업 매칭·사업계획서 및 프로토타입 생성 서비스(이하 "서비스")의 이용과 관련하여 회사와 이용자의 권리·의무 및 책임사항을 정함을 목적으로 합니다.',
    '제2조(서비스의 제공) 회사는 이용자가 입력한 정보를 바탕으로 공고 매칭, 사업계획서 초안 작성, 프로토타입 생성을 지원합니다. 생성된 결과물은 초안이며 제출 전 이용자 본인의 확인과 수정이 필요합니다.',
    '제3조(이용자의 의무) 이용자는 서비스 이용 시 정확한 정보를 제공해야 하며, 생성된 문서를 관계 법령 및 공고 요건에 맞게 검토할 책임이 있습니다.',
  ]},
  privacy:{title:'개인정보 수집·이용 동의',body:[
    '수집 항목: 이메일, 프로필 이름, 사업 아이템 정보, 첨부 문서에서 추출한 텍스트',
    '수집 목적: 계정 식별, 공고 매칭, 사업계획서·프로토타입 생성 및 이력 보관',
    '보유 기간: 회원 탈퇴 시까지 보관하며, 탈퇴 시 지체 없이 파기합니다. 첨부 원본 파일은 텍스트 추출 직후 즉시 파기됩니다.',
    '이용자는 개인정보 수집·이용에 동의하지 않을 권리가 있으나, 이 경우 서비스 이용이 제한될 수 있습니다.',
  ]},
  ai:{title:'서비스 개선을 위한 학습 데이터 활용 동의',body:[
    '이용자가 생성한 사업계획서·프로토타입 및 그에 대한 평가 결과는 익명화 처리 후 서비스 품질 개선을 위한 모델 학습에 활용될 수 있습니다.',
    '동의는 언제든 철회할 수 있으나, 철회 이전에 이미 학습에 반영된 데이터는 되돌릴 수 없습니다.',
  ]},
  notify:{title:'유사 공고 알림 수신 동의',body:[
    '이용자가 등록한 아이템과 유사한 정부지원사업 공고가 새로 게시되면 이메일 또는 서비스 내 알림으로 안내해 드립니다.',
    '동의는 언제든 설정에서 철회할 수 있습니다.',
  ]},
};

function StepConsent({onAgree}){
  const [termsAgreed,setTermsAgreed]=useState(false);
  const [privacyAgreed,setPrivacyAgreed]=useState(false);
  const [aiTrainingAgreed,setAiTrainingAgreed]=useState(false);
  const [notifyAgreed,setNotifyAgreed]=useState(false);
  const [expandedTerm,setExpandedTerm]=useState(null);
  const requiredOk=termsAgreed&&privacyAgreed;
  const allChecked=termsAgreed&&privacyAgreed&&aiTrainingAgreed&&notifyAgreed;
  const toggleAll=checked=>{setTermsAgreed(checked);setPrivacyAgreed(checked);setAiTrainingAgreed(checked);setNotifyAgreed(checked)};
  // "보기" 링크는 <label> 안에 있어 그냥 두면 클릭이 체크박스 토글로도 번진다 —
  // preventDefault로 label의 기본 동작(연결된 input에 클릭 전달)을 막는다.
  const toggleView=key=>e=>{e.preventDefault();setExpandedTerm(prev=>prev===key?null:key)};
  const ConsentRow=({termKey,checked,onChange,tag,tagTone,label})=>(
    <div className="border-b border-[var(--border)] last:border-b-0">
      <label className="flex items-center gap-2.5 py-1.5 text-[13.5px] cursor-pointer select-none">
        <input type="checkbox" checked={checked} onChange={e=>onChange(e.target.checked)} className="w-4 h-4 accent-[var(--primary)]"/>
        <span className="flex-1"><span className={'font-semibold '+tagTone}>{tag}</span> {label}</span>
        <button type="button" onClick={toggleView(termKey)} className="text-[12px] text-[var(--muted-fg)] underline underline-offset-2 hover:text-[var(--fg)]">{expandedTerm===termKey?'닫기':'보기'}</button>
      </label>
      {expandedTerm===termKey&&<div className="soft-scroll mb-2 max-h-32 overflow-y-auto rounded-lg bg-[var(--bg)] border border-[var(--border)] p-3 text-[12px] leading-relaxed text-[var(--muted-fg)] space-y-2">{CONSENT_TERMS[termKey].body.map((p,i)=><p key={i}>{p}</p>)}</div>}
    </div>
  );
  return (
    <React.Fragment>
      <p className="font-extrabold text-[14px] text-[var(--primary)] text-center mb-2">S-Brain</p>
      <h2 id="login-title" className="text-center font-extrabold text-[20px] mb-2">약관 동의가 필요합니다</h2>
      <p className="text-center text-[13.5px] text-[var(--muted-fg)] mb-6">작성한 계획서·프로토타입을 계정에 보관하고 이어서 진행하려면 아래 약관에 동의해주세요</p>
      <label className="flex items-center gap-2.5 py-2 border-b border-[var(--border)] mb-2 text-[14px] font-bold cursor-pointer select-none">
        <input type="checkbox" checked={allChecked} onChange={e=>toggleAll(e.target.checked)} className="w-4 h-4 accent-[var(--primary)]"/>
        전체 동의
      </label>
      <div className="flex flex-col">
        <ConsentRow termKey="terms" checked={termsAgreed} onChange={setTermsAgreed} tag="[필수]" tagTone="text-[var(--primary)]" label="이용약관 동의"/>
        <ConsentRow termKey="privacy" checked={privacyAgreed} onChange={setPrivacyAgreed} tag="[필수]" tagTone="text-[var(--primary)]" label="개인정보 수집·이용 동의"/>
        <ConsentRow termKey="ai" checked={aiTrainingAgreed} onChange={setAiTrainingAgreed} tag="[선택]" tagTone="text-[var(--muted-fg)]" label="서비스 개선을 위한 학습 데이터 활용 동의"/>
        <ConsentRow termKey="notify" checked={notifyAgreed} onChange={setNotifyAgreed} tag="[선택]" tagTone="text-[var(--muted-fg)]" label="유사 공고 알림 수신 동의"/>
      </div>
      <p className="mt-3 text-[11.5px] text-[var(--muted-fg)] leading-relaxed">선택 동의는 이후 언제든 철회할 수 있습니다. 다만 철회 전 이미 학습에 반영된 데이터는 되돌릴 수 없습니다.</p>
      <button onClick={()=>onAgree({aiTrainingAgreed,notifyAgreed})} disabled={!requiredOk}
        className="w-full mt-6 rounded-xl bg-[var(--primary)] text-white py-3 text-[14.5px] font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[var(--primary-dim)] transition-[background-color,scale] duration-150 ease-out active:scale-[0.98]">동의하고 계속하기</button>
      {!requiredOk&&<p className="mt-2 text-[12px] text-[var(--muted-fg)] text-center">필수 항목에 모두 동의해야 계속할 수 있어요</p>}
    </React.Fragment>
  );
}

export function UserPill({user}){
  return (
    <div className="flex items-center gap-2 pl-1 pr-3 py-1 rounded-full bg-[var(--muted)]">
      <span className="w-6 h-6 rounded-full bg-[var(--primary)] text-white flex items-center justify-center text-[11px] font-semibold flex-shrink-0">{user.name[0].toUpperCase()}</span>
      <span className="text-[13px] font-medium max-w-[110px] truncate">{user.name}</span>
    </div>
  );
}

export function LoginModal({open,onClose,onSuccess}){
  const dialogRef=useRef(null);
  const closeBtnRef=useRef(null);
  const [step,setStep]=useState('method'); // 'method' | 'consent' | 'success' | 'error'
  const [account,setAccount]=useState(null);
  const [errorMsg,setErrorMsg]=useState('');
  // 약관 동의는 "최초 로그인 시"만 받는다 — 이 세션에서 이미 한 번 동의했다면
  // (로그아웃 후 재로그인 등) 다시 묻지 않고 바로 완료 처리한다. id_token은 백엔드
  // 검증(POST /auth/google)에 실제로 보내야 하니 credential 자체도 같이 들고 있는다.
  const [hasAgreedBefore,setHasAgreedBefore]=useState(false);
  const [lastConsent,setLastConsent]=useState({aiTrainingAgreed:false,notifyAgreed:true});
  const credentialRef=useRef(null);

  useEffect(()=>{if(!open)return;setStep('method');setAccount(null);setErrorMsg('')},[open]);

  // 실제 인증은 여기서 끝난다 — id_token을 백엔드로 보내 서명 검증 + 세션 쿠키 발급을
  // 받고, 화면엔 그 결과(UserOut, role 포함)를 반영한다. 로컬 디코드값은 표시용일 뿐이다.
  const finishLogin=async(consent)=>{
    setStep('loading');
    try{
      const res=await api.post('/auth/google',{
        id_token:credentialRef.current,
        ai_training_agreed:consent.aiTrainingAgreed,
        notify_agreed:consent.notifyAgreed,
      });
      setLastConsent(consent);setHasAgreedBefore(true);
      setAccount(res.user);setStep('success');
      onSuccess(res.user,consent);
    }catch(e){
      const msg=e instanceof ApiError?(typeof e.detail==='string'?e.detail:'로그인에 실패했어요'):'서버에 연결할 수 없어요';
      setErrorMsg(msg);setStep('error');
    }
  };
  const handleCredential=credential=>{
    credentialRef.current=credential;
    const {name,email,picture}=decodeIdToken(credential);
    const acc={name:name||email.split('@')[0],email,picture};
    setAccount(acc);
    if(hasAgreedBefore){finishLogin(lastConsent);return}
    setStep('consent');
  };

  useEffect(()=>{
    if(!open)return;
    closeBtnRef.current&&closeBtnRef.current.focus();
    const onKey=e=>{
      if(e.key==='Escape'){onClose();return}
      if(e.key!=='Tab'||!dialogRef.current)return;
      // 포커스 트랩: 모달 안의 포커스 가능 요소끼리만 Tab이 순환하게 한다. 구글 버튼은 iframe이라 따로 넣는다.
      const focusables=dialogRef.current.querySelectorAll('button, a[href], iframe');
      if(focusables.length===0)return;
      const first=focusables[0];const last=focusables[focusables.length-1];
      if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
      else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
    };
    window.addEventListener('keydown',onKey);
    return ()=>window.removeEventListener('keydown',onKey);
  },[open,step,onClose]);

  useEffect(()=>{
    if(step!=='success')return;
    const t=setTimeout(onClose,1400);
    return ()=>clearTimeout(t);
  },[step,onClose]);

  if(!open)return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <div className="absolute inset-0 bg-[var(--fg)]/40 backdrop-blur-sm" onClick={onClose} aria-hidden="true"></div>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="login-title" className="relative w-full max-w-md rounded-2xl bg-white p-8 shadow-[0_24px_64px_-24px_rgba(15,23,42,.4)]">
        <button ref={closeBtnRef} onClick={onClose} aria-label="닫기" className="absolute top-4 right-4 text-[var(--muted-fg)] hover:text-[var(--fg)] transition-[color,scale] duration-150 ease-out active:scale-[0.96]">
          <Icon name="close" size={20}/>
        </button>
        {step==='method'&&<StepMethod onCredential={handleCredential}/>}
        {step==='consent'&&<StepConsent onAgree={finishLogin}/>}
        {step==='loading'&&<StepLoading/>}
        {step==='success'&&<StepSuccess account={account}/>}
        {step==='error'&&<StepError message={errorMsg} onRetry={()=>setStep('method')}/>}
      </div>
    </div>
  );
}
