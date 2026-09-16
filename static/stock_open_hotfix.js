(()=>{'use strict';
/* Root fix: the legacy app keeps longData/dayData/openDetail in top-level lexical scope, not on window. Expose the real references once, then use ONE delegated click handler. */
try{
  if(typeof longData!=='undefined') window.longData=longData;
  if(typeof dayData!=='undefined') window.dayData=dayData;
  if(typeof openDetail==='function') window.openDetail=openDetail;
  if(typeof go==='function') window.go=go;
}catch(e){console.warn('stock bridge init',e)}
function tickerFromRow(el){const s=el?.querySelector('strong')?.textContent||'';return String(s).trim().toUpperCase().match(/[A-Z.]{1,8}/)?.[0]||''}
function open(type,ticker){
  ticker=String(ticker||'').trim().toUpperCase(); if(!ticker)return;
  try{
    if(type==='day' && typeof dayData!=='undefined' && Array.isArray(window.dayData) && window.dayData!==dayData){dayData.splice(0,dayData.length,...window.dayData)}
    if(type==='long' && typeof longData!=='undefined' && Array.isArray(window.longData) && window.longData!==longData){longData.splice(0,longData.length,...window.longData)}
    if(typeof openDetail==='function') return openDetail(type,ticker);
  }catch(e){console.error('open stock failed',ticker,e)}
}
window.smartOpenStock=open;
document.addEventListener('click',e=>{
  const row=e.target.closest('#v5Day .v5-row,#v5LongList .v5-row'); if(!row)return;
  e.preventDefault();e.stopImmediatePropagation();
  open(row.closest('#v5Day')?'day':'long',tickerFromRow(row));
},true);
})();