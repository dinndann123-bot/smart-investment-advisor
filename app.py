# Recovery composition: keep the stable scanner/chart APIs, but serve the last
# complete application shell.  The experimental v7 document only implemented
# the home screen, so making it canonical removed navigation, portfolio,
# long-term views and the mature chart/data lifecycle.
from app_v66 import *
import app_v66 as _scanner_core
from scanner_session_fix import install as _install_scanner_session_fix
SCANNER_SESSION_DATA_FIX=_install_scanner_session_fix(_scanner_core)
from scanner_core import install_local_scanner
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from chart_api_v7 import install_chart_api
from pathlib import Path
from fastapi.responses import FileResponse

_local_scanner_engine=install_local_scanner(app)
CHART_API_V7=install_chart_api(app)

_old_root=next((r for r in app.routes if getattr(r,'path',None)=='/' and 'GET' in getattr(r,'methods',set())),None)
if _old_root is not None:app.router.routes.remove(_old_root)
@app.get('/',include_in_schema=False)
async def production_root():
    return FileResponse(
        Path(__file__).with_name('index.html'),
        media_type='text/html',
        headers={
            'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma':'no-cache',
        },
    )

_v66_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
if _v66_day_route is None:raise RuntimeError('local full-market day scanner route not found')
_v66_scanner_engine=_v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async=install_async_scanner(app,_v66_scanner_engine)
app.add_api_route('/api/scanner/day',_async['day'],methods=['GET'],name='scanner_day_v7')
app.add_api_route('/api/scanner/day/start',_async['start'],methods=['POST'],name='scanner_day_start_v7')
app.add_api_route('/api/scanner/day/status',_async['status'],methods=['GET'],name='scanner_day_status_v7')

try:
 import learning_store
 from scheduled_learning import install_scheduled_learning
 SCHEDULED_LEARNING=install_scheduled_learning(app,_v66_scanner_engine,learning_store,ASYNC_STRATEGY_VERSION,price_fetcher=getattr(_scanner_core,'_future_prices',None))
except Exception as _scheduled_error:
 SCHEDULED_LEARNING={'installed':False,'error':f'{type(_scheduled_error).__name__}: {_scheduled_error}'}

@app.get('/api/scanner/async-status')
async def scanner_async_status():
    return {'installed':True,'strategy_version':ASYNC_STRATEGY_VERSION,'engine':'local-full-market-predictive-shortlist-progressive-top10','live_market_source':'Alpaca','cache_scope':'last-scanner-result-only','canonical_top10_contract':True,'canonical_ui':'index.html','ui_recovery':'complete-navigation-and-data-shell','canonical_chart_api':'/api/market/chart/{symbol}','scheduled_learning':SCHEDULED_LEARNING,'session_data_fix':SCANNER_SESSION_DATA_FIX,'local_scanner_core':True}

try:
 from app_tail import install_app_tail
 install_app_tail(globals())
except ImportError:
 pass
