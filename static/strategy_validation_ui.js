// Modular production UI loader r14. index.html keeps loading this stable entry point.
(function(){
'use strict';
const modules=['/static/dashboard_r14.js?v=20260918-r14','/static/stock_strategy_r13.js?v=20260918-r13'];
for(const src of modules){
  if(document.querySelector('script[src="'+src+'"]'))continue;
  const s=document.createElement('script');s.src=src;s.defer=true;s.dataset.smartUiModule='1';document.head.appendChild(s);
}
})();
