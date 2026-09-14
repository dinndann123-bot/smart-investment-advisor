"""Minimal production startup safety for Smart Investment Advisor V22.

This module keeps the existing static index safe for mobile startup and adds a
small client-side guard for transient empty day-scanner responses.
"""
from pathlib import Path

try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _OriginalFileResponse = _responses.FileResponse

    def _safe_index(path):
        html = Path(path).read_text(encoding="utf-8")

        # OCR is optional. Never let its CDN block first paint.
        html = html.replace(
            '<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            '<script async src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            1,
        )

        # During V22 stability verification the Service Worker must not own
        # navigation or inject extra UX scripts. Keep the surrounding update code
        # syntactically valid by returning a harmless registration-like object.
        html = html.replace(
            "const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});",
            "const reg={waiting:null,installing:null,update:async()=>{},addEventListener:()=>{}};",
            1,
        )

        # Fix icon paths used by the real repository layout.
        html = html.replace('/static/icons/apple-touch-icon.png', '/static/icons/icons/apple-touch-icon.png')
        html = html.replace('/static/icons/icon-192.png', '/static/icons/icons/icon-192.png')

        # Styling is safe to keep; feature JavaScript layers stay off until the
        # core app is proven stable.
        for tag in (
            '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=22">',
            '<link rel="stylesheet" href="/static/ui-v2.css?v=22">',
        ):
            if tag not in html:
                html = html.replace('</head>', tag + '\n</head>', 1)

        # Never let a transient 200 response with results:[] wipe a valid scanner
        # list from the UI. Cache only genuinely non-empty live responses. If a
        # later refresh is empty, reuse the last good payload and mark it stale so
        # the UI/data layer can distinguish it from a fresh scan.
        scanner_guard = """<script id="day-scan-last-good-r11">
(()=>{
  const KEY='smartAdvisor:lastGoodDayScan:v1';
  const nativeFetch=window.fetch.bind(window);
  window.fetch=async function(input,init){
    const url=typeof input==='string'?input:(input&&input.url)||'';
    const res=await nativeFetch(input,init);
    if(!url.includes('/api/scanner/day')) return res;
    try{
      const clone=res.clone();
      const data=await clone.json();
      const rows=Array.isArray(data&&data.results)?data.results:[];
      if(res.ok && rows.length){
        try{localStorage.setItem(KEY,JSON.stringify({savedAt:Date.now(),payload:data}))}catch(_){ }
        return res;
      }
      if(res.ok && rows.length===0){
        try{
          const raw=localStorage.getItem(KEY);
          const cached=raw?JSON.parse(raw):null;
          if(cached&&cached.payload&&Array.isArray(cached.payload.results)&&cached.payload.results.length){
            const payload={...cached.payload,
              source:'client_last_good_cache',
              stale:true,
              stale_reason:'live_scan_returned_empty',
              live_generated_at:data&&data.generated_at||null,
              cached_at:new Date(cached.savedAt).toISOString()
            };
            console.warn('DAY_SCAN_EMPTY_PROTECTED=true',payload.results.length);
            return new Response(JSON.stringify(payload),{
              status:200,
              headers:{'Content-Type':'application/json','Cache-Control':'no-store'}
            });
          }
        }catch(_){ }
      }
    }catch(_){ }
    return res;
  };
})();
</script>"""
        if 'day-scan-last-good-r11' not in html:
            html = html.replace('</head>', scanner_guard + '\n</head>', 1)

        # One small cleanup only. No reload loop, no route replacement.
        cleanup = """<script>
window.addEventListener('load',()=>{
  setTimeout(async()=>{
    try{
      if('serviceWorker' in navigator){
        const regs=await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map(r=>r.unregister()));
      }
      if(window.caches){
        const keys=await caches.keys();
        await Promise.all(keys.map(k=>caches.delete(k)));
      }
    }catch(e){console.warn('PWA cleanup skipped',e)}
  },1500);
},{once:true});
</script>"""
        html = html.replace('</body>', cleanup + '\n</body>', 1)
        return html

    def _safe_file_response(path, *args, **kwargs):
        p = Path(path)
        if p.name == 'index.html' and p.parent.name == 'static' and p.exists():
            headers = dict(kwargs.pop('headers', None) or {})
            headers.update({
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0',
            })
            return HTMLResponse(
                content=_safe_index(p),
                status_code=kwargs.pop('status_code', 200),
                headers=headers,
            )
        return _OriginalFileResponse(path, *args, **kwargs)

    _responses.FileResponse = _safe_file_response
    print('V22_MINIMAL_BOOT_INSTALLED=true', flush=True)
    print('DAY_SCAN_LAST_GOOD_GUARD_R11=true', flush=True)
except Exception as exc:
    # During dependency installation FastAPI may not exist yet. This is harmless;
    # sitecustomize will run again in the actual application interpreter.
    print('V22_MINIMAL_BOOT_WARNING=' + repr(exc), flush=True)
