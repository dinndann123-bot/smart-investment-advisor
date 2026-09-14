// Strategy validation dashboard v4 — production-safe
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
    wrap.innerHTML=`<div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:20px">אימות היסטורי לשיטת המסחר</h2><p>Walk-forward: בדיקה היסטורית כבדה. מטעמי יציבות היא מופעלת ידנית בלבד ולא בזמן טעינת האפליקציה.</p></div><button class="btn btn-primary" id="runStrategyValidationBtn">הרץ אימות</button></div><div id="strategyValidationStatus" class="note">האימות הכבד מושהה בטעינת האפליקציה כדי לשמור זיכרון למסחר החי.</div><div id="strategyValidationResults"></div>`;
    anchor.insertAdjacentElement('beforebegin',wrap);
    document.getElementById('runStrategyValidationBtn')?.addEventListener('click',run);
  }

  async function run(){
    const btn=document.getElementById('runStrategyValidationBtn');
    const status=document.getElementById('strategyValidationStatus');
    const out=document.getElementById('strategyValidationResults');
    if(!btn||!status||!out)return;
    btn.disabled=true; status.textContent='מריץ אימות היסטורי מורחב...'; out.innerHTML='';
    try{
      const r=await fetch('/api/strategy/validate',{cache:'no-store'});
      let j={}; try{j=await r.json()}catch(_e){}
      if(!r.ok)throw new Error(errText(j.detail||j.error||j));
      window.__strategyValidation=j;
      const s=j.selected||{}, t=s.test||{};
      const enough=(j.samples?.test||0)>=50;
      const good=enough && (t.signals||0)>=8 && ((s.lift3_vs_baseline||s.lift_vs_baseline||0)>=1.15) && ((t.expectancy_t3_s3_pct??t.expectancy_3pct_stop3_pct??0)>0);
      status.innerHTML=`<b>${good?'השיטה מציגה יתרון במדגם הבדיקה':'עדיין אין יתרון מספיק חזק במדגם הבדיקה'}</b> · ${j.samples?.test||0} דגימות holdout · ${j.daily_candidate_days||0} ימי מועמדים · Feed: ${(j.feed||'').toUpperCase()}`;
      const buckets=(j.score_buckets_test||[]).map(b=>`<tr><td>${b.bucket}</td><td>${b.samples}</td><td>${pct(b.hit_rate_3pct??b.hit_rate_pct)}</td><td>${pct(b.avg_max_up_pct)}</td><td>${pct(b.avg_drawdown_pct)}</td></tr>`).join('');
      out.innerHTML=`<div class="cards" style="margin-top:12px"><div class="card metric"><b>${s.model||'—'}</b><span>מודל שנבחר על train בלבד</span></div><div class="card metric"><b>${s.threshold??'—'}</b><span>סף כניסה שנבחר</span></div><div class="card metric"><b>${pct(t.hit_rate_3pct)}</b><span>פגע ב־3%+ אחרי 10:00</span></div><div class="card metric"><b>${Number.isFinite(+(t.expectancy_t3_s3_pct??t.expectancy_3pct_stop3_pct))?+(t.expectancy_t3_s3_pct??t.expectancy_3pct_stop3_pct).toFixed?.(2)||'—':'—'}</b><span>Expectancy</span></div></div><div class="table-wrap" style="margin-top:12px"><table class="compact-table"><thead><tr><th>טווח ציון</th><th>דגימות</th><th>פגיעה 3%+</th><th>עלייה מקס' ממוצעת</th><th>Drawdown ממוצע</th></tr></thead><tbody>${buckets}</tbody></table></div>`;
      enhancePredictionUI();
    }catch(e){status.textContent='❌ '+(e?.message||String(e))}
    finally{btn.disabled=false}
  }

  const style=document.createElement('style');
  style.textContent=`.metric-help{display:inline-flex;align-items:center;justify-content:center;width:18px;height:18px;border-radius:50%;background:#eef2fb;color:#40516d;font-size:11px;font-weight:900;cursor:help;margin-inline-start:5px}.prediction-legend{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0 14px}.prediction-legend>div{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px 12px;font-size:12px;line-height:1.45}.prediction-legend b{display:block;margin-bottom:3px}.success-chip{display:inline-block;padding:5px 8px;border-radius:999px;font-weight:800;font-size:11px;background:#eef8f4;color:#08734f;white-space:nowrap}.success-chip.wait{background:#f1f3f8;color:#6d778b}.horizon-chip{display:inline-block;padding:4px 7px;border-radius:999px;background:#eef2ff;color:#3049af;font-size:10px;font-weight:800;margin-top:3px}@media(max-width:760px){.prediction-legend{grid-template-columns:1fr}}`;
  document.head.appendChild(style);

  function parseBucket(label){
    const s=String(label||'').replace(/\s/g,'');
    let m=s.match(/(\d+)[–-](\d+)/); if(m)return {min:+m[1],max:+m[2]};
    m=s.match(/(\d+)\+/); if(m)return {min:+m[1],max:Infinity};
    m=s.match(/<\s*(\d+)/); if(m)return {min:-Infinity,max:+m[1]-0.0001};
    m=s.match(/(\d+)/); if(m)return {min:+m[1],max:+m[1]};
    return null;
  }
  function daySuccessForScore(score){
    const buckets=window.__strategyValidation?.score_buckets_test||[];
    for(const b of buckets){
      const r=parseBucket(b.bucket);
      if(r&&score>=r.min&&score<=r.max){
        const n=Number(b.samples||0),hit=Number(b.hit_rate_3pct??b.hit_rate_pct);
        if(n>=8&&Number.isFinite(hit))return {text:`${hit.toFixed(0)}%`,title:`${n} מקרים היסטוריים בטווח הציון הזה.`};
        return {text:'מדגם קטן',title:`רק ${n} מקרים היסטוריים.`};
      }
    }
    return {text:'טרם נמדד',title:'האימות ההיסטורי הכבד מופעל ידנית בלבד.'};
  }
  function longSuccessForScore(){return {text:'בבדיקת Long',title:'יוצג רק לאחר Backtest ייעודי לטווח הארוך.'}}
  function ensureLegend(sectionId,kind){
    const sec=document.getElementById(sectionId);if(!sec||sec.querySelector('.prediction-legend'))return;
    const head=sec.querySelector('.section-head');if(!head)return;
    const div=document.createElement('div');div.className='prediction-legend';
    div.innerHTML=`<div><b>ציון התאמה לשיטה</b>דירוג 0–100 של התאמת המניה לקריטריונים; אינו הסתברות לרווח.</div><div><b>אחוז הצלחה היסטורי</b>${kind==='day'?'נלקח מאימות Holdout כאשר קיים מדגם מספיק.':'יוצג רק מתוך Backtest ייעודי לטווח הארוך.'}</div><div><b>שינוי מחיר בפועל</b>כמה המניה כבר עלתה או ירדה; זה אינו יעד.</div>`;
    head.insertAdjacentElement('afterend',div);
  }
  function enhancePredictionUI(){
    const longSec=document.getElementById('page-long'),daySec=document.getElementById('page-day');
    if(longSec){const h=longSec.querySelector('.section-head h2');if(h)h.textContent='10 תחזיות השיטה לטווח חודשי–שנתי';}
    if(daySec){const h=daySec.querySelector('.section-head h2');if(h)h.textContent='10 תחזיות השיטה למסחר יומי';}
    ensureLegend('page-long','long');ensureLegend('page-day','day');
    const dscore=document.getElementById('dScore');if(dscore){const label=dscore.nextElementSibling;if(label)label.textContent='ציון התאמה לשיטה (לא אחוז הצלחה)';}
  }

  // Keep only genuine day-trading candidates; never pad the list with weak names.
  const previousRefresh=window.refreshDayScanner;
  if(typeof previousRefresh==='function'){
    window.refreshDayScanner=async function(manual=false){
      if(typeof scannerBusy!=='undefined'&&scannerBusy)return;
      if(typeof scannerBusy!=='undefined')scannerBusy=true;
      const st=document.getElementById('scannerStatus');
      if(st){st.textContent='סורק מועמדות שעוברות את השיטה...';st.className='live-badge live-delayed'}
      try{
        const r=await fetch('/api/scanner/day?top=20&candidates=60',{cache:'no-store'});const j=await r.json();
        if(!r.ok)throw new Error(j.detail||'Scanner error');
        const all=Array.isArray(j.results)?j.results:[];
        const qualified=all.filter(x=>Number(x.score||0)>=80&&((Number.isFinite(+x.rvol)&&+x.rvol>=1.2)||(x.news_count||0)>0)).slice(0,10);
        dayData=qualified.map(x=>({...x,name:x.name||x.ticker,summary:`RVOL ${Number.isFinite(+x.rvol)?(+x.rvol).toFixed(2)+'×':'—'} · ${x.news_count||0} חדשות`}));
        if(typeof renderTables==='function')renderTables();if(typeof renderHome==='function')renderHome();enhancePredictionUI();
        if(typeof loadLivePerformance==='function')loadLivePerformance(false);
        if(st){const short=qualified.length<10?` · רק ${qualified.length} עברו את הסף`:'';st.textContent=`${j.full_market?'סריקת שוק מלאה':'סריקת גיבוי'} · ${j.feed||'—'}${short}`;st.className='live-badge '+(j.full_market?'live-on':'live-delayed');}
      }catch(e){if(st){st.textContent='שגיאת סריקה';st.className='live-badge live-error';st.title=e.message}}
      finally{if(typeof scannerBusy!=='undefined')scannerBusy=false}
    };
  }

  const previousRender=window.renderTables;
  if(typeof previousRender==='function')window.renderTables=function(){previousRender();enhancePredictionUI();};

  // IMPORTANT: do not auto-run /api/strategy/validate here. It is intentionally manual.
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{setTimeout(install,0);setTimeout(enhancePredictionUI,50)});
  else {setTimeout(install,0);setTimeout(enhancePredictionUI,50)}
})();
