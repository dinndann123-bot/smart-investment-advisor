"""Startup hooks for Smart Investment Advisor.

1) Preserve the sequential 50-scenario research bootstrap.
2) Inject the Hebrew-first UX layer into the existing index page even when Render
   starts the service with `uvicorn app:app`.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path


# ---------- Hebrew-first presentation hook ----------
try:
    import fastapi.responses as _responses
    from fastapi.responses import HTMLResponse

    _OriginalFileResponse = _responses.FileResponse

    def _enhanced_file_response(path, *args, **kwargs):
        p = Path(path)
        if p.name == "index.html" and p.parent.name == "static" and p.exists():
            html = p.read_text(encoding="utf-8")
            css = '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=3">'
            js = '<script src="/static/hebrew_ux_v3.js?v=3" defer></script>'
            if css not in html:
                html = html.replace("</head>", css + "\n</head>", 1)
            if js not in html:
                html = html.replace("</body>", js + "\n</body>", 1)
            headers = kwargs.pop("headers", None)
            status_code = kwargs.pop("status_code", 200)
            return HTMLResponse(content=html, status_code=status_code, headers=headers)
        return _OriginalFileResponse(path, *args, **kwargs)

    _responses.FileResponse = _enhanced_file_response
except Exception as exc:
    print("UX_V3_INSTALL_WARNING=" + repr(exc), flush=True)


# ---------- Historical research bootstrap ----------
def _bootstrap():
    # Wait until app.py has created the FastAPI instance.
    for _ in range(120):
        mod = sys.modules.get("app")
        app_obj = getattr(mod, "app", None) if mod else None
        if app_obj is not None:
            try:
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

    time.sleep(5)
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
