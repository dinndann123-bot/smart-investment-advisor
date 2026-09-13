import os
import json
import asyncio
import sqlite3
import math
import statistics
import csv
import io
from datetime import datetime, timezone, timedelta, time as dtime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, Any

import httpx
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
MARKET_CACHE_DIR = BASE_DIR / "market_cache"
MARKET_CACHE_DIR.mkdir(exist_ok=True)
load_dotenv(BASE_DIR / ".env")

ALPHA_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "").strip()
ALPACA_KEY = os.getenv("ALPACA_API_KEY", "").strip()
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY", "").strip()
ALPACA_FEED = os.getenv("ALPACA_FEED", "iex").strip().lower()
if ALPACA_FEED not in {"iex", "sip", "delayed_sip"}:
    ALPACA_FEED = "iex"

APP_VERSION = os.getenv("APP_VERSION", "2026.09.12-pwa1")

app = FastAPI(title="Smart Investment Advisor", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

ALLOWED_ALPHA_FUNCTIONS = {
    "GLOBAL_QUOTE",
    "NEWS_SENTIMENT",
    "TIME_SERIES_INTRADAY",
    "TIME_SERIES_DAILY",
    "TIME_SERIES_WEEKLY",
    "TOP_GAINERS_LOSERS",
}

@app.get("/")
async def root():
    # index.html must be revalidated so deployed UI updates appear without a new download.
    return FileResponse(
        BASE_DIR / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(
        BASE_DIR / "static" / "manifest.webmanifest",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Service-Worker-Allowed": "/"},
    )


@app.get("/api/version")
async def api_version():
    return JSONResponse(
        {"version": APP_VERSION, "pwa": True},
        headers={"Cache-Control": "no-store"},
    )

@app.get("/api/status")
async def status():
    return {
        "ok": True,
        "alpha_vantage_configured": bool(ALPHA_KEY),
        "alpaca_configured": bool(ALPACA_KEY and ALPACA_SECRET),
        "alpaca_feed": ALPACA_FEED,
        "secrets_exposed_to_browser": False,
        "app_version": APP_VERSION,
        "pwa": True,
    }


def _write_env_values(updates: Dict[str, str]):
    env_path=BASE_DIR / ".env"
    lines=[]
    if env_path.exists():
        lines=env_path.read_text(encoding="utf-8").splitlines()
    found=set()
    out=[]
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key=line.split("=",1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                found.add(key)
                continue
        out.append(line)
    for key,val in updates.items():
        if key not in found:
            out.append(f"{key}={val}")
    env_path.write_text("\n".join(out).rstrip()+"\n",encoding="utf-8")


def _reload_runtime_config():
    global ALPHA_KEY, ALPACA_KEY, ALPACA_SECRET, ALPACA_FEED
    load_dotenv(BASE_DIR / ".env", override=True)
    ALPHA_KEY=os.getenv("ALPHA_VANTAGE_API_KEY","").strip()
    ALPACA_KEY=os.getenv("ALPACA_API_KEY","").strip()
    ALPACA_SECRET=os.getenv("ALPACA_SECRET_KEY","").strip()
    ALPACA_FEED=os.getenv("ALPACA_FEED","iex").strip().lower()
    if ALPACA_FEED not in {"iex","sip","delayed_sip"}:
        ALPACA_FEED="iex"


async def _verify_alpaca_credentials(key: str, secret: str, feed: str):
    headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret}
    details={"clock":False,"market_data":False,"feed":feed}
    async with httpx.AsyncClient(timeout=15) as client:
        # Account/clock auth check.
        r=await client.get("https://paper-api.alpaca.markets/v2/clock",headers=headers)
        if r.status_code>=400:
            # Some users may be using live rather than paper credentials.
            r2=await client.get("https://api.alpaca.markets/v2/clock",headers=headers)
            if r2.status_code>=400:
                raise HTTPException(status_code=400,detail="Alpaca דחתה את המפתחות. בדוק API Key ו-Secret.")
        details["clock"]=True
        # Verify the selected market-data feed independently.
        dr=await client.get(
            "https://data.alpaca.markets/v2/stocks/AAPL/snapshot",
            headers=headers,
            params={"feed":feed},
        )
        if dr.status_code<400:
            details["market_data"]=True
        elif feed=="sip" and dr.status_code in {401,403,422}:
            raise HTTPException(status_code=400,detail="המפתחות תקינים, אבל לחשבון אין הרשאת SIP. בחר IEX או שדרג את חבילת הנתונים ב-Alpaca.")
        elif dr.status_code>=400:
            raise HTTPException(status_code=400,detail="המפתחות אומתו, אך Alpaca לא מאפשרת את Feed הנתונים שנבחר.")
    return details


@app.post("/api/settings/alpaca/test")
async def test_alpaca_settings(payload: Dict[str, Any] = Body(...)):
    key=str(payload.get("api_key") or "").strip()
    secret=str(payload.get("secret_key") or "").strip()
    feed=str(payload.get("feed") or "iex").strip().lower()
    if feed not in {"iex","sip","delayed_sip"}:
        raise HTTPException(status_code=400,detail="Feed לא תקין")
    if not key or not secret:
        raise HTTPException(status_code=400,detail="יש להזין API Key ו-Secret")
    details=await _verify_alpaca_credentials(key,secret,feed)
    return {"ok":True,"message":"החיבור ל-Alpaca תקין.","details":details}


@app.post("/api/settings/alpaca/save")
async def save_alpaca_settings(payload: Dict[str, Any] = Body(...)):
    key=str(payload.get("api_key") or "").strip()
    secret=str(payload.get("secret_key") or "").strip()
    feed=str(payload.get("feed") or "iex").strip().lower()
    if feed not in {"iex","sip","delayed_sip"}:
        raise HTTPException(status_code=400,detail="Feed לא תקין")
    if not key or not secret:
        raise HTTPException(status_code=400,detail="יש להזין API Key ו-Secret")
    details=await _verify_alpaca_credentials(key,secret,feed)
    _write_env_values({
        "ALPACA_API_KEY":key,
        "ALPACA_SECRET_KEY":secret,
        "ALPACA_FEED":feed,
    })
    _reload_runtime_config()
    return {
        "ok":True,
        "message":"Alpaca נשמרה והחיבור הופעל.",
        "alpaca_configured":True,
        "alpaca_feed":ALPACA_FEED,
        "details":details,
    }


@app.delete("/api/settings/alpaca")
async def clear_alpaca_settings():
    _write_env_values({"ALPACA_API_KEY":"","ALPACA_SECRET_KEY":"","ALPACA_FEED":"iex"})
    _reload_runtime_config()
    return {"ok":True,"message":"מפתחות Alpaca נמחקו מהמחשב המקומי."}


@app.get("/api/market/status")
async def market_status():
    """
    Server-synchronized clocks for Israel and New York, plus Alpaca US market status.
    Falls back to a time-of-day estimate if the trading clock is unavailable.
    """
    now_utc=datetime.now(timezone.utc)
    israel=now_utc.astimezone(ZoneInfo("Asia/Jerusalem"))
    ny=now_utc.astimezone(ZoneInfo("America/New_York"))

    result={
        "server_utc":now_utc.isoformat(),
        "israel_time":israel.isoformat(),
        "new_york_time":ny.isoformat(),
        "market":{
            "source":"server_fallback",
            "is_open":False,
            "session":"closed",
            "session_he":"סגור",
            "next_open":None,
            "next_close":None,
            "today_is_trading_day":ny.weekday()<5,
        }
    }

    if ALPACA_KEY and ALPACA_SECRET:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                headers={
                    "APCA-API-KEY-ID":ALPACA_KEY,
                    "APCA-API-SECRET-KEY":ALPACA_SECRET,
                }
                clock_r=await client.get("https://paper-api.alpaca.markets/v2/clock",headers=headers)
                if clock_r.status_code<400:
                    c=clock_r.json()
                    result["market"]["source"]="alpaca_clock"
                    result["market"]["is_open"]=bool(c.get("is_open"))
                    result["market"]["next_open"]=c.get("next_open")
                    result["market"]["next_close"]=c.get("next_close")

                d=ny.date().isoformat()
                cal_r=await client.get(
                    "https://paper-api.alpaca.markets/v2/calendar",
                    headers=headers,
                    params={"start":d,"end":d},
                )
                trading_day=False
                open_t=None
                close_t=None
                if cal_r.status_code<400:
                    arr=cal_r.json() or []
                    trading_day=bool(arr)
                    if arr:
                        open_t=arr[0].get("open")
                        close_t=arr[0].get("close")
                result["market"]["today_is_trading_day"]=trading_day

                t=ny.time()
                if result["market"]["is_open"]:
                    session="regular"; he="מסחר פתוח"
                elif trading_day and dtime(4,0)<=t<dtime(9,30):
                    session="premarket"; he="טרום מסחר"
                elif trading_day and dtime(16,0)<=t<dtime(20,0):
                    session="afterhours"; he="אחרי המסחר"
                else:
                    session="closed"; he="סגור"
                result["market"]["session"]=session
                result["market"]["session_he"]=he
                result["market"]["today_open"]=open_t
                result["market"]["today_close"]=close_t
                return result
        except Exception as exc:
            result["market"]["error"]=str(exc)

    # Fallback if Alpaca unavailable. This is not holiday-aware.
    t=ny.time()
    trading_day=ny.weekday()<5
    if trading_day and dtime(9,30)<=t<dtime(16,0):
        session="regular"; he="מסחר פתוח"
    elif trading_day and dtime(4,0)<=t<dtime(9,30):
        session="premarket"; he="טרום מסחר"
    elif trading_day and dtime(16,0)<=t<dtime(20,0):
        session="afterhours"; he="אחרי המסחר"
    else:
        session="closed"; he="סגור"
    result["market"]["session"]=session
    result["market"]["session_he"]=he
    return result

@app.get("/api/alpha")
async def alpha_proxy(request_function: str | None = Query(None, alias="function"),
                      symbol: str | None = None,
                      interval: str | None = None,
                      extended_hours: str | None = None,
                      outputsize: str | None = None,
                      tickers: str | None = None,
                      sort: str | None = None,
                      limit: str | None = None,
                      entitlement: str | None = None):
    if not ALPHA_KEY:
        raise HTTPException(503, "ALPHA_VANTAGE_API_KEY is not configured on the server")
    if not request_function or request_function not in ALLOWED_ALPHA_FUNCTIONS:
        raise HTTPException(400, "Unsupported Alpha Vantage function")

    params: Dict[str, Any] = {"function": request_function, "apikey": ALPHA_KEY}
    optional = {
        "symbol": symbol, "interval": interval, "extended_hours": extended_hours,
        "outputsize": outputsize, "tickers": tickers, "sort": sort,
        "limit": limit, "entitlement": entitlement,
    }
    params.update({k: v for k, v in optional.items() if v not in (None, "")})

    async with httpx.AsyncClient(timeout=25) as client:
        r = await client.get("https://www.alphavantage.co/query", params=params)
        try:
            data = r.json()
        except Exception:
            raise HTTPException(502, "Alpha Vantage returned invalid JSON")
    return data




def _market_cache_path(symbol, range_key):
    safe="".join(ch for ch in symbol.upper() if ch.isalnum() or ch in {"-","_"})
    return MARKET_CACHE_DIR / f"{safe}_{range_key.upper()}.json"

def _write_market_cache(symbol, range_key, payload):
    try:
        path=_market_cache_path(symbol,range_key)
        tmp=path.with_suffix(".tmp")
        obj={"saved_at":datetime.now(timezone.utc).isoformat(),"payload":payload}
        tmp.write_text(json.dumps(obj,ensure_ascii=False),encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass

def _read_market_cache(symbol, range_key):
    try:
        path=_market_cache_path(symbol,range_key)
        if not path.exists(): return None
        obj=json.loads(path.read_text(encoding="utf-8"))
        payload=obj.get("payload") or {}
        payload["cache_saved_at"]=obj.get("saved_at")
        return payload
    except Exception:
        return None

def _normalize_alpha_bars(series):
    rows=[]
    if not series:
        return rows
    for dt,o in series.items():
        try:
            rows.append({
                "d":dt,
                "o":float(o.get("1. open") or 0),
                "h":float(o.get("2. high") or 0),
                "l":float(o.get("3. low") or 0),
                "v":float(o.get("4. close") or 0),
                "volume":float(o.get("5. volume") or 0),
            })
        except Exception:
            continue
    return sorted([x for x in rows if x["v"]>0],key=lambda x:x["d"])

async def _alpha_stock_bundle(client,symbol,range_key):
    if not ALPHA_KEY:
        return {"quote":None,"bars":[],"news":[],"errors":["Alpha Vantage לא מוגדר"]}
    errors=[]; quote=None; bars=[]; news=[]
    try:
        q=(await client.get("https://www.alphavantage.co/query",params={"function":"GLOBAL_QUOTE","symbol":symbol,"apikey":ALPHA_KEY})).json()
        g=q.get("Global Quote") or {}
        price=float(g.get("05. price") or 0)
        change=float(str(g.get("10. change percent") or "0").replace("%",""))
        if price>0: quote={"price":price,"change":change,"date":g.get("07. latest trading day")}
    except Exception as exc:
        errors.append(f"Alpha quote: {exc}")
    try:
        if range_key=="1D":
            j=(await client.get("https://www.alphavantage.co/query",params={"function":"TIME_SERIES_INTRADAY","symbol":symbol,"interval":"5min","extended_hours":"true","outputsize":"compact","apikey":ALPHA_KEY})).json()
            key=next((k for k in j if k.startswith("Time Series")),None)
            bars=_normalize_alpha_bars(j.get(key) if key else None)[-120:]
        elif range_key=="1M":
            j=(await client.get("https://www.alphavantage.co/query",params={"function":"TIME_SERIES_DAILY","symbol":symbol,"outputsize":"compact","apikey":ALPHA_KEY})).json()
            bars=_normalize_alpha_bars(j.get("Time Series (Daily)"))[-40:]
        else:
            j=(await client.get("https://www.alphavantage.co/query",params={"function":"TIME_SERIES_WEEKLY","symbol":symbol,"apikey":ALPHA_KEY})).json()
            bars=_normalize_alpha_bars(j.get("Weekly Time Series"))[-(60 if range_key=="1Y" else 270):]
    except Exception as exc:
        errors.append(f"Alpha bars: {exc}")
    try:
        j=(await client.get("https://www.alphavantage.co/query",params={"function":"NEWS_SENTIMENT","tickers":symbol,"sort":"LATEST","limit":"8","apikey":ALPHA_KEY})).json()
        news=[{"title":x.get("title"),"source":x.get("source"),"url":x.get("url"),"published_at":x.get("time_published")} for x in (j.get("feed") or [])]
    except Exception as exc:
        errors.append(f"Alpha news: {exc}")
    return {"quote":quote,"bars":bars,"news":news,"errors":errors}

async def _alpaca_stock_bundle(client,symbol,range_key):
    if not (ALPACA_KEY and ALPACA_SECRET):
        return {"quote":None,"bars":[],"news":[],"errors":["Alpaca לא מוגדר"]}
    headers={"APCA-API-KEY-ID":ALPACA_KEY,"APCA-API-SECRET-KEY":ALPACA_SECRET}
    errors=[]; quote=None; bars=[]; news=[]
    try:
        r=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot",headers=headers,params={"feed":ALPACA_FEED})
        if r.status_code<400:
            snap=r.json() or {}
            latest=snap.get("latestTrade") or {}; minute=snap.get("minuteBar") or {}; daily=snap.get("dailyBar") or {}; prev=snap.get("prevDailyBar") or {}
            price=latest.get("p") or minute.get("c") or daily.get("c")
            prev_close=prev.get("c")
            if price:
                change=((float(price)/float(prev_close)-1)*100) if prev_close else None
                quote={"price":float(price),"change":change,"date":datetime.now(NY).date().isoformat()}
        else:
            errors.append(f"Alpaca snapshot HTTP {r.status_code}")
    except Exception as exc:
        errors.append(f"Alpaca snapshot: {exc}")

    now=datetime.now(timezone.utc)
    if range_key=="1D":
        start=now-timedelta(days=4); timeframe="5Min"; limit=1200
    elif range_key=="1M":
        start=now-timedelta(days=45); timeframe="1Day"; limit=1000
    elif range_key=="1Y":
        start=now-timedelta(days=380); timeframe="1Day"; limit=1000
    else:
        start=now-timedelta(days=int(365.25*5)+20); timeframe="1Day"; limit=10000
    try:
        r=await client.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",headers=headers,params={
            "timeframe":timeframe,"start":start.isoformat(),"end":now.isoformat(),"limit":limit,
            "adjustment":"split","feed":ALPACA_FEED,"sort":"asc"
        })
        if r.status_code<400:
            raw=(r.json() or {}).get("bars") or []
            bars=[{"d":b.get("t"),"o":float(b.get("o") or 0),"h":float(b.get("h") or 0),"l":float(b.get("l") or 0),"v":float(b.get("c") or 0),"volume":float(b.get("v") or 0)} for b in raw if b.get("c") is not None]
            if range_key=="1D": bars=bars[-180:]
            elif range_key=="1M": bars=bars[-40:]
            elif range_key=="1Y": bars=bars[-260:]
        else:
            errors.append(f"Alpaca bars HTTP {r.status_code}")
    except Exception as exc:
        errors.append(f"Alpaca bars: {exc}")
    try:
        r=await client.get("https://data.alpaca.markets/v1beta1/news",headers=headers,params={"symbols":symbol,"limit":8,"sort":"desc","include_content":"false"})
        if r.status_code<400:
            raw=(r.json() or {}).get("news") or []
            news=[{"title":x.get("headline"),"source":x.get("source"),"url":x.get("url"),"published_at":x.get("created_at") or x.get("updated_at")} for x in raw]
        else:
            errors.append(f"Alpaca news HTTP {r.status_code}")
    except Exception as exc:
        errors.append(f"Alpaca news: {exc}")
    return {"quote":quote,"bars":bars,"news":news,"errors":errors}



def _freshness_meta(quote, bars, provider, range_key):
    now=datetime.now(timezone.utc)
    ts=None
    if bars:
        raw=bars[-1].get("d")
        try:
            ts=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
            if ts.tzinfo is None:
                ts=ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts=None
    age=None
    if ts:
        age=max(0,(now-ts.astimezone(timezone.utc)).total_seconds())
    # Historical ranges are expected to be older; freshness is primarily relevant to 1D/live views.
    if range_key=="1D":
        if "Alpaca" in provider:
            state="live_or_near_live" if age is None or age<=180 else ("delayed" if age<=1200 else "stale")
        elif "Alpha" in provider:
            state="delayed" if age is None or age<=1800 else "stale"
        else:
            state="fallback"
    else:
        state="historical"
    return {
        "state":state,
        "age_seconds":round(age,1) if age is not None else None,
        "last_bar_at":ts.isoformat() if ts else None,
        "generated_at":now.isoformat(),
    }

async def _yahoo_stock_bundle(client,symbol,range_key):
    """No-key public price-history fallback. Not treated as consolidated real-time market data."""
    ranges={"1D":("5d","5m"),"1M":("1mo","1d"),"1Y":("1y","1d"),"5Y":("5y","1d")}
    rr,interval=ranges.get(range_key,("1mo","1d"))
    try:
        r=await client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range":rr,"interval":interval,"includePrePost":"true","events":"div,splits"},
            headers={"User-Agent":"Mozilla/5.0"},
        )
        if r.status_code>=400:
            return {"quote":None,"bars":[],"news":[],"errors":[f"Public fallback HTTP {r.status_code}"]}
        root=((r.json() or {}).get("chart") or {}).get("result") or []
        if not root:
            return {"quote":None,"bars":[],"news":[],"errors":["Public fallback empty"]}
        obj=root[0]; meta=obj.get("meta") or {}; ts=obj.get("timestamp") or []
        q=(((obj.get("indicators") or {}).get("quote") or [{}])[0])
        opens=q.get("open") or []; highs=q.get("high") or []; lows=q.get("low") or []; closes=q.get("close") or []; vols=q.get("volume") or []
        rows=[]
        for i,t in enumerate(ts):
            try:
                c=closes[i] if i<len(closes) else None
                if c is None: continue
                rows.append({
                    "d":datetime.fromtimestamp(int(t),timezone.utc).isoformat(),
                    "o":float(opens[i] if i<len(opens) and opens[i] is not None else c),
                    "h":float(highs[i] if i<len(highs) and highs[i] is not None else c),
                    "l":float(lows[i] if i<len(lows) and lows[i] is not None else c),
                    "v":float(c),
                    "volume":float(vols[i] if i<len(vols) and vols[i] is not None else 0),
                })
            except Exception:
                continue
        price=meta.get("regularMarketPrice") or (rows[-1]["v"] if rows else None)
        prev=meta.get("chartPreviousClose") or meta.get("previousClose")
        change=((float(price)/float(prev)-1)*100) if price and prev else None
        quote={"price":float(price),"change":change,"date":str(rows[-1]["d"])[:10]} if price else None
        return {"quote":quote,"bars":rows,"news":[],"errors":[]}
    except Exception as exc:
        return {"quote":None,"bars":[],"news":[],"errors":[f"Public fallback: {exc}"]}


