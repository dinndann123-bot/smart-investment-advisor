// Strategy validation dashboard v1
(function(){
  function pct(v){return v==null?'—':`${Number(v).toFixed(1)}%`}
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
    btn.disabled=true; status.textContent='מריץ אימות היסטורי. זה עשוי לקחת כחצי דקה...'; out.innerHTML='';
    try{
      const r=await fetch('/api/strategy/validate?days=60&symbols=20',{cache:'no-store'});
      const j=await r.json(); if(!r.ok)throw new Error(j.detail||'האימות נכשל');
      const s=j.selected||{}, t=s.test||{};
      const good=(t.signals||0)>=8 && (s.lift_vs_baseline||0)>=1.15;
      status.innerHTML=`<b>${good?'השיטה מציגה יתרון במדגם הבדיקה':'עדיין אין יתרון מספיק חזק במדגם הבדיקה'}</b> · ${j.samples?.test||0} דגימות holdout · Feed: ${(j.feed||'').toUpperCase()}`;
      const buckets=(j.score_buckets_test||[]).map(b=>`<tr><td>${b.bucket}</td><td>${b.samples}</td><td>${pct(b.hit_rate_pct)}</td><td>${pct(b.avg_max_up_pct)}</td></tr>`).join('');
      out.innerHTML=`<div class="cards" style="margin-top:12px"><div class="card metric"><b>${s.model||'—'}</b><span>מודל שנבחר על train בלבד</span></div><div class="card metric"><b>${s.threshold??'—'}</b><span>סף כניסה שנבחר</span></div><div class="card metric"><b>${pct(t.hit_rate_pct)}</b><span>פגע ב־5%+ אחרי 10:00</span></div><div class="card metric"><b>${s.lift_vs_baseline??'—'}×</b><span>שיפור מול בסיס holdout</span></div></div><div class="table-wrap" style="margin-top:12px"><table class="compact-table"><thead><tr><th>טווח ציון</th><th>דגימות</th><th>שיעור הצלחה</th><th>עלייה מקס' ממוצעת</th></tr></thead><tbody>${buckets}</tbody></table></div><div class="plan-note" style="margin-top:12px"><b>משקולות מומלצות כרגע:</b> מומנטום ${Math.round((s.weights?.momentum||0)*100)}% · RVOL ${Math.round((s.weights?.rvol||0)*100)}% · נזילות ${Math.round((s.weights?.liquidity||0)*100)}% · מבנה תוך־יומי ${Math.round((s.weights?.structure||0)*100)}% · מחיר/סחירות ${Math.round((s.weights?.price||0)*100)}%.<br><span class="small">חדשות נשארות שכבת אישור נפרדת כי האימות הזה לא משתמש בחדשות היסטוריות. אין look-ahead בתכונות.</span></div>`;
    }catch(e){status.textContent='❌ '+e.message}finally{btn.disabled=false}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(install,0));else setTimeout(install,0);
})();
