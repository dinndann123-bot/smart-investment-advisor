"""Timing-learning engine for intraday signals.
Measures entry windows, MFE/MAE and peak timing. Also segments holdout timing
by signal pattern without changing the live score until validation is strong.
"""
from datetime import time as dtime
import statistics

ENTRY_WINDOWS = [("09:30", dtime(9,30)), ("09:35", dtime(9,35)), ("09:45", dtime(9,45)), ("10:00", dtime(10,0))]


def _pct(a,b): return ((b/a)-1)*100 if a and b else None

def _first_at_or_after(bars,clock): return next((b for b in bars if b["ts"].time()>=clock),None)

def measure_entry_window(bars,label,clock):
    entry=_first_at_or_after(bars,clock)
    if not entry:return None
    later=[b for b in bars if b["ts"]>=entry["ts"]]
    if not later or entry["c"]<=0:return None
    peak=max(later,key=lambda b:b["h"]); trough=min(later,key=lambda b:b["l"])
    mfe=_pct(entry["c"],peak["h"]); mae=_pct(entry["c"],trough["l"]); close_return=_pct(entry["c"],later[-1]["c"])
    return {"entry_window_ny":label,"entry_time":entry["ts"].isoformat(),"entry_price":round(entry["c"],4),"peak_time":peak["ts"].isoformat(),"peak_price":round(peak["h"],4),"trough_time":trough["ts"].isoformat(),"trough_price":round(trough["l"],4),"mfe_pct":round(mfe,3) if mfe is not None else None,"mae_pct":round(mae,3) if mae is not None else None,"minutes_to_peak":round(max(0,(peak["ts"]-entry["ts"]).total_seconds()/60),1),"close_return_pct":round(close_return,3) if close_return is not None else None}

def measure_day_timing(bars): return [x for label,clock in ENTRY_WINDOWS if (x:=measure_entry_window(bars,label,clock))]

def summarize_timing(events):
    by_window={}
    for event in events:
        for row in event.get("timing_windows") or []:by_window.setdefault(row["entry_window_ny"],[]).append(row)
    out=[]
    for label,rows in sorted(by_window.items()):
        mfes=[r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]; maes=[r["mae_pct"] for r in rows if r.get("mae_pct") is not None]; peaks=[r["minutes_to_peak"] for r in rows if r.get("minutes_to_peak") is not None]; closes=[r["close_return_pct"] for r in rows if r.get("close_return_pct") is not None]
        out.append({"entry_window_ny":label,"samples":len(rows),"median_mfe_pct":round(statistics.median(mfes),3) if mfes else None,"median_mae_pct":round(statistics.median(maes),3) if maes else None,"median_minutes_to_peak":round(statistics.median(peaks),1) if peaks else None,"positive_close_pct":round(100*sum(v>0 for v in closes)/len(closes),2) if closes else None})
    return out

def _median(events,key):
    xs=[float(e[key]) for e in events if e.get(key) is not None]
    return statistics.median(xs) if xs else None

def _pattern_specs(train):
    """Thresholds are learned from train only, preventing holdout leakage."""
    return {"gap":_median(train,"gap_pct"),"rvol":_median(train,"rvol"),"momentum":_median(train,"move_to_1000_pct")}

def _pattern_name(e,t):
    g=e.get("gap_pct",0); r=e.get("rvol",0); m=e.get("move_to_1000_pct",0)
    gb="gap_high" if t["gap"] is not None and g>=t["gap"] else "gap_low"
    rb="rvol_high" if t["rvol"] is not None and r>=t["rvol"] else "rvol_low"
    mb="momentum_high" if t["momentum"] is not None and m>=t["momentum"] else "momentum_low"
    return f"{gb}+{rb}+{mb}"

def summarize_timing_patterns(train,holdout,min_samples=20):
    """Segment both sets using thresholds learned exclusively on train."""
    thresholds=_pattern_specs(train); groups={}
    for e in holdout:groups.setdefault(_pattern_name(e,thresholds),[]).append(e)
    patterns=[]
    for name,events in sorted(groups.items(),key=lambda kv:len(kv[1]),reverse=True):
        timing=summarize_timing(events)
        eligible=[x for x in timing if x["samples"]>=min_samples and x["median_mfe_pct"] is not None and x["median_mae_pct"] is not None]
        best=max(eligible,key=lambda x:x["median_mfe_pct"]+0.35*x["median_mae_pct"],default=None)
        patterns.append({"pattern":name,"events":len(events),"validated":bool(best),"best_window_ny":best["entry_window_ny"] if best else None,"best_window":best,"windows":timing})
    return {"threshold_source":"train_only","thresholds":{"gap_pct":round(thresholds["gap"],3) if thresholds["gap"] is not None else None,"rvol":round(thresholds["rvol"],3) if thresholds["rvol"] is not None else None,"move_to_1000_pct":round(thresholds["momentum"],3) if thresholds["momentum"] is not None else None},"minimum_samples_per_window":min_samples,"patterns":patterns,"score_impact":"none until pattern holdout validation"}
