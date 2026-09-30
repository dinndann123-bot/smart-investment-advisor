# Recovery composition: keep the stable scanner/chart APIs, but serve the last
# complete application shell.  The experimental v7 document only implemented
# the home screen, so making it canonical removed navigation, portfolio,
# long-term views and the mature chart/data lifecycle.
from app_v66 import *
import app_v66 as _scanner_core
from scanner_session_fix import install as _install_scanner_session_fix
SCANNER_SESSION_DATA_FIX=_install_scanner_session_fix(_scanner_core)
from scanner_core import install_local_scanner
from scanner_async_v67 import install_async_scanner, STRATEGY_VERSION as ASYNC_STRATEGY_VERSION
from chart_api_v7 import install_chart_api
from pathlib import Path
from fastapi import Request
from fastapi.responses import FileResponse
import asyncio
import re
import httpx

_local_scanner_engine=install_local_scanner(app)
CHART_API_V7=install_chart_api(app)

# News providers return English headlines.  Translation is presentation-only:
# market data and scanner decisions always continue to use the original payload.
_headline_translation_cache={}
_hebrew_re=re.compile(r'[\u0590-\u05ff]')

async def _translate_headline_to_hebrew(client,text,symbol):
    clean=' '.join(str(text or '').split())[:500]
    if not clean:return 'ללא כותרת'
    if _hebrew_re.search(clean):return clean
    cached=_headline_translation_cache.get(clean)
    if cached:return cached
    translated=''
    try:
        response=await client.get(
            'https://api.mymemory.translated.net/get',
            params={'q':clean,'langpair':'en|he'},
            timeout=8.0,
        )
        if response.is_success:
            candidate=str((response.json().get('responseData') or {}).get('translatedText') or '').strip()
            if _hebrew_re.search(candidate):translated=candidate
    except Exception:
        pass
    if not translated:
        translated=f'עדכון חדשות בנוגע למניית {symbol}' if symbol else 'עדכון חדשות בנוגע למניה'
    if len(_headline_translation_cache)>=2000:
        _headline_translation_cache.pop(next(iter(_headline_translation_cache)))
    _headline_translation_cache[clean]=translated
    return translated

@app.post('/api/translate/headlines')
async def translate_news_headlines(request:Request):
    try:payload=await request.json()
    except Exception:payload={}
    symbol=re.sub(r'[^A-Z0-9.\-]','',str(payload.get('symbol') or '').upper())[:12]
    headlines=payload.get('headlines') if isinstance(payload.get('headlines'),list) else []
    headlines=headlines[:20]
    async with httpx.AsyncClient(headers={'User-Agent':'SmartInvestmentAdvisor/1.0'}) as client:
        translated=await asyncio.gather(*[_translate_headline_to_hebrew(client,x,symbol) for x in headlines])
    return {'translations':translated,'language':'he','originals_preserved':True}

_old_root=next((r for r in app.routes if getattr(r,'path',None)=='/' and 'GET' in getattr(r,'methods',set())),None)
if _old_root is not None:app.router.routes.remove(_old_root)
@app.get('/',include_in_schema=False)
async def production_root():
    return FileResponse(
        Path(__file__).with_name('index.html'),
        media_type='text/html',
        headers={
            'Cache-Control':'no-store, no-cache, must-revalidate, max-age=0',
            'Pragma':'no-cache',
        },
    )

_v66_day_route=next((r for r in app.routes if getattr(r,'path',None)=='/api/scanner/day' and 'GET' in getattr(r,'methods',set())),None)
if _v66_day_route is None:raise RuntimeError('local full-market day scanner route not found')
_v66_scanner_engine=_v66_day_route.endpoint
app.router.routes.remove(_v66_day_route)
_async=install_async_scanner(app,_v66_scanner_engine)
app.add_api_route('/api/scanner/day',_async['day'],methods=['GET'],name='scanner_day_v7')
app.add_api_route('/api/scanner/day/start',_async['start'],methods=['POST'],name='scanner_day_start_v7')
app.add_api_route('/api/scanner/day/status',_async['status'],methods=['GET'],name='scanner_day_status_v7')

try:
 import learning_store
 from scheduled_learning import install_scheduled_learning
 SCHEDULED_LEARNING=install_scheduled_learning(app,_v66_scanner_engine,learning_store,ASYNC_STRATEGY_VERSION,price_fetcher=getattr(_scanner_core,'_future_prices',None))
 from timing_signals import install_timing_routes
 TIMING_SIGNALS=install_timing_routes(app,learning_store)
except Exception as _scheduled_error:
 SCHEDULED_LEARNING={'installed':False,'error':f'{type(_scheduled_error).__name__}: {_scheduled_error}'}
 TIMING_SIGNALS={'installed':False,'error':f'{type(_scheduled_error).__name__}: {_scheduled_error}'}

try:
 from missed_movers_learning import install_missed_movers_learning
 MISSED_MOVERS_LEARNING=install_missed_movers_learning(app,_scanner_core,learning_store,ASYNC_STRATEGY_VERSION)
