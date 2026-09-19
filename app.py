# v6.7 local composition: keep the verified v6.6 market engine and wrap only its day scanner.
from app_v66 import *
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from pathlib import Path

# Frontend compatibility fix for the existing "סרוק עכשיו" flow.
# A manual scan must force refresh=1 and then wait for the v6.7 background job
# to finish before replacing the visible Top 10. Automatic/page loads keep using
# the latest cached result and remain fast.
try:
    _index_path = Path(__file__).with_name('index.html')
    _html = _index_path.read_text(encoding='utf-8')

    _old_plain = '''const r=await fetch("/api/scanner/day?top=10&candidates=40");
   const j=await r.json();'''
    _old_refresh_only = '''const r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});
   const j=await r.json();'''
    _new = '''let r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});
   let j=await r.json();
   if(manual && (r.status===202 || j.refresh_running || j.scanner_job?.status==="running")){
     const requestedJobId=j.scanner_job?.job_id||null;
     const started=Date.now();
     while(Date.now()-started<120000){
       await new Promise(resolve=>setTimeout(resolve,1500));
       const sr=await fetch("/api/scanner/day/status",{cache:"no-store"});
       const sj=await sr.json();
       const job=sj.scanner_job||{};
       if(job.status==="error")throw new Error(job.error||"Scanner job failed");
       if(job.status==="complete" && (!requestedJobId || job.job_id===requestedJobId)){
         if(sj.result && Array.isArray(sj.result.results) && sj.result.results.length){
           j=sj.result;
           r=sr;
           break;
         }
       }
     }
     if(!Array.isArray(j.results) || !j.results.length || j.refresh_running){
       throw new Error("הסריקה לא הסתיימה בזמן. נסה שוב בעוד רגע.");
     }
   }'''

    if _old_plain in _html:
        _index_path.write_text(_html.replace(_old_plain, _new, 1), encoding='utf-8')
        print('SCANNER_UI_ASYNC_POLL_PATCH=true_from_plain', flush=True)
    elif _old_refresh_only in _html:
        _index_path.write_text(_html.replace(_old_refresh_only, _new, 1), encoding='utf-8')
        print('SCANNER_UI_ASYNC_POLL_PATCH=true_from_refresh_only', flush=True)
    elif '/api/scanner/day/status' in _html and 'requestedJobId' in _html:
        print('SCANNER_UI_ASYNC_POLL_PATCH=already_present', flush=True)
    else:
        print('SCANNER_UI_ASYNC_POLL_PATCH=pattern_missing', flush=True)
except Exception as _ui_patch_error:
    print(f'SCANNER_UI_ASYNC_POLL_PATCH_ERROR={type(_ui_patch_error).__name__}: {_ui_patch_error}', flush=True)

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
        'manual_refresh_polling': True,
    }
