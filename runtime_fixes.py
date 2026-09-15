import asyncio
from datetime import datetime, timezone, timedelta, time as dtime

import httpx
from fastapi.responses import Response

RUNTIME_FIX_VERSION = "2026.09.15-r15-top10-learning"


def _research_dates():
    out=[]; y=2021; m=7
    for _ in range(50):
        nxt=datetime(y+1,1,1) if m==12 else datetime(y,m+1,1)
        out.append((nxt-timedelta(days=1)).date().isoformat())
        m+=1
        if m==13: y+=1; m=1
    return out


def install_runtime_fixes(app):
    import sys
    if getattr(app.state,"runtime_fixes_installed",False): return
    app.state.runtime_fixes_installed=True
    app.state.last_good_day_scan=None
    mod=sys.modules.get("app")
    if mod is None: return

    try:
        import research_50
        research_50.SCENARIOS=_research_dates()
        research_50.install_research_50(app)
    except Exception as exc:
        print("RESEARCH50_INSTALL_ERROR="+repr(exc),flush=True)

    @app.head("/")
    async def root_head():
        return Response(status_code=200,headers={"Cache-Control":"no-store"})

    @app.get("/api/runtime-health")
    async def runtime_health():
        db_ok=False; db_error=None
        try:
            con=mod._db(); con.execute("SELECT 1").fetchone(); con.close(); db_ok=True
        except Exception as exc: db_error=str(exc)
        return {"ok":db_ok,"runtime_fix_version":RUNTIME_FIX_VERSION,"db_writable":db_ok,
                "db_error":db_error,"alpaca_configured":bool(mod.ALPACA_KEY and mod.ALPACA_SECRET),
                "alpha_vantage_configured":bool(mod.ALPHA_KEY),"feed":mod.ALPACA_FEED,
                "startup_research":False,"generated_at":datetime.now(timezone.utc).isoformat()}

    original_day_endpoint=None
    for route in app.routes:
        if getattr(route,"path",None)=="/api/scanner/day" and "GET" in getattr(route,"methods",set()):
            original_day_endpoint=route.endpoint
            break

    def _session_expected_fraction(now_ny):
        t=now_ny.time()
        if t<dtime(9,30): return 0.03
        mins=max(0,min(390,(now_ny.hour*60+now_ny.minute)-(9*60+30)))
        if mins<=5:return 0.05
        if mins<=15:return 0.10
        if mins<=30:return 0.16
        if mins<=60:return 0.25
        if mins<=120:return 0.42
        if mins<=240:return 0.68
        return max(0.68,min(1.0,0.68+(mins-240)/150*0.32))

    async def _safe_snapshot(client,s):
        try:
            pair=await mod._fetch_snapshot(client,s)
            return pair if isinstance(pair,tuple) and len(pair)==2 else (s,{})
        except Exception as exc:
            print(f"SCANNER_SNAPSHOT_FAIL_{s}="+repr(exc),flush=True)
            return (s,{})

    async def _safe_bars(client,s):
        try:
            pair=await mod._fetch_daily_bars(client,s)
            return pair if isinstance(pair,tuple) and len(pair)==2 else (s,[])
        except Exception as exc:
            print(f"SCANNER_BARS_FAIL_{s}="+repr(exc),flush=True)
            return (s,[])

    async def _score_symbols(client,symbols,snapshots=None,source="fallback_watchlist",top=10):
        snapshots=dict(snapshots or {})
        symbols=list(dict.fromkeys([str(s).upper() for s in symbols if s]))
        missing=[s for s in symbols if s not in snapshots]
        if missing:
            pairs=await asyncio.gather(*[_safe_snapshot(client,s) for s in missing])
            snapshots.update(dict(pairs))

        bars_pairs=await asyncio.gather(*[_safe_bars(client,s) for s in symbols])
        bars_map=dict(bars_pairs)
        try:
            news=await mod._fetch_news_batch(client,symbols)
            if not isinstance(news,list): news=[]
        except Exception as exc:
            print("SCANNER_NEWS_FAIL="+repr(exc),flush=True)
            news=[]

        news_map={s:[] for s in symbols}; now=datetime.now(timezone.utc)
        for article in news:
            if not isinstance(article,dict): continue
            for s in article.get("symbols") or []:
                if s in news_map: news_map[s].append(article)

        expected_frac=_session_expected_fraction(now.astimezone(mod.NY)); out=[]
        for s in symbols:
            snap=snapshots.get(s) or {}; latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}; daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}
            price=latest.get("p") or minute.get("c") or daily.get("c"); prev_close=prev.get("c")
            try: price=float(price); prev_close=float(prev_close)
            except Exception: continue
            if price<=0 or prev_close<=0: continue

            change=(price/prev_close-1)*100
            try: daily_volume=float(daily.get("v") or 0)
            except Exception: daily_volume=0.0
            bars=bars_map.get(s) or []
            hist=[]
            for b in bars[:-1] if isinstance(bars,list) else []:
                try:
                    vv=float((b or {}).get("v") or 0)
                    if vv>0: hist.append(vv)
                except Exception: pass
            avg_vol=sum(hist[-20:])/len(hist[-20:]) if hist else None
            rvol=(daily_volume/(avg_vol*expected_frac)) if avg_vol and expected_frac else None
            hi=daily.get("h"); lo=daily.get("l"); strength=None
            try:
                if hi and lo and float(hi)>float(lo): strength=(price-float(lo))/(float(hi)-float(lo))
            except Exception: pass

            articles=news_map.get(s) or []; news_minutes=None
            if articles:
                try:
                    created=datetime.fromisoformat(str(articles[0].get("created_at")).replace("Z","+00:00")); news_minutes=max(0,(now-created).total_seconds()/60)
                except Exception: pass

            try:
                score=mod._score_day_candidate(change,rvol,avg_vol or daily_volume,price,len(articles),news_minutes,strength)
            except Exception:
                # Degraded but useful score: never throw away a valid live snapshot merely because one enrichment failed.
                momentum=min(45,max(0,change*3.0))
                liquidity=20 if daily_volume>=1000000 else 14 if daily_volume>=250000 else 8 if daily_volume>=50000 else 3
                relvol=min(20,max(0,(rvol or 0)*8))
                catalyst=min(15,len(articles)*7)
                score=round(momentum+liquidity+relvol+catalyst)

            catalyst=(articles[0].get("headline") if articles else None) or ("מומנטום/Gap חריג ללא קטליזטור חדשותי מאומת" if change>10 else "סריקת שוק חיה")
            risk=3+(1 if price<2 else 0)+(1 if abs(change)>50 else 0)+(1 if avg_vol and avg_vol<300000 else 0)
            out.append({"ticker":s,"name":s,"domain":None,"score":int(max(0,min(100,score))),"risk":max(1,min(5,risk)),
                        "price":price,"change":round(change,2),"media":min(100,35+len(articles)*15),
                        "catalyst":catalyst,"volume":int(daily_volume),"avg_daily_volume":round(avg_vol) if avg_vol else None,
                        "rvol":round(rvol,2) if rvol is not None else None,"news_count":len(articles),
                        "news_minutes":round(news_minutes,1) if news_minutes is not None else None,
                        "day_high":hi,"day_low":lo,"intraday_strength":round(strength,3) if strength is not None else None,
                        "degraded":not bool(bars)})

        out.sort(key=lambda x:(x.get("score") or 0,x.get("change") or -999,x.get("volume") or 0),reverse=True)
        print(f"SCANNER_SCORE source={source} symbols={len(symbols)} rows={len(out)}",flush=True)
        return out[:top]

    async def _iex_candidates(client,candidate_count):
        assets=await mod._get_assets_all(client)
        chunks=[assets[i:i+80] for i in range(0,len(assets),80)]
        sem=asyncio.Semaphore(6)
        async def pull(chunk):
            async with sem:
                try:
                    j=await mod._alpaca_json(client,"https://data.alpaca.markets/v2/stocks/snapshots",{"symbols":",".join(chunk),"feed":mod.ALPACA_FEED})
                    if not isinstance(j,dict): return {}
                    return j.get("snapshots") if isinstance(j.get("snapshots"),dict) else j
                except Exception: return {}
        packs=await asyncio.gather(*[pull(c) for c in chunks])
        rows=[]; snapmap={}
        for pack in packs:
            if not isinstance(pack,dict): continue
            for sym,snap in pack.items():
                if not isinstance(snap,dict): continue
                daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}; latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}
                price=latest.get("p") or minute.get("c") or daily.get("c"); pc=prev.get("c")
                try: price=float(price); pc=float(pc)
                except Exception: continue
                if price<=0 or pc<=0 or price<1 or price>500: continue
                ch=(price/pc-1)*100
                try: vol=float(daily.get("v") or 0)
                except Exception: vol=0
                # Broad discovery: do not require a stock to have already exploded before it can be scored.
                if ch<-8 and vol<25000: continue
                rows.append((sym,ch,vol)); snapmap[sym]=snap
        rows.sort(key=lambda z:(z[1],z[2]),reverse=True)
        syms=[x[0] for x in rows[:max(candidate_count,200)]]
        return syms,snapmap,len(assets)

    def _remember(payload):
        if isinstance(payload,dict) and isinstance(payload.get("results"),list) and payload["results"]:
            app.state.last_good_day_scan=payload
        return payload

    def _cached(now,reason):
        cached=getattr(app.state,"last_good_day_scan",None)
        if not cached: return None
        payload=dict(cached)
        payload.update({"generated_at":now.isoformat(),"source":"server_last_good_cache","stale":True,"stale_reason":reason})
        print(f"SCANNER_SERVER_CACHE rows={len(payload.get('results') or [])} reason={reason}",flush=True)
        return payload

    async def day_scanner_failsafe(top:int=10,candidates:int=40):
        top=10; candidates=max(200,min(int(candidates) if candidates else 200,500)); now=datetime.now(timezone.utc)
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):
            try:
                p=await original_day_endpoint(top=top,candidates=candidates)
                if isinstance(p,dict) and p.get("results"): return _remember(p)
            except Exception as exc:
                print("SCANNER_ORIGINAL_NO_ALPACA_FAIL="+repr(exc),flush=True)
            return _cached(now,"no_alpaca_and_original_empty") or {"generated_at":now.isoformat(),"source":"empty","results":[]}

        async with httpx.AsyncClient(timeout=40) as client:
            try:
                symbols,snapshots,universe_size=await _iex_candidates(client,candidates)
                if symbols:
                    rows=await _score_symbols(client,symbols,snapshots,"alpaca_iex_full_market",top)
                    if len(rows) >= 10:
                        saved=mod._persist_scanner_signals(rows,now.isoformat(),"alpaca_iex_full_market")
                        return _remember({"generated_at":now.isoformat(),"source":"alpaca_iex_full_market","feed":mod.ALPACA_FEED,
                                "full_market":True,"screener_error":None,"candidate_count":len(symbols),"universe_size":universe_size,
                                "saved_signals":saved,"results":rows,"rvol_basis":"session_normalized","ranking_policy":"always_top_10","learning_sample":True})
            except Exception as exc:
                print("IEX_FAILSAFE_PRIMARY="+repr(exc),flush=True)

            fallback=["NVDA","TSLA","AMD","PLTR","HOOD","COIN","MARA","SOFI","SMCI","RKLB","IONQ","SOUN","RIVN","AAPL","META","AMZN","MSFT","AVGO","MU","INTC","ARM","QCOM","NFLX","GOOGL","CRDO","NBIS","TEM","HIMS","RGTI","QBTS"]
            try:
                rows=await _score_symbols(client,fallback,None,"fallback_liquid_watchlist",top)
            except Exception as exc:
                print("SCANNER_FALLBACK_SCORE_FAIL="+repr(exc),flush=True)
                rows=[]
            if len(rows) >= 10:
                saved=mod._persist_scanner_signals(rows,now.isoformat(),"fallback_liquid_watchlist")
                return _remember({"generated_at":now.isoformat(),"source":"fallback_liquid_watchlist","feed":mod.ALPACA_FEED,
                        "full_market":False,"screener_error":"IEX full-market returned no usable candidates; fallback activated automatically.",
                        "candidate_count":len(fallback),"saved_signals":saved,"results":rows,"rvol_basis":"session_normalized","ranking_policy":"always_top_10","learning_sample":True})

        try:
            p=await original_day_endpoint(top=top,candidates=candidates)
            if isinstance(p,dict) and p.get("results"): return _remember(p)
        except Exception as exc:
            print("SCANNER_ORIGINAL_FINAL_FAIL="+repr(exc),flush=True)
        return _cached(now,"all_live_scan_paths_empty") or {"generated_at":now.isoformat(),"source":"empty","feed":getattr(mod,"ALPACA_FEED",None),"full_market":False,"results":[]}

    if original_day_endpoint:
        for route in app.routes:
            if getattr(route,"path",None)=="/api/scanner/day" and "GET" in getattr(route,"methods",set()):
                route.endpoint=day_scanner_failsafe
                if getattr(route,"dependant",None) is not None: route.dependant.call=day_scanner_failsafe
                break

    # Final client-side OCR override. It installs after the other UI patches so Blink's
    # labels, not unrelated percentages/value fields, determine quantity and average cost.
    ocr_patch=r'''<script id="portfolio-ocr-r14-blink">
(function(){
 const SKIP=new Set(['WWW','WEB','QQ','USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','ETF','BUY','SELL','AVG','COST','MARKET','LIMIT','DAY','GTC','PNL','GAIN','LOSS','PORTFOLIO','OPEN','CLOSE','HIGH','LOW','CHANGE','TODAY']);
 const clean=s=>String(s||'').replace(/,/g,'.').replace(/[–−]/g,'-');
 const nums=s=>[...clean(s).matchAll(/-?\d+(?:\.\d+)?/g)].map(m=>({n:Number(m[0]),i:m.index,raw:m[0]})).filter(x=>Number.isFinite(x.n));
 function nearLabel(text,labelRe,opt={}){
   const m=labelRe.exec(text); if(!m)return null;
   const a=Math.max(0,m.index-(opt.before||70)), b=Math.min(text.length,m.index+m[0].length+(opt.after||70));
   const chunk=text.slice(a,b), rel=m.index-a, all=nums(chunk).filter(x=>x.n>0);
   if(!all.length)return null;
   const ranked=all.map(x=>({x,d:Math.min(Math.abs(x.i-rel),Math.abs(x.i-(rel+m[0].length)))})).sort((p,q)=>p.d-q.d);
   for(const r of ranked){if(!opt.accept||opt.accept(r.x.n,r.x.raw,chunk,r.x.i))return r.x.n}
   return null;
 }
 async function validSymbol(s){
   if(!s||s.length<2||s.length>5||SKIP.has(s))return false;
   try{const r=await fetch('/api/stock/'+encodeURIComponent(s)+'/bundle?range=1M',{cache:'no-store'});if(!r.ok)return false;const j=await r.json();return !!(j?.quote?.price||(j?.bars||[]).length)}catch(_){return false}
 }
 function blinkFields(text){
   const t=clean(text);
   let qty=nearLabel(t,/(?:מספר\s*מניות|כמות|quantity|shares?)/i,{before:90,after:90,accept:(n)=>n>0&&n<100000});
   let buy=nearLabel(t,/(?:מחיר\s*קנ(?:י|יי)ה\s*ממוצע|מחיר\s*ממוצע|average\s*price|avg\.?\s*price|cost\s*basis)/i,{before:100,after:100,accept:(n)=>n>0&&n<100000});
   if(qty==null){
     const precise=[...t.matchAll(/\b(\d+\.\d{3,6})\b/g)].map(m=>Number(m[1])).filter(n=>n>0&&n<100000);
     if(precise.length)qty=precise[0];
   }
   if(buy==null){
     const lm=t.match(/(?:מחיר\s*קנ(?:י|יי)ה\s*ממוצע)[\s\S]{0,80}?\$?\s*(\d+(?:\.\d+)?)/i)||t.match(/\$\s*(\d+(?:\.\d+)?)[\s\S]{0,80}?(?:מחיר\s*קנ(?:י|יי)ה\s*ממוצע)/i);
     if(lm)buy=Number(lm[1]);
   }
   return {qty,buy};
 }
 async function scan(file){
   const st=document.getElementById('ocrStatus'),raw=document.getElementById('ocrRaw'),rows=document.getElementById('ocrRows');
   if(st)st.textContent='קורא צילום Blink וממפה סימול, כמות ומחיר קנייה ממוצע...';
   try{
     let text='';try{text=(await Tesseract.recognize(file,'heb+eng')).data.text||''}catch(_){text=(await Tesseract.recognize(file,'eng')).data.text||''}
     if(raw)raw.value=text;
     const c=[...new Set([...text.toUpperCase().matchAll(/\b[A-Z]{2,5}\b/g)].map(m=>m[0]).filter(x=>!SKIP.has(x)))].slice(0,15);
     let sym=null;for(const s of c){if(await validSymbol(s)){sym=s;break}}
     if(rows)rows.innerHTML='';
     if(!sym){window.addOcrRow?.();if(st)st.textContent='לא זוהה סימול מניה אמין. לא נשמרו נתונים.';return}
     const f=blinkFields(text);
     window.addOcrRow?.(sym,f.qty??'',f.buy??'');
     if(st){
       if(f.qty!=null&&f.buy!=null)st.textContent=`זוהתה ${sym}: כמות ${f.qty} · מחיר קנייה ממוצע $${Number(f.buy).toFixed(2)}. בדוק לפני שמירה.`;
       else st.textContent=`זוהתה ${sym}, אבל לא כל שדות Blink נקראו בביטחון. השלם רק את השדה החסר לפני שמירה.`;
     }
   }catch(e){if(st)st.textContent='הסריקה נכשלה; התיק לא שונה.'}
 }
 function install(){
   const i=document.getElementById('imgInput');if(!i)return;
   i.onchange=async e=>{const f=e.target.files?.[0];if(f)await scan(f)};
 }
 window.addEventListener('load',()=>setTimeout(install,3200),{once:true});
 setTimeout(install,4200);
})();
</script>'''

    @app.middleware("http")
    async def inject_patch(request,call_next):
        response=await call_next(request)
        if request.url.path!="/" or response.status_code!=200 or "text/html" not in response.headers.get("content-type",""): return response
        try:
            body=b"".join([chunk async for chunk in response.body_iterator]); html=body.decode("utf-8")
            if "portfolio-ocr-r14-blink" not in html: html=html.replace("</body>",ocr_patch+"</body>")
            headers={k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")}; headers["Cache-Control"]="no-store, no-cache, must-revalidate"
            return Response(content=html,status_code=response.status_code,headers=headers,media_type="text/html; charset=utf-8")
        except Exception as exc:
            print("FRONTEND_PATCH_ERROR="+repr(exc),flush=True); return response

    print("PRODUCTION_RUNTIME_SAFE=true",flush=True)
    print("DAY_SCANNER_TOP10_R15=true",flush=True)
    print("PORTFOLIO_OCR_BLINK_R14=true",flush=True)
