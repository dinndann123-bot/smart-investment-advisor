(()=>{
'use strict';
if(document.getElementById('timingHighlightV1'))return;
const style=document.createElement('style');style.id='timingHighlightV1';style.textContent=`
.timing-entry-row{background:linear-gradient(90deg,rgba(46,230,166,.16),rgba(220,177,91,.08))!important;box-shadow:inset 4px 0 #2ee6a6;animation:timingEntryPulse 1.8s ease-in-out infinite}
.timing-exit-row{background:linear-gradient(90deg,rgba(255,103,80,.18),rgba(255,174,66,.08))!important;box-shadow:inset 4px 0 #ff6750;animation:timingExitPulse 1.4s ease-in-out infinite}
.timing-active-row{background:rgba(49,91,234,.08)!important;box-shadow:inset 3px 0 #6f8cff}
.signal-exit{color:#ff846f!important;border-color:#ff6750!important;background:rgba(255,103,80,.13)!important}
.signal-active{color:#9eb0ff!important;border-color:#6f8cff!important;background:rgba(49,91,234,.12)!important}
.signal-closed{opacity:.72}
@keyframes timingEntryPulse{50%{box-shadow:inset 4px 0 #2ee6a6,0 0 16px rgba(46,230,166,.22)}}
@keyframes timingExitPulse{50%{box-shadow:inset 4px 0 #ff6750,0 0 16px rgba(255,103,80,.22)}}
@media(prefers-reduced-motion:reduce){.timing-entry-row,.timing-exit-row{animation:none!important}}
`;document.head.appendChild(style);
function decorate(detail){
 const rows=detail?.results||[];
 document.querySelectorAll('[data-day-sync][data-ticker]').forEach(card=>{
  const row=rows.find(x=>x.ticker===card.dataset.ticker);card.classList.remove('timing-entry-row','timing-exit-row','timing-active-row');
  if(row?.timing_signal==='entry')card.classList.add('timing-entry-row');
  else if(row?.timing_signal==='exit')card.classList.add('timing-exit-row');
  else if(row?.timing_signal==='active')card.classList.add('timing-active-row');
  if(row?.timing_reason)card.title=row.timing_reason;
 });
}
window.addEventListener('smartadvisor:day-scan',e=>requestAnimationFrame(()=>decorate(e.detail)));
})();
