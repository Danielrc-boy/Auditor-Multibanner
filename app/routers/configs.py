"""
Rutas para gestionar las búsquedas configuradas (search_configs):
crear, listar, activar/desactivar, y eliminar términos de búsqueda.

Este router se conecta a la app principal en main.py con:
    app.include_router(configs.router)
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import get_db_connection

router = APIRouter(tags=["configs"])


class SearchConfigCreate(BaseModel):
    search_term: Optional[str] = None
    keyword: Optional[str] = None


@router.get("/configs")
@router.get("/configs/")
def get_configs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM search_configs ORDER BY created_at DESC;")
    configs = cursor.fetchall()
    cursor.close()
    conn.close()
    return configs


@router.post("/configs")
@router.post("/configs/")
def create_config(config: SearchConfigCreate):
    term = config.search_term or config.keyword
    if not term:
        raise HTTPException(
            status_code=400, detail="Debe proporcionar 'search_term' o 'keyword'."
        )
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO search_configs (search_term, is_active) VALUES (%s, TRUE) RETURNING *;",
            (term,),
        )
        new_config = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        return new_config
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error guardando: {str(e)}")


@router.patch("/configs/{config_id}/toggle")
def toggle_config(config_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE search_configs SET is_active = NOT is_active WHERE id = %s RETURNING id, search_term, is_active;",
            (config_id,),
        )
        updated = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        if not updated:
            raise HTTPException(status_code=404, detail="Configuración no encontrada.")
        return {"status": "success", "config": updated}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(
            status_code=400, detail=f"Error actualizando estado: {str(e)}"
        )


@router.delete("/configs/{config_id}")
def delete_config(config_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "DELETE FROM search_configs WHERE id = %s RETURNING id;", (config_id,)
        )
        deleted = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()
        if not deleted:
            raise HTTPException(status_code=404, detail="Configuración no encontrada.")
        return {"status": "success", "deleted_id": config_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Error eliminando: {str(e)}")