import asyncio
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

from market_search import install_market_search
from long_strategy import install_long_strategy
from timing_learning import measure_day_timing, summarize_timing, summarize_timing_patterns
from signal_journal import install_signal_journal

NY=ZoneInfo("America/New_York")
UNIVERSE=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","AVGO","PLTR","HOOD","COIN","MARA","RIOT","SMCI","SOFI","RIVN","IONQ","SOUN","RKLB","APP","MU","INTC","ARM","QCOM","MRVL","CRWD","NET","SNOW","SHOP","UBER","PYPL","NFLX","ORCL","TSM","NIO","LCID","AFRM","UPST","CVNA","DKNG","RBLX","PATH","AI","BBAI","QBTS","RGTI","QUBT","ACHR","JOBY","LUNR","ASTS","RDW","SPCE","OPEN","CHPT","QS","LAZR","HIMS","TEM","RXRX","VRT","DELL","ANET","PANW","DDOG","MDB","ZS","OKTA","CELH","CAVA","RDDT","DUOL","TOST","NU","GRAB","PINS","SNAP","ROKU","FUBO","GME","AMC","KOSS","BB","WULF","CLSK","IREN","CIFR","HUT","BITF","BTDR","CORZ","MSTR","XYZ","RKT","LMND","ROOT","WBD","PARA","OXY"]
_CACHE={}; _CACHE_TTL_SECONDS=600

def _safe_mean(xs): return round(statistics.mean(xs),3) if xs else None
def _parse_bar(b):
    ts=datetime.fromisoformat(str(b.get("t","")).replace("Z","+00:00")).astimezone(NY)
    return {"ts":ts,"o":float(b.get("o") or 0),"h":float(b.get("h") or 0),"l":float(b.get("l") or 0),"c":float(b.get("c") or 0),"v":float(b.get("v") or 0)}

async def _fetch(client,symbol,headers,feed,days):
    end=datetime.now(timezone.utc); start=end-timedelta(days=days+30)
    r=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",headers=headers,params={"timeframe":"15Min","start":start.isoformat(),"end":end.isoformat(),"limit":10000,"adjustment":"split","feed":feed,"sort":"asc"})
    if r.status_code>=400:return [],f"{symbol}: HTTP {r.status_code}"
    grouped=defaultdict(list)
    for raw in (r.json() or {}).get("bars") or []:
        try:
            b=_parse_bar(raw)
            if dtime(4,0)<=b["ts"].time()<dtime(16,0):grouped[b["ts"].date().isoformat()].append(b)
        except Exception:pass
    return [(d,sorted(x,key=lambda z:z["ts"])) for d,x in sorted(grouped.items()) if len([b for b in x if dtime(9,30)<=b["ts"].time()<dtime(16,0)])>=8],None

def _events(symbol,days):
    out=[]; early_history=[]; pm_history=[]; prev_close=None
    for date,bars in days:
        pm=[b for b in bars if dtime(4,0)<=b["ts"].time()<dtime(9,30)]
        regular=[b for b in bars if dtime(9,30)<=b["ts"].time()<dtime(16,0)]
        early=[b for b in regular if b["ts"].time()<dtime(10,0)]; post=[b for b in regular if b["ts"].time()>=dtime(10,0)]
        if len(early)<2 or len(post)<4:
            if regular:prev_close=regular[-1]["c"]
            continue
        early_vol=sum(b["v"] for b in early); baseline=statistics.median(early_history[-20:]) if len(early_history)>=8 else None; early_history.append(early_vol)
        open_px=early[0]["o"] or early[0]["c"]; px=early[-1]["c"]
        pm_vol=sum(b["v"] for b in pm); pm_baseline=statistics.median(pm_history[-20:]) if len(pm_history)>=8 else None
        if pm_vol>0:pm_history.append(pm_vol)
        if not baseline or baseline<=0 or open_px<=0 or px<=0:prev_close=regular[-1]["c"]; continue
        gap=((open_px/prev_close)-1)*100 if prev_close else 0; move=(px/open_px-1)*100; rvol=early_vol/baseline
        strength=(px-min(b["l"] for b in early))/max(.01,max(b["h"] for b in early)-min(b["l"] for b in early)); volume_accel=early[-1]["v"]/max(1,statistics.mean([b["v"] for b in early[:-1]])); early_range=(max(b["h"] for b in early)/min(b["l"] for b in early)-1)*100; max_up=(max(b["h"] for b in post)/px-1)*100
        pm_last=pm[-1]["c"] if pm else open_px; pm_first=(pm[0]["o"] or pm[0]["c"]) if pm else open_px; pm_high=max((b["h"] for b in pm),default=open_px); pm_low=min((b["l"] for b in pm),default=open_px)
        pm_gap=((pm_last/prev_close)-1)*100 if prev_close and pm else gap
        pm_range=((pm_high/pm_low)-1)*100 if pm_low>0 and pm else 0
        pm_position=(pm_last-pm_low)/max(.01,pm_high-pm_low) if pm else .5
        pm_momentum=((pm_last/pm_first)-1)*100 if pm_first>0 and pm else 0
        pm_rvol=(pm_vol/pm_baseline) if pm_baseline and pm_baseline>0 else 1.0
        out.append({"symbol":symbol,"date":date,"price":px,"gap_pct":gap,"move_to_1000_pct":move,"rvol":rvol,"strength":strength,"volume_accel":volume_accel,"early_range_pct":early_range,"premarket_gap_pct":pm_gap,"premarket_rvol":pm_rvol,"premarket_range_pct":pm_range,"premarket_position":pm_position,"premarket_momentum_pct":pm_momentum,"premarket_volume":pm_vol,"premarket_bars":len(pm),"max_up_pct":max_up,"est_daily_volume":baseline*13,"hit10":int(max_up>=10),"hit20":int(max_up>=20),"hit30":int(max_up>=30),"timing_windows":measure_day_timing(regular)})
        prev_close=regular[-1]["c"]
    return out

