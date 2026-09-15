(()=>{
'use strict';
const scripts=['/static/day_sync_r16.js?v=16','/static/mobile_ui_r20.js?v=20'];
for(const src of scripts){
  if(document.querySelector(`script[src^="${src.split('?')[0]}"]`))continue;
  const s=document.createElement('script');s.src=src;s.defer=true;document.head.appendChild(s);
}
})();
