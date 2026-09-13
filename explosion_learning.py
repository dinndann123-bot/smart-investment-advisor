import asyncio
import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

from runtime_fixes import install_runtime_fixes
from market_search import install_market_search

NY = ZoneInfo("America/New_York")

UNIVERSE = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","AVGO","PLTR",
    "HOOD","COIN","MARA","RIOT","SMCI","SOFI","RIVN","IONQ","SOUN","RKLB",
    "APP","MU","INTC","ARM","QCOM","MRVL","CRWD","NET","SNOW","SHOP",
    "UBER","PYPL","NFLX","ORCL","TSM","NIO","LCID","AFRM","UPST","CVNA",
    "DKNG","RBLX","PATH","AI","BBAI","QBTS","RGTI","QUBT","ACHR","JOBY",
    "LUNR","ASTS","RDW","SPCE","OPEN","CHPT","QS","LAZR","HIMS","TEM",
    "RXRX","VRT","DELL","ANET","PANW","DDOG","MDB","ZS","OKTA","CELH",
    "CAVA","RDDT","DUOL","TOST","NU","GRAB","PINS","SNAP","ROKU","FUBO",
    "GME","AMC","KOSS","BB","WULF","CLSK","IREN","CIFR","HUT","BITF",
    "BTDR","CORZ","MSTR","XYZ","RKT","LMND","ROOT","WBD","PARA","OXY"
]

_CACHE = {}
_CACHE_TTL_SECONDS = 600


def _safe_mean(xs):
    return round(statistics.mean(xs), 3) if xs else None


def _parse_bar(b):
    ts = datetime.fromisoformat(str(b.get("t", "")).replace("Z", "+00:00")).astimezone(NY)
    return {"ts": ts, "o": float(b.get("o") or 0), "h": float(b.get("h") or 0), "l": float(b.get("l") or 0), "c": float(b.get("c") or 0), "v": float(b.get("v") or 0)}


async def _fetch(client, symbol, headers, feed, days):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 30)
    r = await client.get(
        f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
        headers=headers,
        params={"timeframe":"15Min","start":start.isoformat(),"end":end.isoformat(),"limit":10000,"adjustment":"split","feed":feed,"sort":"asc"},
    )
    if r.status_code >= 400:
        return [], f"{symbol}: HTTP {r.status_code}"
    grouped = defaultdict(list)
    for raw in (r.json() or {}).get("bars") or []:
        try:
            b = _parse_bar(raw)
            if dtime(9,30) <= b["ts"].time() < dtime(16,0):
                grouped[b["ts"].date().isoformat()].append(b)
        except Exception:
            pass
    return [(d, sorted(x, key=lambda z:z["ts"])) for d,x in sorted(grouped.items()) if len(x) >= 8], None


def _events(symbol, days):
    out=[]
    history=[]
    prev_close=None
    for date,bars in days:
        early=[b for b in bars if b["ts"].time() < dtime(10,0)]
        post=[b for b in bars if b["ts"].time() >= dtime(10,0)]
        if len(early)<2 or len(post)<4:
            if bars: prev_close=bars[-1]["c"]
            continue
        early_vol=sum(b["v"] for b in early)
        baseline=statistics.median(history[-20:]) if len(history)>=8 else None
        history.append(early_vol)
        open_px=early[0]["o"] or early[0]["c"]
        px=early[-1]["c"]
        if not baseline or baseline<=0 or open_px<=0 or px<=0:
            prev_close=bars[-1]["c"]
            continue
        gap=((open_px/prev_close)-1)*100 if prev_close else 0
        move=(px/open_px-1)*100
        rvol=early_vol/baseline
        strength=(px-min(b["l"] for b in early))/max(0.01,max(b["h"] for b in early)-min(b["l"] for b in early))
        volume_accel=early[-1]["v"]/max(1,statistics.mean([b["v"] for b in early[:-1]])) if len(early)>1 else 1
        early_range=(max(b["h"] for b in early)/min(b["l"] for b in early)-1)*100
        max_up=(max(b["h"] for b in post)/px-1)*100
        out.append({"symbol":symbol,"date":date,"price":px,"gap_pct":gap,"move_to_1000_pct":move,"rvol":rvol,"strength":strength,"volume_accel":volume_accel,"early_range_pct":early_range,"est_daily_volume":baseline*13,"max_up_pct":max_up,"hit10":int(max_up>=10),"hit20":int(max_up>=20),"hit30":int(max_up>=30)})
        prev_close=bars[-1]["c"]
    return out


def _robust(xs):
    med=statistics.median(xs); dev=[abs(x-med) for x in xs]; mad=statistics.median(dev) or 1e-9
    return med,mad


def _fit(train):
    feats=["gap_pct","move_to_1000_pct","rvol","strength","volume_accel","early_range_pct"]
    model={}
    positives=[e for e in train if e["hit10"]]; negatives=[e for e in train if not e["hit10"]]
    for f in feats:
        vals=[e[f] for e in train]; med,mad=_robust(vals)
        p=_safe_mean([e[f] for e in positives]) or med; n=_safe_mean([e[f] for e in negatives]) or med
        separation=abs(p-n)/(mad or 1)
        model[f]={"median":med,"mad":mad,"positive_mean":p,"negative_mean":n,"direction":1 if p>=n else -1,"raw_weight":max(.05,min(4,separation))}
    total=sum(x["raw_weight"] for x in model.values()) or 1
    for x in model.values(): x["weight"]=x["raw_weight"]/total
    return model


