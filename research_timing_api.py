"""Read-only research endpoints. No changes to live scanner scores or trading rules."""
from collections import defaultdict
from datetime import datetime, timezone
import os
import psycopg
from fastapi import HTTPException

def install(app):
    @app.get("/api/research/previous-session-timing")
    def previous_session_timing():
        dsn=os.getenv("DATABASE_URL","").strip()
        if not dsn:
            raise HTTPException(503,"DATABASE_URL unavailable")
        with psycopg.connect(dsn,connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT left(signal_time,10) AS day, ticker, payload
                  FROM strategy_learning_signals
                  WHERE record_type='scheduled_checkpoint'
                  AND signal_time IS NOT NULL
                  ORDER BY signal_epoch DESC LIMIT 1500""")
                records=cur.fetchall()
        dates=sorted({d for d,t,p in records if d},reverse=True)
        for day in dates:
            candidates=[(t,p) for d,t,p in records if d==day and isinstance(p,dict) and p.get("rank") is not None]
            if not candidates:continue
            # A single coherent checkpoint: never combine picks from different scans.
            scans=defaultdict(list)
            for t,p in candidates:
                scans[str(p.get("scan_id") or p.get("checkpoint") or "unknown")].append((t,p))
            scan_id,chosen=max(scans.items(),key=lambda kv:(len(kv[1]),sum(1 for _,p in kv[1] if p.get("ret15m_pct") is not None)))
            chosen=sorted(chosen,key=lambda x:float(x[1].get("rank",999)))[:10]
            if len(chosen)<5:continue
            offsets=[1,3,5,10,15]
            series=[]
            for t,p in chosen:
                vals=[]
                for m in offsets:
                    v=p.get("ret%sm_pct"%m)
                    try: vals.append(float(v) if v is not None else None)
                    except (ValueError,TypeError):vals.append(None)
                series.append({"ticker":t,"rank":p.get("rank"),"returns_pct":vals})
            mean=[round(sum(s["returns_pct"][i] for s in series if s["returns_pct"][i] is not None)/sum(s["returns_pct"][i] is not None for s in series),4) if any(s["returns_pct"][i] is not None for s in series) else None for i in range(len(offsets))]
            return {"trade_date":day,"scan_id":scan_id,"minutes_after_signal":offsets,"stocks":series,"average_return_pct":mean,"count":len(series),"method":"snapshot-relative returns, not minute-by-minute price curves","data_quality":"historical IEX checkpoint; not proof of optimal entry"}
        return {"trade_date":None,"stocks":[],"average_return_pct":[],"count":0,"data_quality":"no complete historical checkpoint"}
