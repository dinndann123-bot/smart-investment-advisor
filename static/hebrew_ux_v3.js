(()=>{
'use strict';
const $=id=>document.getElementById(id);
const safe=n=>Number.isFinite(+n)?+n:null;

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
    <div class="section-head"><div><h2 style="margin:0">🧠 מד הלמידה והאימות</h2><p>כמה פעמים השיטה צדקה בפועל, על כמה תרחישים זה מבוסס, ומה המרחק מיעד המחקר.</p></div><span class="ux-pill">יעד מחקר: 90%+</span></div>
    <div class="ux-research-grid">
      <div class="ux-research-card"><span>תרחישים שנבדקו</span><b id="uxScenarios">—</b><div class="small">איתותים היסטוריים שנמדדו בפועל</div></div>
      <div class="ux-research-card"><span>הצלחות</span><b id="uxWins">—</b><div class="small">יעד 1 הושג לפני עצירת הפסד</div></div>
      <div class="ux-research-card"><span>אחוז הצלחה אמיתי</span><b id="uxRate">—</b><div class="ux-progress"><i id="uxRateBar" style="width:0%"></i></div></div>
      <div class="ux-research-card"><span>תוחלת לתרחיש</span><b id="uxExpectancy">—</b><div class="small">ממוצע R — לא אחוז תשואה</div></div>
    </div>
    <div id="uxGoalText" class="ux-tip">טוען נתוני אימות…</div>
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
  // Find smallest k such that (wins+k)/(total+k) > 0.90.
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
      ?`היעד עבר כרגע: ${wins}/${total} הצלחות = ${rate.toFixed(1)}%. עדיין נדרש להמשיך לאמת על תרחישים חדשים כדי לוודא שהיתרון נשמר.`
      :`נכון לעכשיו: ${wins}/${total} הצלחות = ${rate.toFixed(1)}%. כדי לעבור 90% במדגם המצטבר נדרשות לפחות ${k??'—'} הצלחות נוספות ברצף. זה יעד מחקר — לא הבטחה.`;
  }catch(e){
    if($('uxGoalText'))$('uxGoalText').textContent='עדיין אין מספיק נתוני אימות שמורים להצגת מד הלמידה.';
  }
}

function addTermHelp(){
  const terms={
    'VWAP':'מחיר ממוצע משוקלל לפי מחזור המסחר.',
    'RVOL':'מחזור יחסי: כמה המחזור חריג לעומת הרגיל במניה.',
    'ATR(14)':'מדד לתנודתיות המחיר ב־14 תקופות.',
    'תוחלת R':'התוצאה הממוצעת ביחידות סיכון. R אחד = הסיכון שהוגדר לעסקה.',
    'שיעור איתור':'כמה מהימים שהתפוצצו בפועל השיטה הצליחה לזהות.',
    'פער פתיחה':'הפער בין מחיר הפתיחה למחיר הסגירה הקודם.'
  };
  document.querySelectorAll('span,th,h3,h4').forEach(el=>{
    const txt=el.textContent.trim();if(!terms[txt]||el.querySelector('.ux-help'))return;
    const b=document.createElement('button');b.className='ux-help';b.type='button';b.textContent='?';b.title=terms[txt];b.setAttribute('aria-label',terms[txt]);el.append(' ',b);
  });
}

function installChartStates(){
  const configs=[['detailChart','detailChartSection'],['fiveYearChart','fiveYearProfile'],['portfolioChart','portfolioChartWrap']];
  configs.forEach(([canvasId,parentId])=>{
    const parent=$(parentId),canvas=$(canvasId);if(!parent||!canvas||parent.querySelector('.ux-chart-state'))return;
    const st=document.createElement('div');st.className='ux-chart-state';st.dataset.for=canvasId;
    st.innerHTML='<div><b>טוען גרף…</b><span>מביא נתוני מחיר מהשרת</span></div>';parent.appendChild(st);
  });
}
function showChartState(canvasId,title,text){
  const st=document.querySelector(`.ux-chart-state[data-for="${canvasId}"]`);if(!st)return;
  st.innerHTML=`<div><b>${title}</b><span>${text}</span></div>`;st.classList.add('show');
}
function hideChartState(canvasId){document.querySelector(`.ux-chart-state[data-for="${canvasId}"]`)?.classList.remove('show')}

function improveImageImport(){
  const input=$('imgInput'),modal=$('importModal');if(!input||!modal||$('uxImagePreview'))return;
  const preview=document.createElement('img');preview.id='uxImagePreview';preview.className='ux-image-preview';preview.alt='תצוגה מקדימה של צילום המסך שנבחר';
  input.closest('.upload')?.insertAdjacentElement('afterend',preview);
  const steps=document.createElement('div');steps.className='ux-ocr-steps';steps.id='uxOcrSteps';steps.innerHTML='<span class="ux-step" data-s="1">1. בחירת תמונה</span><span class="ux-step" data-s="2">2. זיהוי טקסט</span><span class="ux-step" data-s="3">3. בדיקת נתונים</span><span class="ux-step" data-s="4">4. שמירה לתיק</span>';
  preview.insertAdjacentElement('afterend',steps);
  input.addEventListener('change',()=>{
    const f=input.files?.[0];if(!f)return;
    preview.src=URL.createObjectURL(f);preview.classList.add('show');
    steps.querySelector('[data-s="1"]')?.classList.add('on');
    const status=$('ocrStatus');if(status)status.textContent='התמונה נבחרה. מתחיל לזהות מניות ונתוני קנייה…';
  },true);
  const observer=new MutationObserver(()=>{
    const t=$('ocrStatus')?.textContent||'';
    if(/קורא|מזהה|זיהוי/.test(t))steps.querySelector('[data-s="2"]')?.classList.add('on');
    if(/הסתיים|בדוק/.test(t))steps.querySelector('[data-s="3"]')?.classList.add('on');
  });
  if($('ocrStatus'))observer.observe($('ocrStatus'),{childList:true,characterData:true,subtree:true});
}

function translateStaticLabels(){
  hebrewizeText();
  document.querySelectorAll('.score').forEach(x=>x.title='זהו ציון התאמה לשיטה מתוך 100 — לא אחוז תשואה ולא הסתברות מובטחת.');
  const dScore=$('dScore');if(dScore?.nextElementSibling?.tagName==='SPAN')dScore.nextElementSibling.textContent='ציון התאמה לשיטה';
  const scoreHeaders=[...document.querySelectorAll('th')].filter(x=>x.textContent.trim()==='ציון');scoreHeaders.forEach(x=>x.textContent='ציון השיטה');
}

function monitorChartNotes(){
  const map=[['chartNote','detailChart'],['portfolioChartNote','portfolioChartNote']];
  map.forEach(([noteId,canvasId])=>{
    const n=$(noteId);if(!n)return;
    const obs=new MutationObserver(()=>{
      const t=n.textContent||'';
      if(/טוען/.test(t))showChartState(canvasId,'טוען גרף…','מביא נתונים ומכין את התצוגה');
      else if(/אין|לא ניתן|נדרש API|שגיאה/.test(t))showChartState(canvasId,'הגרף לא זמין כרגע',t);
      else hideChartState(canvasId);
    });obs.observe(n,{childList:true,characterData:true,subtree:true});
  });
}

function init(){
  addResearchPanel();translateStaticLabels();addTermHelp();installChartStates();monitorChartNotes();improveImageImport();loadResearchMeter();
  setInterval(loadResearchMeter,5*60*1000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
