import urllib.request

# Keep the approved stable application as the runtime base.
_STABLE='https://raw.githubusercontent.com/dinndann123-bot/smart-investment-advisor/1b8068c52a5f7ba5ab6ee455999330b102dbc90a/app.py'
_code=urllib.request.urlopen(_STABLE, timeout=30).read().decode('utf-8')
exec(compile(_code, _STABLE, 'exec'), globals(), globals())

# Add research/learning endpoints only after the stable app has been created.
# This deliberately does not replace UI, scanner routes, charts, or Alpaca setup.
try:
    import sys
    _core = sys.modules[__name__]
    from signal_journal import install_signal_journal
    from missed_movers_learning import install_missed_movers_learning
    install_signal_journal(app, _core)
    install_missed_movers_learning(app, _core)
    LEARNING_ENGINE_STATUS = {
        'installed': True,
        'strategy_version': 'strategy-learning-v2',
        'stable_base': '1b8068c52a5f7ba5ab6ee455999330b102dbc90a',
    }
except Exception as _learning_error:
    # Fail-open: a learning-layer problem must never prevent the stable app boot.
    LEARNING_ENGINE_STATUS = {
        'installed': False,
        'strategy_version': 'strategy-learning-v2',
        'error': f'{type(_learning_error).__name__}: {_learning_error}',
    }

@app.get('/api/learning/status')
async def learning_status():
    return LEARNING_ENGINE_STATUS
