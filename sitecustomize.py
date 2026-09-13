"""Startup safety hooks for Smart Investment Advisor.

V20 emergency stability mode:
- never let OCR block first paint
- do not inject the heavy research UX script during startup
- unregister stale Service Workers and clear PWA caches
- install research routes, but never run the expensive 50-scenario job at boot
"""
import os
import sys
import threading
import time
from pathlib import Path

try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _OriginalFileResponse = _responses.FileResponse

    def _prepare_index_html(path):
        html = Path(path).read_text(encoding="utf-8")
        html = html.replace(
            '<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            '<script async src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            1,
        )
        # Keep the lightweight styling/UI layer, but temporarily remove the
        # research UX JS. That script was calling the expensive research-50
        # endpoint on load, every 5 minutes, and again on every mobile resize.
        css = '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=20">'
        ui_css = '<link rel="stylesheet" href="/static/ui-v2.css?v=20">'
        ui_js = '<script src="/static/ui-v2.js?v=20" defer></script>'
        for tag in (css, ui_css):
            if tag not in html:
                html = html.replace("</head>", tag + "\n</head>", 1)
        if ui_js not in html:
            html = html.replace("</body>", ui_js + "\n</body>", 1)
        return html

    def _enhanced_file_response(path, *args, **kwargs):
        p = Path(path)
        if p.name == "index.html" and p.parent.name == "static" and p.exists():
            headers = dict(kwargs.pop("headers", None) or {})
            headers.update({
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
            return HTMLResponse(
                content=_prepare_index_html(p),
                status_code=kwargs.pop("status_code", 200),
                headers=headers,
            )
        return _OriginalFileResponse(path, *args, **kwargs)

    _responses.FileResponse = _enhanced_file_response
except Exception as exc:
    print("UX_V20_INSTALL_WARNING=" + repr(exc), flush=True)


def _install_routes(app_obj):
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse

        app_obj.router.routes[:] = [
            r for r in app_obj.router.routes
            if not (getattr(r, "path", None) == "/" and
                    ({"GET", "HEAD"} & (getattr(r, "methods", set()) or set())))
        ]

        async def root(request: Request):
            qp = request.query_params
            if qp.get("source") == "pwa":
                # Do this on every installed-app launch in V20. It is cheap and
                # guarantees that a stale worker cannot own the next navigation.
                recovery = """<!doctype html><html lang='he' dir='rtl'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='theme-color' content='#19244f'><title>היועץ החכם להשקעות</title>
<style>html,body{margin:0;height:100%;background:#19244f;color:#fff;font-family:Arial,sans-serif}body{display:grid;place-items:center}.b{text-align:center;padding:24px}.s{width:38px;height:38px;border:4px solid #ffffff55;border-top-color:#fff;border-radius:50%;margin:0 auto 16px;animation:r .8s linear infinite}@keyframes r{to{transform:rotate(360deg)}}p{opacity:.85;font-size:14px}</style></head><body><div class='b'><div class='s'></div><b>פותח גרסה יציבה…</b><p>מנקה רכיבי PWA ישנים</p></div><script>
(async()=>{try{if('serviceWorker' in navigator){const rs=await navigator.serviceWorker.getRegistrations();await Promise.all(rs.map(r=>r.unregister()));}if(window.caches){const ks=await caches.keys();await Promise.all(ks.map(k=>caches.delete(k)));}}catch(e){}location.replace('/?stable=20&t='+Date.now());})();
</script></body></html>"""
                return HTMLResponse(recovery, headers={"Cache-Control":"no-cache, no-store, must-revalidate"})

            index_path = Path(__file__).resolve().parent / "static" / "index.html"
            html = _prepare_index_html(index_path)
            # Disable Service Worker registration in stability mode. We first
            # prove the web app itself is stable, then restore offline/PWA cache.
            if qp.get("stable") == "20":
                html = html.replace(
                    "navigator.serviceWorker.register('/sw.js'",
                    "Promise.reject(new Error('SW disabled in V20')).then(()=>navigator.serviceWorker.register('/sw.js'",
                )
                cleanup = """<script>(async()=>{try{if('serviceWorker' in navigator){const rs=await navigator.serviceWorker.getRegistrations();await Promise.all(rs.map(r=>r.unregister()));}}catch(e){}})();</script>"""
                html = html.replace("</head>", cleanup + "\n</head>", 1)
            return HTMLResponse(html, headers={"Cache-Control":"no-cache, no-store, must-revalidate","Pragma":"no-cache","Expires":"0"})

        app_obj.add_api_route("/", root, methods=["GET", "HEAD"], include_in_schema=False)

        # Keep the endpoint available for manual/research use, but do not run it
        # automatically at server startup.
        from research_50 import install_research_50
        install_research_50(app_obj)
        print("PWA_STABILITY_V20_INSTALLED=true", flush=True)
    except Exception as exc:
        print("PWA_STABILITY_V20_ERROR=" + repr(exc), flush=True)


def _bootstrap():
    for _ in range(120):
        mod = sys.modules.get("app")
        app_obj = getattr(mod, "app", None) if mod else None
        if app_obj is not None:
            _install_routes(app_obj)
            return
        time.sleep(0.1)
    print("PWA_STABILITY_V20_ERROR=app_not_found", flush=True)


if os.getenv("PORT"):
    threading.Thread(target=_bootstrap, name="pwa-stability-bootstrap", daemon=True).start()
