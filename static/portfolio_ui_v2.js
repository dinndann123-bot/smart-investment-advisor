// Portfolio UI v2 — concise, explicit P/L and method success per holding.
(function(){
  const cache=new Map();
  const ttl=15*60*1000;
  const num=v=>Number.isFinite(+v)?+v:null;
  const signMoney=v=>{
    if(!Number.isFinite(v))return '—';
    const abs=Math.abs(v);
    return (v>=0?'+':'−')+money(abs);
  };
  const signPct=v=>Number.isFinite(v)?`${v>=0?'+':'−'}${Math.abs(v).toFixed(2)}%`:'—';
  const successText=(hist)=>{
    const m=num(hist?.one_month?.success_pct), y=num(hist?.one_year?.success_pct);
    if(m==null && y==null)return '<span class="small">אין עדיין מדגם מספיק</span>';
    const parts=[];
    if(m!=null)parts.push(`<span title="${hist?.one_month?.basis||''}">חודש <b>${m.toFixed(1)}%</b></span>`);
    if(y!=null)parts.push(`<span title="${hist?.one_year?.basis||''}">שנה <b>${y.toFixed(1)}%</b></span>`);
    return parts.join(' · ');
  };
  async function strategyFor(symbol){
    const hit=cache.get(symbol);if(hit&&Date.now()-hit.at<ttl)return hit.data;
    try{
      const r=await fetch(`/api/market-asset/${encodeURIComponent(symbol)}`,{cache:'no-store'});
      const j=await r.json();if(!r.ok)throw new Error(j.detail||'asset error');
      const data={score:num(j?.long_model?.score),hist:j?.long_model?.historical_success||null,price:num(j?.price)};
      cache.set(symbol,{at:Date.now(),data});return data;
    }catch(e){return {score:null,hist:null,price:null}}
  }
  function setup(){
    const page=document.getElementById('page-portfolio');if(!page)return;
    const p=page.querySelector('.section-head p');
    if(p)p.textContent='התיק בפועל: שווי, רווח/הפסד ואחוזי הצלחה היסטוריים של השיטה לכל נייר.';
    const head=page.querySelector('.portfolio-table thead tr');
    if(head)head.innerHTML='<th>נייר</th><th>כמות</th><th>קנייה</th><th>נוכחי</th><th>שווי</th><th>תוצאה</th><th>השיטה</th><th>פעולות</th>';
    let note=document.getElementById('portfolioMethodNote');
    if(!note){
      note=document.createElement('div');note.id='portfolioMethodNote';note.className='note';note.style.marginTop='10px';
      note.innerHTML='<b>איך לקרוא את הנתונים:</b> ציון 0–100 = התאמה לתנאי המודל. אחוז הצלחה = מה קרה היסטורית במקרים דומים ב־Backtest. אלה שני נתונים שונים.';
      page.querySelector('.table-wrap')?.insertAdjacentElement('afterend',note);
    }
  }
  window.renderPortfolio=async function(){
    setup();
    const b=document.getElementById('portfolioBody');if(!b)return;
    if(!holdings.length){
      b.innerHTML='<tr><td colspan="8"><div class="empty">עדיין לא הוספת מניות לתיק.</div></td></tr>';
      ['pCost','pValue','pPnl','pPct'].forEach((id,i)=>{const e=document.getElementById(id);if(e){e.textContent=i===0?'$0.00':'—';e.className='';}});
      return;
    }
    b.innerHTML='<tr><td colspan="8"><div class="empty">מעדכן מחירים ואחוזי הצלחה של השיטה...</div></td></tr>';
    const rows=await Promise.all(holdings.map(async(h,i)=>{
      let qPrice=null;
      try{qPrice=num((await getQuote(h.symbol))?.price)}catch(e){}
      const method=await strategyFor(h.symbol);
      h.currentPrice=qPrice??method.price??num(h.currentPrice);
      const val=h.currentPrice!=null?h.currentPrice*h.qty:null;
      const cost=h.buyPrice*h.qty;
      const pnl=val==null?null:val-cost;
      const pct=pnl==null||!cost?null:pnl/cost*100;
      const cls=pnl==null?'':pnl>=0?'positive':'negative';
      const score=method.score;
      return `<tr>
        <td><b>${h.symbol}</b><div class="small">${h.date||''}</div></td>
        <td>${Number(h.qty).toLocaleString('en-US',{maximumFractionDigits:6})}</td>
        <td>${money(h.buyPrice)}</td>
        <td>${h.currentPrice!=null?money(h.currentPrice):'—'}</td>
        <td>${val!=null?money(val):'—'}</td>
        <td class="${cls}"><b>${pnl==null?'—':signMoney(pnl)}</b><div class="small ${cls}">${signPct(pct)}</div></td>
        <td><div>${score!=null?`<span class="score ${scoreClass(score)}" title="ציון התאמה למודל, לא הסתברות">${score.toFixed(0)}/100</span>`:'<span class="small">ציון לא זמין</span>'}</div><div class="small" style="margin-top:5px">${successText(method.hist)}</div></td>
        <td><button class="btn btn-secondary" onclick="showPChart('${h.symbol}')">גרף</button> <button class="btn btn-danger" onclick="delHold(${i})">מחק</button></td>
      </tr>`;
    }));
    saveHoldings();
    b.innerHTML=rows.join('');
    const cost=holdings.reduce((a,h)=>a+(Number(h.qty)||0)*(Number(h.buyPrice)||0),0);
    const known=holdings.filter(h=>num(h.currentPrice)!=null);
    const val=known.reduce((a,h)=>a+h.qty*h.currentPrice,0);
    const kc=known.reduce((a,h)=>a+h.qty*h.buyPrice,0);
    const pnl=known.length?val-kc:null;
    const pct=pnl==null||!kc?null:pnl/kc*100;
    const put=(id,text,cls='')=>{const e=document.getElementById(id);if(e){e.textContent=text;e.className=cls;}};
    put('pCost',money(cost));put('pValue',known.length?money(val):'—');
    put('pPnl',pnl==null?'—':signMoney(pnl),pnl==null?'':pnl>=0?'positive':'negative');
    put('pPct',pct==null?'—':signPct(pct),pct==null?'':pct>=0?'positive':'negative');
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{setup();setTimeout(()=>window.renderPortfolio?.(),0)});
  else {setup();setTimeout(()=>window.renderPortfolio?.(),0)}
})();
