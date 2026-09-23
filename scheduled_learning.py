import asyncio
import math
import statistics
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY=ZoneInfo('America/New_York')

# Research checkpoints, deliberately separated so we can compare what the
# strategy knew before the open with what it knew after the first five minutes.
CHECKPOINTS={(8,0):'08:00_pre_market',(9,25):'09:25_pre_open',(9,35):'09:35_post_open'}
HORIZONS=(1,3,5,10,15)
PERIODS={'day':24*60*60,'week':7*24*60*60,'month':30*24*60*60}
PERIOD_LABELS={'day':'יום','week':'שבוע','month':'חודש'}
MIN_VALIDATION_SAMPLES=50
MEASUREMENT_GRACE_SECONDS=70
MARKET_SAMPLE_SECONDS=300


def _number(value):
    try:
        value=float(value)
        return value if math.isfinite(value) else None
    except (TypeError,ValueError):
        return None


def _criteria(row):
    rv=_number(row.get('rvol')); burst=_number(row.get('minute_volume_burst'))
    rp=_number(row.get('current_range_position')); used=_number(row.get('intraday_move_used_pct'))
    gap=_number(row.get('snapshot_gap_pct') if row.get('snapshot_gap_pct') is not None else row.get('premarket_gap_pct'))
    change=_number(row.get('change_pct')); volume=_number(row.get('day_volume')); baseline=_number(row.get('historical_baseline_volume'))
    return [
        {'key':'stage','label':'שלב המהלך','value':row.get('breakout_stage'),'passed':row.get('breakout_stage') in {'pre_breakout','early_breakout'}},
        {'key':'rvol','label':'מחזור יחסי','value':rv,'passed':bool(row.get('rvol_reliable') and rv is not None and rv>=1.5)},
        {'key':'volume_burst','label':'האצת מחזור בדקה','value':burst,'passed':burst is not None and burst>=1.5},
        {'key':'range_position','label':'מיקום בטווח','value':rp,'passed':rp is not None and .55<=rp<=.95},
        {'key':'move_used','label':'ניצול המהלך','value':used,'passed':used is not None and used<92},
        {'key':'gap','label':'פער','value':gap,'passed':gap is not None and abs(gap)<=8},
        {'key':'liquidity','label':'נזילות','value':volume,'passed':volume is not None and baseline is not None and volume>=1000 and baseline>=1000},
        {'key':'momentum','label':'מומנטום מוקדם','value':change,'passed':change is not None and -3<=change<=8},
    ]


