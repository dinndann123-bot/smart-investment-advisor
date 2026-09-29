// Canonical production UI loader r18.
// One shell owns layout; canonical theme loads last so legacy light styles cannot override it.
(function(){
'use strict';
const BUILD='20260918-r18';
function addCss(href){if(document.querySelector('link[data-smart-ui-css="'+href+'"]'))return;const l=document.createElement('link');l.rel='stylesheet';l.href=href+'?v='+BUILD;l.dataset.smartUiCss=href;document.head.appendChild(l)}
function loadScript(src){return new Promise((resolve,reject)=>{const existing=document.querySelector('script[data-smart-ui-src="'+src+'"]');if(existing){if(existing.dataset.loaded==='1')return resolve();existing.addEventListener('load',resolve,{once:true});existing.addEventListener('error',reject,{once:true});return}const s=document.createElement('script');s.src=src+'?v='+BUILD;s.async=false;s.dataset.smartUiSrc=src;s.dataset.smartUiModule='1';s.addEventListener('load',()=>{s.dataset.loaded='1';resolve()},{once:true});s.addEventListener('error',()=>reject(new Error('UI module failed: '+src)),{once:true});document.head.appendChild(s)})}
async function boot(){
  // Base component geometry first, approved black/gold palette LAST so it wins the cascade.
  addCss('/static/app_shell_v5.css');
  addCss('/static/canonical_black_gold.css');
  try{
    await loadScript('/static/chart_ui_v2.js');
    if(!window.marketChart)throw new Error('canonical chart engine unavailable');
    // Install the symbol-based detail handler before dashboard taps are wired.
    await loadScript('/static/stock_detail_v7.js');
    await loadScript('/static/app_shell_v5_core.js');
    await loadScript('/static/stock_detail_rebuild_v8.js');
    await loadScript('/static/chart_shell_bridge_v1.js');
    await loadScript('/static/stock_strategy_r13.js');
    await loadScript('/static/strategy_learning_r15.js');
    document.documentElement.dataset.smartUi='r18';
    document.documentElement.dataset.dashboardOwner='professional-shell';
    window.dispatchEvent(new CustomEvent('smart-ui-ready',{detail:{build:BUILD,chart:'v8',dashboard:'professional-shell'}}));
  }catch(err){console.error('[smart-ui] boot failed',err);document.documentElement.dataset.smartUi='error'}
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();