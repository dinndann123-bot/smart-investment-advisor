import asyncio
import math
import statistics
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import HTTPException, Query

# Long-term model: price/volume only, point-in-time. Sector ETFs are fetched as
# benchmarks and are not eligible for the final stock-pick list.
CORE_UNIVERSE = [
    "SPY","QQQ","VOO","VTI","IWM","DIA",
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","COST","LLY","JPM","XOM","JNJ","PG","VRT",
    "PLTR","APP","RKLB","SMCI","AMD","TSM","ORCL","NFLX","UBER","HOOD","COIN","MSTR","CRWD","PANW","ANET","MU",
    "CVX","COP","SLB","CAT","DE","GE","BA","WMT","HD","LOW","KO","PEP","MCD","NKE","UNH","ABBV","MRK","PFE",
    "GS","MS","BAC","C","WFC","V","MA","CRM","ADBE","NOW","QCOM","TXN","AMAT","LRCX","KLAC","INTU","BKNG"
]
SECTOR_ETFS = ["XLK","XLE","XLF","XLV","XLY","XLP","XLI","XLB","XLU","XLRE","XLC"]
LONG_UNIVERSE = CORE_UNIVERSE + SECTOR_ETFS
ETF_SYMBOLS = {"SPY","QQQ","VOO","VTI","IWM","DIA",*SECTOR_ETFS}

SECTOR_MAP = {
    "AAPL":"XLK","MSFT":"XLK","NVDA":"XLK","AVGO":"XLK","AMD":"XLK","TSM":"XLK","ORCL":"XLK","CRWD":"XLK","PANW":"XLK","ANET":"XLK","MU":"XLK","QCOM":"XLK","TXN":"XLK","AMAT":"XLK","LRCX":"XLK","KLAC":"XLK","ADBE":"XLK","NOW":"XLK","CRM":"XLK","INTU":"XLK","SMCI":"XLK","VRT":"XLK",
    "META":"XLC","GOOGL":"XLC","NFLX":"XLC",
    "AMZN":"XLY","TSLA":"XLY","HD":"XLY","LOW":"XLY","MCD":"XLY","NKE":"XLY","BKNG":"XLY",
    "XOM":"XLE","CVX":"XLE","COP":"XLE","SLB":"XLE",
    "JPM":"XLF","GS":"XLF","MS":"XLF","BAC":"XLF","C":"XLF","WFC":"XLF","V":"XLF","MA":"XLF","HOOD":"XLF",
    "LLY":"XLV","JNJ":"XLV","UNH":"XLV","ABBV":"XLV","MRK":"XLV","PFE":"XLV",
    "PG":"XLP","WMT":"XLP","KO":"XLP","PEP":"XLP","COST":"XLP",
    "CAT":"XLI","DE":"XLI","GE":"XLI","BA":"XLI",
}
_CACHE = {"at": None, "value": None}
_CACHE_TTL = 6 * 3600


