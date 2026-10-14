"""Independent read-only source triangulation. SEC filing presence is not news corroboration."""
import asyncio, os, re
from datetime import datetime, timezone
from urllib.parse import quote
from xml.etree import ElementTree as ET
import httpx
from fastapi import HTTPException

SEC_HEADERS={"User-Agent":os.getenv("SEC_USER_AGENT","SmartInvestmentAdvisor research admin@example.com"),"Accept":"application/json"}
def clean_symbol(s):
    s=str(s or "").upper().strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}",s):raise HTTPException(400,"Invalid ticker")
    return s

async def get_json(client,url,headers=None):
    try:
        r=await client.get(url,headers=headers,timeout=9,follow_redirects=True)
        if r.status_code==200:return r.json()
    except (httpx.HTTPError,ValueError):pass
    return None

async def sec_filings(client,symbol):
    tickers=await get_json(client,"https://www.sec.gov/files/company_tickers.json",SEC_HEADERS)
    if not isinstance(tickers,dict):return {"status":"unavailable","filings":[]}
    match=next((v for v in tickers.values() if isinstance(v,dict) and str(v.get("ticker","")).upper()==symbol),None)
    if not match:return {"status":"ticker_not_found","filings":[]}
    cik=int(match["cik_str"])
    data=await get_json(client,f"https://data.sec.gov/submissions/CIK{cik:010d}.json",SEC_HEADERS)
    if not data:return {"status":"unavailable","filings":[]}
    recent=((data.get("filings") or {}).get("recent") or {})
    forms=recent.get("form") or []
    out=[]
    for i,form in enumerate(forms):
        if form not in ("8-K","6-K","S-3","424B5","424B3","S-1","10-Q","10-K"):continue
        accession=(recent.get("accessionNumber") or [])[i]
        primary=(recent.get("primaryDocument") or [])[i]
        filed=(recent.get("filingDate") or [])[i]
        out.append({"form":form,"filed":filed,"source":"SEC EDGAR","url":f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-','')}/{quote(primary)}"})
        if len(out)>=12:break
    return {"status":"ok","cik":cik,"company":match.get("title"),"filings":out}

async def headlines(client,symbol):
    # Secondary reporting; not independently verified corporate announcements.
    url="https://news.google.com/rss/search?q="+quote(symbol+" stock when:7d")+"&hl=en-US&gl=US&ceid=US:en"
    try:
        r=await client.get(url,timeout=9,follow_redirects=True)
        if r.status_code!=200:return {"status":"unavailable","articles":[]}
        root=ET.fromstring(r.text)
        out=[]
        for item in root.findall("./channel/item")[:12]:
            out.append({"title":item.findtext("title") or "","published":item.findtext("pubDate") or "","url":item.findtext("link") or "","source":item.findtext("source") or "Google News RSS"})
        return {"status":"ok","articles":out}
    except (httpx.HTTPError,ET.ParseError):return {"status":"unavailable","articles":[]}

def install(app):
    @app.get("/api/research/news-verification/{ticker}")
    async def verify_news(ticker:str):
        symbol=clean_symbol(ticker)
        async with httpx.AsyncClient(headers={"User-Agent":"SmartInvestmentAdvisor/1.0"}) as client:
            sec,news=await asyncio.gather(sec_filings(client,symbol),headlines(client,symbol))
        return {"ticker":symbol,"checked_at":datetime.now(timezone.utc).isoformat(),"official_filings":sec,"secondary_news":news,"verified_catalyst":None,"verification_status":"requires_manual_event_matching","warning":"SEC filing existence does not prove a headline. Match event, dates, and actual filing text before asserting verification. No effect on live scoring."}
