# v6.7 local composition: keep the verified v6.6 market engine and wrap only its day scanner.
from app_v66 import *
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from pathlib import Path

# Frontend compatibility fix: the existing "Scan now" button already calls
# refreshDayScanner(true), but the old JS ignored that flag. Patch only the
# request URL at startup so a manual click explicitly asks v6.7 for a fresh job.
# Automatic/page loads continue to read the current cached result normally.
try:
    _index_path = Path(__file__).with_name('index.html')
    _html = _index_path.read_text(encoding='utf-8')
    _old = 'const r=await fetch("/api/scanner/day?top=10&candidates=40");'
    _new = 'const r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});'
    if _old in _html:
        _index_path.write_text(_html.replace(_old, _new, 1), encoding='utf-8')
        print('SCANNER_UI_MANUAL_REFRESH_PATCH=true', flush=True)
    else:
        print('SCANNER_UI_MANUAL_REFRESH_PATCH=not_needed_or_pattern_missing', flush=True)
except Exception as _ui_patch_error:
    print(f'SCANNER_UI_MANUAL_REFRESH_PATCH_ERROR={type(_ui_patch_error).__name__}: {_ui_patch_error}', flush=True)

_v66_day_route = next((r for r in app.routes if getattr(r, 'path', None) == '/api/scanner/day' and 'GET' in getattr(r, 'methods', set())), None)
if _v66_day_route is None:
    raise RuntimeError('v6.6 day scanner route not found')

_v66_scanner_engine = _v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async = install_async_scanner(app, _v66_scanner_engine)
app.add_api_route('/api/scanner/day', _async['day'], methods=['GET'], name='scanner_day_v67')
app.add_api_route('/api/scanner/day/start', _async['start'], methods=['POST'], name='scanner_day_start_v67')
app.add_api_route('/api/scanner/day/status', _async['status'], methods=['GET'], name='scanner_day_status_v67')

@app.get('/api/scanner/async-status')
async def scanner_async_status():
    return {
        'installed': True,
        'strategy_version': ASYNC_STRATEGY_VERSION,
        'engine': 'v6.6-progressive-forward-top10',
        'live_market_source': 'Alpaca',
        'cache_scope': 'last-scanner-result-only',
        'manual_refresh_ui_patch': True,
    }