def _score(e,model):
    total=0; reasons=[]
    for f,m in model.items():
        z=(e[f]-m["median"])/(1.4826*m["mad"] or 1)
        aligned=max(-2.5,min(2.5,z*m["direction"]))
        component=(aligned+2.5)/5*100
        total+=component*m["weight"]
        if component>=70: reasons.append(f)
    return round(max(0,min(100,total)),1),reasons


def _color(score):
    if score>=80:return "red"
    if score>=65:return "orange"
    if score>=50:return "yellow"
    return "gray"


def _summary(rows):
    if not rows:return {"samples":0,"hit10_pct":None,"hit20_pct":None,"hit30_pct":None,"avg_max_up_pct":None}
    n=len(rows)
    return {"samples":n,"hit10_pct":round(100*sum(e["hit10"] for e in rows)/n,2),"hit20_pct":round(100*sum(e["hit20"] for e in rows)/n,2),"hit30_pct":round(100*sum(e["hit30"] for e in rows)/n,2),"avg_max_up_pct":round(statistics.mean(e["max_up_pct"] for e in rows),2)}


def _bucket(test):
    specs=[("red",80,100),("orange",65,79),("yellow",50,64),("gray",0,49)]
    return [{"color":name,**_summary([e for e in test if lo<=e["explosion_score"]<=hi])} for name,lo,hi in specs]


def install_explosion_learning(app):
    install_runtime_fixes(app)
    install_market_search(app)

    @app.get("/api/strategy/explosions")
    async def explosion_learning(days:int=Query(180,ge=120,le=365),symbols:int=Query(90,ge=50,le=len(UNIVERSE))):
        key=os.getenv("ALPACA_API_KEY","").strip(); secret=os.getenv("ALPACA_SECRET_KEY","").strip()
        feed=os.getenv("ALPACA_FEED","iex").strip().lower() or "iex"
        if not key or not secret: raise HTTPException(503,"Alpaca לא מוגדר")
        if feed not in {"iex","sip","delayed_sip"}: feed="iex"

        symbol_count=max(50,min(symbols,len(UNIVERSE)))
        cache_key=(max(180,days),symbol_count,feed)
        cached=_CACHE.get(cache_key)
        if cached:
            age=(datetime.now(timezone.utc)-cached["at"]).total_seconds()
            if age <= _CACHE_TTL_SECONDS:
                out=dict(cached["value"])
                out["cached"]=True
                out["cache_age_seconds"]=round(age,1)
                return out

        headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}
        universe=UNIVERSE[:symbol_count]
        raw=[]; errors=[]
        sem=asyncio.Semaphore(8)

        async with httpx.AsyncClient(timeout=45) as client:
            async def one(symbol):
                async with sem:
                    try:
                        ds,err=await _fetch(client,symbol,headers,feed,max(180,days))
                        if err:
                            return [], err
                        return _events(symbol,ds), None
                    except Exception as exc:
                        return [], f"{symbol}: {exc}"

            results=await asyncio.gather(*[one(symbol) for symbol in universe])

        for events,err in results:
            if err:
                errors.append(err)
            raw.extend(events)

        eligible=[e for e in raw if e["price"]>=1 and e["est_daily_volume"]>=100000]
        dates=sorted({e["date"] for e in eligible})
        if len(eligible)<300 or len(dates)<30: raise HTTPException(503,f"אין מספיק היסטוריה ללימוד ({len(eligible)} אירועים)")
        split=dates[max(1,int(len(dates)*.70))]
        train=[e for e in eligible if e["date"]<split]
        test=[e for e in eligible if e["date"]>=split]
        model=_fit(train)
        for e in train+test:
            e["explosion_score"],e["reasons"]=_score(e,model); e["color"]=_color(e["explosion_score"])
        feature_importance=sorted([{"feature":f,"weight_pct":round(m["weight"]*100,1),"exploders_mean":m["positive_mean"],"others_mean":m["negative_mean"],"direction":"higher" if m["direction"]>0 else "lower"} for f,m in model.items()],key=lambda x:x["weight_pct"],reverse=True)
        biggest=sorted(test,key=lambda e:e["max_up_pct"],reverse=True)[:25]
        strongest=sorted(test,key=lambda e:e["explosion_score"],reverse=True)[:25]
        out={"ok":True,"method":"explosion-pattern chronological holdout","cutoff_ny":"10:00","feed":feed,"split_date":split,"samples":{"total":len(eligible),"train":len(train),"test":len(test)},"baseline_test":_summary(test),"color_buckets_test":_bucket(test),"feature_importance_train_only":feature_importance,"largest_holdout_explosions":biggest,"strongest_holdout_signals":strongest,"error_count":len(errors),"errors":errors[:20],"cached":False,"limitations":["המודל לומד רק מידע שהיה זמין עד 10:00 ניו יורק.","המשקולות נלמדות מתקופת train בלבד; holdout משמש לבדיקה בלבד.","היקום עדיין קבוע ואינו כל השוק האמריקאי.","חדשות, float ו-short interest עדיין אינם כלולים ולכן יתווספו כשכבות נפרדות.","ב-Feed מסוג IEX הנתונים אינם מייצגים את כל עסקאות השוק המאוחד; SIP מדויק יותר כאשר זמין.","צבע הוא דמיון היסטורי לדפוסי התפוצצות ולא הבטחה לרווח."]}
        _CACHE[cache_key]={"at":datetime.now(timezone.utc),"value":out}
        return out