def _robust(xs):
    med=statistics.median(xs); mad=statistics.median([abs(x-med) for x in xs]) or 1e-9; return med,mad

def _fit(train,features):
    model={}; positives=[e for e in train if e["hit10"]]; negatives=[e for e in train if not e["hit10"]]
    for f in features:
        vals=[e[f] for e in train]; med,mad=_robust(vals); p=_safe_mean([e[f] for e in positives]) or med; n=_safe_mean([e[f] for e in negatives]) or med; separation=abs(p-n)/(mad or 1); model[f]={"median":med,"mad":mad,"positive_mean":p,"negative_mean":n,"direction":1 if p>=n else -1,"raw_weight":max(.05,min(4,separation))}
    total=sum(x["raw_weight"] for x in model.values()) or 1
    for x in model.values():x["weight"]=x["raw_weight"]/total
    return model

def _score(e,model):
    total=0; reasons=[]
    for f,m in model.items():
        z=(e[f]-m["median"])/(1.4826*m["mad"] or 1); aligned=max(-2.5,min(2.5,z*m["direction"])); component=(aligned+2.5)/5*100; total+=component*m["weight"]
        reasons.append({"feature":f,"value":round(e[f],3),"weight":round(m["weight"],4),"direction":"higher" if m["direction"]>0 else "lower"})
    return round(total,1),sorted(reasons,key=lambda x:x["weight"],reverse=True)[:5]

def _walk_forward(events,features):
    events=sorted(events,key=lambda x:x["date"]); cut=max(30,int(len(events)*.7)); train=events[:cut]; test=events[cut:]
    if len(train)<30 or len(test)<10:return None
    model=_fit(train,features); scored=[]
    for e in test:
        s,_=_score(e,model); scored.append((s,e))
    scored.sort(key=lambda x:x[0],reverse=True); top=scored[:max(10,int(len(scored)*.2))]
    return {"train":len(train),"test":len(test),"top_bucket":len(top),"base_hit10":round(sum(e["hit10"] for e in test)/len(test)*100,1),"top_hit10":round(sum(e["hit10"] for _,e in top)/len(top)*100,1),"top_hit20":round(sum(e["hit20"] for _,e in top)/len(top)*100,1),"top_hit30":round(sum(e["hit30"] for _,e in top)/len(top)*100,1),"model":model}

async def install_explosion_learning(app,headers_fn,feed_fn):
    install_market_search(app,headers_fn,feed_fn)
    install_long_strategy(app,headers_fn,feed_fn)
    install_signal_journal(app,headers_fn,feed_fn)

    @app.get("/api/strategy/explosions")
    async def explosion_research(days:int=Query(180,ge=60,le=3650),symbols:int=Query(60,ge=10,le=len(UNIVERSE)),refresh:bool=False):
        feed=feed_fn(); key=(days,symbols,feed)
        cached=_CACHE.get(key)
        if cached and not refresh and (datetime.now(timezone.utc)-cached[0]).total_seconds()<_CACHE_TTL_SECONDS:return cached[1]
        sem=asyncio.Semaphore(8); events=[]; errors=[]
        async with httpx.AsyncClient(timeout=25) as client:
            async def one(symbol):
                async with sem:
                    d,e=await _fetch(client,symbol,headers_fn(),feed,days)
                    if e:errors.append(e)
                    else:events.extend(_events(symbol,d))
            await asyncio.gather(*(one(s) for s in UNIVERSE[:symbols]))
        features=["gap_pct","move_to_1000_pct","rvol","strength","volume_accel","early_range_pct","premarket_gap_pct","premarket_rvol","premarket_range_pct","premarket_position","premarket_momentum_pct"]
        validation=_walk_forward(events,features)
        payload={"generated_at":datetime.now(timezone.utc).isoformat(),"feed":feed,"days_requested":days,"symbols_requested":symbols,"events":len(events),"validation":validation,"timing_summary":summarize_timing(events),"timing_patterns":summarize_timing_patterns(events),"errors":errors[:20]}
        _CACHE[key]=(datetime.now(timezone.utc),payload);return payload
