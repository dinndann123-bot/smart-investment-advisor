(()=>{'use strict';const V='20260916-1838',h=document.head;const css=src=>{const l=document.createElement('link');l.rel='stylesheet';l.href=`${src}?v=${V}`;h.appendChild(l)};const js=src=>{const s=document.createElement('script');s.src=`${src}?v=${V}`;s.defer=true;document.body.appendChild(s)};
css('/static/app_shell_v5.css');css('/static/mobile_hotfix_r20.css');css('/static/portfolio_hotfix_r21.css');
js('/static/chart_ui_v2.js');js('/static/app_shell_v5.js');
// dashboard_detail_bridge_v8 removed: its document-wide MutationObserver caused work on every DOM/class change.
})();