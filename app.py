# v6.8.1 composition: verified full-market scanner + repeatable manual scan + canonical Top-10.
from app_v66 import *
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from pathlib import Path

try:
    _index_path = Path(__file__).with_name('index.html')
    _html = _index_path.read_text(encoding='utf-8')

    # Patch only the scanner fetch block; do not touch layout/styles.
    _old_plain = '''const r=await fetch("/api/scanner/day?top=10&candidates=40");
   const j=await r.json();'''
    _old_refresh = '''const r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});
   const j=await r.json();'''
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
       if(job.status==="complete" && (!requestedJobId || job.job_id===requestedJobId) && sj.result && Array.isArray(sj.result.results)){
         r=sr;j=sj.result;break;
       }
     }
     if(!j || !Array.isArray(j.results))throw new Error("הסריקה לא הסתיימה בזמן. נסה שוב בעוד רגע.");
   }else{
     r=await fetch("/api/scanner/day?top=10&candidates=40",{cache:"no-store"});
     j=await r.json();
     if(r.status===202 || j.scan_pending){
       const requestedJobId=j.requested_job_id||j.scanner_job?.job_id||null;
       const started=Date.now();
       while(Date.now()-started<120000){
         await new Promise(resolve=>setTimeout(resolve,1000));
         const sr=await fetch("/api/scanner/day/status",{cache:"no-store"});
         const sj=await sr.json();
         const job=sj.scanner_job||{};
         if(job.status==="error")throw new Error(job.error||"Scanner job failed");
         if(job.status==="complete" && (!requestedJobId || job.job_id===requestedJobId) && sj.result){r=sr;j=sj.result;break;}
       }
     }
   }
   const canonicalScanId=j.scan_id||j.job_id||j.scanner_job?.job_id||null;
   const canonicalTop10=(Array.isArray(j.results)?j.results:[]).slice(0,10).map((row,index)=>({...row,scanner_rank:index+1,canonical_scan_id:canonicalScanId,canonical_strategy_version:j.strategy_version||row.strategy_version||null,canonical_scanner_result:true}));
   j={...j,results:canonicalTop10,canonical_top10:true,canonical_scan_id:canonicalScanId,canonical_count:canonicalTop10.length};'''

    patched=False
    for old in (_old_refresh,_old_plain):
        if old in _html:
            _html=_html.replace(old,_new,1);patched=True;break
    if not patched:
        # Replace the previous runtime-injected v6.8 block when present in source HTML.
        start='''let r=await fetch("/api/scanner/day?top=10&candidates=40"+(manual?"&refresh=1":""),{cache:"no-store"});'''
        end='''j={...j,results:canonicalTop10,canonical_top10:true,canonical_scan_id:canonicalScanId,canonical_count:canonicalTop10.length};'''
        si=_html.find(start);ei=_html.find(end,si)
        if si>=0 and ei>=0:
            _html=_html[:si]+_new+_html[ei+len(end):];patched=True
    if patched:
        _index_path.write_text(_html,encoding='utf-8');print('SCANNER_UI_EXPLICIT_START=true',flush=True)
    else:
        print('SCANNER_UI_EXPLICIT_START=pattern_missing',flush=True)
except Exception as _ui_patch_error:
    print(f'SCANNER_UI_EXPLICIT_START_ERROR={type(_ui_patch_error).__name__}: {_ui_patch_error}',flush=True)

_v66_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
if _v66_day_route is None:raise RuntimeError('full-market day scanner route not found')
_v66_scanner_engine=_v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async=install_async_scanner(app,_v66_scanner_engine)
app.add_api_route('/api/scanner/day',_async['day'],methods=['GET'],name='scanner_day_v681')
app.add_api_route('/api/scanner/day/start',_async['start'],methods=['POST'],name='scanner_day_start_v681')
app.add_api_route('/api/scanner/day/status',_async['status'],methods=['GET'],name='scanner_day_status_v681')

@app.get('/api/scanner/async-status')
async def scanner_async_status():
    return {'installed':True,'strategy_version':ASYNC_STRATEGY_VERSION,'engine':'full-market-predictive-shortlist-progressive-top10','live_market_source':'Alpaca','cache_scope':'last-scanner-result-only','manual_refresh_ui_patch':True,'manual_refresh_explicit_start_endpoint':True,'manual_refresh_polling':True,'canonical_top10_contract':True,'canonical_rule':'displayed day symbols/order == scanner results[0:10]'}
