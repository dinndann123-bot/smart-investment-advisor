import asyncio
import math
import statistics
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException, Query

LONG_UNIVERSE = [
    "SPY","QQQ","VOO","VTI","IWM","DIA",
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","COST","LLY","JPM","XOM","JNJ","PG","VRT",
    "PLTR","APP","RKLB","SMCI","AMD","TSM","ORCL","NFLX","UBER","HOOD","COIN","MSTR","CRWD","PANW","ANET","MU"
]

_CACHE = {"at": None, "value": None}
_CACHE_TTL = 6 * 3600


def _f(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _ret(a,b):
    return ((b/a)-1)*100 if a and b else None


def _stdev_pct(vals):
    rets=[]
    for a,b in zip(vals[:-1],vals[1:]):
        if a and b: rets.append(b/a-1)
    return statistics.pstdev(rets)*(252**0.5)*100 if len(rets)>=10 else None


def _score(hist):
    closes=[x["c"] for x in hist]
    vols=[x["v"] for x in hist]
    if len(closes)<252:return None
    c=closes[-1]
    r1=_ret(closes[-21],c) if len(closes)>=21 else None
    r3=_ret(closes[-63],c) if len(closes)>=63 else None
    r6=_ret(closes[-126],c) if len(closes)>=126 else None
    r12=_ret(closes[-252],c)
    ma50=sum(closes[-50:])/50
    ma200=sum(closes[-200:])/200
    high52=max(x["h"] for x in hist[-252:] if x["h"]>0)
    dd52=(c/high52-1)*100 if high52 else None
    vol=_stdev_pct(closes[-252:])
    avgvol=sum(vols[-60:])/60 if len(vols)>=60 else None

    score=0.0; reasons=[]
    if r12 is not None:
        if r12>=30:score+=24
        elif r12>=15:score+=19
        elif r12>=5:score+=12
        elif r12<0:score-=8
        reasons.append("12m_momentum")
    if r6 is not None:
        if r6>=18:score+=18
        elif r6>=8:score+=13
        elif r6>=0:score+=7
        else:score-=5
    if r3 is not None:
        if r3>=10:score+=10
        elif r3>=0:score+=6
        else:score-=4
    if r1 is not None:
        if r1>=5:score+=4
        elif r1< -8:score-=4
    if c>ma50:score+=10
    if c>ma200:score+=15;reasons.append("above_ma200")
    elif c<ma200*0.9:score-=10
    if ma50>ma200:score+=8;reasons.append("trend_alignment")
    if dd52 is not None:
        if -12<=dd52<=0:score+=7
        elif dd52<-30:score-=5
    if vol is not None:
        if 18<=vol<=55:score+=4
        elif vol>90:score-=6
    if avgvol and avgvol>=500_000:score+=2
    score=max(0,min(100,score))
    return {"score":round(score,1),"r1":r1,"r3":r3,"r6":r6,"r12":r12,"ma50":ma50,"ma200":ma200,"dd52":dd52,"volatility":vol,"reasons":reasons}


async def _fetch_symbol(client, symbol, headers, feed, years):
    end=datetime.now(timezone.utc)
    start=end-timedelta(days=int(365.25*years)+400)
    r=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",headers=headers,params={
        "timeframe":"1Day","start":start.isoformat(),"end":end.isoformat(),"limit":10000,
        "adjustment":"split","feed":feed,"sort":"asc"
    })
    if r.status_code>=400:return []
    rows=[]
    for b in (r.json() or {}).get("bars") or []:
        c=_f(b.get("c"));h=_f(b.get("h"));v=_f(b.get("v"));t=str(b.get("t") or "")[:10]
        if c and h and t:rows.append({"d":t,"c":c,"h":h,"v":v or 0})
    return rows


def _monthly_indices(rows):
    out=[]; last_month=None
    for i,r in enumerate(rows):
        m=r["d"][:7]
        if last_month is not None and m!=last_month:
            out.append(i-1)
        last_month=m
    if rows:out.append(len(rows)-1)
    return out