def install_scheduled_learning(app, scanner_engine, learning_store, strategy_version, price_fetcher=None):
    state={'installed':True,'strategy_version':strategy_version,'checkpoints':list(CHECKPOINTS.values()),'horizons_minutes':list(HORIZONS),'periods':PERIOD_LABELS,'minimum_validation_samples':MIN_VALIDATION_SAMPLES,'last_capture':{},'last_evaluation':None,'last_market_sample_epoch':0,'last_error':None}

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
        if len(rows)<10:
            state['last_error']=f'incomplete_checkpoint:{label}:rows={len(rows)}'
            return
        scan_id=(payload or {}).get('scan_id') or key
        for rank,row in enumerate(rows[:10],1):
            criteria=_criteria(row)
            rec={'record_type':'scheduled_checkpoint','checkpoint':label,'trade_date':ny.date().isoformat(),'signal_time':now.isoformat(),'epoch':now.timestamp(),'scan_id':f'{key}:{scan_id}','strategy_version':strategy_version,'engine_strategy_version':(payload or {}).get('engine_strategy_version') or (payload or {}).get('strategy_version'),'ticker':row.get('ticker'),'rank':rank,'signal_price':row.get('price'),'score':row.get('score'),'stage':row.get('breakout_stage'),'change_pct':row.get('change_pct'),'gap_pct':row.get('snapshot_gap_pct',row.get('premarket_gap_pct')),'rvol':row.get('rvol'),'premarket_volume':row.get('premarket_volume'),'premarket_high':row.get('premarket_high'),'premarket_low':row.get('premarket_low'),'premarket_vwap':row.get('premarket_vwap'),'distance_from_pm_high_pct':row.get('distance_from_pm_high_pct'),'distance_from_pm_vwap_pct':row.get('distance_from_pm_vwap_pct'),'minute_volume_burst':row.get('minute_volume_burst'),'move_used_pct':row.get('intraday_move_used_pct'),'range_position':row.get('current_range_position'),'gate_metrics':row.get('gate_metrics'),'criteria':criteria,'market_timestamp':row.get('market_timestamp'),'data_feed':row.get('data_feed'),'market_session':row.get('market_session') or (payload or {}).get('session'),'observed_peak_price':row.get('price'),'observed_trough_price':row.get('price'),'minutes_to_peak':0,'minutes_to_trough':0,'peak_observed_at':now.isoformat(),'trough_observed_at':now.isoformat()}
            learning_store.upsert(rec)
        state['last_capture'][label]=ny.date().isoformat();state['last_error']=None

    async def evaluate_due():
        if not price_fetcher:return
        now=datetime.now(timezone.utc); rows=learning_store.load(3000); due=[]; active=[]
        for rec in rows:
            if rec.get('record_type')!='scheduled_checkpoint' or rec.get('strategy_version')!=strategy_version:continue
            elapsed=now.timestamp()-float(rec.get('epoch') or 0)
            # Entry timing is an intraday parameter.  Never pretend a first
            # observation weeks later was the time of the move.
            if 0<=elapsed<=PERIODS['day']:active.append(rec)
            for minutes in HORIZONS:
                result_key=f'ret{minutes}m_pct'; missed_key=f'missed{minutes}m'
                if result_key in rec or missed_key in rec or elapsed<minutes*60:continue
                if elapsed>minutes*60+MEASUREMENT_GRACE_SECONDS:
                    rec[missed_key]=True
                    learning_store.upsert(rec)
                    continue
                due.append((rec,'minute',minutes))
            for period,seconds in PERIODS.items():
                if f'ret_{period}_pct' not in rec and elapsed>=seconds:
                    due.append((rec,'period',period))
        sample_market=bool(active) and now.timestamp()-state['last_market_sample_epoch']>=MARKET_SAMPLE_SECONDS
        targets=active if sample_market else []
        symbols=sorted({r.get('ticker') for r,_,_ in due if r.get('ticker')}|{r.get('ticker') for r in targets if r.get('ticker')})
        if not symbols:return
        prices=await price_fetcher(symbols)
        changed={}
        for rec,kind,horizon in due:
            price=_number(prices.get(rec.get('ticker'))); signal=_number(rec.get('signal_price'))
            if price is None or signal is None or signal<=0:continue
            if kind=='minute':
                rec[f'p{horizon}m']=round(price,4);rec[f'ret{horizon}m_pct']=round((price/signal-1)*100,3)
            else:
                rec[f'p_{horizon}']=round(price,4);rec[f'ret_{horizon}_pct']=round((price/signal-1)*100,3);rec[f'evaluated_{horizon}_at']=now.isoformat()
            changed[id(rec)]=rec
        if sample_market:
            for rec in targets:
                price=_number(prices.get(rec.get('ticker')));signal=_number(rec.get('signal_price'))
                if price is None or signal is None or signal<=0:continue
                elapsed_minutes=max(0,(now.timestamp()-float(rec.get('epoch') or now.timestamp()))/60)
                peak=_number(rec.get('observed_peak_price'));trough=_number(rec.get('observed_trough_price'))
                if peak is None or price>peak:
                    rec['observed_peak_price']=round(price,4);rec['minutes_to_peak']=round(elapsed_minutes,1);rec['peak_observed_at']=now.isoformat();changed[id(rec)]=rec
                if trough is None or price<trough:
                    rec['observed_trough_price']=round(price,4);rec['minutes_to_trough']=round(elapsed_minutes,1);rec['trough_observed_at']=now.isoformat();changed[id(rec)]=rec
                rec['observed_peak_return_pct']=round((float(rec.get('observed_peak_price'))/signal-1)*100,3)
                rec['observed_trough_return_pct']=round((float(rec.get('observed_trough_price'))/signal-1)*100,3)
            state['last_market_sample_epoch']=now.timestamp()
        for rec in changed.values():learning_store.upsert(rec)
        state['last_evaluation']=now.isoformat()

    def summary():
        all_rows=learning_store.load(3000)
        rows=[r for r in all_rows if r.get('record_type')=='scheduled_checkpoint' and r.get('strategy_version')==strategy_version]
        evaluated=[]
        for r in rows:
            values=[(m,_number(r.get(f'ret{m}m_pct'))) for m in HORIZONS]
            values=[x for x in values if x[1] is not None]
            if values:evaluated.append((r,values[-1][0],values[-1][1]))
        features=[]
        for key,label in [(x['key'],x['label']) for x in _criteria({})]:
            vals=[ret for r,_,ret in evaluated if any(c.get('key')==key and c.get('passed') for c in r.get('criteria') or [])]
            features.append({'feature':key,'label':label,'signals':len(vals),'success_pct':round(100*sum(v>0 for v in vals)/len(vals),1) if vals else None,'avg_return_pct':round(sum(vals)/len(vals),3) if vals else None})
        n=len(evaluated); ready=n>=MIN_VALIDATION_SAMPLES
        recent=[]
        for r,m,ret in reversed(evaluated[-50:]):recent.append({'date':r.get('trade_date'),'symbol':r.get('ticker'),'checkpoint':r.get('checkpoint'),'score':r.get('score'),'close_return_pct':ret,'horizon_minutes':m,'scan_id':r.get('scan_id'),'criteria':r.get('criteria'),'day_return_pct':_number(r.get('ret_day_pct')),'week_return_pct':_number(r.get('ret_week_pct')),'month_return_pct':_number(r.get('ret_month_pct')),'minutes_to_peak':_number(r.get('minutes_to_peak')),'minutes_to_trough':_number(r.get('minutes_to_trough'))})
        stock_performance=[]
        for symbol in sorted({r.get('ticker') for r in rows if r.get('ticker')}):
            own=[r for r in rows if r.get('ticker')==symbol];item={'symbol':symbol,'signals':len(own)}
            for period in PERIODS:
                vals=[_number(r.get(f'ret_{period}_pct')) for r in own];vals=[v for v in vals if v is not None]
                item[period]={'samples':len(vals),'success_pct':round(100*sum(v>0 for v in vals)/len(vals),1) if vals else None,'avg_return_pct':round(sum(vals)/len(vals),3) if vals else None}
            peaks=[_number(r.get('minutes_to_peak')) for r in own];troughs=[_number(r.get('minutes_to_trough')) for r in own]
            peaks=[x for x in peaks if x is not None];troughs=[x for x in troughs if x is not None]
            item['median_minutes_to_peak']=round(statistics.median(peaks),1) if peaks else None;item['median_minutes_to_trough']=round(statistics.median(troughs),1) if troughs else None
            stock_performance.append(item)
        stock_performance.sort(key=lambda x:(x['signals'],x['day']['success_pct'] if x['day']['success_pct'] is not None else -1),reverse=True)
        missed=sum(sum(bool(r.get(f'missed{m}m')) for m in HORIZONS) for r in rows)
        return {'has_data':bool(rows),'source':'scheduled_point_in_time_forward_validation','storage':learning_store.status(),'strategy_version':strategy_version,'signals':len(rows),'evaluated':n,'pending':len(rows)-n,'missed_measurement_windows':missed,'success_rate_pct':round(100*sum(v>0 for _,_,v in evaluated)/n,1) if n else None,'expectancy_r':round(sum(v for _,_,v in evaluated)/n,3) if n else None,'universe_size':len({r.get('ticker') for r in rows}),'feature_learning':features,'recent_signals':recent,'stock_performance':stock_performance,'horizons_minutes':list(HORIZONS),'periods':PERIOD_LABELS,'validation':{'ready':ready,'minimum_samples':MIN_VALIDATION_SAMPLES,'chronological_point_in_time':True,'measurement_grace_seconds':MEASUREMENT_GRACE_SECONDS,'weights_changed':False,'legacy_records_excluded':len(all_rows)-len(rows)},'definitions':{'score':'התאמה לשיטה, לא הסתברות הצלחה','success_rate':'תשואה חיובית באופק הנמדד','timing':'זמן מהאות עד לשיא ולשפל שנצפו בדגימות השוק'}}

    async def loop():
        while True:
            try:
                ny=datetime.now(timezone.utc).astimezone(NY)
                if ny.weekday()<5:
                    label=CHECKPOINTS.get((ny.hour,ny.minute))
                    if label:await capture(label)
                    await evaluate_due()
            except Exception as e:state['last_error']=f'{type(e).__name__}: {e}'
            await asyncio.sleep(20)

    @app.on_event('startup')
    async def _start_learning_scheduler():
        asyncio.create_task(loop())

    @app.get('/api/learning/scheduled-status')
    async def scheduled_status():return state

    for route in list(app.routes):
        if getattr(route,'path',None) in {'/api/learning/summary','/api/learning/forward-validation','/api/learning/stock/{symbol}'}:
            app.router.routes.remove(route)

    @app.get('/api/learning/summary')
    async def scheduled_summary():
        await evaluate_due()
        return summary()

    @app.get('/api/learning/forward-validation')
    async def scheduled_forward_validation():
        await evaluate_due()
        return summary()

    @app.get('/api/learning/stock/{symbol}')
    async def scheduled_stock_learning(symbol:str):
        await evaluate_due();symbol=symbol.upper().strip();data=summary()
        rows=[r for r in learning_store.load(3000) if r.get('record_type')=='scheduled_checkpoint' and r.get('strategy_version')==strategy_version and r.get('ticker')==symbol]
        profile=next((x for x in data.get('stock_performance') or [] if x.get('symbol')==symbol),None)
        return {'has_data':bool(rows),'symbol':symbol,'signals':len(rows),'profile':profile,'rows':[{'date':r.get('trade_date'),'score':r.get('score'),'gap_pct':r.get('gap_pct'),'rvol_open':r.get('rvol'),'day_return_pct':_number(r.get('ret_day_pct')),'week_return_pct':_number(r.get('ret_week_pct')),'month_return_pct':_number(r.get('ret_month_pct')),'minutes_to_peak':_number(r.get('minutes_to_peak')),'minutes_to_trough':_number(r.get('minutes_to_trough'))} for r in reversed(rows[-50:])],'validation':data.get('validation'),'definitions':data.get('definitions')}

    return state
