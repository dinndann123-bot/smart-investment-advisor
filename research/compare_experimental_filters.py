"""Offline, non-production comparison of baseline vs experimental entry filters.
Input CSV: symbol,signal_time,score,entry_price,exit_15m,exit_30m,exit_60m,
mfe_price,mae_price,news_sentiment,news_verified,rvol_reliable,
spread_bps,vwap,pm_high,volume_confirmed,dilution_risk
All fields must reflect information known at signal_time except outcome columns.
"""
import argparse,csv,statistics
from datetime import datetime

def number(row,key):
    try: return float(row[key])
    except (KeyError,ValueError,TypeError): return None

def eligible(row):
    required=("signal_time","entry_price","exit_15m","exit_30m","exit_60m","mfe_price","mae_price","vwap","pm_high","spread_bps","news_sentiment","news_verified","rvol_reliable","volume_confirmed","dilution_risk")
    if any(row.get(k,"")=="" for k in required): return False
    if any(number(row,k) is None for k in ("entry_price","exit_15m","exit_30m","exit_60m","mfe_price","mae_price","vwap","pm_high","spread_bps")): return False
    return True

def experimental(row):
    if not eligible(row): return None
    return (row["rvol_reliable"].lower()=="true" and row["volume_confirmed"].lower()=="true"
        and row["dilution_risk"].lower()=="false" and row["news_verified"].lower()=="true"
        and row["news_sentiment"].lower()=="positive"
        and number(row,"spread_bps")<=50
        and number(row,"entry_price")>=number(row,"vwap")
        and number(row,"entry_price")>=number(row,"pm_high"))

def metrics(rows):
    if not rows:return {"n":0}
    def ret(r,k):return 100*(number(r,k)/number(r,"entry_price")-1)
    out={"n":len(rows)}
    for k in ("exit_15m","exit_30m","exit_60m"):
        vals=[ret(r,k) for r in rows]
        out[k+"_win_rate"]=round(100*sum(v>0 for v in vals)/len(vals),2)
        out[k+"_mean_pct"]=round(statistics.mean(vals),3)
    out["mfe_mean_pct"]=round(statistics.mean(ret(r,"mfe_price") for r in rows),3)
    out["mae_mean_pct"]=round(statistics.mean(ret(r,"mae_price") for r in rows),3)
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv_file")
    p.add_argument("--train-before",required=True,help="ISO timestamp: historical development period ends before this time")
    a=p.parse_args()
    with open(a.csv_file,newline="",encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
    clean=[r for r in rows if eligible(r) and number(r,"entry_price")>0]
    train=[r for r in clean if r["signal_time"]<a.train_before]
    test=[r for r in clean if r["signal_time"]>=a.train_before]
    for label,group in (("development",train),("held_out",test)):
        selected=[r for r in group if experimental(r)]
        print(label,"baseline",metrics(group),"experiment",metrics(selected),"excluded_missing",sum(not eligible(r) for r in rows))
    print("Research only: no transaction costs or executable fill validation; do not deploy from these figures.")

if __name__=="__main__":main()
