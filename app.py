import urllib.request

# Keep v6.6 scanner logic as the stable engine; v6.7 wraps it with async jobs/cache
# so mobile clients do not hold a long HTTP request while the market scan runs.
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/fe683b58c443db1d78d4ec1a9a8e3a1116431805/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

try:
 import asyncio,time,uuid
 from datetime import datetime,timezone
 from fastapi.responses import JSONResponse

 STRATEGY_VERSION_V67='strategy-learning-v6.7-async-scanner-cache'
 _scanner_engine=next((r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 _old_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 if _old_day_route: app.router.routes.remove(_old_day_route)

 _scan_state={'status':'idle','job_id':None,'started_at':None,'finished_at':None,'result':None,'error':None,'duration_sec':None}
 _scan_lock=asyncio.Lock()

 def _public_state():
  result=_scan_state.get('result') or {}
  return {
   'status':_scan_state.get('status'),'job_id':_scan_state.get('job_id'),
   'started_at':_scan_state.get('started_at'),'finished_at':_scan_state.get('finished_at'),
   'duration_sec':_scan_state.get('duration_sec'),'error':_scan_state.get('error'),
   'has_cached_result':bool(result.get('results')),'cached_count':len(result.get('results') or []),
   'strategy_version':STRATEGY_VERSION_V67
  }

 async def _run_scan(job_id,top,candidates):
  if _scanner_engine is None:
   _scan_state.update(status='error',error='scanner_engine_missing',finished_at=datetime.now(timezone.utc).isoformat());return
  async with _scan_lock:
   t0=time.monotonic();_scan_state.update(status='running',job_id=job_id,started_at=datetime.now(timezone.utc).isoformat(),finished_at=None,error=None,duration_sec=None)
   print(f'SCANNER_V67_JOB_START job_id={job_id} top={top} candidates={candidates}',flush=True)
   try:
    response=await _scanner_engine(top=top,candidates=candidates)
    import json
    body=getattr(response,'body',b'{}');payload=json.loads(body.decode('utf-8')) if isinstance(body,(bytes,bytearray)) else {}
    payload['async_strategy_version']=STRATEGY_VERSION_V67;payload['job_id']=job_id;payload['job_status']='complete'
    _scan_state.update(status='complete',result=payload,finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-t0,2),error=None)
    print(f"SCANNER_V67_JOB_DONE job_id={job_id} results={len(payload.get('results') or [])} duration={_scan_state['duration_sec']}",flush=True)
   except Exception as e:
    _scan_state.update(status='error',error=f'{type(e).__name__}: {e}',finished_at=datetime.now(timezone.utc).isoformat(),duration_sec=round(time.monotonic()-t0,2))
    print(f"SCANNER_V67_JOB_ERROR job_id={job_id} error={_scan_state['error']}",flush=True)

 @app.get('/api/scanner/day')
 async def scanner_day_v67(top:int=10,candidates:int=40,refresh:int=0):
  # Compatibility endpoint: return cached data immediately. If none exists, start a job.
  cached=_scan_state.get('result') or {}
  running=_scan_state.get('status')=='running'
  if refresh or (not cached and not running):
   if not running:
    jid=f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    asyncio.create_task(_run_scan(jid,top,candidates));running=True
  if cached:
   out=dict(cached);out.update({'scanner_job':_public_state(),'served_from_cache':True,'refresh_running':running})
   return JSONResponse(out,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION_V67})
  return JSONResponse({'results':[],'scanner_job':_public_state(),'scan_pending':True,'served_from_cache':False,'strategy_version':STRATEGY_VERSION_V67},status_code=202,headers={'Cache-Control':'no-store','X-Scanner-Version':STRATEGY_VERSION_V67})

 @app.post('/api/scanner/day/start')
 async def scanner_day_start_v67(top:int=10,candidates:int=40):
  if _scan_state.get('status')=='running':return JSONResponse({'accepted':True,'already_running':True,'scanner_job':_public_state()},status_code=202)
  jid=f"scan-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
  asyncio.create_task(_run_scan(jid,top,candidates))
  return JSONResponse({'accepted':True,'job_id':jid,'scanner_job':_public_state()},status_code=202)

 @app.get('/api/scanner/day/status')
 async def scanner_day_status_v67():
  return JSONResponse({'scanner_job':_public_state(),'result':_scan_state.get('result') if _scan_state.get('status')=='complete' else None},headers={'Cache-Control':'no-store'})

 SCANNER_ASYNC_STATUS={'installed':True,'strategy_version':STRATEGY_VERSION_V67,'keeps_last_result':True,'single_flight':True,'nonblocking_get':True}
except Exception as e:
 SCANNER_ASYNC_STATUS={'installed':False,'error':f'{type(e).__name__}: {e}'}

@app.get('/api/scanner/async-status')
async def scanner_async_status():return SCANNER_ASYNC_STATUS