async def _stooq_stock_bars(client, symbol, years=6):
    """Second no-key historical fallback for US equities (daily CSV)."""
    end=datetime.now(timezone.utc).date()
    start=end-timedelta(days=int(365.25*years)+30)
    stooq_symbol=symbol.lower().replace("-", ".")+".us"
    try:
        r=await client.get(
            "https://stooq.com/q/d/l/",
            params={"s":stooq_symbol,"d1":start.strftime("%Y%m%d"),"d2":end.strftime("%Y%m%d"),"i":"d"},
            headers={"User-Agent":"Mozilla/5.0"},
        )
        if r.status_code>=400:
            return {"bars":[],"errors":[f"Stooq HTTP {r.status_code}"]}
        text=r.text.strip()
        if not text or text.lower().startswith("no data"):
            return {"bars":[],"errors":["Stooq empty"]}
        rows=[]
        reader=csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                c=float(row.get("Close") or 0)
                if c<=0: continue
                rows.append({
                    "d":row.get("Date"),
                    "o":float(row.get("Open") or c),
                    "h":float(row.get("High") or c),
                    "l":float(row.get("Low") or c),
                    "v":c,
                    "volume":float(row.get("Volume") or 0),
                })
            except Exception:
                continue
        rows.sort(key=lambda x:x["d"])
        return {"bars":rows,"errors":[]}
    except Exception as exc:
        return {"bars":[],"errors":[f"Stooq: {exc}"]}

async def _public_day_scan(client, top=10, candidates=40):
    """No-key fallback scanner. Not full-market; scans a broad liquid/volatile universe."""
    universe=[
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AMD","AVGO","PLTR",
        "HOOD","COIN","MARA","RIOT","SMCI","SOFI","RIVN","IONQ","SOUN","RKLB",
        "APP","MU","INTC","ARM","QCOM","MRVL","CRWD","NET","SNOW","SHOP",
        "UBER","PYPL","NFLX","ORCL","TSM","NIO","LCID","AFRM","UPST","CVNA"
    ]
    universe=universe[:max(top,min(candidates,len(universe)))]
    sem=asyncio.Semaphore(8)
    async def one(sym):
        async with sem:
            data=await _yahoo_stock_bundle(client,sym,"1M")
            bars=data.get("bars") or []
            q=data.get("quote") or {}
            if not bars and not q:
                st=await _stooq_stock_bars(client,sym,years=1)
                bars=(st.get("bars") or [])[-40:]
                if bars:
                    last=bars[-1]; prev=bars[-2] if len(bars)>1 else None
                    q={"price":last.get("v"),"change":((last.get("v")/prev.get("v")-1)*100 if prev and prev.get("v") else None),"date":last.get("d")}
            if not bars and not q:
                return None
            price=q.get("price") or (bars[-1]["v"] if bars else None)
            change=q.get("change")
            daily_volume=(bars[-1].get("volume") or 0) if bars else 0
            prev_vols=[float(x.get("volume") or 0) for x in bars[-21:-1] if float(x.get("volume") or 0)>0]
            avg_vol=sum(prev_vols)/len(prev_vols) if prev_vols else None
            rvol=(float(daily_volume)/avg_vol) if avg_vol and daily_volume else None
            h=(bars[-1].get("h") if bars else None); l=(bars[-1].get("l") if bars else None)
            strength=None
            try:
                if price and h and l and float(h)>float(l):
                    strength=(float(price)-float(l))/(float(h)-float(l))
            except Exception:
                pass
            score=_score_day_candidate(change,rvol,float(daily_volume or 0),float(price) if price else None,0,None,strength)
            risk=3
            if price and float(price)<2: risk+=1
            if change is not None and abs(float(change))>50: risk+=1
            return {
                "ticker":sym,"name":sym,"domain":None,"score":score,"risk":max(1,min(5,risk)),
                "price":float(price) if price else None,
                "change":round(float(change),2) if change is not None else None,
                "media":35,"catalyst":"סריקת מחיר ומחזור — ללא קטליזטור חדשותי מאומת",
                "volume":int(daily_volume or 0),"rvol":round(rvol,2) if rvol is not None else None,
                "news_count":0,"news_minutes":None,"day_high":h,"day_low":l,
                "intraday_strength":round(strength,3) if strength is not None else None,
            }
    rows=await asyncio.gather(*[one(x) for x in universe])
    rows=[x for x in rows if x and x.get("price")]
    rows.sort(key=lambda x:(x.get("score") or 0,x.get("change") or -999),reverse=True)
    return rows[:top],len(universe)

