"""
Módulo de conexión a base de datos.

Toda la app obtiene su conexión a Postgres a través de get_db_connection().
Centralizar esto aquí significa que un cambio en cómo nos conectamos
(por ejemplo, agregar un pool de conexiones más adelante) se hace en
un solo lugar, no en cada archivo de rutas.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import HTTPException

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    """
    Abre y devuelve una conexión nueva a Postgres.
    Lanza un HTTPException 500 si DATABASE_URL no está configurada
    o si la conexión falla, para que FastAPI devuelva un error claro
    en vez de que la app truene sin explicación.
    """
    if not DATABASE_URL:
        raise HTTPException(
            status_code=500,
            detail="Error BD: La variable DATABASE_URL no está configurada.",
        )
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error BD: {str(e)}")