"""Temporary activation bridge for canonical presentation assets.

This bridge only adds the canonical UI bootstrap to the served HTML. It does
not alter scanner routes, strategy scoring, fetch responses, market data, or
application state. Remove after the script tag is moved directly into the
canonical HTML source.
"""
from pathlib import Path
try:
    from fastapi.responses import FileResponse, HTMLResponse
    _original = FileResponse.__call__
    async def _canonical_ui_call(self, scope, receive, send):
        path = str(getattr(self, "path", ""))
        if path.endswith("static/index.html"):
            try:
                html = Path(path).read_text(encoding="utf-8")
                tag = '<script src="/static/canonical_bootstrap.js?v=4" defer></script>'
                if 'canonical_bootstrap.js' not in html:
                    html = html.replace("</body>", tag + "\n</body>")
                else:
                    import re
                    html = re.sub(r'<script src="/static/canonical_bootstrap\.js\?v=\d+" defer></script>', tag, html)
                response = HTMLResponse(html, headers={"Cache-Control":"no-store, no-cache, must-revalidate","Pragma":"no-cache","Expires":"0"})
                return await response(scope, receive, send)
            except Exception:
                pass
        return await _original(self, scope, receive, send)
    FileResponse.__call__ = _canonical_ui_call
    print("CANONICAL_UI_ACTIVE=true version=4")
except Exception as exc:
    print(f"CANONICAL_UI_ACTIVE=false error={exc}")