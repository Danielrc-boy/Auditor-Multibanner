"""
Endpoint que dispara la ejecución del scraping bajo demanda.

Este router se conecta a la app principal en main.py con:
    app.include_router(scraping.router)
"""
from fastapi import APIRouter
from app.database import get_db_connection
from app.services.scraping_orchestrator import run_all_scraping

router = APIRouter(tags=["scraping"])


@router.post("/trigger-now")
@router.post("/trigger-now/")
async def trigger_now():
    conn = get_db_connection()
    try:
        total_records = await run_all_scraping(conn)
        return {
            "status": "success",
            "message": f"Monitoreo ejecutado correctamente. {total_records} productos guardados.",
            "total_records": total_records,
        }
    except Exception as e:
        print(f"[TRIGGER ERROR] {e}", flush=True)
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()
