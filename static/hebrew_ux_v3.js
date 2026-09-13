(()=>{
'use strict';
const $=id=>document.getElementById(id);
const safe=n=>Number.isFinite(+n)?+n:null;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const replacements=[
  ['Backtest','בדיקת עבר'],['BACKTEST','בדיקת עבר'],['Universe','מאגר מניות'],['False Positive','איתות שווא'],
  ['Recall','שיעור איתור'],['Expectancy','תוחלת R'],['Feed','ערוץ נתונים'],['WebSocket','חיבור חי'],
  ['Premarket','טרום־מסחר'],['Gap','פער פתיחה'],['Target 1','יעד 1'],['Target 2','יעד 2']
];
function hebrewizeText(root=document.body){
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:n=>{
    if(!n.parentElement)return NodeFilter.FILTER_REJECT;
    if(['SCRIPT','STYLE','TEXTAREA','INPUT'].includes(n.parentElement.tagName))return NodeFilter.FILTER_REJECT;
    return NodeFilter.FILTER_ACCEPT;
  }});
  const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  nodes.forEach(n=>{let t=n.nodeValue;replacements.forEach(([a,b])=>{t=t.split(a).join(b)});n.nodeValue=t});
}

function addResearchPanel(){
  const home=$('page-home'); if(!home||$('uxResearchPanel'))return;
  const panel=document.createElement('section');
  panel.id='uxResearchPanel';panel.className='card ux-research-panel';
  panel.innerHTML=`
    <div class="ux-research-hero">
      <div><span class="ux-eyebrow">מחקר השיטה בזמן אמת</span><h2>🧠 מד הלמידה והאימות</h2><p>כאן רואים כמה בדיקות בוצעו, כמה הצליחו, ואיך ביצועי השיטה משתנים ככל שנצברים תרחישים חדשים.</p></div>
      <span class="ux-pill">יעד מחקר: 90%+</span>
    </div>
    <div class="ux-research-grid">
      <div class="ux-research-card"><span>תרחישים שנבדקו</span><b id="uxScenarios">—</b><div class="small">אימות למסחר יומי לפי T1</div></div>
      <div class="ux-research-card"><span>הצלחות</span><b id="uxWins">—</b><div class="small">יעד 1 הושג לפני עצירת הפסד</div></div>
      <div class="ux-research-card"><span>אחוז הצלחה אמיתי</span><b id="uxRate">—</b><div class="ux-progress"><i id="uxRateBar" style="width:0%"></i></div></div>
      <div class="ux-research-card"><span>תוחלת לתרחיש</span><b id="uxExpectancy">—</b><div class="small">ממוצע R — לא אחוז תשואה</div></div>
    </div>
    <div id="uxGoalText" class="ux-tip">טוען נתוני אימות…</div>
    <div class="ux-learning-chart-card">
      <div class="ux-chart-head">
        <div><span class="ux-eyebrow">50 תרחישים היסטוריים · אסטרטגיית חודשי/שנתי</span><h3>עקומת הלמידה וההצלחה</h3><p>כל נקודה מוסיפה עוד 10 תרחישים למחקר. הקווים מציגים הצלחה מצטברת של בחירות השיטה, בלי לערבב עם מדד T1 של המסחר היומי.</p></div>
        <div class="ux-legend"><span><i class="m1"></i> חודש</span><span><i class="y1"></i> 12 חודשים</span><span><i class="goal"></i> יעד 90%</span></div>
      </div>
      <div id="uxLearningChart" class="ux-learning-chart"><div class="ux-chart-loading">טוען עקומת למידה…</div></div>
      <div id="uxLearningSummary" class="ux-learning-summary"></div>
    </div>
    <div class="ux-actions">
      <button class="btn btn-primary" onclick="document.getElementById('homeLearningPanel')?.scrollIntoView({behavior:'smooth'})">פתח פירוט למידה</button>
      <button class="btn btn-secondary" onclick="window.go?.('lab')">מעבדת בדיקות עבר</button>
      <button class="btn btn-secondary" onclick="window.go?.('day')">מניות למסחר יומי</button>
      <button class="btn btn-secondary" onclick="window.go?.('long')">מניות לחודשי/שנתי</button>
    </div>`;
  const firstGrid=home.querySelector('.home-grid');
  if(firstGrid) firstGrid.insertAdjacentElement('afterend',panel); else home.prepend(panel);
}

