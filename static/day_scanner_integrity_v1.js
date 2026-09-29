(()=>{
'use strict';
let lastAcceptedScanId=null;
function clearDay(reason){
  try{dayData=[];renderTables();renderHome();}catch(e){}
  const st=document.getElementById('scannerStatus');
  if(st){st.textContent=reason||'הסריקה אינה מסונכרנת';st.className='live-badge live-error';}
}
function validPayload(j){
  if(!j||!j.scan_id||!Array.isArray(j.results)||j.results.length!==10)return false;
  const seen=new Set();
  for(let i=0;i<10;i++){
    const x=j.results[i];
    if(!x||!x.ticker||seen.has(x.ticker))return false;
    seen.add(x.ticker);
    if(x.scan_id&&x.scan_id!==j.scan_id)return false;
  }
  return true;
}
async function strictRefreshDayScanner(manual=false){
  if(scannerBusy)return;
  scannerBusy=true;
  const st=document.getElementById('scannerStatus');
  if(st){st.textContent='סורק את השוק...';st.className='live-badge live-delayed';}
  try{
    const r=await fetch('/api/scanner/day?top=10&candidates=40',{cache:'no-store'});
    const j=await r.json();
    if(!r.ok)throw new Error(j.detail||'Scanner error');
    if(!validPayload(j)){
      clearDay('הסריקה אינה מסונכרנת — לא מוצגות מניות ישנות');
      console.error('DAY_TOP10_INTEGRITY_FAIL',j?.scan_id,j?.results?.length);
      return;
    }
    dayData=j.results.map((x,i)=>({...x,scanner_rank:i+1,canonical_scan_id:j.scan_id,name:x.name||x.ticker,summary:`RVOL ${Number.isFinite(+x.rvol)?(+x.rvol).toFixed(2)+'×':'—'} · ${x.news_count||0} חדשות`}));
    lastAcceptedScanId=j.scan_id;
    renderTables();renderHome();loadLivePerformance(false);
    if(st){
      st.textContent=`מסונכרן 10/10 · ${j.feed||'—'} · ${new Date(j.generated_at).toLocaleTimeString('he-IL')}`;
      st.className='live-badge live-on';
      st.title=`scan_id: ${j.scan_id}`;
    }
    console.info('DAY_TOP10_INTEGRITY_OK',j.scan_id,dayData.map(x=>x.ticker).join(','));
  }catch(e){
    clearDay('שגיאת סריקה — הרשימה הקודמת הוסרה');
    if(st)st.title=e.message||String(e);
  }finally{scannerBusy=false;}
}
window.refreshDayScanner=strictRefreshDayScanner;
window.dayScannerIntegrity={version:'1.0',getScanId:()=>lastAcceptedScanId,validate:validPayload};
console.info('DAY_SCANNER_INTEGRITY_V1_INSTALLED');
})();
