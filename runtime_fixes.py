import asyncio
from datetime import datetime, timezone, timedelta, time as dtime

import httpx
from fastapi.responses import Response


RUNTIME_FIX_VERSION = "2026.09.14-r9-scanner-ocr"


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

    if getattr(app.state, "runtime_fixes_installed", False):
        return
    app.state.runtime_fixes_installed = True

    app.__module__ = "app"
    mod = sys.modules.get("app") or sys.modules.get(app.__module__)
    if mod is None:
        return

    try:
        import research_50
        research_50.SCENARIOS = _research_dates()
        research_50.install_research_50(app)
    except Exception as exc:
        print("RESEARCH50_INSTALL_ERROR=" + repr(exc), flush=True)

    @app.head("/")
    async def root_head():
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    @app.get("/api/runtime-health")
    async def runtime_health():
        db_ok = False
        db_error = None
        try:
            con = mod._db(); con.execute("SELECT 1").fetchone(); con.close(); db_ok = True
        except Exception as exc:
            db_error = str(exc)
        return {
            "ok": db_ok,
            "runtime_fix_version": RUNTIME_FIX_VERSION,
            "db_writable": db_ok,
            "db_error": db_error,
            "alpaca_configured": bool(mod.ALPACA_KEY and mod.ALPACA_SECRET),
            "alpha_vantage_configured": bool(mod.ALPHA_KEY),
            "feed": mod.ALPACA_FEED,
            "startup_research": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _persist_scanner_signals_fixed(items, generated_at, source):
        con = mod._db()
        created = generated_at or datetime.now(timezone.utc).isoformat()
        d = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(mod.NY).date().isoformat()
        saved = 0
        for x in items:
            score = float(x.get("score") or 0)
            rvol = x.get("rvol")
            news = int(x.get("news_count") or 0)
            qualifies = score >= 85 and ((rvol is not None and float(rvol) >= 1.5) or news > 0)
            if not qualifies:
                continue
            plan = mod._derive_live_signal_plan(x)
            if not plan:
                continue
            try:
                cur = con.execute(
                    """INSERT OR IGNORE INTO live_signals(
                        created_at,signal_date,symbol,signal_type,score,entry,stop,target1,target2,
                        source,catalyst,rvol,gap_pct,status
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (created,d,x.get("ticker"),"scanner",score,plan["entry"],plan["stop"],plan["target1"],plan["target2"],source,x.get("catalyst"),float(rvol) if rvol is not None else None,float(x.get("change")) if x.get("change") is not None else None,"open"),
                )
                if cur.rowcount == 1: saved += 1
            except Exception:
                pass
        con.commit(); con.close(); return saved

    async def _refresh_live_signal_rows_fixed(rows):
        if not rows: return []
        sem = asyncio.Semaphore(6)
        async with httpx.AsyncClient(timeout=25) as client:
            async def one(row):
                async with sem:
                    r=dict(row); symbol=r["symbol"]; signal_date=r["signal_date"]
                    entry=float(r["entry"] or 0); stop=float(r["stop"] or 0) if r["stop"] else None
                    t1=float(r["target1"] or 0) if r["target1"] else None; t2=float(r["target2"] or 0) if r["target2"] else None
                    hit1=bool(r["hit1"]); hit2=bool(r["hit2"]); stopped=bool(r["stopped"])
                    price_task=asyncio.create_task(mod._latest_price_for_signal(client,symbol))
                    signal_day_task=asyncio.create_task(mod._fetch_minute_window(client,symbol,signal_date,mod.ALPACA_FEED)) if (mod.ALPACA_KEY and mod.ALPACA_SECRET) else None
                    daily_task=asyncio.create_task(mod._bars_since_signal(client,symbol,signal_date))
                    price=await price_task; minute_bars=await signal_day_task if signal_day_task else []; daily_bars=await daily_task
                    try: created_local=datetime.fromisoformat(str(r["created_at"]).replace("Z","+00:00")).astimezone(mod.NY)
                    except Exception: created_local=None
                    ordered=[]
                    for b in minute_bars:
                        dt=mod._bar_dt(b)
                        if not dt or dt.date().isoformat()!=signal_date: continue
                        if created_local and dt<created_local: continue
                        ordered.append((dt,b,"minute"))
                    for b in daily_bars:
                        dt=mod._bar_dt(b)
                        if not dt or dt.date().isoformat()<=signal_date: continue
                        ordered.append((dt,b,"daily"))
                    ordered.sort(key=lambda z:z[0]); highs=[]; lows=[]; terminal=hit2 or stopped
                    for _,b,_ in ordered:
                        hi=float(b.get("h") or 0); lo=float(b.get("l") or 0)
                        if hi>0: highs.append(hi)
                        if lo>0: lows.append(lo)
                        if terminal: continue
                        if stop and lo>0 and lo<=stop and not hit1: stopped=True; terminal=True; continue
                        if t1 and hi>=t1: hit1=True
                        if t2 and hi>=t2: hit2=True; terminal=True
                    status="target2" if hit2 else "stopped" if stopped else "target1" if hit1 else "open"
                    maxret=((max(highs)/entry-1)*100) if highs and entry else None
                    minret=((min(lows)/entry-1)*100) if lows and entry else None
                    curret=((price/entry-1)*100) if price and entry else None
                    rr=2.5 if hit2 else -1.0 if stopped else None
                    r.update({"last_price":price,"hit1":int(hit1),"hit2":int(hit2),"stopped":int(stopped),"status":status,"max_return_pct":maxret,"min_return_pct":minret,"current_return_pct":curret,"result_r":rr,"last_checked_at":datetime.now(timezone.utc).isoformat()})
                    return r
            return await asyncio.gather(*[one(row) for row in rows])

    async def _iex_universe_candidates(client, candidate_count):
        """Market-wide discovery that works with the free IEX feed; no SIP screener required."""
        assets = await mod._get_assets_all(client)
        chunks=[assets[i:i+180] for i in range(0,len(assets),180)]
        sem=asyncio.Semaphore(7)
        rows=[]
        async def pull(chunk):
            async with sem:
                try:
                    j=await mod._alpaca_json(client,"https://data.alpaca.markets/v2/stocks/snapshots",{"symbols":",".join(chunk),"feed":mod.ALPACA_FEED})
                    if not isinstance(j,dict): return {}
                    snapshots=j.get("snapshots")
                    if isinstance(snapshots,dict): return snapshots
                    return j
                except Exception:
                    return {}
        packs=await asyncio.gather(*[pull(c) for c in chunks])
        for pack in packs:
            for sym,snap in pack.items():
                if not isinstance(snap,dict): continue
                latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}; daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}
                price=latest.get("p") or minute.get("c") or daily.get("c"); prev_close=prev.get("c")
                try: price=float(price); prev_close=float(prev_close)
                except Exception: continue
                if price<=0 or prev_close<=0 or price<1 or price>500: continue
                change=(price/prev_close-1)*100
                vol=float(daily.get("v") or 0)
                if change < 2.0 and vol < 100000: continue
                rows.append((sym,change,vol,snap))
        rows.sort(key=lambda z:(z[1],z[2]),reverse=True)
        movers=rows[:max(candidate_count,60)]
        liquid=sorted(rows,key=lambda z:z[2],reverse=True)[:max(20,candidate_count//2)]
        merged=[]; seen=set(); snapmap={}
        for z in movers+liquid:
            if z[0] in seen: continue
            seen.add(z[0]); merged.append(z[0]); snapmap[z[0]]=z[3]
            if len(merged)>=max(candidate_count,60): break
        return merged,snapmap,len(assets)

    def _session_expected_fraction(now_ny):
        t=now_ny.time()
        if t < dtime(9,30): return 0.03
        mins=max(0,min(390,(now_ny.hour*60+now_ny.minute)-(9*60+30)))
        if mins<=5: return 0.05
        if mins<=15: return 0.10
        if mins<=30: return 0.16
        if mins<=60: return 0.25
        if mins<=120: return 0.42
        if mins<=240: return 0.68
        return max(0.68,min(1.0,0.68+(mins-240)/150*0.32))

    async def _day_scanner_iex(top=10,candidates=40):
        top=max(3,min(int(top),20)); candidates=max(top,min(int(candidates),60))
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):
            return await original_day_endpoint(top=top,candidates=candidates)
        now=datetime.now(timezone.utc); now_ny=now.astimezone(mod.NY)
        async with httpx.AsyncClient(timeout=40) as client:
            try:
                symbols,snapshots,universe_size=await _iex_universe_candidates(client,candidates)
            except Exception as exc:
                print("IEX_UNIVERSE_SCAN_ERROR="+repr(exc),flush=True)
                return await original_day_endpoint(top=top,candidates=candidates)
            if not symbols:
                return {"generated_at":now.isoformat(),"source":"alpaca_iex_full_market","feed":mod.ALPACA_FEED,"full_market":True,"screener_error":None,"candidate_count":0,"universe_size":universe_size,"saved_signals":0,"results":[]}
            bar_pairs,news=await asyncio.gather(
                asyncio.gather(*[mod._fetch_daily_bars(client,s) for s in symbols]),
                mod._fetch_news_batch(client,symbols),
            )
        bars_map=dict(bar_pairs); news_map={s:[] for s in symbols}
        for article in news:
            for s in article.get("symbols") or []:
                if s in news_map: news_map[s].append(article)
        expected_frac=_session_expected_fraction(now_ny); results=[]
        for s in symbols:
            snap=snapshots.get(s) or {}; latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}; daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}
            price=latest.get("p") or minute.get("c") or daily.get("c"); prev_close=prev.get("c")
            try: price=float(price); change=(price/float(prev_close)-1)*100
            except Exception: continue
            daily_volume=float(daily.get("v") or 0); bars=bars_map.get(s) or []
            hist=[float(b.get("v") or 0) for b in bars[:-1] if float(b.get("v") or 0)>0]
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
            if now_ny.time()<dtime(9,45) and change>=5 and rvol is not None and rvol>=2: score=min(100,score+8)
            risk=3
            if price<2: risk+=1
            if abs(change)>50: risk+=1
            if avg_vol and avg_vol<300000: risk+=1
            if not articles and change>20: risk+=1
            risk=max(1,min(5,risk))
            catalyst=(articles[0].get("headline") if articles else None) or ("מומנטום/Gap חריג ללא קטליזטור חדשותי מאומת" if change>10 else "סריקת IEX חיה")
            results.append({"ticker":s,"name":s,"domain":None,"score":int(score),"risk":risk,"price":price,"change":round(change,2),"media":min(100,35+len(articles)*15+(15 if news_minutes is not None and news_minutes<180 else 0)),"catalyst":catalyst,"volume":int(daily_volume),"avg_daily_volume":round(avg_vol) if avg_vol else None,"rvol":round(rvol,2) if rvol is not None else None,"news_count":len(articles),"news_minutes":round(news_minutes,1) if news_minutes is not None else None,"day_high":hi,"day_low":lo,"intraday_strength":round(strength,3) if strength is not None else None})
        results.sort(key=lambda x:(x.get("score") or 0,x.get("change") or -999),reverse=True)
        selected=results[:top]; saved=mod._persist_scanner_signals(selected,now.isoformat(),"alpaca_iex_full_market")
        return {"generated_at":now.isoformat(),"source":"alpaca_iex_full_market","feed":mod.ALPACA_FEED,"full_market":True,"screener_error":None,"candidate_count":len(symbols),"universe_size":universe_size,"saved_signals":saved,"results":selected,"rvol_basis":"session_normalized"}

    mod._persist_scanner_signals = _persist_scanner_signals_fixed
    mod._refresh_live_signal_rows = _refresh_live_signal_rows_fixed

    original_day_endpoint=None
    for route in app.routes:
        if getattr(route,"path",None)=="/api/scanner/day" and "GET" in getattr(route,"methods",set()):
            original_day_endpoint=route.endpoint
            route.endpoint=_day_scanner_iex
            if getattr(route,"dependant",None) is not None:
                route.dependant.call=_day_scanner_iex
            break

    ocr_patch = r'''<script id="portfolio-ocr-r9">
(function(){
  const SKIP=new Set(['USD','TOTAL','PRICE','VALUE','NASDAQ','NYSE','NYS','ETF','BUY','SELL','AVG','PCT','COST','MARKET','LIMIT','DAY','GTC','PNL']);
  const num=v=>{if(v==null)return null;const n=Number(String(v).replace(/[$₪,%\s]/g,'').replace(',','.'));return Number.isFinite(n)?n:null};
  async function validSymbol(s){
    if(!s||SKIP.has(s)||s.length>5)return false;
    try{const r=await fetch('/api/stock/'+encodeURIComponent(s)+'/bundle?range=1M',{cache:'no-store'});if(!r.ok)return false;const j=await r.json();return !!(j?.quote?.price||(j?.bars||[]).length)}catch(e){return false}
  }
  function labeled(text,patterns){
    for(const p of patterns){const m=text.match(p);if(m){const n=num(m[1]);if(n!=null&&n>0)return n}}
    return null;
  }
  async function scanPortfolioImage(file){
    const status=document.getElementById('ocrStatus'), raw=document.getElementById('ocrRaw'), rows=document.getElementById('ocrRows');
    status.textContent='קורא את התמונה ומאמת מניות...';
    let text='';
    try{
      if(typeof Tesseract==='undefined')throw new Error('OCR library unavailable');
      try{text=(await Tesseract.recognize(file,'heb+eng')).data.text||''}catch(_e){text=(await Tesseract.recognize(file,'eng')).data.text||''}
      raw.value=text;
      const upper=text.toUpperCase();
      const candidates=[...new Set([...upper.matchAll(/\b[A-Z]{1,5}\b/g)].map(m=>m[0]).filter(x=>!SKIP.has(x)))].slice(0,25);
      const checks=await Promise.all(candidates.map(async s=>[s,await validSymbol(s)]));
      const symbols=checks.filter(x=>x[1]).map(x=>x[0]).slice(0,12);
      rows.innerHTML='';
      const qty=labeled(text,[/(?:כמות|מספר\s*מניות|quantity|shares?)\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)/i]);
      const buy=labeled(text,[/(?:מחיר\s*(?:קנייה|ממוצע)|עלות\s*ממוצעת|average\s*price|avg\.?\s*price|buy\s*price|cost\s*basis)\s*[:\-]?\s*[$₪]?\s*([0-9]+(?:[.,][0-9]+)?)/i]);
      if(!symbols.length){
        if(typeof addOcrRow==='function')addOcrRow();
        status.textContent='לא זוהה סימול מניה בוודאות. השארתי שורה לעריכה ידנית ולא שמרתי נתון חשוד.';
        return;
      }
      symbols.forEach((s,i)=>addOcrRow(s,i===0&&qty?qty:'',i===0&&buy?buy:''));
      const filled=(qty&&buy)?' זוהו גם כמות ומחיר קנייה.':' הסימול אומת מול נתוני השוק; כמות/מחיר שלא זוהו נשארו ריקים לבדיקה.';
      status.textContent='הזיהוי הסתיים.'+filled;
    }catch(err){
      status.textContent='הזיהוי נכשל; לא נשמרו נתונים אוטומטית. אפשר להזין ידנית.';
    }
  }
  window.addEventListener('load',()=>{
    const input=document.getElementById('imgInput'); if(!input)return;
    input.onchange=async e=>{const f=e.target.files?.[0];if(f)await scanPortfolioImage(f)};
  });
})();
</script>'''

    @app.middleware("http")
    async def _inject_frontend_runtime_patch(request, call_next):
        response = await call_next(request)
        if request.url.path != "/" or response.status_code != 200:
            return response
        ctype = response.headers.get("content-type", "")
        if "text/html" not in ctype:
            return response
        try:
            body = b"".join([chunk async for chunk in response.body_iterator])
            html = body.decode("utf-8")
            if "portfolio-ocr-r9" not in html:
                html = html.replace("</body>", ocr_patch + "</body>")
            headers = {k:v for k,v in response.headers.items() if k.lower() not in ("content-length","content-type")}
            headers["Cache-Control"] = "no-store"
            return Response(content=html,status_code=response.status_code,headers=headers,media_type="text/html; charset=utf-8")
        except Exception as exc:
            print("FRONTEND_PATCH_ERROR="+repr(exc),flush=True)
            return response

    print("PRODUCTION_RUNTIME_SAFE=true", flush=True)
    print("IEX_FULL_MARKET_SCANNER=true", flush=True)
    print("PORTFOLIO_OCR_PATCH=true", flush=True)