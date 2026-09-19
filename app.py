# v6.7 local composition: keep the verified v6.6 market engine and wrap only its day scanner.
from app_v66 import *
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION

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
    }
