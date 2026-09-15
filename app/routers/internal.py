"""
Herramientas internas -- NO client-facing. A propósito bajo el prefijo
"/internal/" y no "/admin/" para no confundirlo con la regla de CLAUDE.md
sobre nunca dejar endpoints TEMPORALES de diagnóstico (/admin/...): esto
es una herramienta interna permanente y protegida por clave, no un
olvido de desarrollo.

Nunca vinculado desde dashboard.html -- solo accesible conociendo la URL,
y aun así inútil sin INTERNAL_ADMIN_KEY configurada en el entorno.

Este router se conecta a la app principal en main.py con:
    app.include_router(internal.router)
"""
import os
from fastapi import APIRouter, HTTPException, Query
from app.database import get_db_connection

router = APIRouter(tags=["internal"])

INTERNAL_ADMIN_KEY = os.getenv("INTERNAL_ADMIN_KEY", "")


def _check_key(key: str):
    # Sin INTERNAL_ADMIN_KEY configurada en el entorno, SIEMPRE se rechaza
    # -- nunca se permite un borrado "por accidente" porque la variable
    # esté vacía en ambos lados de la comparación.
    if not INTERNAL_ADMIN_KEY or key != INTERNAL_ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Acceso no autorizado.")


@router.delete("/internal/clean-db")
def clean_database(key: str = Query(...), confirm: bool = Query(False)):
    _check_key(key)
    if not confirm:
        raise HTTPException(status_code=400, detail="Pasa confirm=true para confirmar el borrado.")

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM scraper_results;")
            deleted = cur.rowcount
        conn.commit()
        return {"status": "success", "message": f"{deleted} registros eliminados de scraper_results."}
    finally:
        conn.close()
