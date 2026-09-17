"""
Marcas que cuentan como "cliente" para todo el sistema (Share of Shelf,
Índice de Precio, Disponibilidad, motor de insights, y la heurística de
detección de marca por texto en cafam_scraper.py).

Única fuente de verdad: antes vivía duplicada dentro de
app/routers/analytics.py -- moverla aquí evita que las copias se
desincronicen con el tiempo (el mismo riesgo ya documentado en CLAUDE.md
sobre get_db_connection() duplicado). Para monitorear otro cliente en el
futuro, el único cambio necesario es esta lista.

En minúsculas porque se compara contra LOWER(brand) en SQL y contra
strings ya normalizados a minúscula en Python.
"""
CLIENT_BRANDS = ["nosotras", "pequeñin", "pequeñín", "tena", "zewa"]

# Nombre del cliente para mostrar (portada del PDF ejecutivo, etc.) --
# espejo del ACTIVE_CLIENT_NAME hardcodeado en app/dashboard.html. Vive
# acá para que el backend (que no carga dashboard.html) tenga su propia
# fuente de verdad sin duplicar la lista de marcas.
ACTIVE_CLIENT_NAME = "Essity"