function successesNeededFor90(wins,total){
  if(!Number.isFinite(wins)||!Number.isFinite(total)||total<0)return null;
  if(total>0 && wins/total>0.90)return 0;
  for(let k=1;k<10000;k++) if((wins+k)/(total+k)>0.90)return k;
  return null;
}
async function loadResearchMeter(){
  try{
    const r=await fetch('/api/learning/summary',{cache:'no-store'});const j=await r.json();
    if(!r.ok||!j.has_data)throw new Error('no data');
    const total=safe(j.signals)??0,wins=safe(j.correct_target1)??0,rate=safe(j.success_rate_pct)??0,exp=safe(j.expectancy_r);
    $('uxScenarios').textContent=total.toLocaleString('he-IL');
    $('uxWins').textContent=`${wins.toLocaleString('he-IL')} מתוך ${total.toLocaleString('he-IL')}`;
    $('uxRate').textContent=rate.toFixed(1)+'%';$('uxRate').className=rate>=90?'good':rate>=70?'warn':'';
    $('uxRateBar').style.width=Math.max(0,Math.min(100,rate))+'%';
    $('uxExpectancy').textContent=exp==null?'—':exp.toFixed(2)+'R';
    const k=successesNeededFor90(wins,total);
    $('uxGoalText').textContent=rate>90
      ?`נכון ${wins} מתוך ${total} — הצלחה ${rate.toFixed(1)}%. היעד עבר כרגע, אך ממשיכים לאמת על תרחישים חדשים כדי לוודא שהוא נשמר.`
      :`נכון ${wins} מתוך ${total} — הצלחה ${rate.toFixed(1)}%. כדי לעבור 90% במדגם המצטבר נדרשות לפחות ${k??'—'} הצלחות נוספות ברצף. זה יעד מחקר — לא הבטחה.`;
  }catch(e){
    if($('uxGoalText'))$('uxGoalText').textContent='עדיין אין מספיק נתוני אימות שמורים להצגת מד הלמידה.';
  }
}

