# v8 preview composition: stable scanner core + canonical APIs + isolated professional frontend.
from app_v66 import *
import app_v66 as _scanner_core
from scanner_session_fix import install as _install_scanner_session_fix
SCANNER_SESSION_DATA_FIX=_install_scanner_session_fix(_scanner_core)
from scanner_core import install_local_scanner
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from chart_api_v7 import install_chart_api
from market_indices_v8 import install_market_indices
from pathlib import Path
from fastapi.responses import FileResponse

_local_scanner_engine=install_local_scanner(app)
CHART_API_V7=install_chart_api(app)
MARKET_OVERVIEW_V8=install_market_indices(app)
BASE=Path(__file__).parent

# v8 preview assets. Production root is intentionally unchanged on main until release gate passes.
@app.get('/v8',include_in_schema=False)
async def v8_preview():return FileResponse(BASE/'frontend_v8'/'index.html',media_type='text/html',headers={'Cache-Control':'no-store, max-age=0'})
@app.get('/v8/app.css',include_in_schema=False)
async def v8_css():return FileResponse(BASE/'frontend_v8'/'app.css',media_type='text/css',headers={'Cache-Control':'no-store, max-age=0'})
@app.get('/v8/app.js',include_in_schema=False)
async def v8_js():return FileResponse(BASE/'frontend_v8'/'app.js',media_type='application/javascript',headers={'Cache-Control':'no-store, max-age=0'})

_old_root=next((r for r in app.routes if getattr(r,'path',None)=='/' and 'GET' in getattr(r,'methods',set())),None)
if _old_root is not None:app.router.routes.remove(_old_root)
@app.get('/',include_in_schema=False)
async def production_root():return FileResponse(BASE/'ui_v7.html',media_type='text/html',headers={'Cache-Control':'no-store, max-age=0'})

_v66_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
if _v66_day_route is None:raise RuntimeError('local full-market day scanner route not found')
_v66_scanner_engine=_v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async=install_async_scanner(app,_v66_scanner_engine)
app.add_api_route('/api/scanner/day',_async['day'],methods=['GET'],name='scanner_day_v8')
app.add_api_route('/api/scanner/day/start',_async['start'],methods=['POST'],name='scanner_day_start_v8')
app.add_api_route('/api/scanner/day/status',_async['status'],methods=['GET'],name='scanner_day_status_v8')
try:
 import learning_store
 from scheduled_learning import install_scheduled_learning
 SCHEDULED_LEARNING=install_scheduled_learning(app,_v66_scanner_engine,learning_store,ASYNC_STRATEGY_VERSION)
except Exception as _scheduled_error:SCHEDULED_LEARNING={'installed':False,'error':f'{type(_scheduled_error).__name__}: {_scheduled_error}'}
@app.get('/api/scanner/async-status')
async def scanner_async_status():return {'installed':True,'strategy_version':ASYNC_STRATEGY_VERSION,'engine':'local-full-market-predictive-shortlist-progressive-top10','live_market_source':'Alpaca','canonical_top10_contract':True,'production_ui':'ui_v7.html','preview_ui':'/v8','ui_runtime_patches':False,'canonical_chart_api':'/api/market/chart/{symbol}','market_overview_api':'/api/market/overview','scheduled_learning':SCHEDULED_LEARNING,'session_data_fix':SCANNER_SESSION_DATA_FIX,'local_scanner_core':True}
try:
 from app_tail import install_app_tail
 install_app_tail(globals())
except ImportError:pass
