// Success-rate labels for every stock list + portfolio prewarm.
(function(){
  const assetCache=new Map();
  let longBacktestReady=false;
  let longBacktestPromise=null;

  const n=v=>Number.isFinite(+v)?+v:null;
  const esc=s=>String(s??'').replace(/"/g,'&quot;');

  async function ensureLongBacktest(){
    if(longBacktestReady)return true;
    if(longBacktestPromise)return longBacktestPromise;
    longBacktestPromise=(async()=>{
      try{
        const r=await fetch('/api/strategy/long/validate?years=6',{cache:'no-store'});
        const j=await r.json();
        longBacktestReady=!!(r.ok&&j?.ok);
        window.__longStrategyValidation=j;
      }catch(_e){longBacktestReady=false}
      return longBacktestReady;
    })();
    return longBacktestPromise;
  }

  async function asset(symbol){
    symbol=String(symbol||'').trim().toUpperCase();
    if(!symbol)return null;
    const hit=assetCache.get(symbol);
    if(hit&&Date.now()-hit.at<15*60*1000)return hit.data;
    await ensureLongBacktest();
    try{
      const r=await fetch(`/api/market-asset/${encodeURIComponent(symbol)}`,{cache:'no-store'});
      const j=await r.json();
      if(!r.ok)throw new Error(j?.detail||'asset unavailable');
      assetCache.set(symbol,{at:Date.now(),data:j});
      return j;
    }catch(_e){return null}
  }

  function longText(j){
    const h=j?.long_model?.historical_success;
    const m=n(h?.one_month?.success_pct), y=n(h?.one_year?.success_pct);
    if(m==null&&y==null)return {html:'<span class="success-chip wait">אין מדגם מספיק</span>',title:'אין כרגע מדגם היסטורי מספיק להצגת אחוז אמין.'};
    const p=[];
    if(m!=null)p.push(`חודש ${m.toFixed(0)}%`);
    if(y!=null)p.push(`שנה ${y.toFixed(0)}%`);
    return {html:`<span class="success-chip">${p.join(' · ')}</span>`,title:'אחוז הצלחה היסטורי של מודל הטווח הארוך. הצלחת חודש = 4%+ אחרי 21 ימי מסחר; הצלחת שנה = 15%+ אחרי 252 ימי מסחר.'};
  }

  function dayText(j){
    const h=j?.day_model?.historical_success;
    const p=n(h?.pct);
    if(p==null)return {html:'<span class="success-chip wait">אין מדגם מספיק</span>',title:esc(h?.basis||'אין כרגע מדגם היסטורי מספיק.')};
    return {html:`<span class="success-chip">יומי ${p.toFixed(0)}%</span>`,title:esc(`${h?.basis||'Backtest היסטורי'} · הצלחה = עמידה ביעד השיטה במסחר היומי.`)};
  }

  async function enrichBody(bodyId,kind){
    const body=document.getElementById(bodyId); if(!body)return;
    const table=body.closest('table'), head=table?.querySelector('thead tr');
    if(head&&!head.querySelector('[data-method-success-head]')){
      const th=document.createElement('th');
      th.dataset.methodSuccessHead='1';
      th.innerHTML='אחוז הצלחה <span class="metric-help" title="ביצוע היסטורי של השיטה במקרים דומים. זה אינו סיכוי מובטח לרווח.">?</span>';
      const scoreHead=[...head.children].find(x=>/ציון/.test(x.textContent||''));
      if(scoreHead)scoreHead.insertAdjacentElement('afterend',th); else head.appendChild(th);
    }
    const rows=[...body.querySelectorAll('tr')];
    await Promise.all(rows.map(async tr=>{
      if(tr.querySelector('[data-method-success-cell]'))return;
      const symbol=(tr.querySelector('.company b')||tr.querySelector('td b'))?.textContent?.trim()?.toUpperCase();
      if(!symbol)return;
      const scoreCell=[...tr.children].find(td=>/\/100/.test(td.textContent||''));
      const td=document.createElement('td'); td.dataset.methodSuccessCell='1'; td.innerHTML='<span class="small">מחשב...</span>';
      if(scoreCell)scoreCell.insertAdjacentElement('afterend',td); else tr.appendChild(td);
      const j=await asset(symbol);
      const info=kind==='day'?dayText(j):longText(j);
      td.innerHTML=info.html; td.title=info.title;
    }));
  }

  function installStyle(){
    if(document.getElementById('successRateUiStyle'))return;
    const st=document.createElement('style');st.id='successRateUiStyle';st.textContent=`
      .success-chip{display:inline-block;padding:5px 8px;border-radius:999px;font-size:11px;font-weight:900;background:#e9f8f1;color:#08734f;white-space:nowrap}
      .success-chip.wait{background:#f1f3f8;color:#6d778b}
    `;document.head.appendChild(st);
  }

  let timer=null;
  function refreshSoon(){clearTimeout(timer);timer=setTimeout(()=>{enrichBody('longTable','long');enrichBody('dayTable','day')},150)}

  function install(){
    installStyle();
    ensureLongBacktest().then(()=>{
      refreshSoon();
      if(typeof window.renderPortfolio==='function')window.renderPortfolio();
    });
    ['longTable','dayTable'].forEach(id=>{
      const el=document.getElementById(id);if(el)new MutationObserver(refreshSoon).observe(el,{childList:true,subtree:false});
    });
    refreshSoon();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',install);else install();
})();