except Exception as _missed_movers_error:
 MISSED_MOVERS_LEARNING={'installed':False,'error':f'{type(_missed_movers_error).__name__}: {_missed_movers_error}'}

try:
 from live_signals_canonical import install as _install_live_signals
 LIVE_SIGNALS_CANONICAL=_install_live_signals(app,learning_store)
except Exception as _live_signals_error:
 LIVE_SIGNALS_CANONICAL={'installed':False,'error':f'{type(_live_signals_error).__name__}: {_live_signals_error}'}

try:
 from long_daily_learning import install_long_daily_learning
 LONG_DAILY_LEARNING=install_long_daily_learning(app,learning_store,_scanner_core,quote_fetcher=CHART_API_V7['quote'])
except Exception as _long_daily_error:
 LONG_DAILY_LEARNING={'installed':False,'error':f'{type(_long_daily_error).__name__}: {_long_daily_error}'}

@app.get('/api/scanner/async-status')
async def scanner_async_status():
    return {'installed':True,'strategy_version':ASYNC_STRATEGY_VERSION,'engine':'local-full-market-predictive-shortlist-progressive-top10','live_market_source':'Alpaca','cache_scope':'last-scanner-result-only','canonical_top10_contract':True,'canonical_ui':'index.html','ui_recovery':'complete-navigation-and-data-shell','canonical_chart_api':'/api/market/chart/{symbol}','canonical_quote_api':'/api/market/quote/{symbol}','long_daily_learning':LONG_DAILY_LEARNING if 'LONG_DAILY_LEARNING' in globals() else {'installed':False},'scheduled_learning':SCHEDULED_LEARNING,'missed_movers_learning':MISSED_MOVERS_LEARNING if 'MISSED_MOVERS_LEARNING' in globals() else {'installed':False},'session_data_fix':SCANNER_SESSION_DATA_FIX,'local_scanner_core':True}

try:
 from app_tail import install_app_tail
 install_app_tail(globals())
except ImportError:
 pass

