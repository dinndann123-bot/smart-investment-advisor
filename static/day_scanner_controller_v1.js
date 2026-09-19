(()=>{'use strict';
const ENDPOINT='/api/scanner/day?top=10&candidates=40';
let active=null,seq=0;
const state={status:'idle',error:null,scanId:null,generatedAt:null,count:0,integrity:false};
function emit(detail={}){window.__V5_DAY_SCAN_STATE__={...state,...detail};window.dispatchEvent(new CustomEvent('smartadvisor:day-scan',{detail:window.__V5_DAY_SCAN_STATE__}))}
function normalize(x,i,scanId){const change=Number.isFinite(+x.change)?+x.change:Number.isFinite(+x.change_pct)?+x.change_pct:null;return{...x,ticker:x.ticker.trim().toUpperCase(),change,change_pct:change,scanner_rank:i+1,canonical_scan_id:scanId}}
function validate(j){
 if(!j||typeof j.scan_id!=='string'||!j.scan_id.trim())return 'scan_id missing';
 if(!Array.isArray(j.results)||j.results.length!==10)return `expected 10 results, got ${Array.isArray(j?.results)?j.results.length:'none'}`;
 const seen=new Set();
 for(let i=0;i<10;i++){
  const x=j.results[i];const t=String(x?.ticker||'').trim().toUpperCase();
  if(!t)return `ticker missing at rank ${i+1}`;
  if(seen.has(t))return `duplicate ticker ${t}`;seen.add(t);
  if(x.breakout_stage==='already_extended'||x.candidate_type==='learning_observation')return `non-predictive row ${t}`;
  if(x.scan_id&&x.scan_id!==j.scan_id)return `scan_id mismatch ${t}`;
 }
 return null;
}
function invalidate(message){
 window.dayData=[];
 state.status='error';state.error=message;state.scanId=null;state.generatedAt=null;state.count=0;state.integrity=false;
 window.__V5_DAY_SCAN_PAYLOAD__=null;emit({integrity_error:message});
 console.error('DAY_TOP10_INTEGRITY_FAIL',message);
}
async function scanDay({force=false}={}){
 if(active&&!force)return active;
 const my=++seq;state.status='loading';state.error=null;state.integrity=false;emit();
 active=(async()=>{try{
  const r=await fetch(`${ENDPOINT}&t=${Date.now()}`,{cache:'no-store',headers:{'Accept':'application/json'}});
  if(!r.ok)throw new Error(`HTTP ${r.status}`);
  const j=await r.json();const err=validate(j);if(err)throw new Error(`scanner integrity: ${err}`);
  const rows=j.results.map((x,i)=>normalize(x,i,j.scan_id));
  if(my!==seq)return rows;
  // Atomic canonical ownership: UI is exactly server results[0..9], in server order, from one scan_id.
  window.dayData=rows;
  state.status='success';state.error=null;state.scanId=j.scan_id;state.generatedAt=j.generated_at||j.server_timestamp||new Date().toISOString();state.count=10;state.integrity=true;
  window.__V5_DAY_SCAN_PAYLOAD__=j;emit({payload:j,canonical_symbols:rows.map(x=>x.ticker)});
  console.info('DAY_TOP10_INTEGRITY_OK',j.scan_id,rows.map(x=>x.ticker).join(','));
  return rows;
 }catch(e){
  if(my===seq)invalidate(String(e?.message||e));
  throw e;
 }finally{if(my===seq)active=null}
 })();return active;
}
window.v5DayScanner={scan:scanDay,state:()=>({...state}),validate};
window.addEventListener('smartadvisor:request-day-scan',()=>scanDay({force:true}).catch(()=>{}));
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(()=>scanDay().catch(()=>{}),250),{once:true});else setTimeout(()=>scanDay().catch(()=>{}),250);
})();