@app.get("/api/stock/{symbol}/bundle")
async def stock_bundle(symbol: str, range: str = Query("1M")):
    symbol=symbol.upper().strip()
    range_key=range.upper()
    if range_key not in {"1D","1M","1Y","5Y"}:
        raise HTTPException(400,"טווח לא נתמך")
    async with httpx.AsyncClient(timeout=30) as client:
        alp=await _alpaca_stock_bundle(client,symbol,range_key)
        alpha={"quote":None,"bars":[],"news":[],"errors":[]}
        if not alp.get("quote") or not alp.get("bars") or not alp.get("news"):
            alpha=await _alpha_stock_bundle(client,symbol,range_key)
        public={"quote":None,"bars":[],"news":[],"errors":[]}
        if not (alp.get("quote") or alpha.get("quote")) or not (alp.get("bars") or alpha.get("bars")):
            public=await _yahoo_stock_bundle(client,symbol,range_key)
        stooq={"bars":[],"errors":[]}
        if range_key!="1D" and not (alp.get("bars") or alpha.get("bars") or public.get("bars")):
            stooq=await _stooq_stock_bars(client,symbol,years=6 if range_key=="5Y" else 2)
    quote=alp.get("quote") or alpha.get("quote") or public.get("quote")
    bars=alp.get("bars") or alpha.get("bars") or public.get("bars") or stooq.get("bars") or []
    news=alp.get("news") or alpha.get("news") or []
    provider=[]
    if alp.get("quote") or alp.get("bars") or alp.get("news"): provider.append("Alpaca")
    if alpha.get("quote") or alpha.get("bars") or alpha.get("news"): provider.append("Alpha Vantage")
    if public.get("quote") or public.get("bars"): provider.append("Public price fallback")
    if stooq.get("bars"): provider.append("Stooq historical fallback")
    if not quote and bars:
        last=bars[-1]; prev=bars[-2]["v"] if len(bars)>1 else None
        quote={"price":last["v"],"change":((last["v"]/prev-1)*100 if prev else None),"date":str(last["d"])[:10]}
    if not quote and not bars:
        cached=_read_market_cache(symbol,range_key)
        if cached:
            cached["provider"]="מטמון מקומי · "+str(cached.get("provider") or "")
            cached["from_cache"]=True
            cached["freshness"]={"state":"stale","age_seconds":None,"last_bar_at":((cached.get("freshness") or {}).get("last_bar_at")),"generated_at":datetime.now(timezone.utc).isoformat()}
            errs=list(cached.get("errors") or [])
            errs.append("מקורות הרשת לא היו זמינים; מוצג המטמון האחרון שנשמר.")
            cached["errors"]=errs
            return cached
    payload={
        "symbol":symbol,"range":range_key,"provider":" + ".join(provider) if provider else "none",
        "feed":ALPACA_FEED if (ALPACA_KEY and ALPACA_SECRET) else None,
        "quote":quote,"bars":bars,"news":news,
        "configured":{"alpaca":bool(ALPACA_KEY and ALPACA_SECRET),"alpha":bool(ALPHA_KEY)},
        "errors":(alp.get("errors") or [])+(alpha.get("errors") or [])+(public.get("errors") or [])+(stooq.get("errors") or []),
        "freshness":_freshness_meta(quote,bars," + ".join(provider) if provider else "none",range_key),
        "generated_at":datetime.now(timezone.utc).isoformat(),
    }
    if quote or bars:
        _write_market_cache(symbol,range_key,payload)
    return payload


@app.websocket("/ws/market/{symbol}")
async def market_ws(client_ws: WebSocket, symbol: str):
    await client_ws.accept()
    symbol = symbol.upper().strip()

    if not (ALPACA_KEY and ALPACA_SECRET):
        await client_ws.send_json({"type": "proxy_error", "message": "Alpaca keys are not configured on the server"})
        await client_ws.close()
        return

    alpaca_url = f"wss://stream.data.alpaca.markets/v2/{ALPACA_FEED}"

    try:
        async with websockets.connect(alpaca_url, ping_interval=20, ping_timeout=20) as upstream:
            # Connected event from Alpaca
            raw = await upstream.recv()
            connected = json.loads(raw)
            # Authenticate server-side. The browser never sees these secrets.
            await upstream.send(json.dumps({
                "action": "auth",
                "key": ALPACA_KEY,
                "secret": ALPACA_SECRET,
            }))

            # Wait for auth response.
            raw = await upstream.recv()
            auth_msg = json.loads(raw)
            auth_items = auth_msg if isinstance(auth_msg, list) else [auth_msg]
            if not any(x.get("T") == "success" and x.get("msg") == "authenticated" for x in auth_items):
                await client_ws.send_json({"type": "proxy_error", "message": "Alpaca authentication failed"})
                await client_ws.close()
                return

            await upstream.send(json.dumps({
                "action": "subscribe",
                "trades": [symbol],
                "quotes": [symbol],
                "bars": [symbol],
                "updatedBars": [symbol],
            }))
            await client_ws.send_json({"type": "proxy_status", "status": "connected", "feed": ALPACA_FEED})

            async def relay_upstream():
                async for msg in upstream:
                    await client_ws.send_text(msg)

            async def keep_client():
                while True:
                    # We do not need commands from the browser yet, but reading detects disconnects.
                    await client_ws.receive_text()

            relay_task = asyncio.create_task(relay_upstream())
            client_task = asyncio.create_task(keep_client())
            done, pending = await asyncio.wait(
                {relay_task, client_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()

    except WebSocketDisconnect:
        return
    except Exception as exc:
        try:
            await client_ws.send_json({"type": "proxy_error", "message": str(exc)})
            await client_ws.close()
        except Exception:
            pass


def _max_drawdown_from_closes(closes):
    peak = None
    max_dd = 0.0
    for c in closes:
        if c is None or c <= 0:
            continue
        if peak is None or c > peak:
            peak = c
        dd = (c / peak - 1.0) if peak else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd * 100.0

def _annualized_volatility(closes):
    rets=[]
    prev=None
    for c in closes:
        if c and c>0 and prev and prev>0:
            rets.append(c/prev-1)
        if c and c>0:
            prev=c
    if len(rets)<2:
        return None
    return statistics.pstdev(rets)*(252**0.5)*100

def _sma(vals,n):
    if len(vals)<n:return None
    arr=[x for x in vals[-n:] if x is not None]
    return sum(arr)/len(arr) if len(arr)==n else None

@app.get("/api/history/5y/{symbol}")
async def history_5y(symbol: str):
    """Five-year profile with Alpaca primary and Alpha Vantage fallback."""
    symbol=symbol.upper().strip()
    async with httpx.AsyncClient(timeout=40) as client:
        alp=await _alpaca_stock_bundle(client,symbol,"5Y")
        alpha={"bars":[],"errors":[]}
        if not alp.get("bars"):
            alpha=await _alpha_stock_bundle(client,symbol,"5Y")
        public={"bars":[],"errors":[]}
        if not (alp.get("bars") or alpha.get("bars")):
            public=await _yahoo_stock_bundle(client,symbol,"5Y")
        stooq={"bars":[],"errors":[]}
        if not (alp.get("bars") or alpha.get("bars") or public.get("bars")):
            stooq=await _stooq_stock_bars(client,symbol,years=6)
    rows=(alp.get("bars") or alpha.get("bars") or public.get("bars") or stooq.get("bars") or [])
    if not rows:
        cached=_read_market_cache(symbol,"5Y")
        if cached and cached.get("bars"):
            rows=cached.get("bars") or []
            cache_provider=cached.get("provider") or "מטמון מקומי"
        else:
            raise HTTPException(503,"אין כרגע מקור נתונים היסטורי זמין. נסה שוב לאחר בדיקת חיבור הנתונים.")
    else:
        cache_provider=None

    # Normalize to daily date strings. Alpha weekly fallback is still useful when Alpaca is absent.
    norm=[]
    for b in rows:
        try:
            d=str(b.get("d") or b.get("t") or "")[:10]
            o=float(b.get("o") or 0); h=float(b.get("h") or 0); l=float(b.get("l") or 0)
            c=float(b.get("v") if b.get("v") is not None else b.get("c") or 0)
            vol=float(b.get("volume") if b.get("volume") is not None else b.get("v") or 0)
            if d and c>0: norm.append({"d":d,"o":o,"h":h,"l":l,"v":c,"volume":vol})
        except Exception:
            continue
    norm.sort(key=lambda x:x["d"])
    if len(norm)<2:
        raise HTTPException(404,"לא נמצאו מספיק נתוני 5 שנים")

    closes=[x["v"] for x in norm]
    highs=[x["h"] for x in norm if x["h"]>0]
    lows=[x["l"] for x in norm if x["l"]>0]
    gaps=[]; explosive_days=0; gap10_days=0; year_open={}; year_close={}; prev_close=None
    for x in norm:
        y=int(x["d"][:4]); o=x["o"]; h=x["h"]; c=x["v"]
        year_open.setdefault(y,o if o>0 else c); year_close[y]=c
        if prev_close and o>0:
            gap=(o/prev_close-1)*100; gaps.append(gap)
            if abs(gap)>=10: gap10_days+=1
        if o>0 and h>0 and (h/o-1)*100>=15: explosive_days+=1
        prev_close=c

    first,last=closes[0],closes[-1]
    d0=datetime.fromisoformat(norm[0]["d"]).date(); d1=datetime.fromisoformat(norm[-1]["d"]).date()
    years=max((d1-d0).days/365.25,0.01)
    total_return=(last/first-1)*100 if first else None
    cagr=((last/first)**(1/years)-1)*100 if first and last else None
    max_dd=_max_drawdown_from_closes(closes); vol=_annualized_volatility(closes)
    ma50=_sma(closes,50); ma200=_sma(closes,200)
    annual=[]
    for y in sorted(year_close):
        op=year_open.get(y); cl=year_close.get(y)
        annual.append({"year":y,"return_pct":round((cl/op-1)*100,2) if op and cl else None})
    provider=(cache_provider if cache_provider else ("Alpaca" if alp.get("bars") else ("Alpha Vantage" if alpha.get("bars") else ("Public price fallback" if public.get("bars") else "Stooq historical fallback"))))
    result={
        "symbol":symbol,"provider":provider,"from":norm[0]["d"],"to":norm[-1]["d"],"bars":norm,
        "stats":{
            "total_return_pct":round(total_return,2) if total_return is not None else None,
            "cagr_pct":round(cagr,2) if cagr is not None else None,
            "annualized_volatility_pct":round(vol,2) if vol is not None else None,
            "max_drawdown_pct":round(max_dd,2),
            "high_5y":round(max(highs),4) if highs else None,
            "low_5y":round(min(lows),4) if lows else None,
            "ma50":round(ma50,4) if ma50 else None,"ma200":round(ma200,4) if ma200 else None,
            "above_ma200":bool(last>ma200) if ma200 else None,
            "avg_abs_gap_pct":round(sum(abs(x) for x in gaps)/len(gaps),3) if gaps else None,
            "gap10_days":gap10_days,"explosive_days_15pct":explosive_days,
            "explosive_day_rate_pct":round(explosive_days/len(norm)*100,3),"trading_days":len(norm),
        },"annual_returns":annual,
    }
    if not cache_provider:
        _write_market_cache(symbol,"5Y",{"symbol":symbol,"range":"5Y","provider":provider,"quote":{"price":last,"change":None,"date":norm[-1]["d"]},"bars":norm,"news":[],"freshness":{"state":"historical","last_bar_at":norm[-1]["d"]},"generated_at":datetime.now(timezone.utc).isoformat()})
    return result

@app.get("/api/live/snapshot/{symbol}")
async def alpaca_snapshot(symbol: str):
    """Optional REST snapshot fallback for debugging/initial display."""
    if not (ALPACA_KEY and ALPACA_SECRET):
        raise HTTPException(503, "Alpaca is not configured")
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }
    url = f"https://data.alpaca.markets/v2/stocks/{symbol.upper()}/snapshot"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers, params={"feed": ALPACA_FEED})
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