def _evaluate_symbol(symbol, rows):
    events=[]
    for idx in _monthly_indices(rows):
        if idx<252:continue
        metrics=_score(rows[:idx+1])
        if not metrics:continue
        entry=rows[idx]["c"]
        fwd1=rows[idx+21]["c"] if idx+21<len(rows) else None
        fwd3=rows[idx+63]["c"] if idx+63<len(rows) else None
        fwd12=rows[idx+252]["c"] if idx+252<len(rows) else None
        ret1=_ret(entry,fwd1) if fwd1 else None
        ret3=_ret(entry,fwd3) if fwd3 else None
        ret12=_ret(entry,fwd12) if fwd12 else None
        events.append({
            "symbol":symbol,"date":rows[idx]["d"],"score":metrics["score"],"entry":entry,
            "return_1m_pct":round(ret1,2) if ret1 is not None else None,
            "return_3m_pct":round(ret3,2) if ret3 is not None else None,
            "return_12m_pct":round(ret12,2) if ret12 is not None else None,
            "success_1m":(ret1 is not None and ret1>=4),
            "success_3m":(ret3 is not None and ret3>=8),
            "success_12m":(ret12 is not None and ret12>=15),
            "metrics":metrics,
        })
    return events


def _stats(rows, field):
    return_key={"success_1m":"return_1m_pct","success_3m":"return_3m_pct","success_12m":"return_12m_pct"}[field]
    arr=[x for x in rows if x.get(return_key) is not None]
    if not arr:return {"samples":0,"success_pct":None,"avg_return_pct":None}
    wins=sum(1 for x in arr if x[field])
    return {"samples":len(arr),"success_pct":round(wins/len(arr)*100,1),"avg_return_pct":round(statistics.mean(x[return_key] for x in arr),2)}


def _bucket(events, field):
    specs=[("90-100",90,100),("80-89",80,89.999),("70-79",70,79.999),("0-69",0,69.999)]
    return [{"bucket":name,**_stats([x for x in events if lo<=x["score"]<=hi],field)} for name,lo,hi in specs]


def get_cached_long_success(symbol, score=None):
    val=_CACHE.get("value") or {}
    events=val.get("test_events") or []
    own=[x for x in events if x["symbol"]==symbol]
    out={"one_month":None,"three_month":None,"one_year":None,"source":"long_backtest_holdout"}
    for field,key in [("success_1m","one_month"),("success_3m","three_month"),("success_12m","one_year")]:
        own_stat=_stats(own,field)
        if own_stat["samples"]>=4:
            out[key]={**own_stat,"basis":"היסטוריית Holdout של הנייר עצמו"}
            continue
        if score is None:
            out[key]={"samples":own_stat["samples"],"success_pct":None,"avg_return_pct":None,"basis":"אין מספיק מדגם"}
            continue
        lo=90 if score>=90 else 80 if score>=80 else 70 if score>=70 else 0
        hi=100 if lo==90 else 89.999 if lo==80 else 79.999 if lo==70 else 69.999
        b=[x for x in events if lo<=x["score"]<=hi]
        st=_stats(b,field)
        st["basis"]=f"Holdout בטווח ציון {int(lo)}–{int(hi)}" if st["samples"]>=10 else "מדגם קטן מדי"
        if st["samples"]<10:st["success_pct"]=None
        out[key]=st
    return out


