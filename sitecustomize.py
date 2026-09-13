"""Temporary research bootstrap for the 50-scenario sequential audit."""
import json
import os
import sys
import threading
import time
import urllib.request


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