def _alpaca_headers():
    return {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }

def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def _score_day_candidate(change_pct, rvol, daily_volume, price, news_count, news_minutes, intraday_strength):
    # 100-point day-explosion score:
    # change/momentum 20, RVOL 20, catalyst/news 20, liquidity 15,
    # intraday strength 10, price/tradability 5, risk-adjustment 10.
    score = 0.0

    # Momentum: ideal zone is strong, but not already absurdly extended.
    if change_pct is not None:
        if 5 <= change_pct <= 35:
            score += 20 * _clamp((change_pct - 5) / 30)
        elif 35 < change_pct <= 70:
            score += 20 - 5 * _clamp((change_pct - 35) / 35)
        elif change_pct > 70:
            score += 12
        elif change_pct > 0:
            score += 4 * _clamp(change_pct / 5)

    # Relative volume.
    if rvol is not None:
        score += 20 * _clamp((rvol - 0.8) / 4.2)

    # News/catalyst.
    if news_count:
        freshness = 1.0
        if news_minutes is not None:
            freshness = _clamp(1 - news_minutes / (24 * 60))
        score += min(15, 7 + 3 * min(news_count - 1, 2)) + 5 * freshness

    # Liquidity.
    if daily_volume:
        if daily_volume >= 5_000_000:
            score += 15
        elif daily_volume >= 1_000_000:
            score += 12
        elif daily_volume >= 300_000:
            score += 8
        elif daily_volume >= 100_000:
            score += 4

    # Intraday structure.
    if intraday_strength is not None:
        score += 10 * _clamp(intraday_strength)

    # Tradable price range.
    if price:
        if 2 <= price <= 100:
            score += 5
        elif 1 <= price < 2 or 100 < price <= 250:
            score += 3

    # Penalties.
    if price and price < 1:
        score -= 12
    if daily_volume and daily_volume < 100_000:
        score -= 10
    if change_pct is not None and change_pct > 100:
        score -= 8  # often too extended to chase
    if news_count == 0 and change_pct is not None and change_pct >= 20:
        score -= 12  # unexplained spike

    return int(round(max(0, min(100, score))))

async def _alpaca_json(client, url, params=None):
    r = await client.get(url, headers=_alpaca_headers(), params=params or {})
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:240]}")
    return r.json()

async def _get_market_candidates(client, candidate_count=40):
    """Use Alpaca's whole-market screeners. They are SIP-based."""
    movers_url = "https://data.alpaca.markets/v1beta1/screener/stocks/movers"
    active_url = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"

    movers_task = asyncio.create_task(_alpaca_json(client, movers_url, {"top": min(50, candidate_count)}))
    active_task = asyncio.create_task(_alpaca_json(client, active_url, {"top": min(100, candidate_count * 2), "by": "volume"}))
    movers, active = await asyncio.gather(movers_task, active_task)

    syms = []
    mover_map = {}

    for x in (movers.get("gainers") or []):
        s = (x.get("symbol") or "").upper()
        if s:
            syms.append(s)
            mover_map[s] = x
    for x in (active.get("most_actives") or active.get("mostActive") or active.get("most_active") or []):
        s = (x.get("symbol") or "").upper()
        if s and s not in syms:
            syms.append(s)

    return syms[:candidate_count], mover_map

async def _alpha_fallback_candidates(client, candidate_count=40):
    if not ALPHA_KEY:
        return [], {}, "none"
    params = {"function": "TOP_GAINERS_LOSERS", "apikey": ALPHA_KEY}
    r = await client.get("https://www.alphavantage.co/query", params=params)
    j = r.json()
    syms, mover_map = [], {}
    for x in (j.get("top_gainers") or []):
        s = (x.get("ticker") or "").upper()
        if not s:
            continue
        syms.append(s)
        pct = str(x.get("change_percentage") or "").replace("%", "")
        try:
            cp = float(pct)
        except Exception:
            cp = None
        mover_map[s] = {"symbol": s, "percent_change": cp}
        if len(syms) >= candidate_count:
            break
    return syms, mover_map, "alpha_eod_or_entitled"

async def _fetch_snapshot(client, symbol):
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/snapshot"
    try:
        return symbol, await _alpaca_json(client, url, {"feed": ALPACA_FEED})
    except Exception:
        return symbol, {}

async def _fetch_daily_bars(client, symbol, limit=21):
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "limit": limit, "adjustment": "split", "feed": ALPACA_FEED}
    try:
        j = await _alpaca_json(client, url, params)
        return symbol, (j.get("bars") or [])
    except Exception:
        return symbol, []

async def _fetch_news_batch(client, symbols):
    if not symbols:
        return []
    try:
        j = await _alpaca_json(
            client,
            "https://data.alpaca.markets/v1beta1/news",
            {"symbols": ",".join(symbols[:50]), "limit": 50, "sort": "desc", "include_content": "false"},
        )
        return j.get("news") or []
    except Exception:
        return []

@app.get("/api/scanner/day")
async def day_scanner(top: int = 10, candidates: int = 40):
    """
    Whole-market candidate generation when Alpaca SIP screener access is available.
    Falls back to Alpha Vantage top gainers when the SIP screener is unavailable.
    """
    top = max(3, min(top, 20))
    candidates = max(top, min(candidates, 60))
    if not (ALPACA_KEY and ALPACA_SECRET):
        async with httpx.AsyncClient(timeout=25) as client:
            # Prefer Alpha Vantage market-wide candidates if available, otherwise scan a broad public universe.
            symbols, mover_map, source = await _alpha_fallback_candidates(client, candidates)
            if symbols:
                # Alpha supplies candidate discovery, public price history supplies enrichment when needed.
                rows=[]
                sem=asyncio.Semaphore(8)
                async def one(sym):
                    async with sem:
                        data=await _yahoo_stock_bundle(client,sym,"1M")
                        bars=data.get("bars") or []; q=data.get("quote") or {}
                        if not bars and not q:
                            st=await _stooq_stock_bars(client,sym,years=1)
                            bars=(st.get("bars") or [])[-40:]
                            if bars:
                                last=bars[-1]; prev=bars[-2] if len(bars)>1 else None
                                q={"price":last.get("v"),"change":((last.get("v")/prev.get("v")-1)*100 if prev and prev.get("v") else None),"date":last.get("d")}
                        price=q.get("price") or (bars[-1]["v"] if bars else None)
                        raw=(mover_map.get(sym) or {}).get("percent_change") or (mover_map.get(sym) or {}).get("change_percentage")
                        try: change=float(str(raw).replace("%","")) if raw is not None else q.get("change")
                        except Exception: change=q.get("change")
                        vol=(bars[-1].get("volume") or 0) if bars else 0
                        hist=[float(x.get("volume") or 0) for x in bars[-21:-1] if float(x.get("volume") or 0)>0]
                        av=sum(hist)/len(hist) if hist else None; rvol=(float(vol)/av) if av and vol else None
                        score=_score_day_candidate(change,rvol,float(vol or 0),float(price) if price else None,0,None,None)
                        return {"ticker":sym,"name":sym,"domain":None,"score":score,"risk":3,"price":float(price) if price else None,
                                "change":round(float(change),2) if change is not None else None,"media":35,
                                "catalyst":"מועמד מסריקת מובילות שוק; חדשות דורשות אימות","volume":int(vol or 0),
                                "rvol":round(rvol,2) if rvol is not None else None,"news_count":0,"news_minutes":None,
                                "day_high":bars[-1].get("h") if bars else None,"day_low":bars[-1].get("l") if bars else None,"intraday_strength":None}
                rows=await asyncio.gather(*[one(x) for x in symbols[:candidates]])
                ranked=[x for x in rows if x and x.get("price")]
                ranked.sort(key=lambda x:(x.get("score") or 0,x.get("change") or -999),reverse=True)
                now=datetime.now(timezone.utc)
                saved=_persist_scanner_signals(ranked[:top],now.isoformat(),source)
                return {"generated_at":now.isoformat(),"source":source,"feed":"alpha/public","full_market":False,
                        "screener_error":None,"candidate_count":len(symbols),"saved_signals":saved,"results":ranked[:top]}
            ranked,count=await _public_day_scan(client,top,candidates)
            now=datetime.now(timezone.utc)
            saved=_persist_scanner_signals(ranked,now.isoformat(),"public_watchlist")
            return {"generated_at":now.isoformat(),"source":"public_watchlist","feed":"public","full_market":False,
                    "screener_error":"Alpaca לא מוגדר; מוצגת סריקת גיבוי שאינה כל השוק.","candidate_count":count,
                    "saved_signals":saved,"results":ranked}

    source = "alpaca_sip_screener"
    screener_error = None

    async with httpx.AsyncClient(timeout=25) as client:
        try:
            symbols, mover_map = await _get_market_candidates(client, candidates)
            if not symbols:
                raise RuntimeError("No symbols returned by Alpaca screener")
        except Exception as exc:
            screener_error = str(exc)
            symbols, mover_map, source = await _alpha_fallback_candidates(client, candidates)
            if not symbols:
                # Last-resort curated broad watchlist; not full-market.
                symbols = ["AAPL","NVDA","TSLA","AMD","PLTR","RKLB","APP","HOOD","SOFI","SMCI","MARA","COIN","RIVN","IONQ","SOUN"]
                mover_map = {}
                source = "fallback_watchlist"

        # Enrich candidates concurrently.
        snap_pairs, bar_pairs, news = await asyncio.gather(
            asyncio.gather(*[_fetch_snapshot(client, s) for s in symbols]),
            asyncio.gather(*[_fetch_daily_bars(client, s) for s in symbols]),
            _fetch_news_batch(client, symbols),
        )

    snapshots = dict(snap_pairs)
    bars_map = dict(bar_pairs)

    # Map latest news to symbols.
    news_map = {s: [] for s in symbols}
    now = datetime.now(timezone.utc)
    for article in news:
        for s in (article.get("symbols") or []):
            if s in news_map:
                news_map[s].append(article)

    results = []
    for s in symbols:
        snap = snapshots.get(s) or {}
        latest = snap.get("latestTrade") or {}
        minute = snap.get("minuteBar") or {}
        daily = snap.get("dailyBar") or {}
        prev = snap.get("prevDailyBar") or {}

        price = latest.get("p") or minute.get("c") or daily.get("c")
        prev_close = prev.get("c")
        change_pct = None
        if price and prev_close:
            try:
                change_pct = (float(price) / float(prev_close) - 1) * 100
            except Exception:
                pass
        if change_pct is None:
            mm = mover_map.get(s) or {}
            raw = mm.get("percent_change") or mm.get("percentChange")
            try:
                change_pct = float(str(raw).replace("%",""))
            except Exception:
                change_pct = None

        daily_volume = daily.get("v") or 0
        bars = bars_map.get(s) or []
        hist_vols = [float(b.get("v") or 0) for b in bars[:-1] if float(b.get("v") or 0) > 0]
        avg_vol = sum(hist_vols[-20:]) / len(hist_vols[-20:]) if hist_vols else None
        rvol = (float(daily_volume) / avg_vol) if avg_vol and daily_volume else None

        # Intraday strength: where current price sits in today's high-low range.
        day_high = daily.get("h")
        day_low = daily.get("l")
        intraday_strength = None
        try:
            if price and day_high and day_low and float(day_high) > float(day_low):
                intraday_strength = (float(price) - float(day_low)) / (float(day_high) - float(day_low))
        except Exception:
            pass

        articles = news_map.get(s) or []
        latest_headline = articles[0].get("headline") if articles else None
        news_minutes = None
        if articles:
            try:
                created = datetime.fromisoformat(str(articles[0].get("created_at")).replace("Z","+00:00"))
                news_minutes = max(0, (now - created).total_seconds() / 60)
            except Exception:
                pass

        score = _score_day_candidate(
            change_pct=change_pct,
            rvol=rvol,
            daily_volume=float(daily_volume or 0),
            price=float(price) if price else None,
            news_count=len(articles),
            news_minutes=news_minutes,
            intraday_strength=intraday_strength,
        )

        # Risk badge 1..5
        risk = 3
        if price and float(price) < 2:
            risk += 1
        if change_pct is not None and abs(change_pct) > 50:
            risk += 1
        if daily_volume and float(daily_volume) < 300_000:
            risk += 1
        if len(articles) == 0 and change_pct is not None and change_pct > 20:
            risk += 1
        risk = max(1, min(5, risk))

        media = min(100, 35 + len(articles) * 15 + (15 if news_minutes is not None and news_minutes < 180 else 0))
        catalyst = latest_headline or ("מומנטום/מחזור חריג ללא קטליזטור חדשותי מאומת" if change_pct and change_pct > 10 else "סריקת שוק חיה")

        results.append({
            "ticker": s,
            "name": s,
            "domain": None,
            "score": score,
            "risk": risk,
            "price": float(price) if price else None,
            "change": round(change_pct, 2) if change_pct is not None else None,
            "media": media,
            "catalyst": catalyst,
            "volume": int(daily_volume or 0),
            "rvol": round(rvol, 2) if rvol is not None else None,
            "news_count": len(articles),
            "news_minutes": round(news_minutes, 1) if news_minutes is not None else None,
            "day_high": day_high,
            "day_low": day_low,
            "intraday_strength": round(intraday_strength, 3) if intraday_strength is not None else None,
        })

    # Exclude obviously untradable / missing-price names, rank by methodology.
    ranked = [x for x in results if x["price"] and x["price"] > 0]
    ranked.sort(key=lambda x: (x["score"], x["change"] or -999), reverse=True)

    saved_signals=_persist_scanner_signals(ranked[:top],now.isoformat(),source)
    return {
        "generated_at": now.isoformat(),
        "source": source,
        "feed": ALPACA_FEED,
        "full_market": source == "alpaca_sip_screener",
        "screener_error": screener_error,
        "candidate_count": len(symbols),
        "saved_signals": saved_signals,
        "results": ranked[:top],
    }



