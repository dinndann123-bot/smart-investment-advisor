import math
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

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
        rvol=early_vol/baseline
        move=(px/open_px-1)*100
        gap=(open_px/prev_close-1)*100 if prev_close and prev_close>0 else 0
        lo=min(b["l"] for b in early if b["l"]>0)
        hi=max(b["h"] for b in early)
        strength=(px-lo)/(hi-lo) if hi>lo else .5
        first_vol=early[0]["v"]
        last_vol=early[-1]["v"]
        vol_accel=last_vol/max(first_vol,1)
        early_range=(hi-lo)/open_px*100
        max_up=(max(b["h"] for b in post)/px-1)*100
        max_down=(min(b["l"] for b in post)/px-1)*100
        close_ret=(post[-1]["c"]/px-1)*100
        out.append({
            "symbol":symbol,"date":date,"price":round(px,4),"gap_pct":round(gap,3),
            "move_to_1000_pct":round(move,3),"rvol":round(rvol,3),"strength":round(strength,3),
            "volume_accel":round(vol_accel,3),"early_range_pct":round(early_range,3),
            "est_daily_volume":int(early_vol*13),"max_up_pct":round(max_up,3),
            "max_down_pct":round(max_down,3),"close_ret_pct":round(close_ret,3),
            "hit10":max_up>=10,"hit20":max_up>=20,"hit30":max_up>=30,
        })
        prev_close=bars[-1]["c"]
    return out


FEATURES=("gap_pct","move_to_1000_pct","rvol","strength","volume_accel","early_range_pct")


def _fit(train):
    # Learn robust feature centers/scales and how strongly each feature separates
    # +10% explosions from non-explosions. Holdout is never used here.
    model={}
    pos=[e for e in train if e["hit10"]]
    neg=[e for e in train if not e["hit10"]]
    for f in FEATURES:
        vals=[e[f] for e in train]
        med=statistics.median(vals)
        mad=statistics.median([abs(x-med) for x in vals]) or 1.0
        p=_safe_mean([e[f] for e in pos]) or med
        n=_safe_mean([e[f] for e in neg]) or med
        direction=1 if p>=n else -1
        separation=min(3.0,abs(p-n)/(1.4826*mad))
        model[f]={"median":med,"mad":mad,"direction":direction,"separation":separation,"positive_mean":p,"negative_mean":n}
    total=sum(x["separation"] for x in model.values()) or 1
    for f in model:
        model[f]["weight"]=model[f]["separation"]/total
    return model


def _score(e,model):
    raw=0
    reasons=[]
    for f,m in model.items():
        z=(e[f]-m["median"])/(1.4826*m["mad"] or 1)
        aligned=max(-2.5,min(2.5,z*m["direction"]))
        contribution=m["weight"]*aligned
        raw+=contribution
        if contribution>.08:
            reasons.append(f)
    score=round(100/(1+math.exp(-1.45*(raw-.05))))
    return max(0,min(100,score)),reasons


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
    @app.get("/api/strategy/explosions")
    async def explosion_learning(days:int=Query(180,ge=120,le=365),symbols:int=Query(90,ge=50,le=len(UNIVERSE))):
        key=os.getenv("ALPACA_API_KEY","").strip(); secret=os.getenv("ALPACA_SECRET_KEY","").strip()
        feed=os.getenv("ALPACA_FEED","iex").strip().lower() or "iex"
        if not key or not secret: raise HTTPException(503,"Alpaca לא מוגדר")
        if feed not in {"iex","sip","delayed_sip"}: feed="iex"
        headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}
        universe=UNIVERSE[:max(90,symbols)]
        raw=[]; errors=[]
        async with httpx.AsyncClient(timeout=40) as client:
            for symbol in universe:
                try:
                    ds,err=await _fetch(client,symbol,headers,feed,max(180,days))
                    if err: errors.append(err); continue
                    raw.extend(_events(symbol,ds))
                except Exception as exc: errors.append(f"{symbol}: {exc}")
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
        return {"ok":True,"method":"explosion-pattern chronological holdout","cutoff_ny":"10:00","feed":feed,"split_date":split,"samples":{"total":len(eligible),"train":len(train),"test":len(test)},"baseline_test":_summary(test),"color_buckets_test":_bucket(test),"feature_importance_train_only":feature_importance,"largest_holdout_explosions":biggest,"strongest_holdout_signals":strongest,"error_count":len(errors),"errors":errors[:20],"limitations":["המודל לומד רק מידע שהיה זמין עד 10:00 ניו יורק.","המשקולות נלמדות מתקופת train בלבד; holdout משמש לבדיקה בלבד.","היקום עדיין קבוע ואינו כל השוק האמריקאי.","חדשות, float ו-short interest עדיין אינם כלולים ולכן יתווספו כשכבות נפרדות.","צבע הוא דמיון היסטורי לדפוסי התפוצצות ולא הבטחה לרווח."]}
