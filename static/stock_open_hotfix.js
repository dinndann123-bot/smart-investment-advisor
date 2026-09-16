(()=>{'use strict';
/* This file intentionally does NOT replace openDetail. The canonical detail function in index.html owns selected/dayData/longData in lexical scope. Replacing it broke every stock row because those arrays are not window properties. */
function tickerFromRow(el){const s=el?.querySelector('strong')?.textContent||'';return String(s).trim().toUpperCase().match(/[A-Z.]{1,8}/)?.[0]||''}
function bindRows(){
  document.querySelectorAll('#v5Day .v5-row').forEach(el=>{if(el.dataset.stockBound)return;el.dataset.stockBound='1';el.style.cursor='pointer';el.addEventListener('click',()=>{const t=tickerFromRow(el);if(t&&typeof window.openDetail==='function')window.openDetail('day',t)})});
  document.querySelectorAll('#v5LongList .v5-row').forEach(el=>{if(el.dataset.stockBound)return;el.dataset.stockBound='1';el.style.cursor='pointer';el.addEventListener('click',()=>{const t=tickerFromRow(el);if(t&&typeof window.openDetail==='function')window.openDetail('long',t)})});
  document.querySelectorAll('#v5Yearly .v5-year-row').forEach(el=>{if(el.dataset.stockBound)return;el.dataset.stockBound='1';el.addEventListener('click',()=>{const t=tickerFromRow(el);if(t&&typeof window.openDetail==='function')window.openDetail('long',t)})});
}
function install(){bindRows();new MutationObserver(bindRows).observe(document.body,{childList:true,subtree:true})}
if(document.readyState==='loading')window.addEventListener('DOMContentLoaded',install,{once:true});else install();
})();