# Emit a compact, read-only snapshot of persisted validation records into Render logs.
# This lets operators verify database history without opening PostgreSQL to external IPs.
try:
    import json as _audit_json
    import learning_store as _audit_store
    from scheduled_learning import _first_regular_top10 as _audit_first_top10, _number as _audit_number

    _audit_rows = _audit_store.load(3000)
    _audit_scheduled = [r for r in _audit_rows
                        if r.get("record_type") == "scheduled_checkpoint"
                        and r.get("strategy_version") == ASYNC_STRATEGY_VERSION]
    _audit_top10 = _audit_first_top10(_audit_scheduled)

    def _audit_period(field, rows=None):
        _source = _audit_top10 if rows is None else rows
        _vals = [_audit_number(r.get(field)) for r in _source]
        _vals = [v for v in _vals if v is not None]
        return {
            "samples": len(_vals),
            "positive": sum(v > 0 for v in _vals),
            "success_pct": round(100 * sum(v > 0 for v in _vals) / len(_vals), 1) if _vals else None,
            "mean_return_pct": round(sum(_vals) / len(_vals), 3) if _vals else None,
        }

    _audit_by_trade_date = {}
    for _row in _audit_top10:
        _audit_by_trade_date.setdefault(_row.get("trade_date"), []).append(_row)
    _audit_days = []
    for _day in sorted(day for day in _audit_by_trade_date if day):
        _rows = _audit_by_trade_date[_day]
        _day15 = [_audit_number(r.get("ret15m_pct")) for r in _rows]
        _day15 = [v for v in _day15 if v is not None]
        _audit_days.append({
            "trade_date": _day,
            "first_regular_top10": len(_rows),
            "evaluated_15m": len(_day15),
            "positive_15m": sum(v > 0 for v in _day15),
            "success_15m_pct": round(100 * sum(v > 0 for v in _day15) / len(_day15), 1) if _day15 else None,
            "day": _audit_period("ret_day_pct", _rows),
            "week": _audit_period("ret_week_pct", _rows),
        })
    _audit_15m = [_audit_number(r.get("ret15m_pct")) for r in _audit_top10]
    _audit_15m = [v for v in _audit_15m if v is not None]
    _audit_long_loader = getattr(_audit_store, "load_long_daily", None)
    _audit_long_rows = _audit_long_loader(10000) if _audit_long_loader else []
    _audit_long_rows = [r for r in _audit_long_rows if r.get("record_type") == "long_daily_prediction"]
    _audit_long_done = [r for r in _audit_long_rows if r.get("forecast_closed")
                        and _audit_number(r.get("actual_return_pct")) is not None]
    _audit_long_by_day = {}
    for _row in _audit_long_rows:
        _audit_long_by_day.setdefault(_row.get("trade_date"), []).append(_row)
    _audit_detail_days = sorted(d for d in _audit_by_trade_date if d)[-3:]
    _audit_signal_details = [
        {
            "trade_date": r.get("trade_date"),
            "ticker": r.get("ticker"),
            "rank": r.get("rank"),
            "checkpoint": r.get("checkpoint"),
            "signal_time": r.get("signal_time"),
            "is_predictive_signal": r.get("is_predictive_signal"),
            "quality_tier": r.get("quality_tier"),
            "score": r.get("score"),
            "stage": r.get("stage"),
            "change_pct": r.get("change_pct"),
            "gap_pct": r.get("gap_pct"),
            "rvol": r.get("rvol"),
            "dollar_volume": r.get("dollar_volume"),
            "spread_bps": r.get("spread_bps"),
            "catalyst_present": r.get("catalyst_present"),
            "catalyst_headline": r.get("catalyst_headline"),
            "ret15m_pct": r.get("ret15m_pct"),
            "ret_day_pct": r.get("ret_day_pct"),
            "missed15m": r.get("missed15m"),
        }
        for day in _audit_detail_days for r in _audit_by_trade_date[day]
    ]
    _audit_long_detail_days = sorted(d for d in _audit_long_by_day if d)[-3:]
    _audit_long_details = [
        {
            "trade_date": r.get("trade_date"),
            "ticker": r.get("ticker"),
            "rank": r.get("rank"),
            "forecast_return_pct": r.get("forecast_return_pct"),
            "actual_return_pct": r.get("actual_return_pct"),
            "forecast_direction_correct": r.get("forecast_direction_correct"),
        }
        for day in _audit_long_detail_days for r in _audit_long_by_day[day]
    ]
    _audit_checkpoint_detail_days = sorted(r.get("trade_date") for r in _audit_scheduled if r.get("trade_date"))
    _audit_checkpoint_detail_day = _audit_checkpoint_detail_days[-1] if _audit_checkpoint_detail_days else None
    _audit_all_checkpoint_details = [
        {
            "trade_date": r.get("trade_date"),
            "ticker": r.get("ticker"),
            "rank": r.get("rank"),
            "checkpoint": r.get("checkpoint"),
            "signal_time": r.get("signal_time"),
            "score": r.get("score"),
            "quality_tier": r.get("quality_tier"),
            "stage": r.get("stage"),
            "change_pct": r.get("change_pct"),
            "gap_pct": r.get("gap_pct"),
            "rvol": r.get("rvol"),
            "dollar_volume": r.get("dollar_volume"),
            "spread_bps": r.get("spread_bps"),
            "catalyst_present": r.get("catalyst_present"),
            "catalyst_headline": r.get("catalyst_headline"),
            "ret15m_pct": r.get("ret15m_pct"),
            "ret_day_pct": r.get("ret_day_pct"),
        }
        for r in _audit_scheduled
        if r.get("trade_date") == _audit_checkpoint_detail_day
    ]
    _audit_snapshot = {
        "strategy_version": ASYNC_STRATEGY_VERSION,
        "storage": _audit_store.status(),
        "checkpoint_rows": len(_audit_scheduled),
        "trade_dates": sorted({r.get("trade_date") for r in _audit_scheduled if r.get("trade_date")}),
        "scheduled_by_day": _audit_days,
        "signal_details": _audit_signal_details,
        "all_checkpoints_latest_day": _audit_checkpoint_detail_day,
        "all_checkpoint_details": _audit_all_checkpoint_details,
        "long_daily_details": _audit_long_details,
        "first_regular_top10_rows": len(_audit_top10),
        "evaluated_15m": len(_audit_15m),
        "success_15m_pct": round(100 * sum(v > 0 for v in _audit_15m) / len(_audit_15m), 1) if _audit_15m else None,
        "day": _audit_period("ret_day_pct"),
        "week": _audit_period("ret_week_pct"),
        "month": _audit_period("ret_month_pct"),
        "long_daily_saved_rows": len(_audit_long_rows),
        "long_daily_evaluated_rows": len(_audit_long_done),
        "long_daily_direction_accuracy_pct": round(100 * sum(bool(r.get("forecast_direction_correct")) for r in _audit_long_done) / len(_audit_long_done), 1) if _audit_long_done else None,
        "long_daily_days": [{
            "trade_date": _day,
            "selected": len(_audit_long_by_day[_day]),
            "evaluated": sum(1 for r in _audit_long_by_day[_day] if r.get("forecast_closed") and _audit_number(r.get("actual_return_pct")) is not None),
            "direction_accuracy_pct": (round(100 * sum(bool(r.get("forecast_direction_correct")) for r in _audit_long_by_day[_day] if r.get("forecast_closed") and _audit_number(r.get("actual_return_pct")) is not None) / sum(1 for r in _audit_long_by_day[_day] if r.get("forecast_closed") and _audit_number(r.get("actual_return_pct")) is not None), 1) if any(r.get("forecast_closed") and _audit_number(r.get("actual_return_pct")) is not None for r in _audit_long_by_day[_day]) else None),
        } for _day in sorted(d for d in _audit_long_by_day if d)[-30:]],
    }
    print("LEARNING_AUDIT_IMPORT_SNAPSHOT " + _audit_json.dumps(_audit_snapshot, ensure_ascii=False, separators=(",", ":")), flush=True)
except Exception as _audit_error:
    print(f"LEARNING_AUDIT_IMPORT_ERROR {type(_audit_error).__name__}", flush=True)
