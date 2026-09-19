(()=>{'use strict';
const $=s=>document.querySelector(s),num=v=>Number.isFinite(+v),esc=s=>String(s??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function getSummary(){const r=await fetch('/api/learning/summary?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error(r.status);return r.json()}
function pct(v){return num(v)?(+v).toFixed(1)+'%':'ממתין למדגם'}
function dashboard(j){
 const card=$('#v5Learning');if(!card)return;
 const best=(j.feature_learning||[])[0];
 card.innerHTML=`<header><h3>🧠 מעקב למידה ואימות השיטה</h3><button data-learning-open>הצג בדיקות ›</button></header>
 <div class="v5-row"><strong>אותות שנשמרו</strong><span>Journal חי</span><em>${Number(j.signals||0).toLocaleString('he-IL')}</em><span>${Number(j.universe_size||0)} מניות</span></div>
 <div class="v5-row"><strong>אותות שנבדקו</strong><span>${Number(j.evaluated||0)} הושלמו</span><em>${Number(j.pending||0)} ממתינים</em><span>1–15 דק׳</span></div>
 <div class="v5-row"><strong>תוצאה חיובית</strong><span>באופק האחרון</span><em>${pct(j.success_rate_pct)}</em><span>${j.evaluated||0} דגימות</span></div>
 <div class="v5-row"><strong>קריטריון מוביל</strong><span>${esc(best?.label||'נאספים נתונים')}</span><em>${best?pct(best.success_pct):'—'}</em><span>${best?.signals||0} דגימות</span></div>`;
 card.querySelector('[data-learning-open]')?.addEventListener('click',()=>window.go?.('validation'));
}
function repairFocus(){
 const rows=Array.isArray(window.dayData)?window.dayData:[];const lead=rows[0];if(!lead)return;
 const score=$('#v5Score');if(score&&(!score.textContent||score.textContent.includes('null')||score.textContent==='—'))score.textContent=`${lead.strategy_fit_score??lead.score}/100 התאמה`;
 const fresh=$('#v5Fresh');if(fresh&&String(fresh.textContent).toLowerCase()==='stale')fresh.textContent='שוק סגור · נתון אחרון';
}
async function refresh(){try{const j=await getSummary();if(j.has_data)dashboard(j);repairFocus();window.__LIVE_LEARNING_SUMMARY__=j}catch(e){console.warn('learning bridge',e)}}
window.addEventListener('smartadvisor:day-scan',()=>setTimeout(refresh,0));
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(refresh,900),{once:true});else setTimeout(refresh,900);
setInterval(refresh,60000);
})();
