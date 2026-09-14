// Strategy validation dashboard v6 — production-safe
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

  const previousRefresh=window.refreshDayScanner;
  if(typeof previousRefresh==='function'){
    window.refreshDayScanner=async function(manual=false){
      if(typeof scannerBusy!=='undefined'&&scannerBusy)return;
      if(typeof scannerBusy!=='undefined')scannerBusy=true;
      const st=document.getElementById('scannerStatus');
      if(st){st.textContent='סורק ומדרג את המועמדות החזקות ביותר...';st.className='live-badge live-delayed'}
      try{
        const r=await fetch('/api/scanner/day?top=20&candidates=60',{cache:'no-store'});const j=await r.json();
        if(!r.ok)throw new Error(j.detail||'Scanner error');
        const all=(Array.isArray(j.results)?j.results:[]).filter(x=>x&&x.ticker&&Number.isFinite(Number(x.score)));
        const ranked=[...all].sort((a,b)=>Number(b.score||0)-Number(a.score||0));
        const strong=ranked.filter(x=>Number(x.score||0)>=80&&((Number.isFinite(+x.rvol)&&+x.rvol>=1.2)||(x.news_count||0)>0));
        const chosen=[];
        for(const x of strong){if(chosen.length>=10)break;chosen.push(x)}
        for(const x of ranked){if(chosen.length>=10)break;if(!chosen.some(y=>y.ticker===x.ticker))chosen.push(x)}
        dayData=chosen.map(x=>({...x,name:x.name||x.ticker,summary:`RVOL ${Number.isFinite(+x.rvol)?(+x.rvol).toFixed(2)+'×':'—'} · ${x.news_count||0} חדשות`}));
        if(typeof renderTables==='function')renderTables();if(typeof renderHome==='function')renderHome();enhancePredictionUI();
        if(typeof loadLivePerformance==='function')loadLivePerformance(false);
        if(st){
          const strongCount=chosen.filter(x=>Number(x.score||0)>=80&&((Number.isFinite(+x.rvol)&&+x.rvol>=1.2)||(x.news_count||0)>0)).length;
          const suffix=chosen.length?` · ${chosen.length} מוצגות · ${strongCount} עברו סף מלא`:' · השרת לא החזיר מועמדות';
          st.textContent=`${j.full_market?'סריקת שוק מלאה':'סריקת גיבוי'} · ${j.feed||'—'}${suffix}`;
          st.className='live-badge '+(chosen.length?(j.full_market?'live-on':'live-delayed'):'live-error');
        }
      }catch(e){if(st){st.textContent='שגיאת סריקה';st.className='live-badge live-error';st.title=e.message}}
      finally{if(typeof scannerBusy!=='undefined')scannerBusy=false}
    };
  }

  const previousRender=window.renderTables;
  if(typeof previousRender==='function')window.renderTables=function(){previousRender();enhancePredictionUI();};

  // OCR v14 — tuned for Blink position detail screenshots.
  const OCR_SKIP=new Set(['WWW','WEB','USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','ETF','BUY','SELL','AVG','COST','MARKET','LIMIT','DAY','GTC','PNL','GAIN','LOSS','PORTFOLIO','OPEN','CLOSE','HIGH','LOW','CHANGE','TODAY','QQ']);
  const nval=s=>{const m=String(s||'').replace(/,/g,'.').match(/-?\d+(?:\.\d+)?/);return m?Number(m[0]):null};
  function linesOf(text){return String(text||'').split(/\r?\n/).map(x=>x.trim()).filter(Boolean)}
  function findLabeledNumber(lines,patterns){
    for(let i=0;i<lines.length;i++){
      if(!patterns.some(p=>p.test(lines[i])))continue;
      const here=nval(lines[i]); if(Number.isFinite(here))return here;
      for(let j=1;j<=2;j++){const x=nval(lines[i+j]);if(Number.isFinite(x))return x}
    }
    return null;
  }
  function extractBlink(text){
    const lines=linesOf(text), upper=String(text||'').toUpperCase();
    let symbol=null;
    const top=lines.slice(0,8).join(' ').toUpperCase();
    const sm=top.match(/(?:^|\s|<)([A-Z]{2,5})(?=\s|\(|<|$)/);
    if(sm&&!OCR_SKIP.has(sm[1]))symbol=sm[1];
    if(!symbol){
      for(const m of upper.matchAll(/\b[A-Z]{2,5}\b/g)){if(!OCR_SKIP.has(m[0])){symbol=m[0];break}}
    }
    const qty=findLabeledNumber(lines,[/מספר\s*מניות/i,/כמות/i,/יחידות/i,/shares?/i,/qty/i]);
    let buy=findLabeledNumber(lines,[/מחיר\s*קנייה\s*ממוצע/i,/מחיר\s*קניה\s*ממוצע/i,/מחיר\s*ממוצע/i,/avg(?:erage)?\s*(?:buy\s*)?price/i,/cost\s*basis/i]);
    if(buy!=null&&buy<1){buy=null}
    return {symbol,qty,buy,lines};
  }
  async function valid(sym){
    if(!sym||OCR_SKIP.has(sym)||sym.length<2||sym.length>5)return false;
    try{const r=await fetch('/api/stock/'+encodeURIComponent(sym)+'/bundle?range=1M',{cache:'no-store'});if(!r.ok)return false;const j=await r.json();return !!(j?.quote?.price||(j?.bars||[]).length)}catch(_){return false}
  }
  async function installOcrV14(){
    const input=document.getElementById('imgInput');if(!input||typeof window.addOcrRow!=='function')return;
    input.onchange=async e=>{
      const file=e.target.files?.[0];if(!file)return;
      const st=document.getElementById('ocrStatus'),raw=document.getElementById('ocrRaw'),rows=document.getElementById('ocrRows');
      if(st)st.textContent='קורא צילום Blink ומחלץ סימול, מספר מניות ומחיר קנייה ממוצע...';
      try{
        let text='';
        try{text=(await Tesseract.recognize(file,'heb+eng')).data.text||''}catch(_){text=(await Tesseract.recognize(file,'eng')).data.text||''}
        if(raw)raw.value=text;
        const b=extractBlink(text);
        if(rows)rows.innerHTML='';
        const ok=await valid(b.symbol);
        if(ok&&Number.isFinite(b.qty)&&b.qty>0&&Number.isFinite(b.buy)&&b.buy>0){
          window.addOcrRow(b.symbol,b.qty,b.buy);
          if(st)st.textContent=`זוהתה אחזקה: ${b.symbol} · ${b.qty} מניות · מחיר קנייה ממוצע $${b.buy.toFixed(2)}. בדוק ושמור.`;
          return;
        }
        // Fallback: keep a correctly validated symbol even if OCR missed one numeric field.
        if(ok){window.addOcrRow(b.symbol,Number.isFinite(b.qty)?b.qty:'',Number.isFinite(b.buy)?b.buy:'');if(st)st.textContent=`זוהה ${b.symbol}, אבל אחד הנתונים המספריים לא נקרא היטב. השלם רק את השדה החסר.`;return}
        window.addOcrRow();
        if(st)st.textContent='לא הצלחתי לזהות את האחזקה בביטחון מהצילום הזה; לא הכנסתי סימולים אקראיים.';
      }catch(e){if(st)st.textContent='הסריקה נכשלה; התיק לא שונה.'}
    };
  }

  const boot=()=>{setTimeout(install,0);setTimeout(enhancePredictionUI,50);setTimeout(installOcrV14,1500)};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);
  else boot();
})();
