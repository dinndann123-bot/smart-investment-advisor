# v6.8.3 composition: verified full-market scanner + session-aware PM data + canonical Top-10 + scheduled learning checkpoints.
from app_v66 import *
import app_v66 as _scanner_core
from scanner_session_fix import install as _install_scanner_session_fix
SCANNER_SESSION_DATA_FIX=_install_scanner_session_fix(_scanner_core)
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from pathlib import Path
from fastapi.responses import FileResponse

try:
    _index_path = Path(__file__).with_name('index.html')
    _html = _index_path.read_text(encoding='utf-8')
    _old_plain = '''const r=await fetch("/api/scanner/day?top=10&candidates=40");\n   const j=await r.json();'''
    _old_refresh = '''const r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});\n   const j=await r.json();'''
    _new = '''let r,j;
   if(manual){
     const startResponse=await fetch("/api/scanner/day/start?top=10&candidates=40",{method:"POST",cache:"no-store"});
     const startJson=await startResponse.json();
     const requestedJobId=startJson.job_id||startJson.scanner_job?.job_id||null;
     const started=Date.now();
     while(Date.now()-started<120000){
       await new Promise(resolve=>setTimeout(resolve,1000));
       const sr=await fetch("/api/scanner/day/status",{cache:"no-store"});
       const sj=await sr.json();
       const job=sj.scanner_job||{};
       if(job.status==="error")throw new Error(job.error||"Scanner job failed");
       if(job.status==="complete" && (!requestedJobId || job.job_id===requestedJobId) && sj.result && Array.isArray(sj.result.results)){r=sr;j=sj.result;break;}
     }
     if(!j || !Array.isArray(j.results))throw new Error("הסריקה לא הסתיימה בזמן. נסה שוב בעוד רגע.");
   }else{
     r=await fetch("/api/scanner/day?top=10&candidates=40",{cache:"no-store"});j=await r.json();
     if(r.status===202 || j.scan_pending){
       const requestedJobId=j.requested_job_id||j.scanner_job?.job_id||null;const started=Date.now();
       while(Date.now()-started<120000){await new Promise(resolve=>setTimeout(resolve,1000));const sr=await fetch("/api/scanner/day/status",{cache:"no-store"});const sj=await sr.json();const job=sj.scanner_job||{};if(job.status==="error")throw new Error(job.error||"Scanner job failed");if(job.status==="complete" && (!requestedJobId || job.job_id===requestedJobId) && sj.result){r=sr;j=sj.result;break;}}
     }
   }
   const canonicalScanId=j.scan_id||j.job_id||j.scanner_job?.job_id||null;
   const canonicalTop10=(Array.isArray(j.results)?j.results:[]).slice(0,10).map((row,index)=>({...row,scanner_rank:index+1,canonical_scan_id:canonicalScanId,canonical_strategy_version:j.strategy_version||row.strategy_version||null,canonical_scanner_result:true}));
   j={...j,results:canonicalTop10,canonical_top10:true,canonical_scan_id:canonicalScanId,canonical_count:canonicalTop10.length};'''
    patched=False
    for old in (_old_refresh,_old_plain):
        if old in _html:_html=_html.replace(old,_new,1);patched=True;break
    _bootstrap_tag='<script src="/static/canonical_bootstrap.js?v=20260922-1133"></script>'
    if _bootstrap_tag not in _html and '</body>' in _html:_html=_html.replace('</body>',_bootstrap_tag+'</body>',1);patched=True
    if patched:_index_path.write_text(_html,encoding='utf-8')
except Exception as _ui_patch_error:print(f'SCANNER_UI_PATCH_ERROR={type(_ui_patch_error).__name__}: {_ui_patch_error}',flush=True)

_old_root=next((r for r in app.routes if getattr(r,'path',None)=='/' and 'GET' in getattr(r,'methods',set())),None)
if _old_root is not None:app.router.routes.remove(_old_root)
@app.get('/',include_in_schema=False)
async def production_root():return FileResponse(Path(__file__).with_name('index.html'),media_type='text/html',headers={'Cache-Control':'no-store, max-age=0'})

_v66_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
if _v66_day_route is None:raise RuntimeError('full-market day scanner route not found')
_v66_scanner_engine=_v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async=install_async_scanner(app,_v66_scanner_engine)
app.add_api_route('/api/scanner/day',_async['day'],methods=['GET'],name='scanner_day_v683')
app.add_api_route('/api/scanner/day/start',_async['start'],methods=['POST'],name='scanner_day_start_v683')
app.add_api_route('/api/scanner/day/status',_async['status'],methods=['GET'],name='scanner_day_status_v683')

try:
 import learning_store
 from scheduled_learning import install_scheduled_learning
 SCHEDULED_LEARNING=install_scheduled_learning(app,_v66_scanner_engine,learning_store,ASYNC_STRATEGY_VERSION)
except Exception as _scheduled_error:
 SCHEDULED_LEARNING={'installed':False,'error':f'{type(_scheduled_error).__name__}: {_scheduled_error}'}

@app.get('/api/scanner/async-status')
async def scanner_async_status():
    return {'installed':True,'strategy_version':ASYNC_STRATEGY_VERSION,'engine':'full-market-predictive-shortlist-progressive-top10','live_market_source':'Alpaca','cache_scope':'last-scanner-result-only','canonical_top10_contract':True,'scheduled_learning':SCHEDULED_LEARNING,'session_data_fix':SCANNER_SESSION_DATA_FIX}
