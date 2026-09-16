/* Portfolio live daily-change enhancement */
(function(){
  const REFRESH_MS=15000;
  let refreshing=false;

  function fmtChange(v){
    const n=Number(v);
    if(!Number.isFinite(n)) return '—';
    return `<span class="${n>=0?'positive':'negative'}">${n>=0?'+':''}${n.toFixed(2)}%</span>`;
  }

  function strategyClass(score){
    const n=Number(score);
    if(!Number.isFinite(n)) return '';
    return n>=75?'positive':'negative';
  }

  function decoratePortfolio(){
    const table=document.querySelector('#page-portfolio table');
    const body=document.getElementById('portfolioBody');
    if(!table||!body) return;
    const headRow=table.querySelector('thead tr');
    if(headRow && !headRow.querySelector('[data-live-daily-change]')){
      const th=document.createElement('th');
      th.dataset.liveDailyChange='1';
      th.textContent='שינוי יומי';
      const headers=[...headRow.children];
      const currentIdx=headers.findIndex(x=>x.textContent.includes('מחיר נוכחי'));
      if(currentIdx>=0 && headers[currentIdx].nextSibling) headRow.insertBefore(th,headers[currentIdx].nextSibling);
      else headRow.appendChild(th);
    }
    [...body.querySelectorAll('tr')].forEach((tr,i)=>{
      const h=window.holdings?.[i] || (typeof holdings!=='undefined'?holdings[i]:null);
      if(!h||tr.querySelector('[data-live-daily-cell]')) return;
      const td=document.createElement('td');
      td.dataset.liveDailyCell='1';
      td.innerHTML=fmtChange(h.dailyChange);
      const cells=[...tr.children];
      if(cells[3]?.nextSibling) tr.insertBefore(td,cells[3].nextSibling); else tr.appendChild(td);
      const scoreCell=[...tr.children].find(x=>/\/100/.test(x.textContent));
      if(scoreCell){
        const sc=Number((scoreCell.textContent.match(/\d+(?:\.\d+)?/)||[])[0]);
        const cls=strategyClass(sc);
        if(cls) scoreCell.classList.add(cls);
      }
    });
  }

  function install(){
    if(typeof renderPortfolio!=='function'||typeof getQuote!=='function') return false;
    if(window.__portfolioLivePatchInstalled) return true;
    window.__portfolioLivePatchInstalled=true;

    const originalGetQuote=getQuote;
    getQuote=async function(symbol){
      const q=await originalGetQuote.apply(this,arguments);
      try{
        const list=typeof holdings!=='undefined'?holdings:[];
        const h=list.find(x=>x.symbol===symbol);
        if(h && Number.isFinite(Number(q.change))) h.dailyChange=Number(q.change);
      }catch(_e){}
      return q;
    };

    const originalRender=renderPortfolio;
    renderPortfolio=async function(){
      const result=await originalRender.apply(this,arguments);
      decoratePortfolio();
      return result;
    };

    setInterval(async()=>{
      const page=document.getElementById('page-portfolio');
      if(!page?.classList.contains('active')||refreshing) return;
      refreshing=true;
      try{
        const list=typeof holdings!=='undefined'?holdings:[];
        if(typeof cache!=='undefined') list.forEach(h=>delete cache[`bundle:${h.symbol}:1M`]);
        await renderPortfolio();
      }catch(_e){}finally{refreshing=false;}
    },REFRESH_MS);
    return true;
  }

  if(!install()){
    const t=setInterval(()=>{if(install())clearInterval(t)},250);
    setTimeout(()=>clearInterval(t),15000);
  }
})();
