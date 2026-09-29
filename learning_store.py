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
                signal_epoch DOUBLE PRECISION NOT NULL, signal_time TEXT,
                payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_ticker_epoch ON strategy_learning_signals(ticker, signal_epoch DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS long_daily_predictions (
                trade_date TEXT NOT NULL, ticker TEXT NOT NULL, signal_epoch DOUBLE PRECISION NOT NULL,
                payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (trade_date, ticker))""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_long_daily_epoch ON long_daily_predictions(signal_epoch DESC)")
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS strategy_learning_signals (
                signal_id TEXT PRIMARY KEY, scan_id TEXT, ticker TEXT NOT NULL,
                signal_epoch REAL NOT NULL, signal_time TEXT, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_learning_ticker_epoch ON strategy_learning_signals(ticker, signal_epoch DESC)")
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

def upsert(row):
    initialize();sid=_signal_id(row);payload=json.dumps(row,ensure_ascii=False,separators=(",",":"))
    args=(sid,row.get("scan_id"),row.get("ticker"),float(row.get("epoch") or 0),row.get("signal_time"),payload)
    if DATABASE_URL:
        with _pg() as con:
            con.execute("""INSERT INTO strategy_learning_signals(signal_id,scan_id,ticker,signal_epoch,signal_time,payload)
                VALUES(%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(signal_id) DO UPDATE
                SET payload=EXCLUDED.payload,updated_at=NOW()""",args)
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""INSERT INTO strategy_learning_signals(signal_id,scan_id,ticker,signal_epoch,signal_time,payload)
                VALUES(?,?,?,?,?,?) ON CONFLICT(signal_id) DO UPDATE
                SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP""",args)

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
        rows=load(3000)
        return {"backend":backend(),"durable":durable(),"stored_signals":len(rows),"connected":True}
    except Exception as exc:
        return {"backend":backend(),"durable":False,"stored_signals":0,"connected":False,"error":type(exc).__name__}
