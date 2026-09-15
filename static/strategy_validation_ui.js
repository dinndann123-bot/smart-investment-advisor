// Production UI sync patch v20260915-1735
(function(){
  const $=id=>document.getElementById(id);
  const css=document.createElement('style');
  css.textContent=`
  :root{--mobile-card:#fff;--mobile-soft:#f7f9fd}
  #page-day .section-head,#page-long .section-head{margin-bottom:10px}
  #page-day .table-wrap,#page-long .table-wrap{box-shadow:0 10px 30px rgba(35,48,74,.07)}
  #page-day table,#page-long table{min-width:0}
  #page-day th,#page-long th{white-space:nowrap}
  canvas{display:block;max-width:100%;min-height:280px}
  @media(max-width:760px){
    .hero{padding:16px 14px 14px}.hero h1{font-size:26px}.hero p{font-size:12px}
    .clockbar{gap:7px}.clockitem{padding:8px 9px}.clockitem b{font-size:13px}
    .cards{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.card{padding:12px;border-radius:15px}
    .metric b{font-size:20px}.home-grid{gap:10px}.top-card{gap:8px}.top-card .rank{font-size:16px;width:20px}
    #page-day .table-wrap,#page-long .table-wrap{overflow:visible;border:0;background:transparent;box-shadow:none}
    #page-day table,#page-long table,#page-day tbody,#page-long tbody{display:block;width:100%}
    #page-day thead,#page-long thead{display:none}
    #page-day tr.stock-row,#page-long tr.stock-row{display:grid;grid-template-columns:1fr auto;gap:7px 10px;background:var(--mobile-card);border:1px solid var(--line);border-radius:16px;padding:12px;margin-bottom:10px;box-shadow:var(--shadow)}
    #page-day tr.stock-row td,#page-long tr.stock-row td{display:block;border:0;padding:0;text-align:right;font-size:12px;min-width:0}
    #page-day tr.stock-row td:first-child,#page-long tr.stock-row td:first-child{display:none}
    #page-day tr.stock-row td:nth-child(2),#page-long tr.stock-row td:nth-child(2){grid-column:1/2;grid-row:1/3}
    #page-day tr.stock-row td:nth-child(3),#page-long tr.stock-row td:nth-child(3){grid-column:2;grid-row:1;font-size:16px;font-weight:900;text-align:left}
    #page-day tr.stock-row td:nth-child(4),#page-long tr.stock-row td:nth-child(4){grid-column:2;grid-row:2;text-align:left}
    #page-day tr.stock-row td:nth-child(5),#page-long tr.stock-row td:nth-child(5){grid-column:1/3;background:var(--mobile-soft);padding:8px;border-radius:10px}
    #page-day tr.stock-row td:nth-child(n+6),#page-long tr.stock-row td:nth-child(n+6){grid-column:1/3}
    #page-day tr.stock-row td button,#page-long tr.stock-row td button{width:100%;margin-top:3px}
    .company{min-width:0}.company b{font-size:15px}.logo,.logo-fallback{width:34px;height:34px}
    .prediction-legend{display:none!important}
    .detail{display:block}.kpis,.trade-plan,.tech-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
    canvas{height:260px!important;min-height:260px}
  }`;
  document.head.appendChild(css);

  function normalizeDay(x){
    return {...x,name:x.name||x.ticker,score:Number(x.score)||0,risk:Number(x.risk)||4,media:Number(x.media)||0,price:Number(x.price)||0,change:Number.isFinite(+x.change)?+x.change:null,summary:`RVOL ${Number.isFinite(+x.rvol)?(+x.rvol).toFixed(2)+'×':'—'} · ${x.news_count||0} חדשות`};
  }

  async function synchronizedScan(){
    if(window.__syncScanBusy)return;
    window.__syncScanBusy=true;
    const st=$('scannerStatus');
    if(st){st.textContent='מסנכרן את 10 המניות למסחר יומי...';st.className='live-badge live-delayed'}
    try{
      const r=await fetch('/api/scanner/day?top=10&candidates=60&_='+Date.now(),{cache:'no-store'});
      const j=await r.json();
      if(!r.ok)throw new Error(j.detail||'Scanner error');
      const rows=(Array.isArray(j.results)?j.results:[]).filter(x=>x&&x.ticker).map(normalizeDay).sort((a,b)=>b.score-a.score).slice(0,10);
      if(rows.length){
        window.dayData=rows;
        // top-level `let dayData` is not a window property; assign through the existing binding when available.
        try{dayData=rows}catch(_e){}
        if(typeof renderTables==='function')renderTables();
        if(typeof renderHome==='function')renderHome();
      }
      if($('homeDayCount'))$('homeDayCount').textContent=rows.length||10;
      if(st){st.textContent=`${j.full_market?'סריקת שוק מלאה':'סריקת שוק'} · ${rows.length}/10 מניות · ${String(j.feed||'').toUpperCase()}`;st.className='live-badge '+(rows.length?'live-on':'live-error')}
    }catch(e){if(st){st.textContent='הסריקה לא הסתנכרנה';st.className='live-badge live-error';st.title=e.message}}
    finally{window.__syncScanBusy=false}
  }

  function install(){
    // Always keep the home screen and Day Trading tab on the same dataset.
    try{autoScanEnabled=true;localStorage.setItem('auto_day_scanner','1')}catch(_e){}
    window.refreshDayScanner=synchronizedScan;
    const oldGo=window.go;
    if(typeof oldGo==='function')window.go=function(page){oldGo(page);if(page==='home'||page==='day')synchronizedScan()};
    synchronizedScan();
    setInterval(synchronizedScan,60000);
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')synchronizedScan()});
    window.addEventListener('resize',()=>{const c=document.querySelector('#page-detail canvas');if(c&&typeof drawChart==='function'&&window.selected)try{drawChart()}catch(_e){}});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>setTimeout(install,50));else setTimeout(install,50);
})();