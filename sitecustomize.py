"""Startup hooks for Smart Investment Advisor.

1) Preserve the sequential 50-scenario research bootstrap.
2) Inject the Hebrew-first UX layer into the existing index page even when Render
   starts the service with `uvicorn app:app`.
3) Never let the external OCR library block the first paint of the PWA.
4) Recover installed Android PWAs from stale/broken Service Worker state.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path


# ---------- Presentation + startup safety hook ----------
try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _OriginalFileResponse = _responses.FileResponse

    def _prepare_index_html(path):
        p = Path(path)
        html = p.read_text(encoding="utf-8")

        # Never allow OCR CDN loading to block first paint.
        html = html.replace(
            '<script src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            '<script async src="https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js"></script>',
            1,
        )

        css = '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=19">'
        ui_css = '<link rel="stylesheet" href="/static/ui-v2.css?v=19">'
        js = '<script src="/static/hebrew_ux_v3.js?v=19" defer></script>'
        ui_js = '<script src="/static/ui-v2.js?v=19" defer></script>'
        for tag in (css, ui_css):
            if tag not in html:
                html = html.replace("</head>", tag + "\n</head>", 1)
        for tag in (js, ui_js):
            if tag not in html:
                html = html.replace("</body>", tag + "\n</body>", 1)
        return html

    def _enhanced_file_response(path, *args, **kwargs):
        p = Path(path)
        if p.name == "index.html" and p.parent.name == "static" and p.exists():
            html = _prepare_index_html(p)
            headers = kwargs.pop("headers", None) or {}
            headers = dict(headers)
            headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            status_code = kwargs.pop("status_code", 200)
            return HTMLResponse(content=html, status_code=status_code, headers=headers)
        return _OriginalFileResponse(path, *args, **kwargs)

    _responses.FileResponse = _enhanced_file_response
except Exception as exc:
    print("UX_V19_INSTALL_WARNING=" + repr(exc), flush=True)


def _install_pwa_recovery_route(app_obj):
    """Replace only the root route with a recovery-aware launcher.

    The installed WebAPK opens /?source=pwa. If an old Service Worker/cache is
    wedged, serve a tiny page that unregisters every worker, clears caches and
    redirects to a clean network-loaded index. In recovery mode the normal page
    does not register a Service Worker again, so we cannot fall back into a loop.
    """
    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse

        # Remove existing GET/HEAD root route so this one is the first match.
        app_obj.router.routes[:] = [
            r for r in app_obj.router.routes
            if not (getattr(r, "path", None) == "/" and ("GET" in (getattr(r, "methods", set()) or set()) or "HEAD" in (getattr(r, "methods", set()) or set())))
        ]

        async def recovery_root(request: Request):
            qp = request.query_params
            if qp.get("source") == "pwa":
                recovery = """<!doctype html><html lang='he' dir='rtl'><head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='theme-color' content='#19244f'><title>היועץ החכם להשקעות</title>
<style>html,body{margin:0;height:100%;background:#19244f;color:#fff;font-family:Arial,sans-serif}body{display:grid;place-items:center}.b{text-align:center;padding:24px}.s{width:38px;height:38px;border:4px solid #ffffff55;border-top-color:#fff;border-radius:50%;margin:0 auto 16px;animation:r .8s linear infinite}@keyframes r{to{transform:rotate(360deg)}}p{opacity:.85;font-size:14px}</style></head><body><div class='b'><div class='s'></div><b>מתקן את פתיחת האפליקציה…</b><p>מנקה קאש ישן ומתחבר מחדש</p></div><script>
(async()=>{try{const done=localStorage.getItem('pwa_recovery_v19');if(!done){if('serviceWorker' in navigator){const regs=await navigator.serviceWorker.getRegistrations();await Promise.all(regs.map(r=>r.unregister()));}if(window.caches){const keys=await caches.keys();await Promise.all(keys.map(k=>caches.delete(k)));}localStorage.setItem('pwa_recovery_v19','1');}}catch(e){}location.replace('/?recovered=1&v=19&t='+Date.now());})();
</script></body></html>"""
                return HTMLResponse(recovery, headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                })

            index_path = Path(__file__).resolve().parent / "static" / "index.html"
            html = _prepare_index_html(index_path)
            if qp.get("recovered") == "1":
                # Keep SW disabled while we verify startup is stable.
                html = html.replace(
                    "const reg=await navigator.serviceWorker.register('/sw.js',{scope:'/'});",
                    "throw new Error('PWA recovery mode: Service Worker temporarily disabled');",
                    1,
                )
                # Defensive cleanup in case Android kept a worker despite unregister().
                cleanup = """<script>(async()=>{try{if('serviceWorker' in navigator){const rs=await navigator.serviceWorker.getRegistrations();await Promise.all(rs.map(r=>r.unregister()));}if(window.caches){const ks=await caches.keys();await Promise.all(ks.map(k=>caches.delete(k)));}}catch(e){}})();</script>"""
                html = html.replace("</head>", cleanup + "\n</head>", 1)
            return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

        app_obj.add_api_route("/", recovery_root, methods=["GET", "HEAD"], include_in_schema=False)
        print("PWA_RECOVERY_V19_INSTALLED=true", flush=True)
    except Exception as exc:
        print("PWA_RECOVERY_INSTALL_ERROR=" + repr(exc), flush=True)


# ---------- Historical research bootstrap ----------
def _bootstrap():
    for _ in range(120):
        mod = sys.modules.get("app")
        app_obj = getattr(mod, "app", None) if mod else None
        if app_obj is not None:
            try:
                _install_pwa_recovery_route(app_obj)
                from research_50 import install_research_50
                install_research_50(app_obj)
                break
            except Exception as exc:
                print("RESEARCH50_INSTALL_ERROR=" + repr(exc), flush=True)
                return
        time.sleep(0.1)
    else:
        print("RESEARCH50_INSTALL_ERROR=app_not_found", flush=True)
        return

    # Research runs in a daemon thread after startup and must never block web startup.
    time.sleep(8)
    port = os.getenv("PORT", "10000")
    url = f"http://127.0.0.1:{port}/api/strategy/long/research-50"
    try:
        with urllib.request.urlopen(url, timeout=600) as r:
            data = json.loads(r.read().decode("utf-8"))
        for b in data.get("batches", []):
            compact = {
                "batch": b.get("batch"),
                "dates": b.get("dates"),
                "preset_used": b.get("preset_used"),
                "summary": b.get("summary"),
                "lessons": b.get("lessons"),
                "next_preset": b.get("next_preset"),
            }
            print("RESEARCH50_BATCH=" + json.dumps(compact, ensure_ascii=False, separators=(",", ":")), flush=True)
        final = {
            "date_range": data.get("date_range"),
            "overall": data.get("overall"),
            "final_preset": data.get("final_preset"),
            "method": data.get("method"),
            "limitations": data.get("limitations"),
        }
        print("RESEARCH50_FINAL=" + json.dumps(final, ensure_ascii=False, separators=(",", ":")), flush=True)
    except Exception as exc:
        print("RESEARCH50_RUN_ERROR=" + repr(exc), flush=True)


if os.getenv("PORT"):
    threading.Thread(target=_bootstrap, name="research50-bootstrap", daemon=True).start()
