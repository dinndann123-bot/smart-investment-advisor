import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta


def _scenario_dates():
    out=[]; y=2021; m=7
    for _ in range(50):
        nxt=datetime(y+1,1,1) if m==12 else datetime(y,m+1,1)
        out.append((nxt-timedelta(days=1)).date().isoformat())
        m+=1
        if m==13: y+=1; m=1
    return out


def _bootstrap():
    for _ in range(150):
        mod=sys.modules.get('app')
        app_obj=getattr(mod,'app',None) if mod else None
        if app_obj is not None:
            try:
                import research_50
                research_50.SCENARIOS=_scenario_dates()
                research_50.install_research_50(app_obj)
                print('RESEARCH50_INSTALLED=true',flush=True)
                break
            except Exception as exc:
                print('RESEARCH50_INSTALL_ERROR='+repr(exc),flush=True)
                return
        time.sleep(0.1)
    else:
        print('RESEARCH50_INSTALL_ERROR=app_not_found',flush=True)
        return
    time.sleep(5)
    port=os.getenv('PORT','10000')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/strategy/long/research-50',timeout=600) as r:
            data=json.loads(r.read().decode('utf-8'))
        for b in data.get('batches',[]):
            c={'batch':b.get('batch'),'dates':b.get('dates'),'preset_used':b.get('preset_used'),'summary':b.get('summary'),'lessons':b.get('lessons'),'next_preset':b.get('next_preset')}
            print('RESEARCH50V2_BATCH='+json.dumps(c,ensure_ascii=False,separators=(',',':')),flush=True)
        f={'date_range':data.get('date_range'),'overall':data.get('overall'),'final_preset':data.get('final_preset'),'method':data.get('method'),'limitations':data.get('limitations')}
        print('RESEARCH50V2_FINAL='+json.dumps(f,ensure_ascii=False,separators=(',',':')),flush=True)
    except Exception as exc:
        print('RESEARCH50V2_RUN_ERROR='+repr(exc),flush=True)

threading.Thread(target=_bootstrap,daemon=True,name='research50-bootstrap').start()
