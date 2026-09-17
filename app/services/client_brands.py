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

# Marcas cliente EXCLUIDAS del cálculo de Índice de Precio (price_index)
# -- siguen contando como "cliente" en todo lo demás (Share of Shelf,
# % DN/DP, Posición Dominante, disponibilidad). Solo TENA por ahora.
#
# Confirmado con evidencia real (2026-09-17), investigando por qué el
# Índice de Precio salía extremo (>180) en 6 de 7 retailers con dato
# confiable: TENA es la línea de INCONTINENCIA de Essity ("goteos
# moderados/abundantes", paquetes de 30-60 unidades) -- no toallas
# higiénicas menstruales, que es lo que buscan los términos activos hoy
# ("Toallas Higienicas") y lo que vende toda la competencia capturada
# (Kotex, Stayfree, EKONO, etc.). TENA promedia consistentemente
# 2.4x-3.6x el precio de Nosotras en los 6 retailers donde aparece bajo
# este término (Éxito $47,044 vs $19,836; Coopidrogas $31,000 vs
# $12,313; Carulla $46,944 vs $20,769; Farmatodo $47,650 vs $20,786;
# Pasteur $39,237 vs $13,125 -- La Rebaja no tiene TENA capturado bajo
# este término). Mezclarlo con Nosotras en el promedio "cliente" inflaba
# price_index artificialmente: no hay competidores de incontinencia
# capturados bajo este término de búsqueda, así que TENA no tiene con
# qué compararse -- no es un error de scraping ni de clasificación de
# marca, TENA es un producto real de Essity, simplemente de otra
# categoría de producto que la que cubre el término de búsqueda actual.
# price_index ahora se calcula solo con CLIENT_BRANDS menos este set; el
# precio promedio de TENA se reporta aparte, informativo, sin índice
# (ver client_price_excluded_avg_price en /executive-summary e /insights).
CLIENT_BRANDS_PRICE_EXCLUDED = ["tena"]

# Nombre del cliente para mostrar (portada del PDF ejecutivo, etc.) --
# espejo del ACTIVE_CLIENT_NAME hardcodeado en app/dashboard.html. Vive
# acá para que el backend (que no carga dashboard.html) tenga su propia
# fuente de verdad sin duplicar la lista de marcas.
ACTIVE_CLIENT_NAME = "Essity"
