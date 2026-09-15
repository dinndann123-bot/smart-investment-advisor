(()=>{
'use strict';
const ENDPOINT='/api/scanner/day?top=10&candidates=200';
const REFRESH_OPEN_MS=60000,REFRESH_CLOSED_MS=300000;
let lastFetch=0,busy=false;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot',"'":'&#39;'}[c]));
const pct=n=>Number.isFinite(+n)?((+n)>=0?'+':'')+(+n).toFixed(2)+'%':'—';
const money=n=>Number.isFinite(+n)?'$'+(+n).toFixed(2):'—';
function nyOpen(){const p=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(new Date());const o=Object.fromEntries(p.map(x=>[x.type,x.value]));const m=(+o.hour)*60+(+o.minute);return !['Sat','Sun'].includes(o.weekday)&&m>=570&&m<960;}
function rowHtml(x,i){const ch=+x.change||0,cls=ch>=0?'positive':'negative';return `<div class="top-card" data-day-sync="1" data-ticker="${esc(x.ticker)}"><span class="rank">${i+1}</span><div class="grow"><b>${esc(x.ticker)}</b><div class="small">ציון התאמה לשיטה ${esc(x.score??'—')}/100 · ${esc(x.catalyst||'סריקת שוק חיה')}</div></div><div style="text-align:left"><b>${money(x.price)}</b><div class="${cls}">${pct(ch)}</div></div></div>`;}
function findHomeDayBox(){const home=$('page-home');if(!home)return null;return [...home.querySelectorAll('.card')].find(c=>/מסחר\s*יומי|יומי/.test((c.querySelector('h2,h3,h4')?.textContent||'')))||null;}
function syncHome(rows,payload){const box=findHomeDayBox();if(!box)return;let body=box.querySelector('[data-day-sync-body]');if(!body){body=document.createElement('div');body.dataset.daySyncBody='1';[...box.children].forEach(el=>{if(!el.matches('h1,h2,h3,h4,.section-head'))el.style.display='none'});box.appendChild(body)}body.innerHTML=rows.slice(0,5).map(rowHtml).join('')+`<div class="small" style="margin-top:8px">אותו דירוג כמו בלשונית מסחר יומי · עודכן ${new Date(payload.generated_at||Date.now()).toLocaleTimeString('he-IL')} ${payload.stale?'· נתון שמור — לא חי':''}</div>`;body.querySelectorAll('[data-ticker]').forEach(el=>el.onclick=()=>{const t=el.dataset.ticker;if(window.openDetail)window.openDetail('day',t);else if(window.go)window.go('day')});}
function syncDayDom(payload){const page=$('page-day');if(!page)return;let status=$('daySyncStatusR16');if(!status){status=document.createElement('div');status.id='daySyncStatusR16';status.className='live-strip';page.prepend(status)}status.innerHTML=`<span class="live-badge ${payload.stale?'live-delayed':'live-on'}">${payload.stale?'נתון שמור':'סריקה חיה'}</span><b>Top 10 אחיד בכל האפליקציה</b><span class="small">עודכן ${new Date(payload.generated_at||Date.now()).toLocaleTimeString('he-IL')} · רענון אוטומטי ${nyOpen()?'כל דקה בזמן המסחר':'כל 5 דקות כשהשוק סגור'}</span>`;}
async function refresh(force=false){if(busy)return;const interval=nyOpen()?REFRESH_OPEN_MS:REFRESH_CLOSED_MS;if(!force&&Date.now()-lastFetch<interval)return;busy=true;try{const r=await fetch(ENDPOINT,{cache:'no-store'}),j=await r.json();const rows=Array.isArray(j?.results)?j.results.slice(0,10):[];if(r.ok&&rows.length===10){lastFetch=Date.now();syncHome(rows,j);syncDayDom(j);window.dispatchEvent(new CustomEvent('smartadvisor:day-scan',{detail:j}));}else console.warn('DAY_SYNC_TOP10_INCOMPLETE',rows.length);}catch(e){console.warn('DAY_SYNC_R16_FAIL',e)}finally{busy=false}}
function hookNavigation(){if(window.go&&!window.go.__daySync){const g=window.go;window.go=function(...a){const z=g.apply(this,a);setTimeout(()=>refresh(true),50);return z};window.go.__daySync=true}}
function boot(){hookNavigation();refresh(true);setInterval(()=>{hookNavigation();refresh(false)},30000)}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh(true)});window.addEventListener('focus',()=>refresh(true));
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
