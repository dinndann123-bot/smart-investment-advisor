"""Truthful live-signal summary backed by the durable learning store."""
from datetime import datetime, timezone, timedelta


def _num(value):
    try:return float(value)
    except (TypeError, ValueError):return None


def install(app, learning_store):
    # Replace only the read endpoint.  Confirmation/write routes remain owned
    # by the existing application so the UI contract is unchanged.
    for route in list(app.routes):
        if getattr(route, "path", None) == "/api/live-signals/summary" and "GET" in getattr(route, "methods", set()):
            app.router.routes.remove(route)

    @app.get("/api/live-signals/summary")
    async def canonical_live_summary(refresh: bool = False):
        rows=learning_store.load(3000);now=datetime.now(timezone.utc);recent=[]
        for row in rows:
            # Timing entry/exit events share the same store but are not scanner
            # recommendations and do not carry a strategy score.  Mixing them
            # into this table produced misleading 0/100 rows.
            if row.get("record_type") == "timing_event" or _num(row.get("score")) is None:
                continue
            symbol=row.get("ticker") or row.get("symbol")
            created=row.get("signal_time") or row.get("captured_at")
            entry=_num(row.get("signal_price") if row.get("signal_price") is not None else row.get("price"))
            returns=[_num(row.get(f"ret{m}m_pct")) for m in (1,3,5,10,15)]
            returns=[v for v in returns if v is not None];ret=returns[-1] if returns else None
            if not symbol or not created:continue
            status="target2" if ret is not None and ret>=2 else "target1" if ret is not None and ret>=1 else "stopped" if ret is not None and ret<=-1 else "open"
            last_price=entry*(1+ret/100) if entry is not None and ret is not None else None
            recent.append({"symbol":symbol,"ticker":symbol,"created_at":created,"signal_date":str(created)[:10],"score":row.get("score"),"entry_price":entry,"entry":entry,"last_price":round(last_price,4) if last_price is not None else None,"current_return_pct":ret,"result_r":ret,"status":status,"scan_id":row.get("scan_id"),"record_type":row.get("record_type") or "scanner_signal"})
        recent.sort(key=lambda x:x["created_at"],reverse=True)
        cutoff7=now-timedelta(days=7);cutoff30=now-timedelta(days=30)
        def within(item,cutoff):
            try:return datetime.fromisoformat(str(item["created_at"]).replace("Z","+00:00"))>=cutoff
            except Exception:return False
        def stats(items):
            vals=[x["current_return_pct"] for x in items if x["current_return_pct"] is not None]
            return {"signals":len(items),"evaluated":len(vals),"success_rate_pct":round(100*sum(v>0 for v in vals)/len(vals),1) if vals else None,"stop_rate_pct":round(100*sum(v<=-1 for v in vals)/len(vals),1) if vals else None,"avg_r":round(sum(vals)/len(vals),3) if vals else None}
        d7=[x for x in recent if within(x,cutoff7)];d30=[x for x in recent if within(x,cutoff30)]
        today=stats([x for x in recent if x["signal_date"]==now.date().isoformat()]);days7=stats(d7);days30=stats(d30)
        def legacy(s):
            return {**s,"hit1_pct":s["success_rate_pct"],"stop_pct":s["stop_rate_pct"]}
        return {"ok":True,"source":"durable_learning_store","storage":learning_store.status(),"recent":recent[:200],"today":today,"days7":days7,"days30":days30,"day":legacy(today),"week":legacy(days7),"month":legacy(days30),"refreshed":bool(refresh)}
    return {"installed":True,"source":"durable_learning_store"}
