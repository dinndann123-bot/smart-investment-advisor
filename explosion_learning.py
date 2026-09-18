import asyncio
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Query

from runtime_fixes import install_runtime_fixes
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
            # Extended-hours bars are deliberately retained. They are required to learn
            # whether pre-market information adds predictive value before the open.
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
        if component>=70:reasons.append(f)
    return round(max(0,min(100,total)),1),reasons

def _summary(rows,score_key=None,threshold=65):
    if score_key:rows=[e for e in rows if e.get(score_key,0)>=threshold]
    if not rows:return {"samples":0,"hit10_pct":None,"hit20_pct":None,"hit30_pct":None,"avg_max_up_pct":None}
    n=len(rows); return {"samples":n,"hit10_pct":round(100*sum(e["hit10"] for e in rows)/n,2),"hit20_pct":round(100*sum(e["hit20"] for e in rows)/n,2),"hit30_pct":round(100*sum(e["hit30"] for e in rows)/n,2),"avg_max_up_pct":round(statistics.mean(e["max_up_pct"] for e in rows),2)}
def _color(s):return "red" if s>=80 else "orange" if s>=65 else "yellow" if s>=50 else "gray"
def _bucket(test):return [{"color":name,**_summary([e for e in test if lo<=e["explosion_score"]<=hi])} for name,lo,hi in [("red",80,100),("orange",65,79),("yellow",50,64),("gray",0,49)]]

def install_explosion_learning(app):
    install_runtime_fixes(app); install_long_strategy(app); install_market_search(app)
    import sys
    core=sys.modules.get("app")
    if core is not None and not getattr(app.state,"signal_journal_installed",False):install_signal_journal(app,core); app.state.signal_journal_installed=True
    @app.get("/api/strategy/explosions")
    async def explosion_learning(days:int=Query(180,ge=120,le=365),symbols:int=Query(90,ge=50,le=len(UNIVERSE))):
        key=os.getenv("ALPACA_API_KEY","").strip(); secret=os.getenv("ALPACA_SECRET_KEY","").strip(); feed=os.getenv("ALPACA_FEED","iex").strip().lower() or "iex"
        if not key or not secret:raise HTTPException(503,"Alpaca לא מוגדר")
        if feed not in {"iex","sip","delayed_sip"}:feed="iex"
        cache_key=(max(180,days),max(50,min(symbols,len(UNIVERSE))),feed,"premarket-holdout-v1"); cached=_CACHE.get(cache_key)
        if cached and (datetime.now(timezone.utc)-cached["at"]).total_seconds()<=_CACHE_TTL_SECONDS:return {**cached["value"],"cached":True}
        headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}; universe=UNIVERSE[:cache_key[1]]; raw=[]; errors=[]; sem=asyncio.Semaphore(8)
        async with httpx.AsyncClient(timeout=45) as client:
            async def one(symbol):
                async with sem:
                    try:
                        ds,err=await _fetch(client,symbol,headers,feed,cache_key[0]); return ([],err) if err else (_events(symbol,ds),None)
                    except Exception as exc:return [],f"{symbol}: {exc}"
            results=await asyncio.gather(*[one(s) for s in universe])
        for events,err in results:
            if err:errors.append(err)
            raw.extend(events)
        eligible=[e for e in raw if e["price"]>=1 and e["est_daily_volume"]>=100000]; dates=sorted({e["date"] for e in eligible})
        if len(eligible)<300 or len(dates)<30:raise HTTPException(503,f"אין מספיק היסטוריה ללימוד ({len(eligible)} אירועים)")
        split=dates[max(1,int(len(dates)*.70))]; train=[e for e in eligible if e["date"]<split]; test=[e for e in eligible if e["date"]>=split]
        base_features=["gap_pct","move_to_1000_pct","rvol","strength","volume_accel","early_range_pct"]
        pm_features=["premarket_gap_pct","premarket_rvol","premarket_range_pct","premarket_position","premarket_momentum_pct"]
        base_model=_fit(train,base_features); candidate_model=_fit(train,base_features+pm_features)
        for e in train+test:
            e["baseline_score"],_= _score(e,base_model); e["explosion_score"],e["reasons"]=_score(e,candidate_model); e["color"]=_color(e["explosion_score"])
        base_holdout=_summary(test,"baseline_score"); candidate_holdout=_summary(test,"explosion_score")
        pm_weights={f:round(candidate_model[f]["weight"]*100,2) for f in pm_features}
        # Premarket is considered validated only when the same score cutoff has enough holdout
        # samples and improves hit10 without reducing average max-up. Until then it is research-only.
        pm_validated=bool(candidate_holdout["samples"]>=50 and base_holdout["samples"]>=50 and candidate_holdout["hit10_pct"] is not None and base_holdout["hit10_pct"] is not None and candidate_holdout["hit10_pct"]>base_holdout["hit10_pct"] and candidate_holdout["avg_max_up_pct"]>=base_holdout["avg_max_up_pct"])
        timing_patterns=summarize_timing_patterns(train,test,min_samples=20)
        out={"ok":True,"method":"chronological holdout + explicit premarket candidate features","cutoff_ny":"10:00","feed":feed,"split_date":split,"samples":{"total":len(eligible),"train":len(train),"test":len(test)},"premarket":{"window_ny":"04:00-09:30","features":pm_features,"weights_train_pct":pm_weights,"baseline_holdout_score65":base_holdout,"candidate_holdout_score65":candidate_holdout,"validated":pm_validated,"live_score_impact":"eligible only after holdout validation"},"baseline_test":_summary(test),"color_buckets_test":_bucket(test),"feature_importance_train_only":sorted([{"feature":f,"weight_pct":round(m["weight"]*100,1),"exploders_mean":m["positive_mean"],"others_mean":m["negative_mean"],"direction":"higher" if m["direction"]>0 else "lower"} for f,m in candidate_model.items()],key=lambda x:x["weight_pct"],reverse=True),"timing":{"entry_windows_ny":["09:30","09:35","09:45","10:00"],"train":summarize_timing(train),"holdout":summarize_timing(test),"patterns":timing_patterns,"score_impact":"none until holdout validation"},"largest_holdout_explosions":sorted(test,key=lambda e:e["max_up_pct"],reverse=True)[:25],"strongest_holdout_signals":sorted(test,key=lambda e:e["explosion_score"],reverse=True)[:25],"error_count":len(errors),"errors":errors[:20],"cached":False,"limitations":["Pre-market נמדד רק כאשר ספק הנתונים מחזיר extended-hours bars.","משקלי Pre-market נלמדים מ-train בלבד ונבחנים כרונולוגית ב-holdout.","Pre-market אינו משנה את ציון המסחר החי עד שהוא עובר תנאי אימות.","היקום עדיין קבוע ואינו כל השוק האמריקאי.","IEX אינו השוק המאוחד; SIP עדיף כאשר זמין."]}
        _CACHE[cache_key]={"at":datetime.now(timezone.utc),"value":out}; return out
