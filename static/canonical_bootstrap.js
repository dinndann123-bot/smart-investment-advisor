(()=>{'use strict';const V='20260916-2215',h=document.head;const css=src=>{const l=document.createElement('link');l.rel='stylesheet';l.href=`${src}?v=${V}`;h.appendChild(l)};const js=src=>{const s=document.createElement('script');s.src=`${src}?v=${V}`;s.defer=true;document.body.appendChild(s)};
css('/static/app_shell_v5.css');
js('/static/chart_ui_v2.js');js('/static/app_shell_v5.js');
// Legacy runtime/detail bridge and r20/r21 hotfix styles are no longer loaded by production bootstrap.
})();