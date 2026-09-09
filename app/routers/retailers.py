"""
Rutas relacionadas con retailers (Éxito, Carulla, Farmatodo, etc).

Este router se conecta a la app principal en main.py con:
    app.include_router(retailers.router)

Cuando agreguemos un retailer nuevo (La Rebaja, Falabella...), este
archivo NO cambia -- el retailer nuevo se agrega como una fila en la
tabla `retailers`, no como código nuevo aquí.
"""
from fastapi import APIRouter
from app.database import get_db_connection

router = APIRouter(tags=["retailers"])


@router.get("/retailers")
@router.get("/retailers/")
def get_retailers():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM retailers WHERE is_active = TRUE;")
    retailers = cursor.fetchall()
    cursor.close()
    conn.close()
    return retailers