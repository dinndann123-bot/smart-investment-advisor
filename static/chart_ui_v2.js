// Premium chart renderer v3 — visual layer only. Prices/history are rendered exactly from supplied market/strategy data.
(function(){
'use strict';
const fmtPrice=v=>Number.isFinite(v)?'$'+v.toLocaleString('en-US',{maximumFractionDigits:v<10?3:2}):'—';
const parseDate=v=>{const d=new Date(v);return Number.isNaN(d.getTime())?null:d};
function inferRange(rows){if(!rows?.length)return'empty';const a=parseDate(rows[0].d),b=parseDate(rows.at(-1).d);if(!a||!b)return'generic';const days=(b-a)/86400000;return days<=2?'day':days<=45?'month':days<=550?'year':'multi'}
function fmtX(raw,range){const d=parseDate(raw);if(!d)return String(raw||'').slice(0,10);if(range==='day')return d.toLocaleTimeString('he-IL',{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:'America/New_York'});if(range==='month')return d.toLocaleDateString('he-IL',{day:'2-digit',month:'2-digit'});if(range==='year')return d.toLocaleDateString('he-IL',{month:'short',year:'2-digit'});return d.toLocaleDateString('he-IL',{month:'short',year:'numeric'})}
function rounded(ctx,x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath()}
window.draw=function(canvasId,pts,buyPrice){
 const canvas=document.getElementById(canvasId);if(!canvas)return;const ctx=canvas.getContext('2d'),rect=canvas.getBoundingClientRect(),dpr=Math.max(1,window.devicePixelRatio||1);const W=Math.max(320,rect.width||canvas.clientWidth||800),H=Math.max(260,rect.height||canvas.clientHeight||320);canvas.width=Math.round(W*dpr);canvas.height=Math.round(H*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
 const bg=ctx.createLinearGradient(0,0,0,H);bg.addColorStop(0,'#12171d');bg.addColorStop(1,'#0a0d11');ctx.fillStyle=bg;rounded(ctx,0,0,W,H,16);ctx.fill();
 const rows=(pts||[]).filter(x=>Number.isFinite(+x.v));ctx.font='12px system-ui,Arial';ctx.textBaseline='middle';if(rows.length<2){ctx.fillStyle='#8d96a1';ctx.textAlign='center';ctx.fillText('אין מספיק נתונים להצגת הגרף',W/2,H/2);return}
 const vals=rows.map(x=>+x.v);let mn=Math.min(...vals),mx=Math.max(...vals);if(mx===mn){mx+=Math.max(1,mx*.01);mn-=Math.max(1,mn*.01)}const pad=(mx-mn)*.08;mn-=pad;mx+=pad;const mobile=W<560,L=mobile?12:18,R=mobile?64:78,T=30,B=48,plotW=W-L-R,plotH=H-T-B,x=i=>L+(i/(rows.length-1))*plotW,y=v=>T+(1-(v-mn)/(mx-mn))*plotH;
 // subtle premium grid
 ctx.lineWidth=1;ctx.textAlign='left';for(let i=0;i<=4;i++){const yy=T+plotH*i/4,pv=mx-(mx-mn)*i/4;ctx.strokeStyle='rgba(154,164,176,.13)';ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);ctx.stroke();ctx.fillStyle='#89939f';ctx.font='11px system-ui,Arial';ctx.fillText(fmtPrice(pv),W-R+7,yy)}
 const range=inferRange(rows),ticks=Math.min(mobile?4:6,rows.length);ctx.textAlign='center';for(let i=0;i<ticks;i++){const idx=Math.round(i*(rows.length-1)/Math.max(1,ticks-1)),xx=x(idx);ctx.strokeStyle='rgba(154,164,176,.07)';ctx.beginPath();ctx.moveTo(xx,T);ctx.lineTo(xx,H-B);ctx.stroke();ctx.fillStyle='#7f8995';ctx.font='10px system-ui,Arial';ctx.fillText(fmtX(rows[idx].d,range),xx,H-B+18)}
 // area fill follows raw price series; no derived signal is created here
 const area=ctx.createLinearGradient(0,T,0,H-B);area.addColorStop(0,'rgba(231,184,75,.22)');area.addColorStop(1,'rgba(231,184,75,0)');ctx.beginPath();rows.forEach((r,i)=>i?ctx.lineTo(x(i),y(+r.v)):ctx.moveTo(x(i),y(+r.v)));ctx.lineTo(x(rows.length-1),H-B);ctx.lineTo(x(0),H-B);ctx.closePath();ctx.fillStyle=area;ctx.fill();
 // supplied buy price only — never inferred by the chart layer
 if(Number.isFinite(+buyPrice)&&+buyPrice>=mn&&+buyPrice<=mx){const yy=y(+buyPrice);ctx.save();ctx.setLineDash([6,5]);ctx.strokeStyle='rgba(244,212,119,.58)';ctx.beginPath();ctx.moveTo(L,yy);ctx.lineTo(W-R,yy);ctx.stroke();ctx.restore();ctx.fillStyle='#f4d477';ctx.textAlign='left';ctx.font='600 10px system-ui,Arial';ctx.fillText('מחיר קנייה '+fmtPrice(+buyPrice),L+5,Math.max(T+10,yy-10))}
 // gold price line with soft glow
 ctx.save();ctx.shadowColor='rgba(231,184,75,.30)';ctx.shadowBlur=8;ctx.beginPath();rows.forEach((r,i)=>i?ctx.lineTo(x(i),y(+r.v)):ctx.moveTo(x(i),y(+r.v)));ctx.strokeStyle='#e7b84b';ctx.lineWidth=2.4;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();ctx.restore();
 const last=rows.at(-1),lx=x(rows.length-1),ly=y(+last.v);ctx.fillStyle='#0c1014';ctx.strokeStyle='#f4d477';ctx.lineWidth=2;ctx.beginPath();ctx.arc(lx,ly,4.5,0,Math.PI*2);ctx.fill();ctx.stroke();
 const label='אחרון  '+fmtPrice(+last.v);ctx.font='700 11px system-ui,Arial';const tw=ctx.measureText(label).width+18,boxX=Math.max(L,Math.min(W-R-tw,lx-tw-8)),boxY=Math.max(T,ly-15);ctx.fillStyle='rgba(18,23,29,.96)';ctx.strokeStyle='rgba(231,184,75,.42)';rounded(ctx,boxX,boxY,tw,28,9);ctx.fill();ctx.stroke();ctx.fillStyle='#f4d477';ctx.textAlign='center';ctx.fillText(label,boxX+tw/2,boxY+14);
};
const redraw=()=>{try{if(window.portfolioSymbol&&window.loadPChart)window.loadPChart();if(window.selected&&window.loadDetailחי)window.loadDetailחי()}catch(e){console.warn('CHART_REDRAW',e)}};window.addEventListener('resize',()=>{clearTimeout(window.__chartResizeT);window.__chartResizeT=setTimeout(redraw,180)});
})();