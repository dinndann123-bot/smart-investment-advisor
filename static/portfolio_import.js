// Portfolio screenshot importer v1
// Reads ticker, holding value and current share price from screenshots.
// The only required manual field is average buy price.
(function(){
  const moneyNum = s => {
    if(!s) return null;
    const n = Number(String(s).replace(/[^0-9.,-]/g,'').replace(/,/g,''));
    return Number.isFinite(n) && n>0 ? n : null;
  };
  const esc = s => String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const tickerOk = s => /^[A-Z]{1,6}(?:\.[A-Z])?$/.test(s||'') && !new Set(['USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','ETF','SHARE','SHARES']).has(s);

  function ensureTable(){
    const table=document.querySelector('#ocrRows')?.closest('table');
    if(!table)return;
    const h=table.querySelector('thead tr');
    if(h)h.innerHTML='<th>סימול</th><th>שווי בתמונה</th><th>מחיר נוכחי</th><th>כמות מחושבת</th><th>מחיר קנייה ממוצע</th><th></th>';
    table.style.minWidth='760px';
    const raw=document.getElementById('ocrRaw');
    if(raw){raw.style.display='none';raw.setAttribute('aria-hidden','true');}
    const st=document.getElementById('ocrStatus');
    if(st && !st.dataset.upgraded){st.textContent='העלה צילום מסך של התיק. המערכת תמלא סימול, שווי, מחיר נוכחי וכמות; אתה תשלים רק מחיר קנייה ממוצע.';st.dataset.upgraded='1';}
  }

  function recalcRow(tr){
    const value=moneyNum(tr.querySelector('.ov')?.value);
    const current=moneyNum(tr.querySelector('.oc')?.value);
    const q=(value&&current)?value/current:null;
    const qEl=tr.querySelector('.oq');
    if(qEl && q)qEl.value=q.toFixed(6).replace(/0+$/,'').replace(/\.$/,'');
  }

  window.addOcrRow=function(sym='',qty='',buy='',value='',current='',confidence=''){
    ensureTable();
    const body=document.getElementById('ocrRows');if(!body)return;
    body.insertAdjacentHTML('beforeend',`<tr>
      <td><input class="os" value="${esc(sym)}" autocapitalize="characters"></td>
      <td><input class="ov" type="number" step="0.01" value="${esc(value)}" placeholder="$ שווי"></td>
      <td><input class="oc" type="number" step="0.0001" value="${esc(current)}" placeholder="$ מחיר"></td>
      <td><input class="oq" type="number" step="0.000001" value="${esc(qty)}" placeholder="אוטומטי"></td>
      <td><input class="ob" type="number" step="0.0001" value="${esc(buy)}" placeholder="הזן ידנית"></td>
      <td><button class="btn btn-danger" onclick="this.closest('tr').remove()">מחק</button>${confidence?`<div class="small">זיהוי ${esc(confidence)}%</div>`:''}</td>
    </tr>`);
    const tr=body.lastElementChild;
    tr.querySelector('.ov')?.addEventListener('input',()=>recalcRow(tr));
    tr.querySelector('.oc')?.addEventListener('input',()=>recalcRow(tr));
    if(!qty)recalcRow(tr);
  };

  function groupWords(words){
    const clean=(words||[]).filter(w=>w?.text && w.confidence>=20).map(w=>({
      text:String(w.text).trim(), conf:Math.round(w.confidence||0),
      x:(w.bbox.x0+w.bbox.x1)/2, y:(w.bbox.y0+w.bbox.y1)/2, h:Math.max(1,w.bbox.y1-w.bbox.y0)
    })).filter(w=>w.text);
    const tickers=clean.filter(w=>tickerOk(w.text.toUpperCase())).map(w=>({...w,text:w.text.toUpperCase()}));
    const rows=[];
    for(const t of tickers){
      const near=clean.filter(w=>Math.abs(w.y-t.y)<=Math.max(36,t.h*1.7));
      let dollars=near.filter(w=>/^\$?\s*[0-9][0-9.,]*$/.test(w.text.replace(/\s/g,'')) || /\$/.test(w.text))
        .map(w=>({...w,n:moneyNum(w.text)})).filter(w=>w.n);
      // Blink screenshots place holding value left and current stock price right.
      dollars=dollars.sort((a,b)=>a.x-b.x);
      const value=dollars.length>=2?dollars[0].n:null;
      const current=dollars.length>=2?dollars[dollars.length-1].n:(dollars[0]?.n||null);
      if(value && current && value!==current){
        rows.push({symbol:t.text,value,current,qty:value/current,confidence:t.conf});
      }else{
        rows.push({symbol:t.text,value:null,current:null,qty:null,confidence:t.conf});
      }
    }
    const out=[];const seen=new Set();
    for(const r of rows){if(!seen.has(r.symbol)){seen.add(r.symbol);out.push(r)}}
    return out.slice(0,30);
  }

  function fallbackFromText(text){
    const lines=String(text||'').split(/\n+/).map(x=>x.trim()).filter(Boolean);
    const rows=[];
    for(let i=0;i<lines.length;i++){
      const m=lines[i].match(/\b([A-Z]{1,6}(?:\.[A-Z])?)\b/);if(!m||!tickerOk(m[1]))continue;
      const chunk=lines.slice(i,Math.min(lines.length,i+4)).join(' ');
      const nums=[...chunk.matchAll(/\$\s*([0-9][0-9.,]*)/g)].map(x=>moneyNum(x[1])).filter(Boolean);
      rows.push({symbol:m[1],value:nums[0]||null,current:nums[1]||null,qty:nums[0]&&nums[1]?nums[0]/nums[1]:null,confidence:''});
    }
    const seen=new Set();return rows.filter(r=>!seen.has(r.symbol)&&seen.add(r.symbol)).slice(0,30);
  }

  async function scanFile(f){
    const st=document.getElementById('ocrStatus');
    const body=document.getElementById('ocrRows');
    if(st)st.textContent='סורק את התמונה ומזהה את הפוזיציות...';
    if(body)body.innerHTML='';
    if(typeof Tesseract==='undefined')throw new Error('OCR library unavailable');
    const r=await Tesseract.recognize(f,'eng',{logger:m=>{if(st&&m.status==='recognizing text')st.textContent=`סורק... ${Math.round((m.progress||0)*100)}%`;}});
    const text=r?.data?.text||'';
    const raw=document.getElementById('ocrRaw');if(raw)raw.value=text;
    let rows=groupWords(r?.data?.words||[]);
    if(!rows.some(x=>x.value&&x.current))rows=fallbackFromText(text);
    rows.forEach(x=>window.addOcrRow(x.symbol,x.qty?x.qty.toFixed(6):'','',x.value||'',x.current||'',x.confidence));
    if(!rows.length)window.addOcrRow();
    const complete=rows.filter(x=>x.value&&x.current&&x.qty).length;
    if(st)st.textContent=rows.length?`זוהו ${rows.length} ניירות, ומתוכם ${complete} עם שווי ומחיר. בדוק את הנתונים והשלם רק מחיר קנייה ממוצע.`:'לא זוהו פוזיציות אוטומטית. אפשר להוסיף שורות ידנית.';
  }

  window.openImport=function(){
    ensureTable();
    const modal=document.getElementById('importModal');if(modal)modal.classList.add('open');
    const body=document.getElementById('ocrRows');if(body&&!body.children.length)window.addOcrRow();
  };

  window.saveOcrRows=function(){
    let n=0,missing=0;
    document.querySelectorAll('#ocrRows tr').forEach(tr=>{
      const s=tr.querySelector('.os')?.value.trim().toUpperCase();
      let q=moneyNum(tr.querySelector('.oq')?.value);
      const b=moneyNum(tr.querySelector('.ob')?.value);
      const value=moneyNum(tr.querySelector('.ov')?.value);
      const current=moneyNum(tr.querySelector('.oc')?.value);
      if(!q&&value&&current)q=value/current;
      if(s&&q&&b){
        holdings.push({symbol:s,qty:q,buyPrice:b,date:new Date().toISOString().slice(0,10),currentPrice:current||null,scannedValue:value||null,source:'screenshot'});n++;
      }else if(s)missing++;
    });
    if(!n){alert('יש להשלים מחיר קנייה ממוצע לפחות בשורה תקינה אחת.');return}
    saveHoldings();closeModal('importModal');renderPortfolio();
    if(missing)alert(`נשמרו ${n} פוזיציות. ${missing} שורות לא נשמרו כי חסר מחיר קנייה או נתון חיוני.`);
  };

  function bind(){
    ensureTable();
    const input=document.getElementById('imgInput');
    if(input){input.onchange=async e=>{const f=e.target.files?.[0];if(!f)return;try{await scanFile(f)}catch(err){const st=document.getElementById('ocrStatus');if(st)st.textContent='הסריקה נכשלה. אפשר לנסות צילום חד יותר או להזין ידנית.';console.error(err)}};
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind);else bind();
})();
