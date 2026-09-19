(()=>{'use strict';
const num=v=>Number.isFinite(+v);
function fit(x){if(num(x?.strategy_fit_score))return Math.round(+x.strategy_fit_score);const s=+x?.score;if(!Number.isFinite(s))return null;return Math.max(0,Math.min(99,Math.round(50+49*Math.tanh((s-65)/28))))}
function change(x){for(const k of ['change_pct','change_percent','changePercent','percent_change','pct_change','change'])if(num(x?.[k]))return +x[k];if(num(x?.price)&&num(x?.previous_close)&&+x.previous_close>0)return(+x.price/+x.previous_close-1)*100;return null}
function patchData(){if(!Array.isArray(window.dayData))return;window.dayData=window.dayData.map(x=>{const c=change(x),f=fit(x);return{...x,raw_strategy_score:num(x?.raw_strategy_score)?+x.raw_strategy_score:(num(x?.score)?+x.score:null),strategy_fit_score:f,score:f,change:c,change_pct:c,success_rate:null,score_semantics:'strategy_fit_not_success_probability'}})}
function repaint(){patchData();try{if(typeof window.renderTables==='function')window.renderTables();if(typeof window.renderHome==='function')window.renderHome()}catch(e){}window.dispatchEvent(new CustomEvent('smartadvisor:daily-card-semantics',{detail:{version:'1.0'}}))}
window.addEventListener('smartadvisor:day-scan',()=>setTimeout(repaint,0));
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(repaint,800),{once:true});else setTimeout(repaint,800);
console.info('DAY_CARD_SEMANTICS_V1_INSTALLED');
})();