DB_PATH = BASE_DIR / "backtest_results.sqlite3"
NY = ZoneInfo("America/New_York")

def _db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS backtest_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        months INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        universe_size INTEGER,
        event_count INTEGER,
        signal_count INTEGER,
        win1_count INTEGER,
        win2_count INTEGER,
        stop_count INTEGER,
        false_negative_count INTEGER,
        avg_return_pct REAL,
        median_return_pct REAL,
        avg_r REAL,
        max_drawdown_pct REAL,
        precision_pct REAL,
        recall_pct REAL,
        notes TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS backtest_events(
        run_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        score REAL,
        signaled INTEGER,
        explosive INTEGER,
        gap_pct REAL,
        rvol_open REAL,
        news_count INTEGER,
        entry REAL,
        stop REAL,
        target1 REAL,
        target2 REAL,
        hit1 INTEGER,
        hit2 INTEGER,
        stopped INTEGER,
        close_return_pct REAL,
        mfe_pct REAL,
        mae_pct REAL,
        result_r REAL,
        reason TEXT
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS live_signals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        score REAL,
        entry REAL NOT NULL,
        stop REAL,
        target1 REAL,
        target2 REAL,
        source TEXT,
        catalyst TEXT,
        rvol REAL,
        gap_pct REAL,
        status TEXT NOT NULL DEFAULT 'open',
        last_price REAL,
        last_checked_at TEXT,
        hit1 INTEGER NOT NULL DEFAULT 0,
        hit2 INTEGER NOT NULL DEFAULT 0,
        stopped INTEGER NOT NULL DEFAULT 0,
        max_return_pct REAL,
        min_return_pct REAL,
        current_return_pct REAL,
        result_r REAL,
        UNIQUE(signal_date,symbol,signal_type)
    )""")
    # Backward-compatible schema upgrades for rolling 5Y learning features.
    existing={r["name"] for r in con.execute("PRAGMA table_info(backtest_events)")}
    upgrades={
        "rolling5y_return_pct":"REAL",
        "rolling5y_cagr_pct":"REAL",
        "rolling5y_volatility":"REAL",
        "rolling5y_max_dd":"REAL",
        "rolling5y_avg_gap":"REAL",
        "rolling5y_gap10_rate":"REAL",
        "rolling5y_explosion_rate":"REAL",
        "rolling5y_above_ma200":"INTEGER"
    }
    for col,typ in upgrades.items():
        if col not in existing:
            con.execute(f"ALTER TABLE backtest_events ADD COLUMN {col} {typ}")
    con.commit()
    return con

async def _get_assets_all(client):
    # No status filter: keep inactive/delisted assets where Alpaca still returns them,
    # reducing (not eliminating) survivorship bias.
    r = await client.get(
        "https://paper-api.alpaca.markets/v2/assets",
        headers=_alpaca_headers(),
        params={"asset_class":"us_equity"},
    )
    if r.status_code >= 400:
        raise RuntimeError(f"Assets API {r.status_code}: {r.text[:200]}")
    assets = r.json()
    allowed = {"NASDAQ","NYSE","AMEX","ARCA","NYSEARCA","BATS"}
    out = []
    for a in assets:
        s = (a.get("symbol") or "").upper().strip()
        ex = (a.get("exchange") or "").upper()
        if not s or ex not in allowed:
            continue
        # avoid obviously non-common symbols that create excessive noise
        if len(s) > 6 or "/" in s or "." in s:
            continue
        out.append(s)
    return sorted(set(out))

async def _fetch_multi_daily(client, symbols, start, end, feed):
    """Fetch daily bars for a batch and paginate fully."""
    url = "https://data.alpaca.markets/v2/stocks/bars"
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": start,
        "end": end,
        "limit": 10000,
        "adjustment": "split",
        "feed": feed,
        "sort": "asc",
    }
    out = {s: [] for s in symbols}
    token = None
    pages = 0
    while True:
        if token:
            params["page_token"] = token
        j = await _alpaca_json(client, url, params)
        bars = j.get("bars") or {}
        for s, arr in bars.items():
            if s in out:
                out[s].extend(arr or [])
        token = j.get("next_page_token")
        pages += 1
        if not token or pages > 200:
            break
    return out

async def _fetch_minute_window(client, symbol, date_str, feed):
    # Pull from 04:00 through 16:00 New York for one symbol-day.
    day = datetime.fromisoformat(date_str).date()
    start_local = datetime.combine(day, dtime(4,0), NY)
    end_local = datetime.combine(day, dtime(16,1), NY)
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {
        "timeframe":"1Min",
        "start":start_local.astimezone(timezone.utc).isoformat(),
        "end":end_local.astimezone(timezone.utc).isoformat(),
        "limit":10000,
        "adjustment":"split",
        "feed":feed,
        "sort":"asc",
    }
    try:
        j = await _alpaca_json(client, url, params)
        return j.get("bars") or []
    except Exception:
        return []

async def _fetch_news_window(client, symbol, date_str):
    day = datetime.fromisoformat(date_str).date()
    # Catalyst window: previous session evening through 09:45 ET.
    start_local = datetime.combine(day - timedelta(days=1), dtime(16,0), NY)
    end_local = datetime.combine(day, dtime(9,45), NY)
    params = {
        "symbols":symbol,
        "start":start_local.astimezone(timezone.utc).isoformat(),
        "end":end_local.astimezone(timezone.utc).isoformat(),
        "limit":50,
        "sort":"asc",
        "include_content":"false",
    }
    try:
        j = await _alpaca_json(client, "https://data.alpaca.markets/v1beta1/news", params)
        return j.get("news") or []
    except Exception:
        return []

def _bar_dt(bar):
    try:
        return datetime.fromisoformat(str(bar.get("t")).replace("Z","+00:00")).astimezone(NY)
    except Exception:
        return None

def _sum_volume(bars, start_t, end_t):
    total = 0.0
    for b in bars:
        dt = _bar_dt(b)
        if dt and start_t <= dt.time() < end_t:
            total += float(b.get("v") or 0)
    return total

def _bars_between(bars, start_t, end_t):
    out=[]
    for b in bars:
        dt=_bar_dt(b)
        if dt and start_t <= dt.time() <= end_t:
            out.append(b)
    return out


def _rolling_profile_from_daily(bars, idx, lookback_days=1260):
    """Point-in-time long-history profile ending strictly before bars[idx]."""
    hist=bars[max(0,idx-lookback_days):idx]
    if len(hist)<60:
        return None

    closes=[float(b.get("c") or 0) for b in hist if float(b.get("c") or 0)>0]
    if len(closes)<60:
        return None
    highs=[float(b.get("h") or 0) for b in hist if float(b.get("h") or 0)>0]
    lows=[float(b.get("l") or 0) for b in hist if float(b.get("l") or 0)>0]

    first,last=closes[0],closes[-1]
    years=max(len(closes)/252.0,0.25)
    total=(last/first-1)*100 if first else None
    cagr=((last/first)**(1/years)-1)*100 if first and last else None

    # realized annualized volatility
    rets=[]
    for a,b in zip(closes[:-1],closes[1:]):
        if a>0 and b>0: rets.append(b/a-1)
    vol=statistics.pstdev(rets)*(252**0.5)*100 if len(rets)>1 else None
    maxdd=_max_drawdown_from_closes(closes)

    # point-in-time gap and explosion tendencies
    gaps=[]
    gap10=0
    explosions=0
    prev=None
    valid_days=0
    for b in hist:
        o=float(b.get("o") or 0);h=float(b.get("h") or 0);c=float(b.get("c") or 0)
        if c<=0: continue
        valid_days+=1
        if prev and o>0:
            g=(o/prev-1)*100
            gaps.append(abs(g))
            if abs(g)>=10: gap10+=1
        if o>0 and h>0 and (h/o-1)*100>=15:
            explosions+=1
        prev=c

    ma200=sum(closes[-200:])/200 if len(closes)>=200 else None
    return {
        "return_pct": total,
        "cagr_pct": cagr,
        "volatility": vol,
        "max_dd": maxdd,
        "avg_gap": (sum(gaps)/len(gaps)) if gaps else None,
        "gap10_rate": gap10/max(1,len(gaps))*100,
        "explosion_rate": explosions/max(1,valid_days)*100,
        "above_ma200": (1 if last>ma200 else 0) if ma200 else None,
    }

def _rolling5y_adjustment(p):
    """Small bounded adjustment. Historical validation decides if it deserves to remain."""
    if not p:
        return 0.0, []
    pts=0.0; why=[]
    vol=p.get("volatility")
    exp=p.get("explosion_rate")
    gap=p.get("avg_gap")
    above=p.get("above_ma200")
    dd=p.get("max_dd")

    # Favor demonstrated capacity for movement, but penalize extreme chaos.
    if exp is not None:
        if exp>=0.8: pts+=4; why.append("history_explosive")
        elif exp>=0.3: pts+=2
    if gap is not None:
        if 1.5<=gap<=4.5: pts+=3; why.append("gap_profile")
        elif gap>7: pts-=2; why.append("gap_too_wild")
    if vol is not None:
        if 35<=vol<=90: pts+=3; why.append("volatility_fit")
        elif vol>130: pts-=4; why.append("volatility_extreme")
        elif vol<18: pts-=2
    if above==1: pts+=2; why.append("above_ma200")
    if dd is not None and dd<-85: pts-=2; why.append("deep_drawdown_history")
    return max(-8,min(10,pts)), why

def _historical_signal(event, minute_bars, news, avg_daily_vol):
    """Point-in-time score using only information available by 09:45 ET."""
    pre = _bars_between(minute_bars, dtime(4,0), dtime(9,29))
    first15 = _bars_between(minute_bars, dtime(9,30), dtime(9,45))
    if not first15:
        return None

    entry = float(first15[-1].get("c") or 0)
    if entry <= 0:
        return None

    pre_high = max([float(b.get("h") or 0) for b in pre], default=None)
    pre_low = min([float(b.get("l") or 0) for b in pre if float(b.get("l") or 0)>0], default=None)
    pre_vol = sum(float(b.get("v") or 0) for b in pre)
    open_vol = sum(float(b.get("v") or 0) for b in first15)

    # Expected 15-minute regular-session volume as a simple baseline from avg daily volume.
    expected_15 = (avg_daily_vol / 26.0) if avg_daily_vol else None
    rvol_open = (open_vol / expected_15) if expected_15 else None

    # 09:30-09:45 VWAP
    pv=vol=0.0
    for b in first15:
        v=float(b.get("v") or 0)
        tp=(float(b.get("h") or 0)+float(b.get("l") or 0)+float(b.get("c") or 0))/3
        pv += tp*v; vol += v
    vwap = pv/vol if vol else None

    gap = event["gap_pct"]
    score=0.0
    reasons=[]

    # Gap / momentum (15)
    if gap is not None:
        if 3 <= gap <= 25:
            score += min(15, 6 + (gap-3)*0.45)
            reasons.append("gap")
        elif gap > 25:
            score += 10
            reasons.append("gap_extreme")

    # Opening RVOL (20)
    if rvol_open is not None:
        score += 20*_clamp((rvol_open-1)/5)
        if rvol_open >= 2: reasons.append("rvol")

    # Catalyst/news (20)
    if news:
        score += min(20, 10 + 3*min(len(news),3))
        reasons.append("news")

    # Premarket participation (10)
    if avg_daily_vol and pre_vol:
        pvr = pre_vol/avg_daily_vol
        score += 10*_clamp(pvr/0.12)
        if pvr >= 0.03: reasons.append("premarket_volume")

    # Structure (20)
    if vwap and entry > vwap:
        score += 8; reasons.append("above_vwap")
    if pre_high and entry > pre_high:
        score += 8; reasons.append("break_pm_high")
    elif pre_high and entry >= pre_high*0.99:
        score += 4
    if pre_low and entry < pre_low:
        score -= 10; reasons.append("below_pm_low")

    # Liquidity/tradability (15)
    if avg_daily_vol:
        if avg_daily_vol >= 2_000_000: score += 10
        elif avg_daily_vol >= 500_000: score += 7
        elif avg_daily_vol >= 100_000: score += 3
    if 2 <= entry <= 100: score += 5
    elif entry < 1: score -= 10

    score=max(0,min(100,score))

    # Stop under VWAP / PM low, constrained to avoid absurdly wide stops.
    candidates=[x for x in [vwap, pre_low] if x and x < entry]
    structure_stop=max(candidates) if candidates else entry*0.94
    stop=min(entry*0.985, structure_stop*0.995)
    min_risk=max(entry-stop, entry*0.02)
    stop=entry-min_risk
    target1=entry+1.5*min_risk
    target2=entry+2.5*min_risk

    return {
        "score":round(score,2),"entry":entry,"stop":stop,"target1":target1,"target2":target2,
        "rvol_open":rvol_open,"vwap":vwap,"pre_high":pre_high,"pre_low":pre_low,
        "reason":",".join(reasons)
    }

def _evaluate_trade(minute_bars, sig):
    after = _bars_between(minute_bars, dtime(9,46), dtime(16,0))
    if not after:
        return None
    entry, stop, t1, t2 = sig["entry"], sig["stop"], sig["target1"], sig["target2"]
    risk=max(entry-stop, 1e-9)
    hit1=hit2=stopped=False
    exit_price=float(after[-1].get("c") or entry)
    result_r=(exit_price-entry)/risk

    # Conservative same-bar assumption: if stop and target both touched, count stop first.
    for b in after:
        lo=float(b.get("l") or 0); hi=float(b.get("h") or 0)
        if lo <= stop:
            stopped=True; exit_price=stop; result_r=-1.0
            break
        if not hit1 and hi >= t1:
            hit1=True
        if hi >= t2:
            hit2=True; exit_price=t2; result_r=2.5
            break

    highs=[float(b.get("h") or entry) for b in after]
    lows=[float(b.get("l") or entry) for b in after]
    mfe=(max(highs)-entry)/entry*100 if highs else 0
    mae=(min(lows)-entry)/entry*100 if lows else 0
    close_ret=(float(after[-1].get("c") or entry)-entry)/entry*100
    return {
        "hit1":hit1,"hit2":hit2,"stopped":stopped,
        "result_r":result_r,"mfe_pct":mfe,"mae_pct":mae,"close_return_pct":close_ret
    }



@app.get("/api/learning/stock/{symbol}")
async def stock_learning(symbol: str):
    symbol=symbol.upper().strip()
    con=_db()
    run=con.execute("SELECT id,months,created_at FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        con.close()
        return {"has_data":False,"symbol":symbol}
    rows=[dict(r) for r in con.execute(
        """SELECT date,score,signaled,explosive,gap_pct,rvol_open,hit1,hit2,stopped,
                  close_return_pct,mfe_pct,mae_pct,result_r,reason
           FROM backtest_events
           WHERE run_id=? AND symbol=?
           ORDER BY date DESC""",(run["id"],symbol)
    )]
    con.close()
    signals=[r for r in rows if r["signaled"]]
    hit1=sum(1 for r in signals if r["hit1"])
    hit2=sum(1 for r in signals if r["hit2"])
    return {
        "has_data":bool(rows),
        "symbol":symbol,
        "run_id":run["id"],
        "months":run["months"],
        "events":len(rows),
        "signals":len(signals),
        "successes":hit1,
        "success_rate_pct":round(hit1/len(signals)*100,2) if signals else None,
        "target2_rate_pct":round(hit2/len(signals)*100,2) if signals else None,
        "avg_r":round(sum((r["result_r"] or 0) for r in signals)/len(signals),3) if signals else None,
        "rows":rows[:20],
    }



def _derive_live_signal_plan(item):
    price=float(item.get("price") or 0)
    if price<=0:
        return None
    low=float(item.get("day_low") or 0) if item.get("day_low") else None
    high=float(item.get("day_high") or 0) if item.get("day_high") else None
    # Keep live-tracking plan deterministic and conservative. It is a tracking baseline,
    # not a replacement for the frontend technical plan.
    stop_candidates=[price*0.97]
    if low and low < price:
        stop_candidates.append(low*0.995)
    stop=max(0.01,min(stop_candidates))
    risk=max(price-stop,price*0.02)
    t1=price+1.5*risk
    t2=price+2.5*risk
    return {"entry":price,"stop":stop,"target1":t1,"target2":t2,"risk":risk}

def _persist_scanner_signals(items, generated_at, source):
    """Persist only scanner candidates that clear a quality floor."""
    con=_db()
    created=generated_at or datetime.now(timezone.utc).isoformat()
    d=datetime.fromisoformat(created.replace("Z","+00:00")).astimezone(NY).date().isoformat()
    saved=0
    for x in items:
        score=float(x.get("score") or 0)
        rvol=x.get("rvol")
        news=int(x.get("news_count") or 0)
        # A live signal must be stronger than a mere watchlist candidate.
        qualifies=(score>=85 and ((rvol is not None and float(rvol)>=1.5) or news>0))
        if not qualifies:
            continue
        plan=_derive_live_signal_plan(x)
        if not plan:
            continue
        try:
            con.execute("""INSERT OR IGNORE INTO live_signals(
                created_at,signal_date,symbol,signal_type,score,entry,stop,target1,target2,
                source,catalyst,rvol,gap_pct,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                created,d,x.get("ticker"),"scanner",score,plan["entry"],plan["stop"],plan["target1"],plan["target2"],
                source,x.get("catalyst"),float(rvol) if rvol is not None else None,float(x.get("change")) if x.get("change") is not None else None,"open"
            ))
            saved += con.total_changes > 0
        except Exception:
            pass
    con.commit();con.close()
    return saved

