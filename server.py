from pathlib import Path

from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

import app as core

app = core.app
BASE_DIR = Path(__file__).resolve().parent

# Compatibility wrapper only. Production can run app:app directly.
# Core modules are installed in app.py so Render and local execution behave identically.

app.router.routes[:] = [
    route for route in app.router.routes
    if not (isinstance(route, APIRoute) and route.path == "/" and "GET" in route.methods)
]

@app.get("/", response_class=HTMLResponse)
async def enhanced_root():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    additions_head = ['<link rel="stylesheet" href="/static/hebrew_ux_v3.css?v=3">']
    additions_body = [
        '<script src="/static/hebrew_ux_v3.js?v=3" defer></script>',
        '<script src="/static/strategy_learning_r15.js?v=15.3" defer></script>',
    ]
    for tag in additions_head:
        if tag not in html: html=html.replace('</head>',tag+'\n</head>',1)
    for tag in additions_body:
        if tag not in html: html=html.replace('</body>',tag+'\n</body>',1)
    return HTMLResponse(html,headers={'Cache-Control':'no-cache, no-store, must-revalidate','Pragma':'no-cache','Expires':'0'})
