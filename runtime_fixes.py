import asyncio
from datetime import datetime, timezone, timedelta, time as dtime

import httpx
from fastapi.responses import Response

RUNTIME_FIX_VERSION = "2026.09.14-r10-failsafe-scanner"


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

    async def _score_symbols(client,symbols,snapshots=None,source="fallback_watchlist",top=10):
        snapshots=snapshots or {}
        missing=[s for s in symbols if s not in snapshots]
        if missing:
            pairs=await asyncio.gather(*[mod._fetch_snapshot(client,s) for s in missing])
            snapshots.update(dict(pairs))
        bars_pairs,news=await asyncio.gather(
            asyncio.gather(*[mod._fetch_daily_bars(client,s) for s in symbols]),
            mod._fetch_news_batch(client,symbols),
        )
        bars_map=dict(bars_pairs); news_map={s:[] for s in symbols}; now=datetime.now(timezone.utc)
        for article in news:
            for s in article.get("symbols") or []:
                if s in news_map: news_map[s].append(article)
        expected_frac=_session_expected_fraction(now.astimezone(mod.NY)); out=[]
        for s in symbols:
            snap=snapshots.get(s) or {}; latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}; daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}
            price=latest.get("p") or minute.get("c") or daily.get("c"); prev_close=prev.get("c")
            try: price=float(price); prev_close=float(prev_close)
            except Exception: continue
            if price<=0 or prev_close<=0: continue
            change=(price/prev_close-1)*100; daily_volume=float(daily.get("v") or 0)
            bars=bars_map.get(s) or []; hist=[float(b.get("v") or 0) for b in bars[:-1] if float(b.get("v") or 0)>0]
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
            score=mod._score_day_candidate(change,rvol,avg_vol or daily_volume,price,len(articles),news_minutes,strength)
            catalyst=(articles[0].get("headline") if articles else None) or ("מומנטום/Gap חריג ללא קטליזטור חדשותי מאומת" if change>10 else "סריקת שוק חיה")
            risk=3+(1 if price<2 else 0)+(1 if abs(change)>50 else 0)+(1 if avg_vol and avg_vol<300000 else 0)
            out.append({"ticker":s,"name":s,"domain":None,"score":int(score),"risk":max(1,min(5,risk)),
                        "price":price,"change":round(change,2),"media":min(100,35+len(articles)*15),
                        "catalyst":catalyst,"volume":int(daily_volume),"avg_daily_volume":round(avg_vol) if avg_vol else None,
                        "rvol":round(rvol,2) if rvol is not None else None,"news_count":len(articles),
                        "news_minutes":round(news_minutes,1) if news_minutes is not None else None,
                        "day_high":hi,"day_low":lo,"intraday_strength":round(strength,3) if strength is not None else None})
        out.sort(key=lambda x:(x.get("score") or 0,x.get("change") or -999),reverse=True)
        return out[:top]

    async def _iex_candidates(client,candidate_count):
        assets=await mod._get_assets_all(client)
        # Keep request size conservative; some free-feed responses reject very long URLs.
        chunks=[assets[i:i+80] for i in range(0,len(assets),80)]
        sem=asyncio.Semaphore(6); packs=[]
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
            for sym,snap in pack.items():
                if not isinstance(snap,dict): continue
                daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}; latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}
                price=latest.get("p") or minute.get("c") or daily.get("c"); pc=prev.get("c")
                try: price=float(price); pc=float(pc)
                except Exception: continue
                if price<=0 or pc<=0 or price<1 or price>500: continue
                ch=(price/pc-1)*100; vol=float(daily.get("v") or 0)
                if ch<1.0 and vol<50000: continue
                rows.append((sym,ch,vol)); snapmap[sym]=snap
        rows.sort(key=lambda z:(z[1],z[2]),reverse=True)
        syms=[x[0] for x in rows[:max(candidate_count,60)]]
        return syms,snapmap,len(assets)

    async def day_scanner_failsafe(top:int=10,candidates:int=40):
        top=max(3,min(int(top),20)); candidates=max(top,min(int(candidates),60)); now=datetime.now(timezone.utc)
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):
            return await original_day_endpoint(top=top,candidates=candidates)
        async with httpx.AsyncClient(timeout=40) as client:
            try:
                symbols,snapshots,universe_size=await _iex_candidates(client,candidates)
                if symbols:
                    rows=await _score_symbols(client,symbols,snapshots,"alpaca_iex_full_market",top)
                    if rows:
                        saved=mod._persist_scanner_signals(rows,now.isoformat(),"alpaca_iex_full_market")
                        return {"generated_at":now.isoformat(),"source":"alpaca_iex_full_market","feed":mod.ALPACA_FEED,
                                "full_market":True,"screener_error":None,"candidate_count":len(symbols),"universe_size":universe_size,
                                "saved_signals":saved,"results":rows,"rvol_basis":"session_normalized"}
            except Exception as exc:
                print("IEX_FAILSAFE_PRIMARY="+repr(exc),flush=True)

            # Never leave the UI empty: use a broad, liquid fallback universe and individual snapshots.
            fallback=["NVDA","TSLA","AMD","PLTR","HOOD","COIN","MARA","SOFI","SMCI","RKLB","IONQ","SOUN","RIVN","AAPL","META","AMZN","MSFT","AVGO","MU","INTC","ARM","QCOM","NFLX","GOOGL"]
            rows=await _score_symbols(client,fallback,None,"fallback_liquid_watchlist",top)
            if rows:
                saved=mod._persist_scanner_signals(rows,now.isoformat(),"fallback_liquid_watchlist")
                return {"generated_at":now.isoformat(),"source":"fallback_liquid_watchlist","feed":mod.ALPACA_FEED,
                        "full_market":False,"screener_error":"IEX full-market returned no usable candidates; fallback activated automatically.",
                        "candidate_count":len(fallback),"saved_signals":saved,"results":rows,"rvol_basis":"session_normalized"}

        # Last fallback to the original backend route.
        return await original_day_endpoint(top=top,candidates=candidates)

    if original_day_endpoint:
        for route in app.routes:
            if getattr(route,"path",None)=="/api/scanner/day" and "GET" in getattr(route,"methods",set()):
                route.endpoint=day_scanner_failsafe
                if getattr(route,"dependant",None) is not None: route.dependant.call=day_scanner_failsafe
                break

    ocr_patch=r'''<script id="portfolio-ocr-r10">
(function(){
 const SKIP=new Set(['USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','ETF','BUY','SELL','AVG','COST','MARKET','LIMIT','DAY','GTC','PNL']);
 const num=v=>{const n=Number(String(v||'').replace(/[$₪,%\s]/g,'').replace(',','.'));return Number.isFinite(n)?n:null};
 async function validSymbol(s){try{if(!s||SKIP.has(s)||s.length>5)return false;const r=await fetch('/api/stock/'+encodeURIComponent(s)+'/bundle?range=1M',{cache:'no-store'});if(!r.ok)return false;const j=await r.json();return !!(j?.quote?.price||(j?.bars||[]).length)}catch(e){return false}}
 function labeled(t,ps){for(const p of ps){const m=t.match(p);if(m){const n=num(m[1]);if(n&&n>0)return n}}return null}
 async function scan(file){
  const st=document.getElementById('ocrStatus'),raw=document.getElementById('ocrRaw'),rows=document.getElementById('ocrRows'); st.textContent='קורא תמונה ומאמת נתונים...';
  try{let text='';try{text=(await Tesseract.recognize(file,'heb+eng')).data.text||''}catch(_){text=(await Tesseract.recognize(file,'eng')).data.text||''}raw.value=text;
   const c=[...new Set([...text.toUpperCase().matchAll(/\b[A-Z]{1,5}\b/g)].map(m=>m[0]).filter(x=>!SKIP.has(x)))].slice(0,30);
   const checks=await Promise.all(c.map(async s=>[s,await validSymbol(s)]));const syms=checks.filter(x=>x[1]).map(x=>x[0]).slice(0,12);rows.innerHTML='';
   const qty=labeled(text,[/(?:כמות|מספר\s*מניות|quantity|shares?)\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)/i]);
   const buy=labeled(text,[/(?:מחיר\s*(?:קנייה|ממוצע)|עלות\s*ממוצעת|average\s*price|avg\.?\s*price|buy\s*price|cost\s*basis)\s*[:\-]?\s*[$₪]?\s*([0-9]+(?:[.,][0-9]+)?)/i]);
   if(!syms.length){addOcrRow();st.textContent='לא זוהה סימול בוודאות — השארתי שורה ידנית.';return}
   syms.forEach((s,i)=>addOcrRow(s,i===0&&qty?qty:'',i===0&&buy?buy:''));st.textContent='הסריקה הסתיימה. בדוק את השדות לפני שמירה.';
  }catch(e){st.textContent='הסריקה נכשלה; לא נשמרו נתונים שגויים.'}
 }
 window.addEventListener('load',()=>{const i=document.getElementById('imgInput');if(i)i.onchange=async e=>{const f=e.target.files?.[0];if(f)await scan(f)}});
})();
</script>'''

    @app.middleware("http")
    async def inject_patch(request,call_next):
        response=await call_next(request)
        if request.url.path!="/" or response.status_code!=200 or "text/html" not in response.headers.get("content-type",""): return response
        try:
            body=b"".join([chunk async for chunk in response.body_iterator]); html=body.decode("utf-8")
            if "portfolio-ocr-r10" not in html: html=html.replace("</body>",ocr_patch+"</body>")
            headers={k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")}; headers["Cache-Control"]="no-store, no-cache, must-revalidate"
            return Response(content=html,status_code=response.status_code,headers=headers,media_type="text/html; charset=utf-8")
        except Exception as exc:
            print("FRONTEND_PATCH_ERROR="+repr(exc),flush=True); return response

    print("PRODUCTION_RUNTIME_SAFE=true",flush=True)
    print("DAY_SCANNER_FAILSAFE_R10=true",flush=True)
    print("PORTFOLIO_OCR_R10=true",flush=True)
