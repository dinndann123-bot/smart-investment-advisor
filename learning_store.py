"""Durable storage for forward-validation learning signals."""
import json
import os
import sqlite3
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = Path(__file__).with_name("learning_signals.sqlite3")

def _signal_id(row):
    return f"{row.get('scan_id') or 'scan'}:{row.get('ticker') or 'UNKNOWN'}:{row.get('rank') or 0}"

def backend(): return "postgresql" if DATABASE_URL else "sqlite_ephemeral"
def durable(): return bool(DATABASE_URL)

def _pg():
    import psycopg
    return psycopg.connect(DATABASE_URL, connect_timeout=8)

def initialize():
    if DATABASE_URL:
        with _pg() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS strategy_learning_signals (
                signal_id TEXT PRIMARY KEY, scan_id TEXT, ticker TEXT NOT NULL,
                signal_epoch DOUBLE PRECISION NOT NULL, signal_time TEXT, record_type TEXT NOT NULL DEFAULT '',
                payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            con.execute("ALTER TABLE strategy_learning_signals ADD COLUMN IF NOT EXISTS record_type TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE strategy_learning_signals SET record_type=COALESCE(NULLIF(payload->>'record_type',''),'scanner_signal') WHERE record_type=''")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_ticker_epoch ON strategy_learning_signals(ticker, signal_epoch DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_type_epoch ON strategy_learning_signals(record_type, signal_epoch DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS long_daily_predictions (
                trade_date TEXT NOT NULL, ticker TEXT NOT NULL, signal_epoch DOUBLE PRECISION NOT NULL,
                payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (trade_date, ticker))""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_long_daily_epoch ON long_daily_predictions(signal_epoch DESC)")
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS strategy_learning_signals (
                signal_id TEXT PRIMARY KEY, scan_id TEXT, ticker TEXT NOT NULL,
                signal_epoch REAL NOT NULL, signal_time TEXT, record_type TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            columns={row[1] for row in con.execute("PRAGMA table_info(strategy_learning_signals)")}
            if "record_type" not in columns:
                con.execute("ALTER TABLE strategy_learning_signals ADD COLUMN record_type TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE strategy_learning_signals SET record_type=COALESCE(NULLIF(json_extract(payload,'$.record_type'),''),'scanner_signal') WHERE record_type=''")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_ticker_epoch ON strategy_learning_signals(ticker, signal_epoch DESC)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_type_epoch ON strategy_learning_signals(record_type, signal_epoch DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS long_daily_predictions (
                trade_date TEXT NOT NULL, ticker TEXT NOT NULL, signal_epoch REAL NOT NULL,
                payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (trade_date, ticker))""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_long_daily_epoch ON long_daily_predictions(signal_epoch DESC)")

def load(limit=3000):
    initialize()
    if DATABASE_URL:
        with _pg() as con:
            rows=con.execute("SELECT payload FROM strategy_learning_signals ORDER BY signal_epoch DESC LIMIT %s",(limit,)).fetchall()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            rows=con.execute("SELECT payload FROM strategy_learning_signals ORDER BY signal_epoch DESC LIMIT ?",(limit,)).fetchall()
    out=[]
    for (payload,) in reversed(rows):
        try:out.append(payload if isinstance(payload,dict) else json.loads(payload))
        except Exception:continue
    return out

def load_by_type(record_type, limit=None, since_epoch=None):
    """Load a chronological history lane without unrelated rows crowding it out."""
    initialize()
    clauses=["record_type = %s" if DATABASE_URL else "record_type = ?"]
    params=[str(record_type)]
    if since_epoch is not None:
        clauses.append("signal_epoch >= %s" if DATABASE_URL else "signal_epoch >= ?")
        params.append(float(since_epoch))
    sql="SELECT payload FROM strategy_learning_signals WHERE "+" AND ".join(clauses)+" ORDER BY signal_epoch ASC"
    if limit is not None:
        sql += " LIMIT %s" if DATABASE_URL else " LIMIT ?"
        params.append(max(0,int(limit)))
    with (_pg() if DATABASE_URL else sqlite3.connect(SQLITE_PATH)) as con:
        rows=con.execute(sql,tuple(params)).fetchall()
    out=[]
    for (payload,) in rows:
        try:out.append(payload if isinstance(payload,dict) else json.loads(payload))
        except Exception:continue
    return out

def count(record_type=None):
    initialize()
    with (_pg() if DATABASE_URL else sqlite3.connect(SQLITE_PATH)) as con:
        if record_type is None:
            row=con.execute("SELECT COUNT(*) FROM strategy_learning_signals").fetchone()
        else:
            sql="SELECT COUNT(*) FROM strategy_learning_signals WHERE record_type = %s" if DATABASE_URL else "SELECT COUNT(*) FROM strategy_learning_signals WHERE record_type = ?"
            row=con.execute(sql,(str(record_type),)).fetchone()
    return int(row[0] or 0)

def upsert(row):
    initialize();sid=_signal_id(row);payload=json.dumps(row,ensure_ascii=False,separators=(",",":"))
    record_type=str(row.get("record_type") or "scanner_signal")
    args=(sid,row.get("scan_id"),row.get("ticker"),float(row.get("epoch") or 0),row.get("signal_time"),record_type,payload)
    if DATABASE_URL:
        with _pg() as con:
            con.execute("""INSERT INTO strategy_learning_signals(signal_id,scan_id,ticker,signal_epoch,signal_time,record_type,payload)
                VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(signal_id) DO UPDATE
                SET payload=EXCLUDED.payload,record_type=EXCLUDED.record_type,updated_at=NOW()""",args)
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""INSERT INTO strategy_learning_signals(signal_id,scan_id,ticker,signal_epoch,signal_time,record_type,payload)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE
                SET payload=excluded.payload,record_type=excluded.record_type,updated_at=CURRENT_TIMESTAMP""",args)

def load_long_daily(limit=10000):
    initialize()
    if DATABASE_URL:
        with _pg() as con:
            rows=con.execute("SELECT payload FROM long_daily_predictions ORDER BY signal_epoch,trade_date,ticker LIMIT %s",(limit,)).fetchall()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            rows=con.execute("SELECT payload FROM long_daily_predictions ORDER BY signal_epoch,trade_date,ticker LIMIT ?",(limit,)).fetchall()
    out=[]
    for (payload,) in rows:
        try:out.append(payload if isinstance(payload,dict) else json.loads(payload))
        except Exception:continue
    return out

def upsert_long_daily(row):
    initialize();payload=json.dumps(row,ensure_ascii=False,separators=(",",":"))
    args=(row.get("trade_date"),row.get("ticker"),float(row.get("epoch") or 0),payload)
    if DATABASE_URL:
        with _pg() as con:
            con.execute("""INSERT INTO long_daily_predictions(trade_date,ticker,signal_epoch,payload)
                VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(trade_date,ticker) DO UPDATE
                SET payload=EXCLUDED.payload,updated_at=NOW()""",args)
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""INSERT INTO long_daily_predictions(trade_date,ticker,signal_epoch,payload)
                VALUES(?,?,?,?) ON CONFLICT(trade_date,ticker) DO UPDATE
                SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",args)

def insert_long_daily_once(row):
    """Keep the first daily snapshot immutable when multiple app sessions race."""
    initialize();payload=json.dumps(row,ensure_ascii=False,separators=(",",":"))
    args=(row.get("trade_date"),row.get("ticker"),float(row.get("epoch") or 0),payload)
    if DATABASE_URL:
        with _pg() as con:
            con.execute("""INSERT INTO long_daily_predictions(trade_date,ticker,signal_epoch,payload)
                VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(trade_date,ticker) DO NOTHING""",args)
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""INSERT INTO long_daily_predictions(trade_date,ticker,signal_epoch,payload)
                VALUES(?,?,?,?) ON CONFLICT(trade_date,ticker) DO NOTHING""",args)

def status():
    try:
        return {"backend":backend(),"durable":durable(),"stored_signals":count(),"scheduled_checkpoints":count("scheduled_checkpoint"),"connected":True}
    except Exception as exc:
        return {"backend":backend(),"durable":False,"stored_signals":0,"connected":False,"error":type(exc).__name__}
