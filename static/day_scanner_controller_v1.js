(()=>{'use strict';
const ENDPOINT='/api/scanner/day?top=10&candidates=40';
let active=null,seq=0;
const state={status:'idle',error:null,scanId:null,generatedAt:null,count:0};
function emit(detail={}){window.__V5_DAY_SCAN_STATE__={...state,...detail};window.dispatchEvent(new CustomEvent('smartadvisor:day-scan',{detail:window.__V5_DAY_SCAN_STATE__}))}
function validRow(x){return x&&typeof x==='object'&&typeof x.ticker==='string'&&x.ticker.trim()&&x.breakout_stage!=='already_extended'&&x.candidate_type!=='learning_observation'}
function normalize(x){const change=Number.isFinite(+x.change)?+x.change:Number.isFinite(+x.change_pct)?+x.change_pct:null;return{...x,ticker:x.ticker.trim().toUpperCase(),change,change_pct:change}}
async function scanDay({force=false}={}){
 if(active&&!force)return active;
 const my=++seq;
 state.status='loading';state.error=null;emit();
 active=(async()=>{try{
  const r=await fetch(`${ENDPOINT}&t=${Date.now()}`,{cache:'no-store',headers:{'Accept':'application/json'}});
  if(!r.ok)throw new Error(`HTTP ${r.status}`);
  const j=await r.json();
  if(!j||!Array.isArray(j.results))throw new Error('invalid scanner payload: results missing');
  const rows=j.results.filter(validRow).map(normalize).slice(0,10);
  if(my!==seq)return rows;
  // Atomic ownership: never mix a new scan with stale legacy rows.
  window.dayData=rows;
  state.status='success';state.error=null;state.scanId=j.scan_id||null;state.generatedAt=j.generated_at||j.server_timestamp||new Date().toISOString();state.count=rows.length;
  window.__V5_DAY_SCAN_PAYLOAD__=j;
  emit({payload:j});
  return rows;
 }catch(e){
  if(my===seq){state.status='error';state.error=String(e?.message||e);state.count=Array.isArray(window.dayData)?window.dayData.length:0;emit()}
  throw e;
 }finally{if(my===seq)active=null}
 })();
 return active;
}
window.v5DayScanner={scan:scanDay,state:()=>({...state})};
// V5 owns refreshes. Legacy code may request a scan, but it no longer owns dayData.
window.addEventListener('smartadvisor:request-day-scan',()=>scanDay({force:true}).catch(()=>{}));
// Initial canonical refresh after the shell is ready.
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(()=>scanDay().catch(()=>{}),250),{once:true});else setTimeout(()=>scanDay().catch(()=>{}),250);
})();