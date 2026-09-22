import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')

# Research checkpoints, deliberately separated so we can compare what the
# strategy knew before the open with what it knew after the first five minutes.
CHECKPOINTS={(8,0):'08:00_pre_market',(9,25):'09:25_pre_open',(9,35):'09:35_post_open'}


def install_scheduled_learning(app, scanner_engine, learning_store, strategy_version):
    state={'installed':True,'strategy_version':strategy_version,'checkpoints':list(CHECKPOINTS.values()),'last_capture':{},'last_error':None}

    async def capture(label):
        now=datetime.now(timezone.utc);ny=now.astimezone(NY);key=f'{ny.date().isoformat()}:{label}'
        if state['last_capture'].get(label)==ny.date().isoformat():return
        response=await scanner_engine(top=10,candidates=40)
        try:
            import json
            payload=json.loads(response.body.decode('utf-8')) if hasattr(response,'body') else response
        except Exception:
            payload=response if isinstance(response,dict) else {}
        rows=(payload or {}).get('results') or []
        scan_id=(payload or {}).get('scan_id') or key
        for rank,row in enumerate(rows[:10],1):
            rec={'record_type':'scheduled_checkpoint','checkpoint':label,'trade_date':ny.date().isoformat(),'signal_time':now.isoformat(),'epoch':now.timestamp(),'scan_id':scan_id,'strategy_version':(payload or {}).get('strategy_version') or strategy_version,'ticker':row.get('ticker'),'rank':rank,'signal_price':row.get('price'),'score':row.get('score'),'stage':row.get('breakout_stage'),'change_pct':row.get('change_pct'),'gap_pct':row.get('snapshot_gap_pct',row.get('premarket_gap_pct')),'rvol':row.get('rvol'),'premarket_volume':row.get('premarket_volume'),'premarket_high':row.get('premarket_high'),'premarket_low':row.get('premarket_low'),'premarket_vwap':row.get('premarket_vwap'),'distance_from_pm_high_pct':row.get('distance_from_pm_high_pct'),'distance_from_pm_vwap_pct':row.get('distance_from_pm_vwap_pct'),'minute_volume_burst':row.get('minute_volume_burst'),'move_used_pct':row.get('intraday_move_used_pct'),'range_position':row.get('current_range_position'),'gate_metrics':row.get('gate_metrics'),'learning_profile':row.get('learning_profile'),'market_timestamp':row.get('market_timestamp'),'data_feed':row.get('data_feed')}
            learning_store.upsert(rec)
        state['last_capture'][label]=ny.date().isoformat();state['last_error']=None

    async def loop():
        while True:
            try:
                ny=datetime.now(timezone.utc).astimezone(NY)
                if ny.weekday()<5:
                    label=CHECKPOINTS.get((ny.hour,ny.minute))
                    if label:await capture(label)
            except Exception as e:state['last_error']=f'{type(e).__name__}: {e}'
            await asyncio.sleep(20)

    @app.on_event('startup')
    async def _start_learning_scheduler():
        asyncio.create_task(loop())

    @app.get('/api/learning/scheduled-status')
    async def scheduled_status():return state

    return state
