/* Read-only previous session comparison; never touches live ranking. */
(function(){
  const root=document.getElementById('page-home');
  if(!root)return;
  const card=document.createElement('section');
  card.className='card';
  card.style.margin='16px 0';
  card.innerHTML='<h3 style="margin:0 0 8px;color:#f2ce76">10 המניות מיום המסחר הקודם — התפתחות ממוצעת לאחר האיתות</h3><p class="small" id="research-timing-note">טוען נתונים שמורים…</p><canvas id="research-timing-chart" style="height:240px;max-height:240px"></canvas>';
  root.appendChild(card);
  const note=card.querySelector('#research-timing-note');
  const canvas=card.querySelector('canvas');
  function draw(data){
    const values=data.average_return_pct||[];
    if(!values.length||values.every(v=>v==null)){note.textContent='אין מספיק נתונים שמורים לגרף';return;}
    note.textContent='תאריך: '+data.trade_date+' | '+data.count+' מניות | ממוצע שינוי מהאיתות, לא מהפתיחה. הנתונים אינם מאשרים חלון כניסה מיטבי.';
    const dpr=window.devicePixelRatio||1,w=Math.max(300,canvas.clientWidth),h=240;
    canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);
    const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
    const v=values.filter(x=>x!=null);const lo=Math.min(0,...v),hi=Math.max(0,...v);const span=Math.max(.1,hi-lo);
    const x=i=>44+(w-64)*i/(values.length-1),y=v=>20+(h-55)*(hi-v)/span;
    ctx.strokeStyle='#5c6d77';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(44,y(0));ctx.lineTo(w-20,y(0));ctx.stroke();
    ctx.strokeStyle='#e6b65b';ctx.lineWidth=2.5;ctx.beginPath();
    values.forEach((v,i)=>{if(v==null)return;if(i===0)ctx.moveTo(x(i),y(v));else ctx.lineTo(x(i),y(v));});ctx.stroke();
    ctx.fillStyle='#dce6e9';ctx.font='12px Arial';ctx.textAlign='center';
    (data.minutes_after_signal||[]).forEach((m,i)=>ctx.fillText(m+' דק׳',x(i),h-12));
    ctx.textAlign='left';ctx.fillText(hi.toFixed(2)+'%',4,18);ctx.fillText(lo.toFixed(2)+'%',4,h-35);
  }
  fetch('/api/research/previous-session-timing',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json()}).then(draw).catch(()=>{note.textContent='נתוני המחקר אינם זמינים כרגע';canvas.style.display='none';});
})();
