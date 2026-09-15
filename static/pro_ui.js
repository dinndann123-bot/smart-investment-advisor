(()=>{
'use strict';
const q=s=>document.querySelector(s);
const GOLD='#e7b84b';
function bullSvg(){return `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M8 18c6 0 10 2 14 7 3-7 8-11 15-11 8 0 14 4 17 11 2 5 2 11 0 17-2 6-7 10-13 12l-4-8c5-2 8-5 9-9 1-4 0-8-3-11-3-3-7-4-11-2-5 2-8 7-8 13v13h-9V35c0-6-2-10-7-13V18Z" fill="${GOLD}"/><path d="M13 16 5 9l2 12m43-5 8-7-2 12" fill="none" stroke="${GOLD}" stroke-width="4" stroke-linecap="round"/><path d="M30 44c7-1 13-5 19-12" fill="none" stroke="${GOLD}" stroke-width="3" stroke-linecap="round"/><path d="m43 31 7 1-2-7" fill="none" stroke="${GOLD}" stroke-width="3" stroke-linecap="round"/></svg>`}
function installBrand(){
 const hero=q('.hero-inner'); if(!hero||q('.brand-lockup'))return;
 const first=hero.firstElementChild;if(!first)return;
 const wrap=document.createElement('div');wrap.className='brand-lockup';
 const mark=document.createElement('div');mark.className='brand-mark';mark.setAttribute('aria-label','סמל שור וגרף עולה');mark.innerHTML=bullSvg();
 const copy=document.createElement('div');copy.className='brand-copy';
 while(first.firstChild)copy.appendChild(first.firstChild);
 first.append(mark,copy);first.classList.add('brand-lockup');
}
function mobileHeader(){
 document.querySelectorAll('.hero-actions button').forEach(b=>{const t=(b.textContent||'').trim();if(t.includes('התיק שלי')||t.includes('הגדרות'))b.classList.add('mobile-duplicate')});
 const hero=q('.hero-inner');if(!hero||q('.header-back-pro'))return;
 const back=document.createElement('button');back.className='header-back-pro';back.type='button';back.setAttribute('aria-label','חזרה');back.textContent='‹';
 back.onclick=()=>{const active=q('.page.active');if(active&&active.id!=='page-home'){if(typeof window.go==='function')window.go('home');else history.back()}else history.back()};
 hero.prepend(back);
 const refresh=()=>{const active=q('.page.active');back.style.display=(innerWidth<=760&&active&&active.id!=='page-home')?'grid':'none'};
 document.addEventListener('click',e=>{if(e.target.closest('[data-page],button[onclick*="go("]'))setTimeout(refresh,0)});window.addEventListener('resize',refresh);refresh();
}
async function cleanMarketStatus(){
 const el=q('#apiStatus');if(!el)return;
 try{
   const r=await fetch('/api/runtime-health',{cache:'no-store'});if(!r.ok)throw new Error('health');const j=await r.json();
   if(j.alpaca_configured){el.textContent='● נתוני שוק מחוברים • Alpaca פעיל';el.classList.add('api-connected');el.classList.remove('api-error')}
   else{el.textContent='● נתוני שוק לא מחוברים • יש לבדוק Alpaca';el.classList.add('api-error');el.classList.remove('api-connected')}
 }catch(_){el.textContent='● לא ניתן לאמת כרגע את חיבור נתוני השוק';el.classList.add('api-error');el.classList.remove('api-connected')}
}
function scoreLanguage(){
 document.querySelectorAll('.score').forEach(x=>x.setAttribute('title','ציון התאמה לשיטה — אינו הסתברות לרווח'));
}
function boot(){installBrand();mobileHeader();scoreLanguage();cleanMarketStatus();setInterval(cleanMarketStatus,120000)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
