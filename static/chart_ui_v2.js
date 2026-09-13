// Clear chart renderer v2: explicit time and price axes for day/month/year views.
(function(){
  const fmtPrice=v=>Number.isFinite(v)?'$'+v.toLocaleString('en-US',{maximumFractionDigits:v<10?3:2}):'—';
  function parseDate(v){const d=new Date(v);return Number.isNaN(d.getTime())?null:d;}
  function inferRange(rows){
    if(!rows?.length)return 'empty';
    const a=parseDate(rows[0].d), b=parseDate(rows[rows.length-1].d);
    if(!a||!b)return 'generic';
    const days=(b-a)/86400000;
    if(days<=2)return 'day';
    if(days<=45)return 'month';
    if(days<=550)return 'year';
    return 'multi';
  }
  function fmtX(raw,range){
    const d=parseDate(raw);if(!d)return String(raw||'').slice(0,10);
    if(range==='day')return d.toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'America/New_York'});
    if(range==='month')return d.toLocaleDateString('he-IL',{day:'2-digit',month:'2-digit'});
    if(range==='year')return d.toLocaleDateString('he-IL',{month:'short',year:'2-digit'});
    return d.toLocaleDateString('he-IL',{month:'short',year:'numeric'});
  }
  window.draw=function(canvasId,pts,buyPrice){
    const canvas=document.getElementById(canvasId);if(!canvas)return;
    const ctx=canvas.getContext('2d');
    const rect=canvas.getBoundingClientRect();
    const dpr=Math.max(1,window.devicePixelRatio||1);
    const cssW=Math.max(320,rect.width||canvas.clientWidth||800), cssH=Math.max(250,rect.height||canvas.clientHeight||300);
    canvas.width=Math.round(cssW*dpr);canvas.height=Math.round(cssH*dpr);ctx.scale(dpr,dpr);
    const W=cssW,H=cssH;ctx.clearRect(0,0,W,H);
    const rows=(pts||[]).filter(x=>Number.isFinite(+x.v));
    ctx.font='12px Arial';ctx.textBaseline='middle';
    if(rows.length<2){ctx.fillStyle='#7b8498';ctx.textAlign='center';ctx.fillText('אין מספיק נתונים להצגת גרף',W/2,H/2);return;}
    const vals=rows.map(x=>+x.v);let mn=Math.min(...vals),mx=Math.max(...vals);if(mx===mn){mx*=1.01;mn*=.99}
    const pad=(mx-mn)*.06;mn-=pad;mx+=pad;
    const L=18,R=74,T=22,B=46, plotW=W-L-R, plotH=H-T-B;
    const x=i=>L+(i/(rows.length-1))*plotW;
    const y=v=>T+(1-(v-mn)/(mx-mn))*plotH;
    // horizontal grid + right price axis
    ctx.lineWidth=1;ctx.strokeStyle='#e6ebf3';ctx.fillStyle='#657188';ctx.textAlign='left';
    for(let i=0;i<=4;i++){
      const yy=T+(plotH*i/4), pv=mx-(mx-mn)*i/4;
      ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);ctx.stroke();
      ctx.fillText(fmtPrice(pv),W-R+8,yy);
    }
    // x axis with explicit time scale
    const range=inferRange(rows);const ticks=Math.min(6,rows.length);
    ctx.textAlign='center';ctx.fillStyle='#657188';
    for(let i=0;i<ticks;i++){
      const idx=Math.round(i*(rows.length-1)/(ticks-1));const xx=x(idx);
      ctx.beginPath();ctx.strokeStyle='#eef1f6';ctx.moveTo(xx,T);ctx.lineTo(xx,H-B);ctx.stroke();
      ctx.fillText(fmtX(rows[idx].d,range),xx,H-B+18);
    }
    const xLabel=range==='day'?'שעה (ניו־יורק)':range==='month'?'יום בחודש':range==='year'?'חודש / שנה':'שנה';
    ctx.font='bold 11px Arial';ctx.fillText(xLabel,L+plotW/2,H-10);
    ctx.save();ctx.translate(W-12,T+plotH/2);ctx.rotate(Math.PI/2);ctx.fillText('מחיר מניה ($)',0,0);ctx.restore();
    // buy price line
    if(Number.isFinite(+buyPrice)&&+buyPrice>=mn&&+buyPrice<=mx){
      const yy=y(+buyPrice);ctx.save();ctx.setLineDash([6,5]);ctx.strokeStyle='#7b61ff';ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);ctx.stroke();ctx.restore();
      ctx.fillStyle='#7b61ff';ctx.textAlign='left';ctx.font='11px Arial';ctx.fillText('מחיר קנייה '+fmtPrice(+buyPrice),L+5,Math.max(T+10,yy-9));
    }
    // line
    ctx.beginPath();rows.forEach((r,i)=>{const xx=x(i),yy=y(+r.v);if(i===0)ctx.moveTo(xx,yy);else ctx.lineTo(xx,yy)});ctx.strokeStyle='#315bea';ctx.lineWidth=2.3;ctx.stroke();
    // last point
    const last=rows[rows.length-1];ctx.fillStyle='#315bea';ctx.beginPath();ctx.arc(x(rows.length-1),y(+last.v),3.5,0,Math.PI*2);ctx.fill();
    ctx.fillStyle='#152033';ctx.textAlign='right';ctx.font='bold 11px Arial';ctx.fillText('אחרון '+fmtPrice(+last.v),W-R-2,T+10);
  };
  const redraw=()=>{try{if(window.portfolioSymbol&&window.loadPChart)window.loadPChart();if(window.selected&&window.loadDetailחי)window.loadDetailחי()}catch(e){}};
  window.addEventListener('resize',()=>{clearTimeout(window.__chartResizeT);window.__chartResizeT=setTimeout(redraw,180)});
})();
