"""Research-only entry/exit timing state attached to live scanner rows."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


VERSION='timing-signals-v1'
NY=ZoneInfo('America/New_York')


def _number(value):
    try:return float(value)
    except (TypeError,ValueError):return None


def _entry_gate(row):
    rv=_number(row.get('rvol'));burst=_number(row.get('minute_volume_burst'))
    volume=_number(row.get('day_volume'));baseline=_number(row.get('historical_baseline_volume'))
    dollars=_number(row.get('dollar_volume'));spread=_number(row.get('spread_bps'));price=_number(row.get('price'))
    used=_number(row.get('intraday_move_used_pct'));position=_number(row.get('current_range_position'))
    gap=_number(row.get('snapshot_gap_pct'));change=_number(row.get('change_pct'))
    checks={
        'predictive_stage':row.get('breakout_stage') in {'pre_breakout','early_breakout'},
        'reliable_rvol':bool(row.get('rvol_reliable') and rv is not None and rv>=1.5),
        'volume_acceleration':burst is not None and burst>=1.5,
        'liquid_baseline':volume is not None and baseline is not None and volume>=1000 and baseline>=1000,
        'dollar_liquidity':dollars is not None and dollars>=1_000_000,
        'tradable_spread':spread is not None and spread<=75,
        'price_floor':price is not None and price>=1,
        'move_available':used is not None and used<92,
        'range_position':position is not None and .08<=position<=.97,
        'gap_control':gap is not None and abs(gap)<=8,
        'momentum_window':change is not None and -3<=change<=8,
    }
    return all(checks.values()),checks


def annotate_and_record(rows, learning_store, scan_id, observed_at=None):
    now=observed_at or datetime.now(timezone.utc);day=now.astimezone(NY).date().isoformat()
    history=learning_store.load(3000)
    prior=[x for x in history if x.get('record_type')=='timing_event' and x.get('trade_date')==day and x.get('version')==VERSION]
    by_symbol={}
    for event in prior:by_symbol.setdefault(event.get('ticker'),[]).append(event)
    recorded=[]
    for row in rows:
        symbol=str(row.get('ticker') or '').upper();price=_number(row.get('price'))
        events=sorted(by_symbol.get(symbol,[]),key=lambda x:float(x.get('epoch') or 0))
        entry=next((x for x in events if x.get('event_type')=='entry'),None)
        exit_event=next((x for x in events if x.get('event_type')=='exit'),None)
        passed,checks=_entry_gate(row)
        signal='watch';reason='ממתין לאישור מלא של תנאי הכניסה'
        if entry and not exit_event and price is not None:
            entry_price=_number(entry.get('price'))
            ret=(price/entry_price-1)*100 if entry_price else None
            used=_number(row.get('intraday_move_used_pct'))
            if ret is not None and ret>=2:signal,reason='exit','יעד רווח 2% הושג'
            elif ret is not None and ret<=-1:signal,reason='exit','עצירת הפסד 1% הופעלה'
            elif row.get('breakout_stage')=='already_extended' and used is not None and used>=96:signal,reason='exit','המהלך מוצה והמחיר נמצא בקצה הטווח'
            else:signal,reason='active','עסקה במעקב מאז אות הכניסה'
            row['timing_entry_price']=entry_price;row['timing_return_pct']=round(ret,3) if ret is not None else None
            if signal=='exit':
                event={'record_type':'timing_event','event_type':'exit','trade_date':day,'signal_time':now.isoformat(),'epoch':now.timestamp(),'scan_id':f'timing:{day}:{symbol}:exit','ticker':symbol,'rank':row.get('rank'),'price':price,'entry_price':entry_price,'return_pct':round(ret,3) if ret is not None else None,'reason':reason,'version':VERSION,'production_effect':False,'source_scan_id':scan_id}
                learning_store.upsert(event);recorded.append(event);by_symbol.setdefault(symbol,[]).append(event)
        elif not entry and passed and price is not None:
            signal,reason='entry','כל תנאי v3 לכניסה עברו'
            event={'record_type':'timing_event','event_type':'entry','trade_date':day,'signal_time':now.isoformat(),'epoch':now.timestamp(),'scan_id':f'timing:{day}:{symbol}:entry','ticker':symbol,'rank':row.get('rank'),'price':price,'reason':reason,'checks':checks,'version':VERSION,'production_effect':False,'source_scan_id':scan_id}
            learning_store.upsert(event);recorded.append(event);by_symbol.setdefault(symbol,[]).append(event)
            row['timing_entry_price']=price;row['timing_return_pct']=0
        elif exit_event:
            signal,reason='closed','אות היציאה כבר תועד'
            row['timing_entry_price']=_number(entry.get('price')) if entry else None
            row['timing_exit_price']=_number(exit_event.get('price'))
        row.update({'timing_signal':signal,'timing_reason':reason,'timing_version':VERSION,'timing_observed_at':now.isoformat(),'timing_gate_checks':checks})
    return recorded


def monitor_active_positions(rows, learning_store, scan_id, observed_at=None):
    """Keep target/stop monitoring alive after a ticker leaves the displayed Top-10."""
    now=observed_at or datetime.now(timezone.utc);day=now.astimezone(NY).date().isoformat()
    history=learning_store.load(3000)
    today=[x for x in history if x.get('record_type')=='timing_event' and x.get('trade_date')==day and x.get('version')==VERSION]
    entries={x.get('ticker'):x for x in today if x.get('event_type')=='entry'}
    closed={x.get('ticker') for x in today if x.get('event_type')=='exit'}
    market={str(x.get('ticker') or '').upper():x for x in rows}
    recorded=[]
    for symbol,entry in entries.items():
        if symbol in closed or symbol not in market:continue
        price=_number(market[symbol].get('price'));entry_price=_number(entry.get('price'))
        if price is None or not entry_price:continue
        ret=(price/entry_price-1)*100;reason=None
        if ret>=2:reason='יעד רווח 2% הושג'
        elif ret<=-1:reason='עצירת הפסד 1% הופעלה'
        if not reason:continue
        event={'record_type':'timing_event','event_type':'exit','trade_date':day,'signal_time':now.isoformat(),'epoch':now.timestamp(),'scan_id':f'timing:{day}:{symbol}:exit','ticker':symbol,'rank':entry.get('rank'),'price':price,'entry_price':entry_price,'return_pct':round(ret,3),'reason':reason,'version':VERSION,'production_effect':False,'source_scan_id':scan_id,'monitored_outside_top10':True}
        learning_store.upsert(event);recorded.append(event)
    return recorded


def install_timing_routes(app, learning_store):
    @app.get('/api/learning/timing-events')
    async def timing_events(limit:int=200):
        rows=[x for x in learning_store.load(3000) if x.get('record_type')=='timing_event']
        rows=list(reversed(rows[-max(1,min(limit,500)):]))
        entries=sum(x.get('event_type')=='entry' for x in rows);exits=sum(x.get('event_type')=='exit' for x in rows)
        return {'ok':True,'version':VERSION,'entries':entries,'exits':exits,'events':rows,'production_effect':False,'storage':learning_store.status()}

    return {'installed':True,'version':VERSION,'production_effect':False}
