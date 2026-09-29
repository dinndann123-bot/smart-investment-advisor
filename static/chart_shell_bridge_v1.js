// Dashboard -> canonical marketChart bridge. Keeps chart rendering in one engine without touching strategy/data logic.
(function(){
'use strict';
const ranges=['1D','1W','1M','3M','1Y','5Y'];
const apiRange=r=>r==='1W'?'1M':r==='3M'?'1Y':r;
const filter=(bars,r)=>!Array.isArray(bars)?[]:r==='1W'?bars.slice(-7):r==='3M'?bars.slice(-66):bars;
let seq=0,timer=null;
function selectedRange(){const b=document.querySelector('#page-home .v5-ranges [data-r].on');return ranges.includes(b?.dataset?.r)?b.dataset.r:'1D'}
function ticker(){return (document.querySelector('#v5Ticker')?.textContent||'SPY').trim().toUpperCase()||'SPY'}
async function redraw(){const canvas=document.getElementById('v5Chart');if(!canvas||!window.marketChart)return;const my=++seq,s=ticker(),r=selectedRange();try{const res=await fetch(`/api/stock/${encodeURIComponent(s)}/bundle?range=${apiRange(r)}&chartv=8`,{cache:'no-store'});if(!res.ok)throw new Error(`HTTP ${res.status}`);const j=await res.json();if(my!==seq)return;const bars=filter(j.bars,r);if(bars.length<2)window.marketChart.error('v5Chart','אין מספיק נתוני שוק לטווח שנבחר');else window.marketChart.draw('v5Chart',bars);canvas.dataset.canonicalChart='v8';canvas.dataset.range=r;canvas.dataset.symbol=s;}catch(e){if(my===seq)window.marketChart.error('v5Chart','שגיאה בטעינת נתוני הגרף');}}
function schedule(ms=80){clearTimeout(timer);timer=setTimeout(redraw,ms)}
function bind(){document.addEventListener('click',e=>{if(e.target.closest('.v5-ranges [data-r]'))schedule(180)},true);const root=document.getElementById('page-home');if(root)new MutationObserver(m=>{if(m.some(x=>[...x.addedNodes].some(n=>n.nodeType===1&&(n.id==='v5Chart'||n.querySelector?.('#v5Chart')))))schedule(120)}).observe(root,{childList:true,subtree:true});window.addEventListener('resize',()=>schedule(120),{passive:true});schedule(250)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();