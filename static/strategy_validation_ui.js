// Strategy validation dashboard v2
(function(){
  function pct(v){return v==null?'—':`${Number(v).toFixed(1)}%`}
  function errText(detail){
    if(detail==null)return 'האימות נכשל';
    if(typeof detail==='string')return detail;
    if(Array.isArray(detail))return detail.map(x=>x?.msg||x?.message||JSON.stringify(x)).join(' · ');
    if(typeof detail==='object')return detail.msg||detail.message||JSON.stringify(detail);
    return String(detail);
  }
  function install(){
    if(document.getElementById('strategyValidationCard'))return;
    const anchor=document.getElementById('homeLearningPanel')||document.querySelector('#home .cards')||document.querySelector('.shell');
    if(!anchor)return;
    const wrap=document.createElement('div');
    wrap.id='strategyValidationCard';
    wrap.className='card';
    wrap.style.marginTop='16px';
    wrap.innerHTML=`<div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:20px">אימות היסטורי לשיטת המסחר</h2><p>Walk-forward: משתמש רק בנתונים שהיו זמינים עד 10:00 ניו יורק, ואז בודק מה קרה בהמשך היום.</p></div><button class="btn btn-primary" id="runStrategyValidationBtn">הרץ אימות</button></div><div id="strategyValidationStatus" class="note">עדיין לא הורץ אימות בגרסה הזו.</div><div id="strategyValidationResults"></div>`;
    anchor.insertAdjacentElement('beforebegin',wrap);
    document.getElementById('runStrategyValidationBtn').addEventListener('click',run);
  }
  async function run(){
    const btn=document.getElementById('runStrategyValidationBtn');
    const status=document.getElementById('strategyValidationStatus');
    const out=document.getElementById('strategyValidationResults');
    btn.disabled=true; status.textContent='מריץ אימות היסטורי מורחב על כ-180 ימי מסחר ויקום רחב. זה עשוי לקחת דקה או יותר...'; out.innerHTML='';
    try{
      // Use backend defaults so stale client-side parameters cannot violate the current validation schema.
      const r=await fetch('/api/strategy/validate',{cache:'no-store'});
      let j={};
      try{j=await r.json()}catch(_e){}
      if(!r.ok)throw new Error(errText(j.detail||j.error||j));
      const s=j.selected||{}, t=s.test||{};
      const enough=(j.samples?.test||0)>=50;
      const good=enough && (t.signals||0)>=8 && ((s.lift3_vs_baseline||s.lift_vs_baseline||0)>=1.15) && ((t.expectancy_3pct_stop3_pct??0)>0);
      status.innerHTML=`<b>${good?'השיטה מציגה יתרון במדגם הבדיקה':'עדיין אין יתרון מספיק חזק במדגם הבדיקה'}</b> · ${j.samples?.test||0} דגימות holdout · ${j.daily_candidate_days||0} ימי מועמדים · Feed: ${(j.feed||'').toUpperCase()}`;
      const buckets=(j.score_buckets_test||[]).map(b=>`<tr><td>${b.bucket}</td><td>${b.samples}</td><td>${pct(b.hit_rate_3pct??b.hit_rate_pct)}</td><td>${pct(b.avg_max_up_pct)}</td><td>${pct(b.avg_drawdown_pct)}</td></tr>`).join('');
      out.innerHTML=`<div class="cards" style="margin-top:12px"><div class="card metric"><b>${s.model||'—'}</b><span>מודל שנבחר על train בלבד</span></div><div class="card metric"><b>${s.threshold??'—'}</b><span>סף כניסה שנבחר</span></div><div class="card metric"><b>${pct(t.hit_rate_3pct)}</b><span>פגע ב־3%+ אחרי 10:00</span></div><div class="card metric"><b>${Number.isFinite(+t.expectancy_3pct_stop3_pct)?(+t.expectancy_3pct_stop3_pct).toFixed(2)+'%':'—'}</b><span>Expectancy יעד 3% / Stop 3%</span></div></div><div class="cards" style="margin-top:12px"><div class="card metric"><b>${j.raw_events??'—'}</b><span>אירועים גולמיים</span></div><div class="card metric"><b>${j.samples?.total??'—'}</b><span>מועמדים לאחר סינון יומי</span></div><div class="card metric"><b>${pct(t.hit_rate_2pct)}</b><span>פגע ב־2%+</span></div><div class="card metric"><b>${pct(t.hit_rate_pct)}</b><span>פגע ב־5%+</span></div></div><div class="table-wrap" style="margin-top:12px"><table class="compact-table"><thead><tr><th>טווח ציון</th><th>דגימות</th><th>פגיעה 3%+</th><th>עלייה מקס' ממוצעת</th><th>Drawdown ממוצע</th></tr></thead><tbody>${buckets}</tbody></table></div><div class="plan-note" style="margin-top:12px"><b>משקולות מומלצות כרגע:</b> מומנטום ${Math.round((s.weights?.momentum||0)*100)}% · RVOL ${Math.round((s.weights?.rvol||0)*100)}% · נזילות ${Math.round((s.weights?.liquidity||0)*100)}% · מבנה תוך־יומי ${Math.round((s.weights?.structure||0)*100)}% · מחיר/סחירות ${Math.round((s.weights?.price||0)*100)}%.<br><span class="small">המודל נבחר על תקופת train ונבדק בנפרד על holdout. חדשות היסטוריות עדיין נשארות שכבת אישור נפרדת.</span></div>`;
    }catch(e){status.textContent='❌ '+(e?.message||String(e))}finally{btn.disabled=false}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(install,0));else setTimeout(install,0);
})();