def _point_in_time_pick(symbol, rows, as_of):
    hist=[r for r in rows if r["d"]<=as_of]
    if len(hist)<252:return None
    idx=len(hist)-1
    m=_score(hist)
    if not m:return None
    entry=hist[-1]["c"]
    future=rows[idx+1:]
    def future_close(n):
        return future[n-1]["c"] if len(future)>=n else None
    p1=future_close(21);p3=future_close(63);p12=future_close(252)
    max1=max((x["h"] for x in future[:21]),default=None)
    max12=max((x["h"] for x in future[:252]),default=None)
    ret1=_ret(entry,p1) if p1 else None
    ret3=_ret(entry,p3) if p3 else None
    ret12=_ret(entry,p12) if p12 else None
    max1ret=_ret(entry,max1) if max1 else None
    max12ret=_ret(entry,max12) if max12 else None
    return {
        "symbol":symbol,"as_of_trade_date":hist[-1]["d"],"entry":round(entry,4),"score":m["score"],
        "metrics":{k:(round(v,2) if isinstance(v,(int,float)) and v is not None else v) for k,v in m.items()},
        "return_1m_pct":round(ret1,2) if ret1 is not None else None,
        "return_3m_pct":round(ret3,2) if ret3 is not None else None,
        "return_12m_pct":round(ret12,2) if ret12 is not None else None,
        "max_up_1m_pct":round(max1ret,2) if max1ret is not None else None,
        "max_up_12m_pct":round(max12ret,2) if max12ret is not None else None,
        "success_1m":bool(ret1 is not None and ret1>=4),
        "success_12m":bool(ret12 is not None and ret12>=15),
        "exploded_1m":bool(max1ret is not None and max1ret>=15),
        "exploded_12m":bool(max12ret is not None and max12ret>=30),
    }


