// Universal market search UI v2
(function(){
  let timer=null;
  let currentAsset=null;
  const nf=new Intl.NumberFormat('he-IL',{maximumFractionDigits:1});
  function money(v){return Number.isFinite(+v)?'$'+Number(v).toFixed(2):'—'}
  function pct(v){return Number.isFinite(+v)?(Number(v)>=0?'+':'')+Number(v).toFixed(1)+'%':'—'}
  function compact(v){
    const n=Number(v); if(!Number.isFinite(n))return '—';
    if(Math.abs(n)>=1e12)return (n/1e12).toFixed(2)+'T';
    if(Math.abs(n)>=1e9)return (n/1e9).toFixed(2)+'B';
    if(Math.abs(n)>=1e6)return (n/1e6).toFixed(2)+'M';
    if(Math.abs(n)>=1e3)return (n/1e3).toFixed(1)+'K';
    return nf.format(n);
  }
  function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function successText(x){return x?.success_pct==null?'אין מספיק היסטוריה':Number(x.success_pct).toFixed(1)+'%'}
  function install(){
    if(document.getElementById('marketSearchCard'))return;
    const shell=document.querySelector('.shell'); if(!shell)return;
    const card=document.createElement('section');
    card.id='marketSearchCard'; card.className='card'; card.style.marginBottom='16px';
    card.innerHTML=`
      <div class="section-head" style="margin:0 0 10px">
        <div><h2 style="margin:0">🔎 חיפוש מניה / ETF / נייר ערך</h2><p>חפש לפי שם או סימול. פתיחת נייר מציגה את כל הנתונים, שני מודלי השיטה, חדשות וגרף ליום / שנה / 5 שנים.</p></div>
      </div>
      <div style="position:relative">
        <input id="marketSearchInput" placeholder="לדוגמה: AAPL, Apple, QQQ, S&P 500..." autocomplete="off" style="font-size:16px;padding:13px 14px">
        <div id="marketSearchResults" class="card" style="display:none;position:absolute;z-index:60;top:50px;left:0;right:0;padding:6px;max-height:360px;overflow:auto"></div>
      </div>
      <div id="marketSearchStatus" class="small" style="margin-top:7px">הקלד לפחות תו אחד.</div>
      <div id="marketAssetPanel" style="display:none;margin-top:14px"></div>`;
    shell.insertBefore(card,shell.firstChild);
    const input=document.getElementById('marketSearchInput');
    input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>search(input.value),250)});
    input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();const first=document.querySelector('#marketSearchResults [data-symbol]');if(first)loadAsset(first.dataset.symbol)}});
  }
  async function search(q){
    q=(q||'').trim(); const box=document.getElementById('marketSearchResults'); const st=document.getElementById('marketSearchStatus');
    if(!q){box.style.display='none';st.textContent='הקלד לפחות תו אחד.';return}
    st.textContent='מחפש בכל ניירות הערך הפעילים...';
    try{
      const r=await fetch('/api/market-search?q='+encodeURIComponent(q)+'&limit=20',{cache:'no-store'}); const j=await r.json();
      if(!r.ok)throw new Error(j.detail||'שגיאת חיפוש');
      const rows=j.results||[];
      st.textContent=rows.length?`נמצאו ${j.count??rows.length} התאמות · מוצגות עד 20`:'לא נמצאה התאמה.';
      if(!rows.length){box.style.display='none';return}
      box.innerHTML=rows.map(x=>`<button data-symbol="${esc(x.symbol)}" style="width:100%;border:0;background:#fff;text-align:right;padding:10px;border-bottom:1px solid #edf0f5;cursor:pointer" onclick="window.__marketLoadAsset('${esc(x.symbol)}')"><b>${esc(x.symbol)}</b> · ${esc(x.name)}<div class="small">${esc(x.type_he)} · ${esc(x.exchange||'')}</div></button>`).join('');
      box.style.display='block';
    }catch(e){st.textContent='החיפוש לא זמין כרגע: '+e.message;box.style.display='none'}
  }
  function showChart(range){
    if(!currentAsset)return;
    document.querySelectorAll('.market-chart-range').forEach(b=>b.classList.toggle('active',b.dataset.r===range));
    const rows=currentAsset.charts?.[range]||[];
    if(typeof window.draw==='function')window.draw('marketAssetChart',rows);
    const note=document.getElementById('marketAssetChartNote');
    if(note)note.textContent=`${range==='day'?'יום מסחר':range==='year'?'12 חודשים':'5 שנים'} · ${rows.length} נקודות מחיר · מקור ${currentAsset.provider||'שרת'}`;
  }
  async function runLongBacktest(){
    const b=document.getElementById('runLongBacktestBtn'),n=document.getElementById('longBacktestNote');
    if(b)b.disabled=true;if(n)n.textContent='מריץ Backtest חודשי/שנתי נפרד...';
    try{
      const r=await fetch('/api/strategy/long/validate?years=6',{cache:'no-store'});const j=await r.json();
      if(!r.ok)throw new Error(j.detail||'Backtest failed');
      if(n)n.textContent=`הושלם: ${j.samples?.test||0} אירועי Holdout · הצלחת 3 חודשים ${j.test_3m?.success_pct??'—'}% · הצלחת 12 חודשים ${j.test_12m?.success_pct??'—'}%. פתח מחדש את המניה כדי לרענן את האחוזים שלה.`;
    }catch(e){if(n)n.textContent='ה-Backtest נכשל: '+e.message}finally{if(b)b.disabled=false}
  }
  async function loadAsset(symbol){
    const box=document.getElementById('marketSearchResults'); if(box)box.style.display='none';
    const panel=document.getElementById('marketAssetPanel'); const st=document.getElementById('marketSearchStatus');
    panel.style.display='block'; panel.innerHTML='<div class="plan-note">טוען ניתוח מלא של '+esc(symbol)+'...</div>'; st.textContent='טוען '+symbol+'...';
    try{
      const r=await fetch('/api/market-asset/'+encodeURIComponent(symbol),{cache:'no-store'}); const j=await r.json();
      if(!r.ok)throw new Error(j.detail||'לא ניתן לטעון את הנייר');
      currentAsset=j;
      const a=j.asset||{}, y=j.year||{}, dh=j.day_model?.historical_success||{}, lh=j.long_model?.historical_success||{};
      const dayScore=j.day_model?.score==null?'—':Math.round(j.day_model.score)+'/100';
      const longScore=j.long_model?.score==null?'—':Math.round(j.long_model.score)+'/100';
      const m3=lh.three_month||{}, y1=lh.one_year||{};
      const news=(j.news||[]).map(n=>`<div class="news"><b>${esc(n.title||'')}</b><span>${esc(n.source||'')} ${n.published_at?'· '+new Date(n.published_at).toLocaleString('he-IL'):''}</span></div>`).join('')||'<div class="empty">אין כרגע חדשות זמינות.</div>';
      panel.innerHTML=`
        <div class="detail-hero"><div><h2 style="margin:0">${esc(a.symbol)} · ${esc(a.name)}</h2><div class="small">${esc(a.type_he||'נייר ערך')} · ${esc(a.exchange||'')} · מקור נתונים ${esc(j.provider||'')}</div></div></div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${money(j.price)}</b><span>מחיר אחרון</span></div>
          <div class="card metric"><b class="${Number(j.change_pct)>=0?'positive':'negative'}">${pct(j.change_pct)}</b><span>שינוי בפועל מול סגירה קודמת</span></div>
          <div class="card metric"><b>${dayScore}</b><span>ציון מודל מסחר יומי · לא אחוז</span></div>
          <div class="card metric"><b>${dh.pct==null?'אין מספיק היסטוריה':Number(dh.pct).toFixed(1)+'%'}</b><span>הצלחה היסטורית במסחר יומי · ${esc(dh.basis||'')}</span></div>
        </div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${longScore}</b><span>ציון מודל חודשי–שנתי</span></div>
          <div class="card metric"><b>${successText(m3)}</b><span>הצלחת 3 חודשים · יעד Backtest: 8%+</span></div>
          <div class="card metric"><b>${successText(y1)}</b><span>הצלחת 12 חודשים · יעד Backtest: 15%+</span></div>
          <div class="card metric"><b class="${Number(y.return_pct)>=0?'positive':'negative'}">${pct(y.return_pct)}</b><span>תשואת מחיר בפועל ב־12 חודשים</span></div>
        </div>
        <div class="card" style="margin-top:14px">
          <div class="section-head" style="margin:0 0 8px"><div><h3 style="margin:0">גרף ${esc(a.symbol)}</h3><div id="marketAssetChartNote" class="small"></div></div>
          <div class="ranges"><button class="market-chart-range active" data-r="day" onclick="window.__marketShowChart('day')">יום</button><button class="market-chart-range" data-r="year" onclick="window.__marketShowChart('year')">שנה</button><button class="market-chart-range" data-r="five_year" onclick="window.__marketShowChart('five_year')">5 שנים</button></div></div>
          <canvas id="marketAssetChart"></canvas>
        </div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${compact(y.avg_daily_volume)}</b><span>מחזור מניות יומי ממוצע</span></div>
          <div class="card metric"><b>${compact(y.annual_share_volume)}</b><span>מחזור מניות מצטבר בשנה</span></div>
          <div class="card metric"><b>${y.annual_dollar_turnover==null?'—':'$'+compact(y.annual_dollar_turnover)}</b><span>מחזור מסחר כספי משוער בשנה</span></div>
          <div class="card metric"><b>${j.rvol==null?'—':Number(j.rvol).toFixed(2)+'×'}</b><span>RVOL נוכחי מול ממוצע</span></div>
        </div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${money(y.high)}</b><span>שיא 12 חודשים</span></div>
          <div class="card metric"><b>${money(y.low)}</b><span>שפל 12 חודשים</span></div>
          <div class="card metric"><b>${j.news_count??0}</b><span>חדשות אחרונות שנמצאו</span></div>
          <div class="card metric"><b>${j.long_model?.metrics?.volatility==null?'—':Number(j.long_model.metrics.volatility).toFixed(1)+'%'}</b><span>תנודתיות שנתית היסטורית</span></div>
        </div>
        <div class="home-grid" style="margin-top:14px">
          <div class="card"><h3 style="margin-top:0">ניתוח השיטה</h3><p class="note"><b>יומי:</b> ${dayScore}; ${dh.pct==null?'אין מדגם מספיק לאחוז אמין.':`${Number(dh.pct).toFixed(1)}% הצלחה על ${dh.samples} מקרים.`}<br><b>חודשי–שנתי:</b> ${longScore}; 3 חודשים ${successText(m3)}, שנה ${successText(y1)}.</p><div class="plan-note"><b>קטליזטור/מידע תקשורתי אחרון:</b><br>${esc(j.catalyst||'לא נמצא קטליזטור חדשותי עדכני.')}</div><button id="runLongBacktestBtn" class="btn btn-secondary" onclick="window.__runLongBacktest()">הרץ/רענן Backtest חודשי–שנתי</button><div id="longBacktestNote" class="small" style="margin-top:7px">${m3.success_pct==null&&y1.success_pct==null?'עדיין אין מדגם Long שמור; אפשר להריץ את ה-Backtest מכאן.':'אחוזי Long מבוססים על Holdout כרונולוגי נפרד.'}</div></div>
          <div class="card"><h3 style="margin-top:0">חדשות אחרונות</h3><div class="news-list">${news}</div></div>
        </div>
        <div class="note" style="margin-top:10px">מחזור המסחר השנתי הוא אומדן של פעילות המסחר בנייר ואינו הכנסות החברה. ציון ואחוז הצלחה הם שני נתונים שונים. אחוזי ההצלחה הם היסטוריים בלבד ואינם הבטחה לתשואה עתידית.</div>`;
      st.textContent=`${a.symbol} נטען · עודכן ${new Date(j.generated_at).toLocaleTimeString('he-IL')}`;
      requestAnimationFrame(()=>showChart('day'));
    }catch(e){panel.innerHTML='<div class="plan-note">לא ניתן לטעון את הניתוח: '+esc(e.message)+'</div>';st.textContent='טעינת הנייר נכשלה'}
  }
  window.__marketLoadAsset=loadAsset;
  window.__marketShowChart=showChart;
  window.__runLongBacktest=runLongBacktest;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();
