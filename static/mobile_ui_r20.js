(()=>{
'use strict';
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];

function cleanStatus(){
  const el=document.getElementById('apiStatus');
  if(!el)return;
  const raw=(el.textContent||'').trim();
  const bad=/שגיאה|מנותק|נכשל|error|failed|disconnected/i.test(raw);
  const alpaca=/alpaca/i.test(raw);
  if(!bad&&alpaca){
    el.textContent='● נתוני שוק מחוברים • Alpaca פעיל';
    el.dataset.cleaned='1';
    return;
  }
  if(!bad&&/Alpha Vantage\s*(לא מוגדר|not configured)/i.test(raw)){
    const cleaned=raw.replace(/[·•|]?\s*Alpha Vantage\s*(לא מוגדר|not configured)/ig,'').replace(/\s{2,}/g,' ').trim();
    if(cleaned)el.textContent=cleaned;
  }
}

function buildHeader(){
  const hero=$('.hero'), inner=$('.hero-inner'), title=$('.hero h1'), actions=$('.hero-actions');
  if(!hero||!inner||!title)return;
  hero.classList.add('mobile-header-r20');
  if(!title.closest('.brand-title-r20')){
    const wrap=document.createElement('div');wrap.className='brand-title-r20';
    const bull=document.createElement('span');bull.className='bull-logo-r20';bull.textContent='🐂';bull.setAttribute('aria-hidden','true');
    title.parentNode.insertBefore(wrap,title);wrap.append(bull,title);
  }
  if(!document.getElementById('headerBackR20')){
    const b=document.createElement('button');b.id='headerBackR20';b.className='header-back-r20';b.type='button';b.setAttribute('aria-label','חזרה למסך הקודם');b.textContent='‹';
    b.addEventListener('click',()=>{if(history.length>1)history.back();else if(typeof window.go==='function')window.go('home');});
    inner.prepend(b);
  }
  if(actions){
    $$('button',actions).forEach(b=>{const t=(b.textContent||'').trim();if(t==='התיק שלי'||t==='הגדרות')b.classList.add('desktop-duplicate-r20');});
  }
}

function installStyles(){
  if(document.getElementById('mobileUiR20Style'))return;
  const s=document.createElement('style');s.id='mobileUiR20Style';s.textContent=`
.brand-title-r20{display:flex;align-items:center;gap:11px}.bull-logo-r20{display:inline-grid;place-items:center;width:48px;height:48px;border-radius:14px;background:rgba(255,255,255,.14);font-size:30px;line-height:1;border:1px solid rgba(255,255,255,.2)}
.header-back-r20{display:none;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.12);color:#fff;width:42px;height:42px;min-height:42px;border-radius:12px;font-size:34px;line-height:1;cursor:pointer}
@media(max-width:760px){.mobile-header-r20 .hero-inner{display:grid;grid-template-columns:42px 1fr;align-items:start;gap:10px}.mobile-header-r20 .hero-inner>div:first-of-type{min-width:0}.header-back-r20{display:grid;place-items:center}.bull-logo-r20{width:40px;height:40px;border-radius:12px;font-size:24px}.brand-title-r20{gap:8px}.mobile-header-r20 h1{font-size:27px;margin-top:3px}.desktop-duplicate-r20{display:none!important}.mobile-header-r20 .hero-actions{grid-column:1/-1}.mobile-header-r20 .hero-actions:empty{display:none}}
`;
  document.head.appendChild(s);
}

function boot(){installStyles();buildHeader();cleanStatus();const st=document.getElementById('apiStatus');if(st)new MutationObserver(cleanStatus).observe(st,{childList:true,subtree:true,characterData:true});}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
