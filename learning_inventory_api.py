"""Read-only durable learning inventory for the health dashboard."""
from fastapi.responses import JSONResponse

def install(app):
    @app.get("/api/learning/inventory")
    def learning_inventory():
        try:
            import learning_store
            types=("scanner_signal","timing_event","scheduled_checkpoint","missed_mover_observation","missed_mover_report")
            counts={kind:learning_store.count(kind) for kind in types}
            long_count=learning_store.count_long_daily()
            return JSONResponse({"available":True,"durable":learning_store.durable(),"backend":learning_store.backend(),"total":learning_store.count(),"counts":counts,"long_daily_predictions":long_count,"backtest_equivalent":False,"note":"Stored signals are not validated strategy win rates."},headers={"Cache-Control":"no-store"})
        except Exception as exc:
            return JSONResponse({"available":False,"error_type":type(exc).__name__},status_code=503,headers={"Cache-Control":"no-store"})