def install_long_strategy(app):
    import sys
    mod=sys.modules.get(app.__module__) or sys.modules.get("app")

    @app.get("/api/strategy/long/validate")
    async def validate_long_strategy(years:int=Query(6,ge=4,le=10),symbols:int=Query(len(LONG_UNIVERSE),ge=10,le=len(LONG_UNIVERSE))):
        now=datetime.now(timezone.utc)
        if _CACHE.get("value") and _CACHE.get("at") and (now-_CACHE["at"]).total_seconds()<_CACHE_TTL:
            out=dict(_CACHE["value"]);out["cached"]=True;return out
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):raise HTTPException(503,"Alpaca לא מוגדר")
        headers={"APCA-API-KEY-ID":mod.ALPACA_KEY,"APCA-API-SECRET-KEY":mod.ALPACA_SECRET}
        feed=mod.ALPACA_FEED if mod.ALPACA_FEED in {"iex","sip","delayed_sip"} else "iex"
        universe=LONG_UNIVERSE[:symbols]
        sem=asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=45) as client:
            async def one(s):
                async with sem:return s,await _fetch_symbol(client,s,headers,feed,years)
            fetched=await asyncio.gather(*[one(s) for s in universe])
        events=[]; current=[]
        for s,rows in fetched:
            if len(rows)<300:continue
            events.extend(_evaluate_symbol(s,rows))
            m=_score(rows)
            if m:current.append({"symbol":s,**m,"price":rows[-1]["c"],"date":rows[-1]["d"]})
        dated=sorted({x["date"] for x in events if x["return_1m_pct"] is not None})
        if len(dated)<24:raise HTTPException(503,"אין מספיק היסטוריה ל-Backtest ארוך")
        split=dated[max(1,int(len(dated)*0.70))]
        train=[x for x in events if x["date"]<split]
        test=[x for x in events if x["date"]>=split]
        current.sort(key=lambda x:x["score"],reverse=True)
        out={
            "ok":True,"method":"monthly checkpoints with chronological holdout","feed":feed,"split_date":split,
            "definitions":{"success_1m":"תשואה של 4%+ בתוך 21 ימי מסחר מהאות","success_3m":"תשואה של 8%+ בתוך 63 ימי מסחר מהאות","success_12m":"תשואה של 15%+ בתוך 252 ימי מסחר מהאות"},
            "samples":{"total":len(events),"train":len(train),"test":len(test)},
            "test_1m":_stats(test,"success_1m"),"test_3m":_stats(test,"success_3m"),"test_12m":_stats(test,"success_12m"),
            "score_buckets_1m":_bucket(test,"success_1m"),"score_buckets_3m":_bucket(test,"success_3m"),"score_buckets_12m":_bucket(test,"success_12m"),
            "current_candidates":current[:10],"test_events":test,
            "limitations":["הציון מחושב רק מנתוני מחיר ומחזור שהיו ידועים בתאריך האות.","אין שימוש במידע עתידי בחישוב הציון.","ה-30% האחרונים בזמן משמשים Holdout.","חדשות ופונדמנטלס היסטוריים עדיין אינם חלק מהציון הארוך ולכן הם מוצגים כשכבת מידע נפרדת."],
            "generated_at":now.isoformat(),"cached":False,
        }
        _CACHE.update({"at":now,"value":out})
        return out

    @app.get("/api/strategy/long/time-travel")
    async def long_time_travel(as_of:str=Query("2021-11-30"),top:int=Query(10,ge=3,le=20)):
        try:
            datetime.fromisoformat(as_of)
        except Exception:
            raise HTTPException(400,"as_of must be YYYY-MM-DD")
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):raise HTTPException(503,"Alpaca לא מוגדר")
        headers={"APCA-API-KEY-ID":mod.ALPACA_KEY,"APCA-API-SECRET-KEY":mod.ALPACA_SECRET}
        feed=mod.ALPACA_FEED if mod.ALPACA_FEED in {"iex","sip","delayed_sip"} else "iex"
        sem=asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=45) as client:
            async def one(s):
                async with sem:return s,await _fetch_symbol(client,s,headers,feed,8)
            fetched=await asyncio.gather(*[one(s) for s in LONG_UNIVERSE])
        rows=[]
        for s,data in fetched:
            p=_point_in_time_pick(s,data,as_of)
            if p:rows.append(p)
        if not rows:raise HTTPException(503,"No historical candidates available")
        rows.sort(key=lambda x:x["score"],reverse=True)
        picks=rows[:top]
        spy=next((x for x in rows if x["symbol"]=="SPY"),None)
        for x in rows:
            x["excess_1m_vs_spy_pct"]=round(x["return_1m_pct"]-(spy["return_1m_pct"] or 0),2) if spy and x["return_1m_pct"] is not None and spy["return_1m_pct"] is not None else None
            x["excess_12m_vs_spy_pct"]=round(x["return_12m_pct"]-(spy["return_12m_pct"] or 0),2) if spy and x["return_12m_pct"] is not None and spy["return_12m_pct"] is not None else None
        actual_1m=sorted([x for x in rows if x["return_1m_pct"] is not None],key=lambda x:x["return_1m_pct"],reverse=True)
        actual_12m=sorted([x for x in rows if x["return_12m_pct"] is not None],key=lambda x:x["return_12m_pct"],reverse=True)
        pick_syms={x["symbol"] for x in picks}
        missed_1m=[x for x in actual_1m[:top] if x["symbol"] not in pick_syms]
        missed_12m=[x for x in actual_12m[:top] if x["symbol"] not in pick_syms]
        def agg(field,success):
            valid=[x for x in picks if x[field] is not None]
            return {"samples":len(valid),"avg_return_pct":round(statistics.mean(x[field] for x in valid),2) if valid else None,"success_pct":round(100*sum(1 for x in valid if x[success])/len(valid),1) if valid else None}
        return {
            "ok":True,"as_of":as_of,"feed":feed,"universe_size":len(rows),"top":top,
            "definitions":{"picked":"Top score using only data available on/before as_of","success_1m":"close return >=4% after 21 trading days","success_12m":"close return >=15% after 252 trading days","exploded_1m":"max high >=15% within 21 trading days","exploded_12m":"max high >=30% within 252 trading days"},
            "picks":picks,"portfolio_1m":agg("return_1m_pct","success_1m"),"portfolio_12m":agg("return_12m_pct","success_12m"),
            "benchmark":spy,"actual_top_1m":actual_1m[:top],"actual_top_12m":actual_12m[:top],"missed_top_1m":missed_1m,"missed_top_12m":missed_12m,
            "limitations":["Current universe creates survivorship/selection bias because it is today's maintained universe, not the full historical US market as it existed in 2021.","Historical fundamentals and point-in-time news are not yet included.","This endpoint is an audit tool, not a claim of live tradability or guaranteed future performance."],
            "generated_at":datetime.now(timezone.utc).isoformat(),
        }
