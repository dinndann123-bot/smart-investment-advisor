(()=>{'use strict';/* Canonical presentation bootstrap: explicit assets, no strategy mutation. */
const head=document.head;function css(h){if([...document.styleSheets].some(s=>String(s.href||'').includes(h)))return;const l=document.createElement('link');l.rel='stylesheet';l.href=h;head.appendChild(l)}function js(src){if([...document.scripts].some(s=>String(s.src||'').includes(src)))return;const s=document.createElement('script');s.src=src;s.defer=true;document.body.appendChild(s)}
css('/static/canonical_black_gold.css?v=1');js('/static/data_integrity.js?v=1');
})();