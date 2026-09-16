(()=>{'use strict';
const VERSION='20260916-1838';
const loaded=new Map();
function load(src){if(loaded.has(src))return loaded.get(src);const p=new Promise((resolve,reject)=>{const s=document.createElement('script');s.src=`${src}?v=${VERSION}`;s.defer=true;s.onload=resolve;s.onerror=()=>reject(new Error('טעינת רכיב נכשלה: '+src));document.head.appendChild(s)});loaded.set(src,p);return p}
function idle(fn){if('requestIdleCallback'in window)requestIdleCallback(fn,{timeout:2500});else setTimeout(fn,900)}
// Critical shell first. Independent modules load in parallel instead of a serial chain.
load('/static/app_shell_v5_core.js').then(()=>{
  Promise.allSettled([load('/static/stock_detail_v7.js'),load('/static/stock_detail_rebuild_v8.js')]);
  idle(()=>Promise.allSettled([load('/static/market_leaders_v6.js'),load('/static/learning_dashboard_v9.js')]));
}).catch(console.error);
// OCR importer is heavy/rare: load only when the user opens or interacts with import UI.
let blinkStarted=false;function loadBlink(){if(blinkStarted)return;blinkStarted=true;load('/static/blink_import_v10.js').catch(console.error)}
document.addEventListener('click',e=>{if(e.target.closest('#imgInput,[data-open*="import"],#importModal,.import-btn,[onclick*="importModal"]'))loadBlink()},{capture:true,passive:true});
document.addEventListener('focusin',e=>{if(e.target?.id==='imgInput')loadBlink()});
})();