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

@app.get('/api/premarket/compare')
async def compare_premarket_feeds(symbol: str = ''):
    """Compare the current scan against consolidated SIP minute bars at equal timestamps."""
    import asyncio
    import httpx
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from fastapi.responses import JSONResponse
    scan = _async['state'].get('result') or {}
    symbols = list(dict.fromkeys(str(x.get('ticker', '')).upper() for x in (scan.get('results') or [])[:10] if x.get('ticker')))
    if symbol:
        symbol = symbol.strip().upper()
        if not (1 <= len(symbol) <= 8 and all(c.isalpha() or c == '.' for c in symbol)):
            return JSONResponse({'status':'invalid_symbol'},status_code=400)
        symbols = [symbol]
    now = datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo('America/New_York'))
    start = local.replace(hour=4, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    end = now - timedelta(minutes=16)
    base = {'scan_id': scan.get('scan_id'), 'scan_at': scan.get('generated_at'),
            'checked_at': now.isoformat(), 'symbols': symbols, 'source_a': 'IEX',
            'source_b': '15-minute delayed consolidated SIP', 'delay_minutes': 15}
    if len(symbols) != (1 if symbol else 10):
        return JSONResponse({**base, 'status': 'insufficient_candidates', 'comparison': [],
                             'reason': 'The latest scanner result does not contain ten candidates.'}, headers={'Cache-Control':'no-store'})
    if end <= start:
        return JSONResponse({**base, 'status': 'waiting_for_premarket', 'comparison': []}, headers={'Cache-Control':'no-store'})
    if not (ALPACA_KEY and ALPACA_SECRET):
        return JSONResponse({**base, 'status': 'feed_unavailable', 'comparison': [], 'reason': 'Market data credentials are missing.'}, headers={'Cache-Control':'no-store'})
    headers = {'APCA-API-KEY-ID': ALPACA_KEY, 'APCA-API-SECRET-KEY': ALPACA_SECRET}
    async with httpx.AsyncClient(timeout=25) as client:
        async def read_many(feed):
            try:
                response = await client.get('https://data.alpaca.markets/v2/stocks/bars',
                    headers=headers, params={'symbols':','.join(symbols),'timeframe':'1Min',
                    'start':start.isoformat(),'end':end.isoformat(),'feed':feed,'limit':10000,'sort':'asc'})
                if response.status_code != 200:
                    return {}, f'HTTP {response.status_code}'
                payload = response.json()
                if payload.get('next_page_token'):
                    return {}, 'pagination_required'
                return {sym:{b['t']:b for b in rows if b.get('t') and b.get('c') is not None}
                        for sym,rows in payload.get('bars',{}).items()}, None
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                return {}, type(exc).__name__
        (iex_all, iex_error), (sip_all, sip_error) = await asyncio.gather(read_many('iex'),read_many('delayed_sip'))
    comparisons = []
    for i, symbol in enumerate(symbols):
        iex = iex_all.get(symbol, {})
        sip = sip_all.get(symbol, {})
        shared = sorted(iex.keys() & sip.keys())
        t = shared[-1] if shared else None
        a, b = iex.get(t), sip.get(t)
        comparisons.append({'ticker':symbol, 'iex_bars':len(iex), 'sip_bars':len(sip),
            'iex_last_at':max(iex) if iex else None, 'sip_last_at':max(sip) if sip else None,
            'matched_at':t, 'iex_close':a.get('c') if a else None,
            'sip_close':b.get('c') if b else None,
            'difference_pct':round((a['c']/b['c']-1)*100,4) if a and b and b['c'] else None,
            'iex_error':iex_error, 'sip_error':sip_error})
    return JSONResponse({**base, 'status':'rate_limited' if iex_error == 'HTTP 429' or sip_error == 'HTTP 429' else ('compared' if all(x['matched_at'] for x in comparisons) else 'partial'),
        'comparison':comparisons},headers={'Cache-Control':'no-store'})