function cumulativeLearningPoints(batches){
  let picks=0,w1=0,w12=0;
  return batches.map((b,i)=>{
    const n=safe(b?.summary?.picks)??0;
    const r1=safe(b?.summary?.success_1m_pct)??0;
    const r12=safe(b?.summary?.success_12m_pct)??0;
    picks+=n;w1+=n*r1/100;w12+=n*r12/100;
    return {label:`${(i+1)*10}`,scenarios:(i+1)*10,picks,one:picks?100*w1/picks:0,year:picks?100*w12/picks:0,preset:b?.preset_used||''};
  });
}
function renderLearningChart(points){
  const root=$('uxLearningChart');if(!root||!points.length)return;
  const W=760,H=300,L=48,R=18,T=22,B=42,plotW=W-L-R,plotH=H-T-B;
  const x=i=>L+(points.length===1?plotW/2:i*plotW/(points.length-1));
  const y=v=>T+(100-Math.max(0,Math.min(100,v)))*plotH/100;
  const ticks=[0,25,50,75,90,100];
  const line=key=>points.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(1)} ${y(p[key]).toFixed(1)}`).join(' ');
  const dots=(key,cls)=>points.map((p,i)=>`<circle class="${cls}" cx="${x(i)}" cy="${y(p[key])}" r="4.5"><title>${p.scenarios} תרחישים · ${key==='one'?'חודש':'12 חודשים'}: ${p[key].toFixed(1)}%</title></circle>`).join('');
  root.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="עקומת הלמידה וההצלחה של השיטה">
    <g class="ux-grid-lines">${ticks.map(v=>`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"></line><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${v}%</text>`).join('')}</g>
    <line class="ux-goal-line" x1="${L}" x2="${W-R}" y1="${y(90)}" y2="${y(90)}"></line>
    <path class="ux-line ux-line-m1" d="${line('one')}"></path><path class="ux-line ux-line-y1" d="${line('year')}"></path>
    ${dots('one','ux-dot ux-dot-m1')}${dots('year','ux-dot ux-dot-y1')}
    <g class="ux-x-labels">${points.map((p,i)=>`<text x="${x(i)}" y="${H-14}" text-anchor="middle">${p.scenarios}</text>`).join('')}<text x="${W/2}" y="${H-1}" text-anchor="middle" class="axis-title">תרחישים שנבדקו</text></g>
  </svg>`;
}
async function loadLearningCurve(){
  const root=$('uxLearningChart');if(!root)return;
  try{
    const r=await fetch('/api/strategy/long/research-50',{cache:'no-store'});const j=await r.json();
    const batches=Array.isArray(j?.batches)?j.batches:[];
    if(!r.ok||!batches.length)throw new Error('no batches');
    const points=cumulativeLearningPoints(batches);renderLearningChart(points);
    const last=points[points.length-1],overall=j.overall||{};
    const scenarios=safe(overall.scenario_count)??last.scenarios;
    const picks=safe(overall.stock_pick_count)??last.picks;
    $('uxLearningSummary').innerHTML=`<div><span>אחרי ${scenarios} תרחישים</span><b>${last.one.toFixed(1)}%</b><small>הצלחה מצטברת אחרי חודש</small></div><div><span>אחרי ${scenarios} תרחישים</span><b>${last.year.toFixed(1)}%</b><small>הצלחה מצטברת אחרי 12 חודשים</small></div><div><span>בחירות שנמדדו</span><b>${picks}</b><small>עד 10 מניות בכל תרחיש</small></div>`;
  }catch(e){
    root.innerHTML='<div class="ux-chart-error">אין כרגע נתוני מחקר זמינים לגרף. הנתונים לא יומצאו — הגרף יוצג רק כשיש תוצאות אמיתיות מהשרת.</div>';
  }
}

function addTermHelp(){
  const terms={'VWAP':'מחיר ממוצע משוקלל לפי מחזור המסחר.','RVOL':'מחזור יחסי: כמה המחזור חריג לעומת הרגיל במניה.','ATR(14)':'מדד לתנודתיות המחיר ב־14 תקופות.','תוחלת R':'התוצאה הממוצעת ביחידות סיכון. R אחד = הסיכון שהוגדר לעסקה.','שיעור איתור':'כמה מהימים שהתפוצצו בפועל השיטה הצליחה לזהות.','פער פתיחה':'הפער בין מחיר הפתיחה למחיר הסגירה הקודם.'};
  document.querySelectorAll('span,th,h3,h4').forEach(el=>{const txt=el.textContent.trim();if(!terms[txt]||el.querySelector('.ux-help'))return;const b=document.createElement('button');b.className='ux-help';b.type='button';b.textContent='?';b.title=terms[txt];b.setAttribute('aria-label',terms[txt]);el.append(' ',b)});
}
function installChartStates(){const configs=[['detailChart','detailChartSection'],['fiveYearChart','fiveYearProfile'],['portfolioChart','portfolioChartWrap']];configs.forEach(([canvasId,parentId])=>{const parent=$(parentId),canvas=$(canvasId);if(!parent||!canvas||parent.querySelector('.ux-chart-state'))return;const st=document.createElement('div');st.className='ux-chart-state';st.dataset.for=canvasId;st.innerHTML='<div><b>טוען גרף…</b><span>מביא נתוני מחיר מהשרת</span></div>';parent.appendChild(st)})}
function showChartState(canvasId,title,text){const st=document.querySelector(`.ux-chart-state[data-for="${canvasId}"]`);if(!st)return;st.innerHTML=`<div><b>${esc(title)}</b><span>${esc(text)}</span></div>`;st.classList.add('show')}
function hideChartState(canvasId){document.querySelector(`.ux-chart-state[data-for="${canvasId}"]`)?.classList.remove('show')}
function improveImageImport(){const input=$('imgInput'),modal=$('importModal');if(!input||!modal||$('uxImagePreview'))return;const preview=document.createElement('img');preview.id='uxImagePreview';preview.className='ux-image-preview';preview.alt='תצוגה מקדימה של צילום המסך שנבחר';input.closest('.upload')?.insertAdjacentElement('afterend',preview);const steps=document.createElement('div');steps.className='ux-ocr-steps';steps.id='uxOcrSteps';steps.innerHTML='<span class="ux-step" data-s="1">1. בחירת תמונה</span><span class="ux-step" data-s="2">2. זיהוי טקסט</span><span class="ux-step" data-s="3">3. בדיקת נתונים</span><span class="ux-step" data-s="4">4. שמירה לתיק</span>';preview.insertAdjacentElement('afterend',steps);input.addEventListener('change',()=>{const f=input.files?.[0];if(!f)return;preview.src=URL.createObjectURL(f);preview.classList.add('show');steps.querySelector('[data-s="1"]')?.classList.add('on');const status=$('ocrStatus');if(status)status.textContent='התמונה נבחרה. מתחיל לזהות מניות ונתוני קנייה…'},true)}
function translateStaticLabels(){hebrewizeText();document.querySelectorAll('.score').forEach(x=>x.title='זהו ציון התאמה לשיטה מתוך 100 — לא אחוז תשואה ולא הסתברות מובטחת.');const dScore=$('dScore');if(dScore?.nextElementSibling?.tagName==='SPAN')dScore.nextElementSibling.textContent='ציון התאמה לשיטה';[...document.querySelectorAll('th')].filter(x=>x.textContent.trim()==='ציון').forEach(x=>x.textContent='ציון השיטה')}
function monitorChartNotes(){const map=[['chartNote','detailChart'],['portfolioChartNote','portfolioChart']];map.forEach(([noteId,canvasId])=>{const n=$(noteId);if(!n)return;const obs=new MutationObserver(()=>{const t=n.textContent||'';if(/טוען/.test(t))showChartState(canvasId,'טוען גרף…','מביא נתונים ומכין את התצוגה');else if(/אין|לא ניתן|נדרש API|שגיאה/.test(t))showChartState(canvasId,'הגרף לא זמין כרגע',t);else hideChartState(canvasId)});obs.observe(n,{childList:true,characterData:true,subtree:true})})}
function init(){addResearchPanel();translateStaticLabels();addTermHelp();installChartStates();monitorChartNotes();improveImageImport();loadResearchMeter();loadLearningCurve();setInterval(loadResearchMeter,5*60*1000)}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();