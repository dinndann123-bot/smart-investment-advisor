(()=>{
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const he={Replay:'שחזור היסטורי','Paper Strategy':'תיק ניסוי של השיטה','Why this stock?':'למה המניה נבחרה?'};
function labelScores(){
  $$('.score').forEach(el=>{if(el.dataset.ux)return;el.dataset.ux='1';el.title='ציון השיטה: דירוג פנימי של התאמת המניה לתנאי השיטה. זה אינו אחוז העלייה של המניה ואינו הבטחת הצלחה.';const n=document.createElement('span');n.className='ux-score-label';n.textContent='ציון השיטה';el.after(n)});
  const d=$('#dScore');if(d){const p=d.parentElement?.querySelector('span');if(p)p.textContent='ציון השיטה / 100'}
}
function clarify(){
  const map={dChange:'שינוי מחיר בפועל',learnSuccess:'הצלחה היסטורית ליעד 1',learnT2:'הצלחה היסטורית ליעד 2',learnRecall:'שיעור איתור היסטורי',learnExpectancy:'תוחלת ממוצעת (R)',learnMissed:'מקרים חזקים שהשיטה פספסה'};
  Object.entries(map).forEach(([id,t])=>{const el=$('#'+id),s=el?.parentElement?.querySelector('span');if(s)s.textContent=t});
}
function addHelp(){
  [['#homeBestScore','הציון הגבוה ביותר כרגע לפי השיטה, מתוך 100.'],['#learnSuccess','אחוז האותות ההיסטוריים שהגיעו ליעד 1 לפני עצירת ההפסד.'],['#learnExpectancy','התוחלת הממוצעת של תוצאות השיטה ביחידות R.'],['#rvolVal','RVOL = מחזור יחסי לעומת המחזור הרגיל של המניה.'],['#vwapVal','VWAP = המחיר הממוצע המשוקלל לפי מחזור המסחר.'],['#atrVal','ATR = מדד לתנודתיות הממוצעת של המניה.']].forEach(([sel,txt])=>{const e=$(sel);if(!e||e.parentElement.querySelector('.ux-help'))return;const h=document.createElement('span');h.className='ux-help';h.textContent='?';h.title=txt;e.parentElement.append(h)})
}
function researchStrip(){
  const panel=$('#homeLearningPanel');if(!panel||$('#uxResearchStrip'))return;const d=document.createElement('div');d.id='uxResearchStrip';d.className='ux-research-strip';
  d.innerHTML='<div class="ux-chip"><b>שחזור היסטורי</b><span>בדיקת האות כאילו אנחנו נמצאים בתאריך עבר, בלי מידע מהעתיד.</span></div><div class="ux-chip"><b>למה המניה נבחרה?</b><span>פירוק הציון לפער פתיחה, מחזור יחסי, מומנטום, חדשות והיסטוריה.</span></div><div class="ux-chip"><b>תיק ניסוי של השיטה</b><span>מעקב וירטואלי אחר איתותי השיטה בלי סיכון כסף אמיתי.</span></div><div class="ux-chip"><b>יומן למידה</b><span>שינוי מוצע → אימות על תרחישים חדשים → קבלה או דחייה.</span></div>';
  panel.parentNode.insertBefore(d,panel)
}
function upload(){
  const up=$('.upload');if(!up)return;up.setAttribute('role','button');up.setAttribute('tabindex','0');up.title='העלה צילום מסך של התיק כדי לחלץ ממנו נתונים';
  if(!up.querySelector('.ux-upload-hint')){const x=document.createElement('div');x.className='ux-upload-hint';x.innerHTML='<b>העלאת צילום מסך</b><span>1. בוחרים תמונה · 2. המערכת קוראת את הטקסט · 3. בודקים את הנתונים · 4. שומרים לתיק</span>';up.prepend(x)}
  up.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')up.click()});
  const input=$('#imgInput');if(input&&!input.dataset.preview){input.dataset.preview='1';input.addEventListener('change',e=>{const f=e.target.files?.[0];if(!f)return;let img=$('#uxUploadPreview');if(!img){img=document.createElement('img');img.id='uxUploadPreview';img.className='ux-upload-preview';up.after(img)}img.src=URL.createObjectURL(f);img.alt='תצוגה מקדימה של התמונה שנבחרה'})}
}
function chartGuard(){
  const note=$('#chartNote');if(!note)return;new MutationObserver(()=>{const t=note.textContent||'';if(/טוען/i.test(t)){note.className='small ux-chart-state loading'}else if(/שגיאה|לא ניתן|אין נתונים|לא זמינ/i.test(t)){note.className='small ux-chart-state error';note.title='נסה טווח זמן אחר או רענון נתונים. מקור הנתונים לא החזיר סדרה תקינה.'}else if(t){note.className='small ux-chart-state ok'}}).observe(note,{childList:true,subtree:true,characterData:true})
}
function scoreContributionRows(){
  try{
    const s=typeof selected!=='undefined'?selected:null;if(!s)return [];
    const c=s.criteria||{};return Object.entries(c).map(([k,v])=>({name:k,points:Number(v)||0}))
  }catch(_){return []}
}
function ensureWhyPanel(){
  if($('#uxWhyPanel'))return $('#uxWhyPanel');const anchor=$('#stockLearningPanel')||$('#fiveYearProfile');if(!anchor)return null;
  const p=document.createElement('section');p.id='uxWhyPanel';p.className='card detail-section ux-why-panel';
  p.innerHTML='<div class="section-head"><div><h2>🔎 למה המניה נבחרה?</h2><p>פירוק ציון השיטה והצלבה מול מה שכבר למדנו מהעבר.</p></div><span id="uxWhyStatus" class="live-badge">ממתין לנתונים</span></div><div id="uxWhySummary" class="ux-why-summary"></div><div class="table-wrap"><table class="compact-table"><thead><tr><th>גורם</th><th>תרומה לציון</th><th>מה הוא אומר</th><th>אימות היסטורי</th></tr></thead><tbody id="uxWhyBody"></tbody></table></div><div id="uxWhyNote" class="note" style="margin-top:10px"></div>';
  anchor.parentNode.insertBefore(p,anchor);return p
}
function factorMeaning(name){
  const n=String(name).toLowerCase();
  if(n.includes('gap')||name.includes('פער'))return 'פער הפתיחה ביחס לסגירה הקודמת.';
  if(n.includes('rvol')||name.includes('מחזור'))return 'האם יש מחזור חריג ביחס לרגיל.';
  if(n.includes('חדשות')||n.includes('תקשורת')||n.includes('קטליז'))return 'האם יש סיבה חדשותית/עסקית שמסבירה את התנועה.';
  if(n.includes('מומנט'))return 'עוצמת כיוון המחיר בזמן האיתות.';
  if(n.includes('נזיל'))return 'יכולת להיכנס ולצאת בלי החלקה חריגה.';
  if(n.includes('float'))return 'כמות המניות הזמינה למסחר והשפעתה על תנודתיות.';
  if(n.includes('גרף')||n.includes('מגמה'))return 'מבנה המחיר והמגמה ביחס לרמות מפתח.';
  if(n.includes('פיננס'))return 'איכות המצב הפיננסי של החברה.';
  if(n.includes('תמחור'))return 'האם התמחור סביר ביחס לצמיחה ולסיכון.';
  return 'רכיב בציון הכולל של השיטה.'
}
async function renderWhyPanel(){
  const p=ensureWhyPanel();if(!p)return;let symbol='';try{symbol=(typeof selected!=='undefined'&&selected?.ticker)||$('#dTicker')?.textContent?.trim()||''}catch(_){symbol=$('#dTicker')?.textContent?.trim()||''}if(!symbol)return;
  const rows=scoreContributionRows();const total=rows.reduce((a,x)=>a+x.points,0);$('#uxWhySummary').innerHTML=`<div><b>${symbol}</b><span>הציון בנוי מ־${rows.length||'כמה'} גורמים. תרומה גבוהה יותר = התאמה חזקה יותר לתנאי השיטה.</span></div><div class="ux-score-total">${total||$('#dScore')?.textContent||'—'}<small>נקודות רכיב</small></div>`;
  let learning=null,summary=null;try{[learning,summary]=await Promise.all([fetch('/api/learning/stock/'+encodeURIComponent(symbol),{cache:'no-store'}).then(r=>r.ok?r.json():null),fetch('/api/learning/summary',{cache:'no-store'}).then(r=>r.ok?r.json():null)])}catch(_){ }
  const histByFactor={};
  if(learning?.rows?.length){
    const rs=learning.rows;const gap=rs.filter(x=>Number.isFinite(+x.gap_pct));if(gap.length){const good=gap.filter(x=>x.hit1).length;histByFactor.gap=`${good}/${gap.length} הצליחו (${(100*good/gap.length).toFixed(1)}%)`}
    const rv=rs.filter(x=>Number.isFinite(+x.rvol_open));if(rv.length){const good=rv.filter(x=>x.hit1).length;histByFactor.rvol=`${good}/${rv.length} הצליחו (${(100*good/rv.length).toFixed(1)}%)`}
  }
  (summary?.feature_learning||[]).forEach(x=>{histByFactor[x.feature]=`${x.signals} מקרים · ${Number(x.success_pct||0).toFixed(1)}% הצלחה · ${Number(x.avg_r||0).toFixed(2)}R`});
  const body=$('#uxWhyBody');body.innerHTML=(rows.length?rows:[{name:'ציון כולל',points:0}]).map(x=>{const n=String(x.name).toLowerCase();let h='עדיין לא נמדד בנפרד';if(n.includes('gap')||x.name.includes('פער'))h=histByFactor.gap||h;else if(n.includes('rvol')||x.name.includes('מחזור'))h=histByFactor.rvol||h;return `<tr><td><b>${x.name}</b></td><td><span class="ux-points">+${x.points}</span></td><td>${factorMeaning(x.name)}</td><td>${h}</td></tr>`}).join('');
  const st=$('#uxWhyStatus');if(learning?.has_data){st.textContent=`${learning.signals||0} אותות היסטוריים`;st.className='live-badge live-on'}else{st.textContent='מדגם חלקי';st.className='live-badge live-delayed'}
  $('#uxWhyNote').textContent='חשוב: “תרומה לציון” אינה הסתברות הצלחה. כאשר אין עדיין מדגם היסטורי מספיק לגורם מסוים, המערכת מציגה זאת במפורש ולא ממציאה אחוז.'
}
function watchDetail(){
  const ticker=$('#dTicker');if(!ticker)return;new MutationObserver(()=>setTimeout(renderWhyPanel,100)).observe(ticker,{childList:true,subtree:true,characterData:true});
  document.addEventListener('click',e=>{if(e.target.closest('.stock-row,.top-card'))setTimeout(renderWhyPanel,700)})
}
function run(){labelScores();clarify();addHelp();researchStrip();upload();chartGuard();ensureWhyPanel();watchDetail();new MutationObserver(()=>{labelScores();addHelp()}).observe(document.body,{childList:true,subtree:true})}
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',run):run();
})();