async def _latest_price_for_signal(client, symbol):
    if ALPACA_KEY and ALPACA_SECRET:
        try:
            _,snap=await _fetch_snapshot(client,symbol)
            p=(snap.get("latestTrade") or {}).get("p") or (snap.get("minuteBar") or {}).get("c") or (snap.get("dailyBar") or {}).get("c")
            if p:return float(p)
        except Exception:
            pass
    try:
        y=await _yahoo_stock_bundle(client,symbol,"1D")
        q=y.get("quote") or {}
        if q.get("price"):return float(q["price"])
    except Exception:
        pass
    return None

async def _bars_since_signal(client, symbol, signal_date):
    start=(datetime.fromisoformat(signal_date).date()-timedelta(days=1)).isoformat()
    end=(datetime.now(NY).date()+timedelta(days=1)).isoformat()
    if ALPACA_KEY and ALPACA_SECRET:
        try:
            j=await _alpaca_json(client,f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",{
                "timeframe":"1Day","start":start,"end":end,"limit":1000,"adjustment":"split","feed":ALPACA_FEED,"sort":"asc"
            })
            arr=j.get("bars") or []
            if arr:return arr
        except Exception:
            pass
    try:
        y=await _yahoo_stock_bundle(client,symbol,"1M")
        out=[]
        for r in y.get("bars") or []:
            if str(r.get("d",""))[:10]>=signal_date:
                out.append({"o":r.get("o"),"h":r.get("h"),"l":r.get("l"),"c":r.get("v"),"v":r.get("volume"),"t":r.get("d")})
        return out
    except Exception:
        return []

async def _refresh_live_signal_rows(rows):
    if not rows:
        return []
    updated=[]
    async with httpx.AsyncClient(timeout=20) as client:
        for row in rows:
            r=dict(row)
            price=await _latest_price_for_signal(client,r["symbol"])
            bars=await _bars_since_signal(client,r["symbol"],r["signal_date"])
            highs=[float(b.get("h") or 0) for b in bars if b.get("h")]
            lows=[float(b.get("l") or 0) for b in bars if b.get("l")]
            entry=float(r["entry"] or 0)
            stop=float(r["stop"] or 0) if r["stop"] else None
            t1=float(r["target1"] or 0) if r["target1"] else None
            t2=float(r["target2"] or 0) if r["target2"] else None
            hit1=bool(r["hit1"]);hit2=bool(r["hit2"]);stopped=bool(r["stopped"])
            status=r["status"]
            if highs:
                maxp=max(highs)
                if t1 and maxp>=t1:hit1=True
                if t2 and maxp>=t2:hit2=True
            if lows and stop and min(lows)<=stop and not hit1:
                stopped=True
            if hit2:status="target2"
            elif hit1:status="target1"
            elif stopped:status="stopped"
            else:status="open"
            maxret=((max(highs)/entry-1)*100) if highs and entry else None
            minret=((min(lows)/entry-1)*100) if lows and entry else None
            curret=((price/entry-1)*100) if price and entry else None
            risk=(entry-stop) if stop and entry>stop else None
            rr=((price-entry)/risk) if price and risk else None
            r.update({"last_price":price,"hit1":int(hit1),"hit2":int(hit2),"stopped":int(stopped),"status":status,
                      "max_return_pct":maxret,"min_return_pct":minret,"current_return_pct":curret,"result_r":rr,
                      "last_checked_at":datetime.now(timezone.utc).isoformat()})
            updated.append(r)
    return updated

async def _update_live_signals():
    con=_db();rows=con.execute("SELECT * FROM live_signals ORDER BY created_at DESC").fetchall();con.close()
    updated=await _refresh_live_signal_rows(rows)
    if updated:
        con=_db()
        for r in updated:
            con.execute("""UPDATE live_signals SET last_price=?,last_checked_at=?,hit1=?,hit2=?,stopped=?,status=?,
                max_return_pct=?,min_return_pct=?,current_return_pct=?,result_r=? WHERE id=?""",(
                r.get("last_price"),r.get("last_checked_at"),r.get("hit1"),r.get("hit2"),r.get("stopped"),r.get("status"),
                r.get("max_return_pct"),r.get("min_return_pct"),r.get("current_return_pct"),r.get("result_r"),r["id"]
            ))
        con.commit();con.close()
    return updated


