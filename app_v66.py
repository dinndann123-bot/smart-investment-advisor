import urllib.request
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/8a9c5728ef31adfe3553a6e0d2dd399c9f08e916/app_v66.py'
_code=urllib.request.urlopen(_STABLE,timeout=30).read().decode('utf-8')
exec(compile(_code,_STABLE,'exec'),globals(),globals())

# v6.6.6 quality guard layered on the hybrid scanner.
# Rebind /api/scanner/day with common-share universe filtering + robust RVOL sanity controls.
try:
 import re,statistics
 _hybrid=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
 STRATEGY_VERSION='strategy-learning-v6.6.6-quality-guard'
 _orig_assets=assets
 async def assets():
  rows=await _orig_assets();clean=[]
  bad_name=('preferred','depositary share','depositary shares','warrant','rights','unit ',' units','note due','notes due')
  for a in rows:
   s=str(a.get('ticker') or '').upper();n=str(a.get('name') or '').lower()
   # Keep ordinary US equity symbols; remove preferred/classes encoded with punctuation and obvious structured securities.
   if not re.fullmatch(r'[A-Z]{1,5}',s):continue
   if any(x in n for x in bad_name):continue
   clean.append(a)
  return clean
 _orig_enrich=enrich
 def enrich(r,bs):
  r=_orig_enrich(r,bs)
  raw=f(r.get('rvol'));base=f(r.get('historical_baseline_volume'));live=f(r.get('day_volume'))
  # Require a meaningful historical denominator. Extreme ratios are capped for ranking and flagged rather than trusted blindly.
  reliable=bool(base>=1000 and live>=1000)
  capped=min(raw,25.0) if raw>0 else 0
  r['rvol_raw']=round(raw,2) if raw else None;r['rvol']=round(capped,2) if capped else None;r['rvol_reliable']=reliable;r['rvol_capped']=bool(raw>25);return r
 _orig_stage=stage
 def stage(r):
  # Do not promote a stock on an unreliable RVOL baseline.
  if not r.get('rvol_reliable'):return 'watch'
  return _orig_stage(r)
 _orig_rank=rank
 def rank(r):
  score,st=_orig_rank(r)
  if r.get('rvol_capped'):score-=8
  return score,st
 async def scanner_v666(top:int=10,candidates:int=40):
  # Call the existing hybrid implementation; its globals resolve to the quality-guard functions above.
  response=await scanner(top=top,candidates=candidates)
  try:
   import json
   p=json.loads(response.body.decode('utf-8'));p['strategy_version']=STRATEGY_VERSION;p['quality_guard']={'common_share_symbol_filter':True,'rvol_cap':25,'minimum_baseline_volume':1000,'unreliable_rvol_excluded_from_predictive':True};response.body=json.dumps(p,separators=(',',':')).encode('utf-8');response.headers['content-length']=str(len(response.body));response.headers['X-Scanner-Version']=STRATEGY_VERSION
  except Exception:pass
  return response
 if _hybrid:app.router.routes.remove(_hybrid)
 app.add_api_route('/api/scanner/day',scanner_v666,methods=['GET'],name='scanner_day_v666')
 SCANNER_UNIVERSE_ALIGNMENT={'installed':True,'strategy_version':STRATEGY_VERSION,'hybrid_live':True,'common_share_filter':True,'rvol_sanity_guard':True,'watch_excluded_from_top10':True,'deep_candidate_cap':180}
 print('SCANNER_V666_INSTALLED common_share_filter=true rvol_cap=25 baseline_min=1000',flush=True)
except Exception as e:
 print(f'SCANNER_V666_INSTALL_ERROR {type(e).__name__}: {e}',flush=True)