def _f(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _ret(a,b): return ((b/a)-1)*100 if a and b else None

def _stdev_pct(vals):
    rets=[b/a-1 for a,b in zip(vals[:-1],vals[1:]) if a and b]
    return statistics.pstdev(rets)*(252**0.5)*100 if len(rets)>=10 else None

def _value_on_or_before(rows,date):
    vals=[r for r in rows if r["d"]<=date]
    return vals[-1]["c"] if vals else None

def _benchmark_return(rows,date,lookback):
    hist=[r for r in rows if r["d"]<=date]
    return _ret(hist[-lookback]["c"],hist[-1]["c"]) if len(hist)>=lookback else None

def _regime(spy_hist):
    if not spy_hist or len(spy_hist)<200:return {"name":"unknown","risk_on":False,"score_adj":0}
    c=spy_hist[-1]["c"]; ma50=statistics.mean(x["c"] for x in spy_hist[-50:]); ma200=statistics.mean(x["c"] for x in spy_hist[-200:])
    r3=_ret(spy_hist[-63]["c"],c) if len(spy_hist)>=63 else 0
    if c>ma200 and ma50>ma200 and (r3 or 0)>0:return {"name":"risk_on","risk_on":True,"score_adj":3}
    if c<ma200 and ma50<ma200:return {"name":"risk_off","risk_on":False,"score_adj":-8}
    return {"name":"transition","risk_on":False,"score_adj":-2}


def _score(hist, spy_hist=None, sector_hist=None):
    closes=[x["c"] for x in hist]; vols=[x["v"] for x in hist]
    if len(closes)<252:return None
    c=closes[-1]; r1=_ret(closes[-21],c); r3=_ret(closes[-63],c); r6=_ret(closes[-126],c); r12=_ret(closes[-252],c)
    ma50=statistics.mean(closes[-50:]); ma200=statistics.mean(closes[-200:]); high52=max(x["h"] for x in hist[-252:] if x["h"]>0)
    dd52=(c/high52-1)*100 if high52 else None; vol=_stdev_pct(closes[-252:]); avgvol=statistics.mean(vols[-60:]) if len(vols)>=60 else None
    dist50=(c/ma50-1)*100; dist200=(c/ma200-1)*100

    # Acceleration: rewards improving medium-term momentum, penalizes a one-month
    # parabolic burst that is no longer supported by the 3/6 month slope.
    m1=(r1 or 0); m3_month=(r3 or 0)/3; m6_month=(r6 or 0)/6
    acceleration=m1-m3_month
    deceleration=m3_month-m6_month

    date=hist[-1]["d"]
    spy6=_benchmark_return(spy_hist or [],date,126); spy12=_benchmark_return(spy_hist or [],date,252)
    sec6=_benchmark_return(sector_hist or [],date,126); sec12=_benchmark_return(sector_hist or [],date,252)
    rs_market_6=(r6-spy6) if r6 is not None and spy6 is not None else None
    rs_market_12=(r12-spy12) if r12 is not None and spy12 is not None else None
    rs_sector_6=(r6-sec6) if r6 is not None and sec6 is not None else None
    rs_sector_12=(r12-sec12) if r12 is not None and sec12 is not None else None
    regime=_regime([r for r in (spy_hist or []) if r["d"]<=date])

    score=0.0; reasons=[]; penalties=[]
    if r12>=30:score+=20
    elif r12>=15:score+=16
    elif r12>=5:score+=10
    elif r12<0:score-=8
    if r6>=18:score+=15
    elif r6>=8:score+=11
    elif r6>=0:score+=6
    else:score-=5
    if r3>=10:score+=8
    elif r3>=0:score+=5
    else:score-=4
    if c>ma50:score+=8
    if c>ma200:score+=12;reasons.append("above_ma200")
    elif c<ma200*0.9:score-=10
    if ma50>ma200:score+=7;reasons.append("trend_alignment")
    if dd52 is not None and -15<=dd52<=0:score+=5
    if vol is not None:
        if 18<=vol<=55:score+=3
        elif vol>90:score-=7;penalties.append("extreme_volatility")
    if avgvol and avgvol>=500_000:score+=2

    # Relative strength vs market and sector.
    for rs,label in ((rs_market_6,"rs_market_6m"),(rs_market_12,"rs_market_12m"),(rs_sector_6,"rs_sector_6m"),(rs_sector_12,"rs_sector_12m")):
        if rs is None:continue
        if rs>=10:score+=4;reasons.append(label)
        elif rs>=3:score+=2
        elif rs<=-10:score-=4
        elif rs<=-3:score-=2

    # Acceleration / deceleration.
    if 0<acceleration<=8:score+=4;reasons.append("healthy_acceleration")
    elif acceleration>12:score-=5;penalties.append("parabolic_acceleration")
    elif acceleration<-5:score-=4;penalties.append("momentum_deceleration")
    if deceleration<-4:score-=3;penalties.append("medium_term_deceleration")

    # Overextension penalty: the November-2021 audit showed this was essential.
    overextension_penalty=0
    if dist50>12:overextension_penalty+=4
    if dist50>20:overextension_penalty+=6
    if dist50>30:overextension_penalty+=8
    if dist200>35:overextension_penalty+=4
    if dist200>60:overextension_penalty+=7
    if (r3 or 0)>45:overextension_penalty+=5
    if (r6 or 0)>90:overextension_penalty+=6
    if overextension_penalty:
        score-=overextension_penalty;penalties.append("overextension")

    # Market regime. Risk-off especially penalizes high-volatility/high-extension names.
    score+=regime["score_adj"]
    if regime["name"]=="risk_off" and ((vol or 0)>55 or dist50>10):score-=5;penalties.append("risk_off_high_beta")

    score=max(0,min(100,score))
    return {"score":round(score,1),"r1":r1,"r3":r3,"r6":r6,"r12":r12,"ma50":ma50,"ma200":ma200,"dd52":dd52,"volatility":vol,
            "dist_ma50_pct":dist50,"dist_ma200_pct":dist200,"acceleration":acceleration,"rs_market_6m":rs_market_6,"rs_market_12m":rs_market_12,
            "rs_sector_6m":rs_sector_6,"rs_sector_12m":rs_sector_12,"regime":regime["name"],"overextension_penalty":overextension_penalty,"reasons":reasons,"penalties":penalties}

async def _fetch_symbol(client,symbol,headers,feed,years):
    end=datetime.now(timezone.utc); start=end-timedelta(days=int(365.25*years)+400)
    r=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",headers=headers,params={"timeframe":"1Day","start":start.isoformat(),"end":end.isoformat(),"limit":10000,"adjustment":"split","feed":feed,"sort":"asc"})
    if r.status_code>=400:return []
    rows=[]
    for b in (r.json() or {}).get("bars") or []:
        c=_f(b.get("c"));h=_f(b.get("h"));v=_f(b.get("v"));t=str(b.get("t") or "")[:10]
        if c and h and t:rows.append({"d":t,"c":c,"h":h,"v":v or 0})
    return rows

def _monthly_indices(rows):
    out=[]; last=None
    for i,r in enumerate(rows):
        m=r["d"][:7]
        if last is not None and m!=last:out.append(i-1)
        last=m
    if rows:out.append(len(rows)-1)
    return out

def _future_benchmark(rows,date,n):
    pos=next((i for i,r in enumerate(rows) if r["d"]>=date),None)
    if pos is None or pos+n>=len(rows):return None
    return _ret(rows[pos]["c"],rows[pos+n]["c"])

def _evaluate_symbol(symbol,rows,spy_rows,sector_rows):
    events=[]
    for idx in _monthly_indices(rows):
        if idx<252:continue
        hist=rows[:idx+1]; m=_score(hist,spy_rows,sector_rows)
        if not m:continue
        entry=rows[idx]["c"]
        vals={n:(_ret(entry,rows[idx+n]["c"]) if idx+n<len(rows) else None) for n in (21,63,252)}
        spy_vals={n:_future_benchmark(spy_rows,rows[idx]["d"],n) for n in (21,63,252)}
        events.append({"symbol":symbol,"date":rows[idx]["d"],"score":m["score"],"entry":entry,
            "return_1m_pct":round(vals[21],2) if vals[21] is not None else None,"return_3m_pct":round(vals[63],2) if vals[63] is not None else None,"return_12m_pct":round(vals[252],2) if vals[252] is not None else None,
            "excess_1m_vs_spy_pct":round(vals[21]-spy_vals[21],2) if vals[21] is not None and spy_vals[21] is not None else None,
            "excess_3m_vs_spy_pct":round(vals[63]-spy_vals[63],2) if vals[63] is not None and spy_vals[63] is not None else None,
            "excess_12m_vs_spy_pct":round(vals[252]-spy_vals[252],2) if vals[252] is not None and spy_vals[252] is not None else None,
            "success_1m":bool(vals[21] is not None and vals[21]>=4),"success_3m":bool(vals[63] is not None and vals[63]>=8),"success_12m":bool(vals[252] is not None and vals[252]>=15),
            "beat_spy_1m":bool(vals[21] is not None and spy_vals[21] is not None and vals[21]>spy_vals[21]),"beat_spy_12m":bool(vals[252] is not None and spy_vals[252] is not None and vals[252]>spy_vals[252]),"metrics":m})
    return events

def _stats(rows,field):
    retkey={"success_1m":"return_1m_pct","success_3m":"return_3m_pct","success_12m":"return_12m_pct"}[field]; arr=[x for x in rows if x.get(retkey) is not None]
    if not arr:return {"samples":0,"success_pct":None,"avg_return_pct":None}
    return {"samples":len(arr),"success_pct":round(100*sum(bool(x[field]) for x in arr)/len(arr),1),"avg_return_pct":round(statistics.mean(x[retkey] for x in arr),2)}
def _bucket(events,field):
    return [{"bucket":name,**_stats([x for x in events if lo<=x["score"]<=hi],field)} for name,lo,hi in [("90-100",90,100),("80-89",80,89.999),("70-79",70,79.999),("0-69",0,69.999)]]

def get_cached_long_success(symbol,score=None):
    events=(_CACHE.get("value") or {}).get("test_events") or []; own=[x for x in events if x["symbol"]==symbol]; out={"one_month":None,"three_month":None,"one_year":None,"source":"long_backtest_holdout"}
    for field,key in [("success_1m","one_month"),("success_3m","three_month"),("success_12m","one_year")]:
        st=_stats(own,field)
        if st["samples"]>=4:st["basis"]="היסטוריית Holdout של הנייר עצמו";out[key]=st;continue
        if score is None:out[key]={"samples":st["samples"],"success_pct":None,"avg_return_pct":None,"basis":"אין מספיק מדגם"};continue
        lo=90 if score>=90 else 80 if score>=80 else 70 if score>=70 else 0; hi=100 if lo==90 else 89.999 if lo==80 else 79.999 if lo==70 else 69.999
        st=_stats([x for x in events if lo<=x["score"]<=hi],field);st["basis"]=f"Holdout בטווח ציון {int(lo)}–{int(hi)}" if st["samples"]>=10 else "מדגם קטן מדי"
        if st["samples"]<10:st["success_pct"]=None
        out[key]=st
    return out

def _point_in_time_pick(symbol,rows,as_of,spy_rows,sector_rows):
    hist=[r for r in rows if r["d"]<=as_of]
    if len(hist)<252:return None
    m=_score(hist,spy_rows,sector_rows); entry=hist[-1]["c"]; idx=len(hist)-1; future=rows[idx+1:]
    def fc(n):return future[n-1]["c"] if len(future)>=n else None
    vals={n:(_ret(entry,fc(n)) if fc(n) else None) for n in (21,63,252)}; max1=max((x["h"] for x in future[:21]),default=None);max12=max((x["h"] for x in future[:252]),default=None)
    return {"symbol":symbol,"as_of_trade_date":hist[-1]["d"],"entry":round(entry,4),"score":m["score"],"metrics":{k:(round(v,2) if isinstance(v,(int,float)) and not isinstance(v,bool) else v) for k,v in m.items()},
        "return_1m_pct":round(vals[21],2) if vals[21] is not None else None,"return_3m_pct":round(vals[63],2) if vals[63] is not None else None,"return_12m_pct":round(vals[252],2) if vals[252] is not None else None,
        "max_up_1m_pct":round(_ret(entry,max1),2) if max1 else None,"max_up_12m_pct":round(_ret(entry,max12),2) if max12 else None,"success_1m":bool(vals[21] is not None and vals[21]>=4),"success_12m":bool(vals[252] is not None and vals[252]>=15),"exploded_1m":bool(max1 and _ret(entry,max1)>=15),"exploded_12m":bool(max12 and _ret(entry,max12)>=30)}

def _sector_limited(rows,top=10,max_per_sector=3):
    chosen=[];counts={}
    for x in sorted(rows,key=lambda z:z["score"],reverse=True):
        sec=SECTOR_MAP.get(x["symbol"],"OTHER")
        if counts.get(sec,0)>=max_per_sector:continue
        chosen.append(x);counts[sec]=counts.get(sec,0)+1
        if len(chosen)>=top:break
    return chosen

def install_long_strategy(app):
    import sys
    mod=sys.modules.get(app.__module__) or sys.modules.get("app")
    async def fetch_all(years):
        if not (mod.ALPACA_KEY and mod.ALPACA_SECRET):raise HTTPException(503,"Alpaca לא מוגדר")
        headers={"APCA-API-KEY-ID":mod.ALPACA_KEY,"APCA-API-SECRET-KEY":mod.ALPACA_SECRET};feed=mod.ALPACA_FEED if mod.ALPACA_FEED in {"iex","sip","delayed_sip"} else "iex";sem=asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=45) as client:
            async def one(s):
                async with sem:return s,await _fetch_symbol(client,s,headers,feed,years)
            fetched=await asyncio.gather(*[one(s) for s in LONG_UNIVERSE])
        return dict(fetched),feed

    @app.get("/api/strategy/long/validate")
    async def validate_long_strategy(years:int=Query(6,ge=4,le=10),symbols:int=Query(len(CORE_UNIVERSE),ge=10,le=len(CORE_UNIVERSE))):
        now=datetime.now(timezone.utc)
        if _CACHE.get("value") and _CACHE.get("at") and (now-_CACHE["at"]).total_seconds()<_CACHE_TTL:
            out=dict(_CACHE["value"]);out["cached"]=True;return out
        data,feed=await fetch_all(years);spy=data.get("SPY",[]);events=[];current=[]
        eligible=CORE_UNIVERSE[:symbols]
        for s in eligible:
            rows=data.get(s,[])
            if len(rows)<300:continue
            sec=data.get(SECTOR_MAP.get(s,""),[]);events.extend(_evaluate_symbol(s,rows,spy,sec));m=_score(rows,spy,sec)
            if m and s not in ETF_SYMBOLS:current.append({"symbol":s,**m,"price":rows[-1]["c"],"date":rows[-1]["d"],"sector_proxy":SECTOR_MAP.get(s)})
        dated=sorted({x["date"] for x in events if x["return_1m_pct"] is not None})
        if len(dated)<24:raise HTTPException(503,"אין מספיק היסטוריה ל-Backtest ארוך")
        split=dated[max(1,int(len(dated)*0.70))];train=[x for x in events if x["date"]<split];test=[x for x in events if x["date"]>=split];current=_sector_limited(current,10,3)
        out={"ok":True,"method":"point-in-time monthly checkpoints + chronological holdout + regime/RS/overextension","feed":feed,"split_date":split,
            "definitions":{"success_1m":"4%+ after 21 trading days","success_3m":"8%+ after 63 trading days","success_12m":"15%+ after 252 trading days","relative_success":"positive excess return versus SPY"},
            "samples":{"total":len(events),"train":len(train),"test":len(test)},"test_1m":_stats(test,"success_1m"),"test_3m":_stats(test,"success_3m"),"test_12m":_stats(test,"success_12m"),
            "score_buckets_1m":_bucket(test,"success_1m"),"score_buckets_3m":_bucket(test,"success_3m"),"score_buckets_12m":_bucket(test,"success_12m"),"current_candidates":current,"test_events":test,
            "improvements":["overextension penalty","momentum acceleration/deceleration","relative strength vs SPY","relative strength vs sector ETF","market regime filter","max 3 picks per sector","SPY excess-return measurement"],
            "limitations":["Price/volume data are point-in-time; historical fundamentals/news are not yet in the score.","Universe is broader but still maintained today, so survivorship bias is reduced but not eliminated."],"generated_at":now.isoformat(),"cached":False}
        _CACHE.update({"at":now,"value":out});return out

    @app.get("/api/strategy/long/time-travel")
    async def long_time_travel(as_of:str=Query("2021-11-30"),top:int=Query(10,ge=3,le=20)):
        try:datetime.fromisoformat(as_of)
        except Exception:raise HTTPException(400,"as_of must be YYYY-MM-DD")
        data,feed=await fetch_all(10);spy_rows=data.get("SPY",[]);rows=[]
        for s in CORE_UNIVERSE:
            if s in ETF_SYMBOLS:continue
            p=_point_in_time_pick(s,data.get(s,[]),as_of,spy_rows,data.get(SECTOR_MAP.get(s,""),[]))
            if p:p["sector_proxy"]=SECTOR_MAP.get(s);rows.append(p)
        if not rows:raise HTTPException(503,"No historical candidates available")
        picks=_sector_limited(rows,top,3);spy=_point_in_time_pick("SPY",spy_rows,as_of,spy_rows,[])
        for x in rows:
            x["excess_1m_vs_spy_pct"]=round(x["return_1m_pct"]-spy["return_1m_pct"],2) if spy and x["return_1m_pct"] is not None and spy["return_1m_pct"] is not None else None
            x["excess_12m_vs_spy_pct"]=round(x["return_12m_pct"]-spy["return_12m_pct"],2) if spy and x["return_12m_pct"] is not None and spy["return_12m_pct"] is not None else None
        actual1=sorted([x for x in rows if x["return_1m_pct"] is not None],key=lambda x:x["return_1m_pct"],reverse=True);actual12=sorted([x for x in rows if x["return_12m_pct"] is not None],key=lambda x:x["return_12m_pct"],reverse=True);syms={x["symbol"] for x in picks}
        def agg(field,success):
            valid=[x for x in picks if x[field] is not None];return {"samples":len(valid),"avg_return_pct":round(statistics.mean(x[field] for x in valid),2) if valid else None,"success_pct":round(100*sum(bool(x[success]) for x in valid)/len(valid),1) if valid else None}
        return {"ok":True,"as_of":as_of,"feed":feed,"universe_size":len(rows),"top":top,"picks":picks,"portfolio_1m":agg("return_1m_pct","success_1m"),"portfolio_12m":agg("return_12m_pct","success_12m"),"benchmark":spy,
            "actual_top_1m":actual1[:top],"actual_top_12m":actual12[:top],"missed_top_1m":[x for x in actual1[:top] if x["symbol"] not in syms],"missed_top_12m":[x for x in actual12[:top] if x["symbol"] not in syms],
            "improvements_active":["overextension","acceleration/deceleration","market relative strength","sector relative strength","regime filter","sector concentration cap","SPY excess return"],
            "limitations":["No future data enter the score.","Historical fundamentals/news are not yet point-in-time inputs.","Today's maintained universe still creates some survivorship bias."],"generated_at":datetime.now(timezone.utc).isoformat()}