@app.post("/api/live-signals/confirm")
async def confirm_live_signal(
    symbol: str,
    score: float,
    entry: float,
    stop: float,
    target1: float,
    target2: float,
    source: str = "technical_confirmation",
):
    if entry<=0 or stop<=0 or target1<=0 or target2<=0:
        raise HTTPException(400,"Invalid trade plan")
    symbol=symbol.upper().strip()
    now=datetime.now(timezone.utc)
    d=now.astimezone(NY).date().isoformat()
    con=_db()
    con.execute("""INSERT OR IGNORE INTO live_signals(
        created_at,signal_date,symbol,signal_type,score,entry,stop,target1,target2,source,status
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(
        now.isoformat(),d,symbol,"technical",float(score),float(entry),float(stop),float(target1),float(target2),source,"open"
    ))
    con.commit()
    row=con.execute("SELECT * FROM live_signals WHERE signal_date=? AND symbol=? AND signal_type='technical'",(d,symbol)).fetchone()
    con.close()
    return {"ok":True,"signal":dict(row) if row else None}

@app.post("/api/live-signals/refresh")
async def refresh_live_signals():
    rows=await _update_live_signals()
    return {"ok":True,"updated":len(rows),"generated_at":datetime.now(timezone.utc).isoformat()}

@app.get("/api/live-signals/summary")
async def live_signals_summary(refresh: bool = Query(True)):
    if refresh:
        try: await _update_live_signals()
        except Exception: pass
    con=_db();rows=[dict(r) for r in con.execute("SELECT * FROM live_signals ORDER BY created_at DESC").fetchall()];con.close()
    now=datetime.now(NY).date()
    def metrics(days):
        cutoff=now-timedelta(days=days-1)
        arr=[r for r in rows if datetime.fromisoformat(r["signal_date"]).date()>=cutoff]
        n=len(arr);wins=sum(1 for r in arr if r["hit1"]);t2=sum(1 for r in arr if r["hit2"]);stops=sum(1 for r in arr if r["stopped"])
        closed=[r for r in arr if r.get("result_r") is not None]
        avg_r=sum(float(r["result_r"] or 0) for r in closed)/len(closed) if closed else None
        return {"signals":n,"wins":wins,"hit1_pct":round(wins/n*100,2) if n else None,"hit2_pct":round(t2/n*100,2) if n else None,
                "stops":stops,"stop_pct":round(stops/n*100,2) if n else None,"avg_r":round(avg_r,3) if avg_r is not None else None}
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"day":metrics(1),"week":metrics(7),"month":metrics(30),"recent":rows[:50]}

@app.get("/api/strategy/health")
async def strategy_health():
    """
    Compares the newest portion of the latest backtest with the preceding portion.
    This is a drift/health monitor, not a promise of future performance.
    """
    con=_db()
    run=con.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        con.close()
        return {
            "has_data":False,
            "status":"unknown",
            "status_he":"אין עדיין בדיקה היסטורית",
            "needs_refresh":True,
            "recommendations":["הרץ בדיקה היסטורית של 6–12 חודשים כדי ליצור קו בסיס."]
        }
    run=dict(run)
    rows=[dict(r) for r in con.execute(
        """SELECT date,score,signaled,hit1,hit2,stopped,result_r,close_return_pct,rvol_open,gap_pct
           FROM backtest_events WHERE run_id=? AND signaled=1 ORDER BY date ASC""",(run["id"],)
    )]
    con.close()

    created=datetime.fromisoformat(run["created_at"].replace("Z","+00:00"))
    age_days=max(0,(datetime.now(timezone.utc)-created.astimezone(timezone.utc)).days)
    needs_refresh=age_days>=7

    def metrics(arr):
        n=len(arr)
        if not n:
            return {"n":0,"hit1":0,"hit2":0,"avg_r":0,"avg_ret":0,"stops":0}
        return {
            "n":n,
            "hit1":round(sum(1 for x in arr if x["hit1"])/n*100,2),
            "hit2":round(sum(1 for x in arr if x["hit2"])/n*100,2),
            "avg_r":round(sum(float(x["result_r"] or 0) for x in arr)/n,3),
            "avg_ret":round(sum(float(x["close_return_pct"] or 0) for x in arr)/n,3),
            "stops":round(sum(1 for x in arr if x["stopped"])/n*100,2),
        }

    n=len(rows)
    chunk=max(10,min(60,n//3 if n>=30 else n//2))
    recent=rows[-chunk:] if chunk else []
    previous=rows[-2*chunk:-chunk] if chunk and len(rows)>=2*chunk else rows[:-chunk]
    mr=metrics(recent); mp=metrics(previous)

    delta_hit1=round(mr["hit1"]-mp["hit1"],2) if mp["n"] else None
    delta_r=round(mr["avg_r"]-mp["avg_r"],3) if mp["n"] else None

    status="healthy"; status_he="השיטה יציבה"
    reasons=[]
    if mr["n"]<10:
        status="insufficient"; status_he="אין מספיק נתונים עדכניים"
        reasons.append("המדגם האחרון קטן מדי להסקת מסקנות.")
    elif mr["avg_r"]<=0 or mr["hit1"]<40:
        status="weak"; status_he="ביצועי השיטה נחלשו"
        reasons.append("התקופה האחרונה מציגה Expectancy לא חיובי או אחוז פגיעה נמוך.")
    elif delta_hit1 is not None and (delta_hit1<=-12 or (delta_r is not None and delta_r<=-0.35)):
        status="watch"; status_he="נראית ירידה בביצועים"
        reasons.append("הביצועים האחרונים חלשים משמעותית מהתקופה שקדמה להם.")
    elif mr["hit1"]>=55 and mr["avg_r"]>0:
        status="healthy"; status_he="השיטה יציבה"
        reasons.append("התקופה האחרונה שומרת על אחוז הצלחה ו-Expectancy חיובי.")

    recs=[]
    if needs_refresh:
        recs.append("הבדיקה האחרונה ישנה משבוע — מומלץ להריץ Backtest חדש לפני שינוי משקלים.")
    if mr["stops"]>55:
        recs.append("שיעור עצירות ההפסד גבוה; בדוק סינון RVOL, מרחק כניסה ו-VWAP.")
    if mr["hit2"]<20 and mr["hit1"]>=45:
        recs.append("יעד 2 מושג מעט; בדוק מימוש חלקי ביעד 1 ו-Trailing Stop במקום יעד קשיח.")
    if mr["hit1"]<45:
        recs.append("בדוק העלאת סף הציון והחמרת דרישת קטליזטור/מחזור.")
    if delta_hit1 is not None and delta_hit1>10 and mr["avg_r"]>0:
        recs.append("התקופה האחרונה השתפרה; אל תשנה משקלים לפני אימות Out-of-Sample נוסף.")
    if not recs:
        recs.append("אין כרגע סימן ברור שמצדיק שינוי בשיטה; המשך לצבור מדגם.")

    return {
        "has_data":True,
        "run_id":run["id"],
        "run_created_at":run["created_at"],
        "backtest_age_days":age_days,
        "needs_refresh":needs_refresh,
        "status":status,
        "status_he":status_he,
        "reasons":reasons,
        "recent":mr,
        "previous":mp,
        "delta_hit1_pct_points":delta_hit1,
        "delta_expectancy_r":delta_r,
        "recommendations":recs,
    }

@app.get("/api/learning/summary")
async def learning_summary():
    con=_db()
    run=con.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run:
        con.close()
        return {"has_data":False}

    run=dict(run)
    events=[dict(r) for r in con.execute(
        """SELECT * FROM backtest_events
           WHERE run_id=? AND signaled=1
           ORDER BY date DESC, score DESC LIMIT 20""",(run["id"],)
    )]

    # Score-bucket statistics for learning.
    buckets=[]
    ranges=[(70,79),(80,84),(85,89),(90,100)]
    for lo,hi in ranges:
        row=con.execute(
            """SELECT COUNT(*) n,
                      SUM(CASE WHEN hit1=1 THEN 1 ELSE 0 END) hit1,
                      SUM(CASE WHEN hit2=1 THEN 1 ELSE 0 END) hit2,
                      AVG(result_r) avg_r,
                      AVG(close_return_pct) avg_ret
               FROM backtest_events
               WHERE run_id=? AND score>=? AND score<=?""",
            (run["id"],lo,hi)
        ).fetchone()
        n=row["n"] or 0
        buckets.append({
            "bucket":f"{lo}-{hi}",
            "signals":n,
            "target1_pct":round((row["hit1"] or 0)/n*100,2) if n else 0,
            "target2_pct":round((row["hit2"] or 0)/n*100,2) if n else 0,
            "avg_r":round(row["avg_r"] or 0,3),
            "avg_return_pct":round(row["avg_ret"] or 0,3),
        })

    # Learn whether historical-profile features correlate with better outcomes.
    feature_specs=[
        ("volatility_35_90","rolling5y_volatility>=35 AND rolling5y_volatility<=90"),
        ("high_explosion_history","rolling5y_explosion_rate>=0.8"),
        ("gap_profile_1_5_4_5","rolling5y_avg_gap>=1.5 AND rolling5y_avg_gap<=4.5"),
        ("above_ma200","rolling5y_above_ma200=1"),
        ("extreme_volatility","rolling5y_volatility>130"),
        ("deep_drawdown","rolling5y_max_dd<-85"),
    ]
    feature_learning=[]
    for name,where in feature_specs:
        row=con.execute(f"""SELECT COUNT(*) n,
                    SUM(CASE WHEN hit1=1 THEN 1 ELSE 0 END) hit1,
                    AVG(result_r) avg_r,
                    AVG(close_return_pct) avg_ret
             FROM backtest_events WHERE run_id=? AND signaled=1 AND {where}""",(run["id"],)).fetchone()
        n=row["n"] or 0
        feature_learning.append({
            "feature":name,
            "signals":n,
            "success_pct":round((row["hit1"] or 0)/n*100,2) if n else 0,
            "avg_r":round(row["avg_r"] or 0,3),
            "avg_return_pct":round(row["avg_ret"] or 0,3),
        })
    con.close()
    signals=run["signal_count"] or 0
    success=run["win1_count"] or 0
    success2=run["win2_count"] or 0
    return {
        "has_data":True,
        "run_id":run["id"],
        "created_at":run["created_at"],
        "months":run["months"],
        "universe_size":run["universe_size"] or 0,
        "events_tested":run["event_count"] or 0,
        "signals":signals,
        "correct_target1":success,
        "correct_target2":success2,
        "stops":run["stop_count"] or 0,
        "success_rate_pct":round(success/signals*100,2) if signals else 0,
        "target2_rate_pct":round(success2/signals*100,2) if signals else 0,
        "false_positive_pct":round((signals-success)/signals*100,2) if signals else 0,
        "recall_pct":round(run["recall_pct"] or 0,2),
        "expectancy_r":round(run["avg_r"] or 0,3),
        "median_return_pct":round(run["median_return_pct"] or 0,3),
        "false_negatives":run["false_negative_count"] or 0,
        "buckets":buckets,
        "recent_signals":events,
        "feature_learning":feature_learning,
        "five_year_context":{"enabled":True,"note":"Per-stock 5Y profile is loaded automatically. It is not injected into historical signal scoring unless computed point-in-time before each event."},
    }

@app.get("/api/backtest/runs")
async def backtest_runs(limit: int = 10):
    con=_db()
    rows=[dict(r) for r in con.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?",(max(1,min(limit,50)),))]
    con.close()
    return {"runs":rows}

@app.get("/api/backtest/events/{run_id}")
async def backtest_events(run_id: int, limit: int = 200):
    con=_db()
    rows=[dict(r) for r in con.execute(
        "SELECT * FROM backtest_events WHERE run_id=? ORDER BY date DESC, score DESC LIMIT ?",
        (run_id,max(1,min(limit,1000)))
    )]
    con.close()
    return {"events":rows}

@app.post("/api/backtest/day")
async def run_day_backtest(
    months: int = 6,
    signal_threshold: float = 80,
    max_symbols: int = 0,
    feed: str | None = None,
):
    """
    Historical walk-forward-ish validation for the day strategy.
    Uses only data available by 09:45 ET for the score.
    Outcome is measured after 09:45 through the same-day close.

    IMPORTANT:
    - Full US-equity universe can be a large download and depends on the user's market-data plan.
    - The current Alpaca assets list reduces but cannot guarantee elimination of survivorship bias.
    """
    if not (ALPACA_KEY and ALPACA_SECRET):
        raise HTTPException(503, "Alpaca is not configured")
    months=max(1,min(months,12))
    feed=(feed or ALPACA_FEED).lower()
    if feed not in {"iex","sip","delayed_sip"}: feed=ALPACA_FEED

    end_day=datetime.now(NY).date()
    start_day=end_day-timedelta(days=int(months*30.44))
    warmup=start_day-timedelta(days=45)

    async with httpx.AsyncClient(timeout=60) as client:
        universe=await _get_assets_all(client)
        if max_symbols and max_symbols>0:
            universe=universe[:max_symbols]

        # Pass 1: daily bars across the entire universe.
        all_daily={}
        chunk_size=100
        for i in range(0,len(universe),chunk_size):
            chunk=universe[i:i+chunk_size]
            batch=await _fetch_multi_daily(client,chunk,warmup.isoformat(),end_day.isoformat(),feed)
            all_daily.update(batch)

        # Build candidate symbol-days without looking at future intraday data.
        # Also include hindsight "explosive" outcomes solely to measure false negatives/recall.
        events={}
        for s,bars in all_daily.items():
            bars=sorted(bars,key=lambda b:str(b.get("t")))
            vols=[]
            prev_close=None
            for idx,b in enumerate(bars):
                dt=_bar_dt(b)
                if not dt: continue
                d=dt.date()
                vol=float(b.get("v") or 0)
                op=float(b.get("o") or 0)
                hi=float(b.get("h") or 0)
                cl=float(b.get("c") or 0)
                avg_vol=(sum(vols[-20:])/len(vols[-20:])) if vols[-20:] else None
                if d>=start_day and d<=end_day and prev_close and op>0:
                    gap=(op/prev_close-1)*100
                    explosive=((hi/op-1)*100 >= 15) if hi>0 else False
                    known_candidate=(
                        gap>=3 and
                        prev_close>=1 and
                        (avg_vol or 0)>=100_000 and
                        prev_close*(avg_vol or 0)>=1_000_000
                    )
                    # Outcome-only inclusion is not used to award score; it lets us estimate missed explosions.
                    if known_candidate or explosive:
                        profile=_rolling_profile_from_daily(bars,idx)
                        events[(s,d.isoformat())]={
                            "symbol":s,"date":d.isoformat(),"gap_pct":gap,
                            "explosive":explosive,"avg_daily_vol":avg_vol or 0,
                            "rolling5y":profile,
                        }
                vols.append(vol)
                if cl>0: prev_close=cl

        evaluated=[]
        # Pass 2: minute/news only for relevant symbol-days.
        # This keeps a 6-12 month whole-market backtest tractable.
        sem=asyncio.Semaphore(8)
        async def eval_one(ev):
            async with sem:
                bars_task=asyncio.create_task(_fetch_minute_window(client,ev["symbol"],ev["date"],feed))
                news_task=asyncio.create_task(_fetch_news_window(client,ev["symbol"],ev["date"]))
                mins,news=await asyncio.gather(bars_task,news_task)
                sig=_historical_signal(ev,mins,news,ev["avg_daily_vol"])
                if not sig:
                    return None
                adj,adj_why=_rolling5y_adjustment(ev.get("rolling5y"))
                sig["base_score"]=sig["score"]
                sig["rolling5y_adjustment"]=adj
                sig["score"]=round(max(0,min(100,sig["score"]+adj)),2)
                if adj_why:
                    sig["reason"]=(sig.get("reason","")+","+",".join(adj_why)).strip(",")
                trade=_evaluate_trade(mins,sig)
                if not trade:
                    return None
                signaled=sig["score"]>=signal_threshold
                return {**ev,**sig,**trade,"signaled":signaled,"news_count":len(news)}

        # Process in manageable waves.
        evlist=list(events.values())
        for i in range(0,len(evlist),100):
            wave=await asyncio.gather(*[eval_one(x) for x in evlist[i:i+100]])
            evaluated.extend([x for x in wave if x])

    signals=[x for x in evaluated if x["signaled"]]
    wins1=[x for x in signals if x["hit1"]]
    wins2=[x for x in signals if x["hit2"]]
    stops=[x for x in signals if x["stopped"]]
    explosive=[x for x in evaluated if x["explosive"]]
    missed=[x for x in explosive if not x["signaled"]]

    precision=(len(wins1)/len(signals)*100) if signals else 0
    recall=((len(explosive)-len(missed))/len(explosive)*100) if explosive else 0
    returns=[x["close_return_pct"] for x in signals]
    rs=[x["result_r"] for x in signals]
    maes=[x["mae_pct"] for x in signals]

    con=_db()
    cur=con.execute("""INSERT INTO backtest_runs(
        created_at,months,start_date,end_date,universe_size,event_count,signal_count,
        win1_count,win2_count,stop_count,false_negative_count,avg_return_pct,
        median_return_pct,avg_r,max_drawdown_pct,precision_pct,recall_pct,notes
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        datetime.now(timezone.utc).isoformat(),months,start_day.isoformat(),end_day.isoformat(),
        len(universe),len(evaluated),len(signals),len(wins1),len(wins2),len(stops),len(missed),
        (sum(returns)/len(returns) if returns else 0),
        (statistics.median(returns) if returns else 0),
        (sum(rs)/len(rs) if rs else 0),
        (min(maes) if maes else 0),
        precision,recall,
        f"signal_threshold={signal_threshold}; feed={feed}; explosive=intraday high >=15% above open; entry=09:45 ET"
    ))
    run_id=cur.lastrowid
    for x in evaluated:
        con.execute("""INSERT INTO backtest_events(
            run_id,date,symbol,score,signaled,explosive,gap_pct,rvol_open,news_count,
            entry,stop,target1,target2,hit1,hit2,stopped,close_return_pct,mfe_pct,mae_pct,result_r,reason,
            rolling5y_return_pct,rolling5y_cagr_pct,rolling5y_volatility,rolling5y_max_dd,
            rolling5y_avg_gap,rolling5y_gap10_rate,rolling5y_explosion_rate,rolling5y_above_ma200
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            run_id,x["date"],x["symbol"],x["score"],int(x["signaled"]),int(x["explosive"]),
            x["gap_pct"],x.get("rvol_open"),x.get("news_count",0),x["entry"],x["stop"],x["target1"],x["target2"],
            int(x["hit1"]),int(x["hit2"]),int(x["stopped"]),x["close_return_pct"],x["mfe_pct"],x["mae_pct"],x["result_r"],x["reason"],
            (x.get("rolling5y") or {}).get("return_pct"),
            (x.get("rolling5y") or {}).get("cagr_pct"),
            (x.get("rolling5y") or {}).get("volatility"),
            (x.get("rolling5y") or {}).get("max_dd"),
            (x.get("rolling5y") or {}).get("avg_gap"),
            (x.get("rolling5y") or {}).get("gap10_rate"),
            (x.get("rolling5y") or {}).get("explosion_rate"),
            (x.get("rolling5y") or {}).get("above_ma200")
        ))
    con.commit();con.close()

    return {
        "run_id":run_id,
        "months":months,"start":start_day.isoformat(),"end":end_day.isoformat(),
        "universe_size":len(universe),"events_evaluated":len(evaluated),
        "signals":len(signals),"win1":len(wins1),"win2":len(wins2),"stops":len(stops),
        "success_rate_target1_pct":round(precision,2),
        "target2_rate_pct":round((len(wins2)/len(signals)*100) if signals else 0,2),
        "false_positive_pct":round(((len(signals)-len(wins1))/len(signals)*100) if signals else 0,2),
        "false_negatives":len(missed),
        "recall_explosive_pct":round(recall,2),
        "avg_close_return_pct":round((sum(returns)/len(returns) if returns else 0),3),
        "median_close_return_pct":round((statistics.median(returns) if returns else 0),3),
        "expectancy_r":round((sum(rs)/len(rs) if rs else 0),3),
        "worst_mae_pct":round((min(maes) if maes else 0),3),
        "signal_threshold":signal_threshold,
        "feed":feed,
        "methodology":{
            "entry_time":"09:45 America/New_York",
            "target1":"1.5R before stop",
            "target2":"2.5R before stop",
            "explosive_definition":"intraday high >= 15% above regular-session open",
            "point_in_time":"score uses bars/news only through 09:45 ET",
        }
    }

@app.get("/api/scanner/premarket")
async def premarket_scanner(top: int = 10, candidates: int = 50):
    """
    Current premarket scan. Uses whole-market mover/active candidates when available,
    then calculates premarket high/low/volume from 1-minute bars since 04:00 ET.
    """
    if not (ALPACA_KEY and ALPACA_SECRET):
        raise HTTPException(503,"Alpaca is not configured")
    top=max(3,min(top,20));candidates=max(top,min(candidates,60))
    now=datetime.now(NY)
    today=now.date()
    start_local=datetime.combine(today,dtime(4,0),NY)
    end_local=min(now,datetime.combine(today,dtime(9,30),NY))
    if end_local <= start_local:
        end_local=now

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            symbols,mover_map=await _get_market_candidates(client,candidates)
            source="alpaca_market_screener"
        except Exception:
            symbols,mover_map,_=await _alpha_fallback_candidates(client,candidates)
            source="fallback"

        sem=asyncio.Semaphore(8)
        async def one(s):
            async with sem:
                snap_s,snap=await _fetch_snapshot(client,s)
                prev=(snap.get("prevDailyBar") or {}).get("c")
                try:
                    bars=await _fetch_minute_window(client,s,today.isoformat(),ALPACA_FEED)
                except Exception:
                    bars=[]
                pre=[b for b in bars if (_bar_dt(b) and dtime(4,0)<=_bar_dt(b).time()<dtime(9,30))]
                if not pre:return None
                last=float(pre[-1].get("c") or 0)
                if not last:return None
                high=max(float(b.get("h") or 0) for b in pre)
                low=min(float(b.get("l") or last) for b in pre if float(b.get("l") or 0)>0)
                vol=sum(float(b.get("v") or 0) for b in pre)
                gap=((last/float(prev)-1)*100) if prev else None
                news=await _fetch_news_window(client,s,today.isoformat())
                score=0
                if gap is not None:
                    score += 25*_clamp((gap-2)/18)
                if vol>=1_000_000: score+=20
                elif vol>=250_000: score+=14
                elif vol>=50_000: score+=7
                if news: score+=min(25,12+4*min(len(news),3))
                if last>=2:score+=5
                if high>low and last>=low+(high-low)*0.7:score+=15
                if gap is not None and gap>80:score-=10
                return {
                    "ticker":s,"price":last,"gap":round(gap,2) if gap is not None else None,
                    "pm_high":high,"pm_low":low,"pm_volume":int(vol),"news_count":len(news),
                    "catalyst":news[-1].get("headline") if news else "ללא חדשות מאומתות בחלון הקטליזטור",
                    "score":int(max(0,min(100,round(score))))
                }
        rows=[]
        for i in range(0,len(symbols),40):
            wave=await asyncio.gather(*[one(s) for s in symbols[i:i+40]])
            rows.extend([x for x in wave if x])
    rows.sort(key=lambda x:x["score"],reverse=True)
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"source":source,"feed":ALPACA_FEED,"results":rows[:top]}

@app.get("/api/scanner/watchlist")
async def scanner_watchlist(symbols: str = "AAPL,NVDA,PLTR,RKLB,APP,TSSI,NVTS,CTRI,CRMD,POET"):
    """Backend foundation for a real-time scanner.
    Uses Alpaca snapshots for a configurable watchlist; whole-market scanning
    should use a maintained universe and a data plan that permits that workload.
    """
    if not (ALPACA_KEY and ALPACA_SECRET):
        raise HTTPException(503, "Alpaca is not configured")
    items = [s.strip().upper() for s in symbols.split(",") if s.strip()][:30]
    headers = {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }
    results = []
    async with httpx.AsyncClient(timeout=20) as client:
        for s in items:
            try:
                r = await client.get(
                    f"https://data.alpaca.markets/v2/stocks/{s}/snapshot",
                    headers=headers, params={"feed": ALPACA_FEED}
                )
                if r.status_code == 200:
                    j = r.json()
                    trade = j.get("latestTrade") or {}
                    minute = j.get("minuteBar") or {}
                    daily = j.get("dailyBar") or {}
                    prev = j.get("prevDailyBar") or {}
                    price = trade.get("p") or minute.get("c") or daily.get("c")
                    prev_close = prev.get("c")
                    change_pct = ((price / prev_close - 1) * 100) if price and prev_close else None
                    results.append({
                        "symbol": s,
                        "price": price,
                        "change_pct": change_pct,
                        "minute_volume": minute.get("v"),
                        "daily_volume": daily.get("v"),
                    })
            except Exception:
                continue
    results.sort(key=lambda x: abs(x["change_pct"] or 0), reverse=True)
    return {"feed": ALPACA_FEED, "results": results}


# STRATEGY_VALIDATION_V1
from strategy_validation import install_strategy_validation
install_strategy_validation(app)
