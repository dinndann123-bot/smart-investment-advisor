import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DB=Path(__file__).resolve().parent/'signal_journal.sqlite3'
NY=ZoneInfo('America/New_York')
VERSION='strategy-learning-v2'

def _avg(xs):
    xs=[float(x) for x in xs if x is not None]
    return round(sum(xs)/len(xs),2) if xs else None

def _median(xs):
    xs=sorted(float(x) for x in xs if x is not None)
    if not xs:return None
    n=len(xs);m=n//2
    return round(xs[m] if n%2 else (xs[m-1]+xs[m])/2,2)

def install_learning_comparison(app,core):
    @app.get('/api/learning/feature-comparison')
    async def feature_comparison():
        day=datetime.now(NY).date().isoformat();con=sqlite3.connect(DB);con.row_factory=sqlite3.Row
        mm=con.execute('SELECT symbol,move_pct,was_top10,premarket_gap_pct,premarket_volume,premarket_high,premarket_low,asset_attributes FROM missed_movers WHERE trade_date=? AND strategy_version=? AND eligible_common_stock=1',(day,VERSION)).fetchall()
        captured=[r for r in mm if r['was_top10']==1];missed=[r for r in mm if r['was_top10']==0]
        def group(rows):
            gaps=[r['premarket_gap_pct'] for r in rows];vols=[r['premarket_volume'] for r in rows];moves=[r['move_pct'] for r in rows];ranges=[];halts=0
            for r in rows:
                if r['premarket_high'] and r['premarket_low']:ranges.append((r['premarket_high']/r['premarket_low']-1)*100)
                if 'overnight_halted' in str(r['asset_attributes'] or ''):halts+=1
            return {'count':len(rows),'avg_move_pct':_avg(moves),'median_move_pct':_median(moves),'avg_premarket_gap_pct':_avg(gaps),'median_premarket_gap_pct':_median(gaps),'premarket_gap_coverage':sum(x is not None for x in gaps),'avg_premarket_volume':_avg(vols),'median_premarket_volume':_median(vols),'premarket_volume_coverage':sum(x is not None for x in vols),'avg_premarket_range_pct':_avg(ranges),'overnight_halted':halts,'overnight_halted_pct':round(halts/len(rows)*100,1) if rows else None}
        cg=group(captured);mg=group(missed)
        con.close()
        return {'ok':True,'trade_date':day,'strategy_version':VERSION,'captured':cg,'missed':mg,'delta_missed_minus_captured':{'avg_premarket_gap_pct':round(mg['avg_premarket_gap_pct']-cg['avg_premarket_gap_pct'],2) if mg['avg_premarket_gap_pct'] is not None and cg['avg_premarket_gap_pct'] is not None else None,'avg_premarket_volume':round(mg['avg_premarket_volume']-cg['avg_premarket_volume'],2) if mg['avg_premarket_volume'] is not None and cg['avg_premarket_volume'] is not None else None,'overnight_halted_pct':round(mg['overnight_halted_pct']-cg['overnight_halted_pct'],1) if mg['overnight_halted_pct'] is not None and cg['overnight_halted_pct'] is not None else None},'note':'Descriptive comparison only; do not change strategy weights from one session.'}
