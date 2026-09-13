from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

import app as core

app = core.app
BASE_DIR = Path(__file__).resolve().parent

# Keep every API/WebSocket/static route from app.py, but replace only the home HTML
# response so UX additions can evolve independently without rewriting the large UI file.
app.router.routes[:] = [
    route for route in app.router.routes
    if not (isinstance(route, APIRoute) and route.path == "/" and "GET" in route.methods)
]


@app.get("/", response_class=HTMLResponse)
async def enhanced_root():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    head_addition = '<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=3">'
    body_addition = '<script src="/static/hebrew_ux_v3.js?v=3" defer></script>'
    if head_addition not in html:
        html = html.replace("</head>", head_addition + "\n</head>", 1)
    if body_addition not in html:
        html = html.replace("</body>", body_addition + "\n</body>", 1)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
