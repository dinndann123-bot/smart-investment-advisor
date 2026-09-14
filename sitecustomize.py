"""Production startup safety and client-side feature guards for Smart Investment Advisor."""
from pathlib import Path

try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _OriginalFileResponse = _responses.FileResponse

    def _safe_index(path):
        html = Path(path).read_text(encoding="utf-8")

        html = html.replace(
            '<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            '<script async src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            1,
        )
        html = html.replace(
            "const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});",
            "const reg={waiting:null,installing:null,update:async()=>{},addEventListener:()=>{}};",
            1,
        )
        html = html.replace('/static/icons/apple-touch-icon.png', '/static/icons/icons/apple-touch-icon.png')
        html = html.replace('/static/icons/icon-192.png', '/static/icons/icons/icon-192.png')

        for tag in (
            '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=22">',
            '<link rel="stylesheet" href="/static/ui-v2.css?v=22">',
        ):
            if tag not in html:
                html = html.replace('</head>', tag + '\n</head>', 1)

        scanner_guard = """<script id="day-scan-last-good-r11">
(()=>{
  const KEY='smartAdvisor:lastGoodDayScan:v1';
  const nativeFetch=window.fetch.bind(window);
  window.fetch=async function(input,init){
    const url=typeof input==='string'?input:(input&&input.url)||'';
    const res=await nativeFetch(input,init);
    if(!url.includes('/api/scanner/day')) return res;
    try{
      const data=await res.clone().json();
      const rows=Array.isArray(data&&data.results)?data.results:[];
      if(res.ok&&rows.length){
        try{localStorage.setItem(KEY,JSON.stringify({savedAt:Date.now(),payload:data}))}catch(_){ }
        return res;
      }
      if(res.ok&&!rows.length){
        try{
          const cached=JSON.parse(localStorage.getItem(KEY)||'null');
          if(cached?.payload?.results?.length){
            const payload={...cached.payload,source:'client_last_good_cache',stale:true,
              stale_reason:'live_scan_returned_empty',live_generated_at:data?.generated_at||null,
              cached_at:new Date(cached.savedAt).toISOString()};
            console.warn('DAY_SCAN_EMPTY_PROTECTED=true',payload.results.length);
            return new Response(JSON.stringify(payload),{status:200,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
          }
        }catch(_){ }
      }
    }catch(_){ }
    return res;
  };
})();
</script>"""
        if 'day-scan-last-good-r11' not in html:
            html = html.replace('</head>', scanner_guard + '\n</head>', 1)

        feature_patch = r'''<script id="portfolio-timing-ocr-r12">
(()=>{
  const money=n=>Number.isFinite(+n)?'$'+(+n).toFixed(2):'—';
  const avg=a=>a.length?a.reduce((x,y)=>x+y,0)/a.length:null;
  const median=a=>{if(!a.length)return null;const x=[...a].sort((m,n)=>m-n),i=Math.floor(x.length/2);return x.length%2?x[i]:(x[i-1]+x[i])/2};
  const num=s=>{const m=String(s||'').replace(/[,$₪%]/g,'').match(/-?\d+(?:[.]\d+)?/);return m?Number(m[0]):null};
  const SKIP=new Set(['USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','ETF','BUY','SELL','AVG','COST','MARKET','LIMIT','DAY','GTC','PNL','GAIN','LOSS','PORTFOLIO']);

  function normalizeBars(j){
    let b=j?.bars||j?.history||j?.daily_bars||j?.data||j?.series||[];
    if(!Array.isArray(b)&&b&&typeof b==='object') b=Object.entries(b).map(([d,v])=>({d,...v}));
    return (Array.isArray(b)?b:[]).map(x=>({
      d:x.d||x.t||x.date||x.datetime,
      c:Number(x.c??x.close), h:Number(x.h??x.high), l:Number(x.l??x.low), v:Number(x.v??x.volume||0)
    })).filter(x=>Number.isFinite(x.c)&&x.c>0);
  }
  function sma(arr,n,i){if(i<n-1)return null;let s=0;for(let k=i-n+1;k<=i;k++)s+=arr[k];return s/n}
  function atr(b,n=14){if(b.length<n+1)return null;const tr=[];for(let i=b.length-n;i<b.length;i++){const p=b[i-1]?.c||b[i].c;tr.push(Math.max((b[i].h||b[i].c)-(b[i].l||b[i].c),Math.abs((b[i].h||b[i].c)-p),Math.abs((b[i].l||b[i].c)-p)))}return avg(tr)}
  function rsi(vals,n=14){if(vals.length<n+1)return null;let g=0,l=0;for(let i=vals.length-n;i<vals.length;i++){const d=vals[i]-vals[i-1];if(d>0)g+=d;else l-=d}if(!l)return 100;const rs=(g/n)/(l/n);return 100-100/(1+rs)}

  function timingModel(bars){
    if(bars.length<80)return null;
    const c=bars.map(x=>x.c),v=bars.map(x=>x.v||0),i=c.length-1,price=c[i];
    const ma20=sma(c,20,i),ma50=sma(c,50,i),a=atr(bars,14),r=rsi(c,14);
    const hi20=Math.max(...c.slice(-20)),hi60=Math.max(...c.slice(-60));
    const dist20=(price/hi20-1)*100,dist60=(price/hi60-1)*100;
    const setup=[];
    for(let k=60;k<bars.length-60;k++){
      const m20=sma(c,20,k),m50=sma(c,50,k),av=avg(v.slice(k-19,k+1));
      const mom20=c[k]/c[k-20]-1;
      if(m20&&m50&&c[k]>m20&&m20>m50&&mom20>0.03&&(!av||v[k]>=av*.9)){
        const f=c.slice(k+1,k+61);if(!f.length)continue;
        let mx=f[0],day=1;f.forEach((p,z)=>{if(p>mx){mx=p;day=z+1}});
        setup.push({gain:(mx/c[k]-1)*100,day});
      }
    }
    const wins=setup.filter(x=>x.gain>=5),medDays=median(wins.map(x=>x.day)),medGain=median(wins.map(x=>x.gain));
    const hitRate=setup.length?setup.filter(x=>x.gain>=5).length/setup.length*100:null;
    const trend=ma20&&ma50?price>ma20&&ma20>ma50:false;
    const stretch=a&&ma20?(price-ma20)/a:null;
    let entry='המתן',entryClass='signal-wait',entryReason='המחיר לא באזור כניסה מובהק.';
    if(trend&&dist20<=-1.5&&dist20>=-8&&(stretch==null||stretch<1.5)){entry='כניסה טובה',entryClass='signal-buy',entryReason='מגמה חיובית והמחיר נסוג משיא קצר בלי מתיחת יתר.'}
    else if((dist20>-1.5&&(stretch!=null&&stretch>1.7))||r>72){entry='כניסה יקרה',entryClass='signal-no',entryReason='המחיר קרוב לשיא/מתוח יחסית לממוצע ולתנודתיות.'}
    let exit='החזק',exitClass='signal-buy',exitReason='אין כרגע סימן מובהק למימוש לפי מודל הזמן.';
    if((dist60>-1.2&&(stretch!=null&&stretch>1.8))||r>76){exit='מימוש חלקי',exitClass='signal-wait',exitReason='המחיר באזור שיא יחסי ומתוח; לפי ההיסטוריה זה אזור שבו כדאי להגן על רווח.'}
    if(ma20&&price<ma20&&r<48){exit='יציאה/הידוק סטופ',exitClass='signal-no',exitReason='המומנטום נחלש והמחיר ירד מתחת לממוצע 20.'}
    return {price,entry,entryClass,entryReason,exit,exitClass,exitReason,medDays,medGain,hitRate,rsi:r,dist20,dist60,setups:setup.length};
  }

  function ensureTimingBox(){
    if(document.getElementById('timingAnalysisR12'))return document.getElementById('timingAnalysisR12');
    const plan=document.getElementById('detailPlanSection');if(!plan)return null;
    const box=document.createElement('div');box.id='timingAnalysisR12';box.className='card';box.style.margin='12px 0';
    box.innerHTML='<h3 style="margin-top:0">תזמון לפי היסטוריה והשיטה</h3><div id="timingBodyR12" class="note">טוען 5 שנות היסטוריה...</div>';
    plan.insertAdjacentElement('afterend',box);return box;
  }
  async function loadTiming(ticker){
    const box=ensureTimingBox();if(!box)return;const body=document.getElementById('timingBodyR12');
    body.textContent='מחשב תזמון מתוך היסטוריה של עד 5 שנים...';
    try{
      const r=await fetch('/api/history/5y/'+encodeURIComponent(ticker),{cache:'no-store'});if(!r.ok)throw new Error('history');
      const j=await r.json(),bars=normalizeBars(j),m=timingModel(bars);if(!m)throw new Error('few bars');
      body.innerHTML=`<div class="trade-plan">
        <div class="plan-card"><span>מחיר כניסה עכשיו</span><b><span class="signal ${m.entryClass}">${m.entry}</span></b><small>${m.entryReason}</small></div>
        <div class="plan-card"><span>מצב יציאה</span><b><span class="signal ${m.exitClass}">${m.exit}</span></b><small>${m.exitReason}</small></div>
        <div class="plan-card"><span>זמן חציוני עד שיא מקומי</span><b>${m.medDays?Math.round(m.medDays)+' ימי מסחר':'—'}</b><small>מתוך ${m.setups} תרחישים היסטוריים דומים</small></div>
        <div class="plan-card"><span>רווח מקסימלי חציוני בתרחישים מוצלחים</span><b>${m.medGain!=null?m.medGain.toFixed(1)+'%':'—'}</b><small>שיעור הגעה ל־5%+: ${m.hitRate!=null?m.hitRate.toFixed(0)+'%':'—'}</small></div>
      </div><div class="note">המדד הוא הסתברותי ולא יודע לזהות שיא עתידי בוודאות. RSI ${m.rsi!=null?m.rsi.toFixed(0):'—'}, מרחק משיא 20 יום ${m.dist20.toFixed(1)}%.</div>`;
    }catch(e){body.textContent='לא הצלחתי לבנות כרגע מודל זמן למניה הזאת.'}
  }

  async function validSymbol(s){try{if(!s||SKIP.has(s)||s.length>5)return false;const r=await fetch('/api/stock/'+encodeURIComponent(s)+'/bundle?range=1M',{cache:'no-store'});if(!r.ok)return false;const j=await r.json();return !!(j?.quote?.price||(j?.bars||[]).length)}catch(e){return false}}
  function numbersNear(line){return [...String(line).matchAll(/-?\d+(?:[.,]\d+)?/g)].map(m=>Number(m[0].replace(',','.'))).filter(n=>Number.isFinite(n)&&n>=0)}
  function inferRow(lines,idx,sym){
    const chunk=lines.slice(Math.max(0,idx-1),Math.min(lines.length,idx+3)).join(' ');
    let q=null,b=null;
    const qm=chunk.match(/(?:qty|quantity|shares?|כמות|יחידות)\s*[:\-]?\s*(\d+(?:[.,]\d+)?)/i);if(qm)q=Number(qm[1].replace(',','.'));
    const bm=chunk.match(/(?:avg(?:erage)?\s*(?:price)?|cost\s*basis|buy\s*price|מחיר\s*(?:קניה|קנייה|ממוצע)|עלות\s*ממוצעת)\s*[:\-]?\s*[$₪]?\s*(\d+(?:[.,]\d+)?)/i);if(bm)b=Number(bm[1].replace(',','.'));
    if(q==null||b==null){const ns=numbersNear(chunk).filter(n=>n>0);if(q==null&&ns.length)q=ns.find(n=>n<100000)||null;if(b==null&&ns.length>1)b=ns.find(n=>n>0&&n!==q)||null}
    return {sym,qty:q,buy:b};
  }
  async function scanPortfolio(file){
    const st=document.getElementById('ocrStatus'),raw=document.getElementById('ocrRaw'),rows=document.getElementById('ocrRows');
    st.textContent='קורא צילום ומצליב סימולים, כמות ומחיר ממוצע...';
    try{
      let text='';try{text=(await Tesseract.recognize(file,'heb+eng')).data.text||''}catch(_){text=(await Tesseract.recognize(file,'eng')).data.text||''}
      raw.value=text;const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),cands=[];
      lines.forEach((line,idx)=>{for(const m of line.toUpperCase().matchAll(/\b[A-Z]{1,5}\b/g)){const s=m[0];if(!SKIP.has(s))cands.push({s,idx})}});
      const uniq=[];for(const x of cands){if(!uniq.some(y=>y.s===x.s))uniq.push(x)}
      const checks=await Promise.all(uniq.slice(0,30).map(async x=>({...x,ok:await validSymbol(x.s)})));const good=checks.filter(x=>x.ok).slice(0,15);
      rows.innerHTML='';for(const x of good){const r=inferRow(lines,x.idx,x.s);addOcrRow(r.sym,r.qty??'',r.buy??'')}
      if(!good.length)addOcrRow();
      st.textContent=good.length?`זוהו ${good.length} מניות. בדוק את הכמות והמחיר לפני שמירה; מניה קיימת תעודכן ולא תשוכפל.`:'לא זוהתה מניה בוודאות; אפשר להשלים ידנית.';
    }catch(e){st.textContent='הסריקה נכשלה; לא שיניתי את התיק.'}
  }
  function installPortfolioPatch(){
    const i=document.getElementById('imgInput');if(i)i.onchange=async e=>{const f=e.target.files?.[0];if(f)await scanPortfolio(f)};
    window.saveOcrRows=function(){
      let changed=0;const today=new Date().toISOString().slice(0,10);
      document.querySelectorAll('#ocrRows tr').forEach(tr=>{
        const s=tr.querySelector('.os')?.value.trim().toUpperCase(),q=Number(tr.querySelector('.oq')?.value),b=Number(tr.querySelector('.ob')?.value);
        if(!s||!Number.isFinite(q)||q<0||!Number.isFinite(b)||b<=0)return;
        const idx=holdings.findIndex(h=>String(h.symbol).toUpperCase()===s);
        if(q===0){if(idx>=0){holdings.splice(idx,1);changed++}return}
        const item={symbol:s,qty:q,buyPrice:b,date:idx>=0?(holdings[idx].date||today):today,currentPrice:null,updatedAt:new Date().toISOString()};
        if(idx>=0)holdings[idx]={...holdings[idx],...item};else holdings.push(item);changed++;
      });
      if(!changed){alert('אין שורות תקינות לעדכון.');return}
      saveHoldings();closeModal('importModal');renderPortfolio();alert('התיק עודכן לפי צילום המסך. מניות קיימות עודכנו במקום להיווצר מחדש.');
    };
  }
  function installTimingHook(){
    const original=window.openDetail;if(typeof original!=='function')return;
    window.openDetail=async function(type,ticker){const x=await original(type,ticker);setTimeout(()=>loadTiming(ticker),80);return x};
  }
  window.addEventListener('load',()=>{setTimeout(()=>{installPortfolioPatch();installTimingHook()},700)},{once:true});
})();
</script>'''
        if 'portfolio-timing-ocr-r12' not in html:
            html = html.replace('</body>', feature_patch + '\n</body>', 1)

        cleanup = """<script>
window.addEventListener('load',()=>{
  setTimeout(async()=>{
    try{
      if('serviceWorker' in navigator){
        const regs=await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(r=>r.unregister()));
      }
      if(window.caches){
        const keys=await caches.keys();
        await Promise.all(keys.map(k=>caches.delete(k)));
      }
    }catch(e){console.warn('PWA cleanup skipped',e)}
  },1500);
},{once:true});
</script>"""
        html = html.replace('</body>', cleanup + '\n</body>', 1)
        return html

    def _safe_file_response(path, *args, **kwargs):
        p = Path(path)
        if p.name == 'index.html' and p.parent.name == 'static' and p.exists():
            headers = dict(kwargs.pop('headers', None) or {})
            headers.update({'Cache-Control':'no-cache, no-store, must-revalidate','Pragma':'no-cache','Expires':'0'})
            return HTMLResponse(content=_safe_index(p),status_code=kwargs.pop('status_code',200),headers=headers)
        return _OriginalFileResponse(path,*args,**kwargs)

    _responses.FileResponse = _safe_file_response
    print('V22_MINIMAL_BOOT_INSTALLED=true',flush=True)
    print('DAY_SCAN_LAST_GOOD_GUARD_R11=true',flush=True)
    print('PORTFOLIO_TIMING_OCR_R12=true',flush=True)
except Exception as exc:
    print('V22_MINIMAL_BOOT_WARNING='+repr(exc),flush=True)
