// Universal market search UI
(function(){
  let timer=null;
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
  function install(){
    if(document.getElementById('marketSearchCard'))return;
    const shell=document.querySelector('.shell'); if(!shell)return;
    const card=document.createElement('section');
    card.id='marketSearchCard'; card.className='card'; card.style.marginBottom='16px';
    card.innerHTML=`
      <div class="section-head" style="margin:0 0 10px">
        <div><h2 style="margin:0">🔎 חיפוש מניה / ETF / נייר ערך</h2><p>חפש לפי שם או סימול. התוצאה מציגה נתוני שוק, ביצועי שנה, חדשות, ציון השיטה ואחוז הצלחה היסטורי כשיש מדגם מספיק.</p></div>
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
  async function loadAsset(symbol){
    const box=document.getElementById('marketSearchResults'); if(box)box.style.display='none';
    const panel=document.getElementById('marketAssetPanel'); const st=document.getElementById('marketSearchStatus');
    panel.style.display='block'; panel.innerHTML='<div class="plan-note">טוען ניתוח מלא של '+esc(symbol)+'...</div>'; st.textContent='טוען '+symbol+'...';
    try{
      const r=await fetch('/api/market-asset/'+encodeURIComponent(symbol),{cache:'no-store'}); const j=await r.json();
      if(!r.ok)throw new Error(j.detail||'לא ניתן לטעון את הנייר');
      const a=j.asset||{}, y=j.year||{}, h=j.historical_success||{};
      const success=h.pct==null?'אין מספיק היסטוריה':Number(h.pct).toFixed(1)+'%';
      const successClass=h.pct==null?'':Number(h.pct)>=55?'positive':Number(h.pct)<45?'negative':'';
      const score=j.method_score==null?'—':Math.round(j.method_score)+'/100';
      const news=(j.news||[]).map(n=>`<div class="news"><b>${esc(n.title||'')}</b><span>${esc(n.source||'')} ${n.published_at?'· '+new Date(n.published_at).toLocaleString('he-IL'):''}</span></div>`).join('')||'<div class="empty">אין כרגע חדשות זמינות.</div>';
      panel.innerHTML=`
        <div class="detail-hero"><div><h2 style="margin:0">${esc(a.symbol)} · ${esc(a.name)}</h2><div class="small">${esc(a.type_he||'נייר ערך')} · ${esc(a.exchange||'')} · מקור נתונים ${esc(j.provider||'')}</div></div></div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${money(j.price)}</b><span>מחיר אחרון</span></div>
          <div class="card metric"><b class="${Number(j.change_pct)>=0?'positive':'negative'}">${pct(j.change_pct)}</b><span>שינוי בפועל מול סגירה קודמת</span></div>
          <div class="card metric"><b>${score}</b><span>ציון התאמה לשיטה · לא אחוז</span></div>
          <div class="card metric"><b class="${successClass}">${success}</b><span>אחוז הצלחה היסטורי · ${esc(h.basis||'')}</span></div>
        </div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b class="${Number(y.return_pct)>=0?'positive':'negative'}">${pct(y.return_pct)}</b><span>תשואת מחיר ב־12 חודשים</span></div>
          <div class="card metric"><b>${compact(y.avg_daily_volume)}</b><span>מחזור מניות יומי ממוצע</span></div>
          <div class="card metric"><b>${compact(y.annual_share_volume)}</b><span>מחזור מניות מצטבר בשנה</span></div>
          <div class="card metric"><b>${y.annual_dollar_turnover==null?'—':'$'+compact(y.annual_dollar_turnover)}</b><span>מחזור מסחר כספי משוער בשנה</span></div>
        </div>
        <div class="cards" style="margin-top:12px">
          <div class="card metric"><b>${money(y.high)}</b><span>שיא 12 חודשים</span></div>
          <div class="card metric"><b>${money(y.low)}</b><span>שפל 12 חודשים</span></div>
          <div class="card metric"><b>${j.rvol==null?'—':Number(j.rvol).toFixed(2)+'×'}</b><span>RVOL נוכחי מול ממוצע</span></div>
          <div class="card metric"><b>${j.news_count??0}</b><span>כתבות/חדשות אחרונות שנמצאו</span></div>
        </div>
        <div class="home-grid" style="margin-top:14px">
          <div class="card"><h3 style="margin-top:0">למה השיטה רואה את הנייר כך?</h3><p class="note">ציון ${score} משלב כרגע מומנטום, מחזור יחסי, נזילות, חדשות ומבנה מחיר. ${h.pct==null?'אין עדיין מספיק תוצאות היסטוריות כדי להציג אחוז הצלחה אמין.':`אחוז ההצלחה ${Number(h.pct).toFixed(1)}% מבוסס על ${h.samples} מקרים — ${esc(h.basis)}.`}</p><div class="plan-note"><b>קטליזטור/מידע תקשורתי אחרון:</b><br>${esc(j.catalyst||'לא נמצא קטליזטור חדשותי עדכני.')}</div></div>
          <div class="card"><h3 style="margin-top:0">חדשות אחרונות</h3><div class="news-list">${news}</div></div>
        </div>
        <div class="note" style="margin-top:10px">מחזור המסחר השנתי הוא אומדן של פעילות המסחר בנייר ואינו הכנסות/מחזור עסקי של החברה. אחוז ההצלחה הוא ביצוע היסטורי של השיטה, לא הבטחה לתשואה עתידית.</div>`;
      st.textContent=`${a.symbol} נטען · עודכן ${new Date(j.generated_at).toLocaleTimeString('he-IL')}`;
    }catch(e){panel.innerHTML='<div class="plan-note">לא ניתן לטעון את הניתוח: '+esc(e.message)+'</div>';st.textContent='טעינת הנייר נכשלה'}
  }
  window.__marketLoadAsset=loadAsset;
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();
