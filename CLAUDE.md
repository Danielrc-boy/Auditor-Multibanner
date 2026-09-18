# Auditor-Multibanner — Contexto para Claude Code

Este archivo se lee automáticamente al abrir el proyecto. Contiene las reglas
de trabajo, la arquitectura, y las lecciones aprendidas -- síguelas siempre,
no las repitas de memoria sin releerlas si ha pasado tiempo.

## Qué es este proyecto

Sistema de monitoreo de "digital shelf" para Essity (marcas Nosotras, Tena,
Zewa, Pequeñín) en Colombia. Rastrea posición, precio, marca y disponibilidad
de productos en múltiples retailers (e-commerce) mediante scraping, y expone
los datos vía una API (FastAPI) que alimenta un dashboard.

- Backend: FastAPI + psycopg2, desplegado en Railway.
- Frontend: React/Next.js, desplegado en Vercel.
- Base de datos: PostgreSQL en Railway.
- Repositorio: https://github.com/Danielrc-boy/Auditor-Multibanner

## REGLA DE ORO: nunca tocar `main` directamente

`main` = producción real, lo que ve el cliente (Essity) ahora mismo.
`staging` = ambiente de pruebas, con su propia base de datos separada.

**Importante (confirmado 2026-09-14):** la base de datos de staging tiene
una mezcla de productos NO representativa del negocio real -- está
contaminada con datos de pruebas, corridas manuales repetidas, y
retailers agregados en distintos momentos durante el desarrollo (ej. su
`price_index` puede salir muy distinto al de producción sin que eso sea
un bug -- son catálogos de retailers completamente distintos). Staging
sirve para confirmar que el código FUNCIONA técnicamente (no truena, la
lógica corre, los campos se llenan) -- nunca para validar si un número de
negocio "tiene sentido". Esa validación siempre se hace contra producción.

Flujo obligatorio para CUALQUIER cambio:
1. Trabajar sobre la rama `staging`.
2. Hacer commit y push a `staging`.
3. Verificar en la URL de staging que el cambio funciona
   (`https://auditor-multibanner-staging.up.railway.app`).
4. Solo si staging confirma que funciona: `git checkout main && git merge staging && git push origin main`.
5. Verificar de nuevo en producción real
   (`https://auditor-multibanner-production.up.railway.app`).

Nunca saltar el paso de staging, incluso para cambios que parezcan triviales.
Esta disciplina ya salvó al proyecto una vez: detectamos en staging un import
roto que habría dejado de capturar datos de Éxito/Carulla en silencio en
producción.

## Arquitectura del backend (post-refactor)

`app/main.py` es intencionalmente corto (~85 líneas): solo arranca la app,
configura CORS, y conecta routers. TODA la lógica vive en módulos separados:

```
app/
├── main.py
├── database.py                    -- get_db_connection(), fuente única
├── routers/
│   ├── retailers.py
│   ├── configs.py
│   ├── results.py                  -- incluye /export (Excel)
│   ├── analytics.py                -- incluye /dashboard-data
│   └── scraping.py                 -- endpoint /trigger-now
└── services/
    ├── scraping_orchestrator.py     -- save_scraper_results, run_all_scraping,
    │                                   y run_<retailer>_scraping para los
    │                                   retailers NO-VTEX (Farmatodo, Rappi, Cafam)
    └── scrapers/
        ├── vtex_scraper.py           -- TODOS los retailers VTEX viven aquí,
        │                                vía el diccionario RETAILER_CONFIGS
        ├── farmatodo_scraper.py
        ├── rappi_scraper.py
        └── cafam_scraper.py
```

No dupliques `get_db_connection()` en otro lugar -- ya pasó una vez (quedó
una copia vieja en `main.py` después del refactor) y causó confusión.

## Patrón para agregar un retailer VTEX nuevo

La mayoría de retailers colombianos grandes son VTEX. Si `RETAILER_CONFIGS`
en `vtex_scraper.py` ya tiene una entrada, agregar uno nuevo es SOLO una
entrada más en el diccionario -- no tocar la clase `VTEXScraper` ni la lógica
de parseo.

```python
"nombre_retailer": {
    "base_url": "https://www.dominio.com",
    "search_style": "path",       # o "ft_param" (ver La Rebaja)
    "use_io_prefix": True,        # o False -- confirmar con evidencia real
    "use_scraperapi": True,       # o False -- solo si hay bloqueo confirmado
},
```

Y agregarlo a la lista de retailers dentro de `run_vtex_scraping`.

## Antes de escribir código para un retailer NUEVO: procedimiento obligatorio

NUNCA asumas la plataforma o la URL de búsqueda. Siempre:

1. Buscar el dominio REAL de la tienda (a veces no es obvio -- ej. Coopidrogas
   opera bajo "farmaexpress.com", Cruz Verde bajo su propio dominio).
2. Confirmar la plataforma con evidencia real:
   - Buscar `meta-generator: vtex.render-server` o dominio `*.vtexassets.com`
     en el HTML → es VTEX.
   - Si no hay señal clara, revisar el pie de página ("Powered by/Empowered by")
     o el código fuente en busca de firmas (`webpackJsonpvtex_search_result`,
     `Prestashop`, etc.).
3. Confirmar la ruta exacta de búsqueda probando en el navegador (algunas VTEX
   necesitan `/io/` delante, otras no -- no hay forma de saberlo sin probar).
4. Capturar un JSON/HTML de respuesta REAL antes de escribir el parser.
5. Escribir el scraper basado en esa evidencia, nunca en suposiciones.
6. Verificar con pruebas automatizadas usando el JSON/HTML real capturado
   ANTES de subir nada a staging.

## Lecciones aprendidas (para no repetir errores ya resueltos)

- **Filtro de relevancia**: plataformas que devuelven "carruseles" genéricos
  (Rappi) en vez de resultados de búsqueda reales pueden traer productos
  totalmente ajenos al término buscado. Siempre filtrar por si el término
  (o su forma singular/plural) aparece en el nombre o la marca del producto.
- **Posición real vs. campo "position" de la plataforma**: no confiar
  ciegamente en un campo "position" que trae la API -- puede repetirse
  entre productos (visto en Cafam/PrestaShop) o reflejar un orden interno
  de catálogo, no el ranking real de búsqueda. Preferir numerar por el
  orden real de aparición en la respuesta.
- **Aislamiento de fallos**: cada retailer debe correr dentro de su propio
  try/except en `run_all_scraping` y en cada `run_<retailer>_scraping`. Si
  uno falla, los demás DEBEN seguir guardando datos con normalidad. Probar
  esto explícitamente (simular un fallo) antes de dar por bueno un cambio
  al orquestador.
- **Headers al usar ScraperAPI**: nunca enviar los headers propios (User-Agent,
  Origin, Referer destinados al sitio real) directamente al endpoint de
  ScraperAPI -- esos headers son para el sitio destino, no para el proxy.
- **Retailers que dependen de ScraperAPI (sensibles a que se agote la cuota)**:
  Éxito, Carulla (bloqueo 403 confirmado sin proxy) y Cafam (bloqueo
  Cloudflare confirmado) enrutan TODAS sus peticiones vía ScraperAPI. Si la
  cuota mensual del plan se agota, estos 3 retailers dejan de traer
  resultados en las corridas programadas (confirmado 2026-09-15: "You have
  exhausted the API Credits available in this monthly cycle") mientras el
  resto de retailers (VTEX directos, Farmatodo, Rappi) sigue funcionando
  con normalidad -- no es un bug del código, es esperado hasta que el ciclo
  renueve o se cambie de plan/API key. Si alguno de estos 3 retailers deja
  de traer datos de golpe, revisar la cuota de ScraperAPI antes de asumir
  que el sitio cambió o que el scraper se rompió.
- **Sesiones por cookies (ej. Salesforce Commerce Cloud / Cruz Verde)**: si
  un sitio requiere sesión, puede que ni una visita directa a la home
  entregue cookies útiles a un servidor (vs. un navegador real) -- en ese
  caso, ScraperAPI con `session_number` (misma sesión en varias peticiones)
  y posiblemente `render=true` es la vía, pero cuesta créditos notablemente
  más caros. Evaluar costo/beneficio antes de insistir.
- **discount_price puede no estar disponible** en ciertas plataformas (ej.
  Rappi vía datos estructurados JSON-LD) -- documentarlo explícitamente en
  el scraper en vez de inventar un valor.
- **No asumir que discount_price=null significa "sin descuento real"**:
  confirmado (2026-09-14) que Farmatodo tenía un bug real (el campo
  "offerPrice" de nivel superior de Algolia siempre viene en 0; el precio
  de oferta real vive anidado en "offerPriceByStore"/"offerPriceByCity")
  -- ya corregido. Cafam tiene el mismo síntoma pero por una causa
  distinta y NO corregida a propósito: su endpoint de búsqueda AJAX no
  refleja los descuentos reales (verificado comparando contra la home del
  sitio), y la única fuente confiable es la página de detalle de cada
  producto individual -- una petición HTTP extra POR PRODUCTO, cara
  porque Cafam ya pasa por ScraperAPI (bloqueo Cloudflare). Se decidió no
  implementarlo por el costo; discount_price queda en None para Cafam,
  documentado también en cafam_scraper.py. Antes de "arreglar" un
  discount_price=null en cualquier retailer, verificar primero con el
  sitio real si el producto genuinamente no tiene oferta activa -- en
  Éxito, Carulla, La Rebaja, Locatel, Colsubsidio, Pasteur y Coopidrogas
  el alto % de discount_price=null resultó ser exactamente eso (sin bug).
- Nunca dejar endpoints de administración/diagnóstico temporales
  (`/admin/...`, `/exec-sql`) en el código una vez cumplieron su propósito.
  `/admin/test-cruzverde` en `main.py` (detectado 2026-09-14) ya se
  retiró (2026-09-15), junto con `app/schemas.py`, `app/models.py` y
  `app/routers/skus.py` -- código huérfano de la misma planeación
  temprana con SQLAlchemy, nunca registrado en `main.py` y ya roto
  (importaban `Base`/`get_db`, que no existen en el `database.py` real).
  Pendiente relacionado, sin resolver: `app/services/scheduler.py`
  también importa `app.models` y también está huérfano/roto de la misma
  manera (importa `SessionLocal`, tampoco existe, y no se registra en
  `main.py`) -- no se tocó porque no se confirmó si sigue sin usarse en
  ningún lado antes de borrarlo.
- **PENDIENTE (sin resolver, detectado 2026-09-15): falta filtro de
  relevancia de categoría en el buscador VTEX genérico.** La lección de
  "Filtro de relevancia" de arriba se documentó para Rappi (carruseles
  genéricos), pero se confirmó que también aplica a VTEX -- no es
  exclusivo de plataformas "sucias". El VTEX intelligent search de
  Colsubsidio, al buscar "Toallas Higienicas", devuelve mezclados
  productos de OTRA categoría (ej. "Life Cup Copa Menstrual Talla 0",
  "TOALLAS HIGIENICAS REUTILIZABLES LIFEPAD") junto con toallas
  desechables reales -- confirmado comparando precios reales: esos 2
  productos ($65.322 y $86.550) inflaban el precio promedio de
  competencia de ~$9.212 (comparable real) a $31.454, lo que hubiera
  distorsionado el Índice de Precio de ~190% real a un engañoso 55.8%.
  Este problema es INDEPENDIENTE del de "brand" (ver más abajo) -- ya
  existía en los datos crudos del sitio, solo estaba invisible porque
  antes de corregir "brand" el Índice de Precio de Colsubsidio nunca se
  calculaba (siempre None). Mitigación aplicada mientras tanto (ver
  `RETAILERS_WITH_UNRELIABLE_PRICE_INDEX` en `app/routers/analytics.py`):
  el Índice de Precio de Colsubsidio se fuerza a None
  (`price_index_data_quality: "partial"` en `/executive-summary`) en vez
  de mostrar un número contaminado -- el Share of Shelf de Colsubsidio
  SÍ es confiable y se sigue mostrando normal, porque no depende de
  precio. Pendiente real: agregar un filtro de relevancia de categoría
  (ej. exigir que el título contenga "toalla"/"toallas", o excluir por
  palabras clave como "copa menstrual"/"reutilizable") en `vtex_scraper.py`.
  **Actualización (2026-09-17): ya se evaluó qué otros retailers VTEX
  tienen el mismo problema** (al revisar de dónde salían los valores
  extremos de Índice de Precio en el PDF ejecutivo v1) -- se investigó
  con el mismo método (productos de competencia más caros por retailer +
  búsqueda por palabra clave "copa"/"menstrual"/"reutilizable" sobre
  ~180 productos de competencia combinados) a los 7 retailers restantes
  con Índice de Precio activo: **Locatel SÍ tiene el mismo problema**
  (confirmado, mitigado igual que Colsubsidio -- ver estado en
  "Retailers -- estado actual"); Éxito, Carulla, Farmatodo, La Rebaja,
  Pasteur y Coopidrogas **no** lo tienen. El filtro real en
  `vtex_scraper.py` sigue sin implementarse -- ahora que se confirmó en
  2 de 9 retailers VTEX, debe ser genérico (aplicable a cualquier
  retailer VTEX), no hardcodeado a uno solo.
- **PENDIENTE (sin resolver, detectado 2026-09-15): revisar
  `RETAILERS_WITH_UNRELIABLE_BRAND_FIELD` en `insights_engine.py`.**
  Ese set (`{"cafam", "colsubsidio"}`) excluye a ambos retailers de
  TODOS los insights (Alertas/Oportunidades/Fortalezas: Share of Shelf,
  Índice de Precio, Posición Dominante) porque documentaba que "brand"
  no era confiable en ninguno de los dos -- eso ya se corrigió (ver
  `_detect_client_brand` en `cafam_scraper.py` y `_resolve_brand` en
  `vtex_scraper.py`, ambos verificados con evidencia real). Ahora que
  "brand" sí es confiable, seguir excluyendo a estos dos retailers del
  motor de insights es más estricto de lo necesario -- pero Colsubsidio
  todavía no puede recibir insights de Índice de Precio por el problema
  de categoría documentado arriba. No se tocó en esta sesión porque no
  se pidió explícitamente; evaluar separar el criterio de exclusión por
  métrica (igual que ya se hizo en `/executive-summary` con
  `price_index_data_quality`) en vez de excluir todo-o-nada por retailer.
- **`/internal/...` es distinto de `/admin/...`**: `/internal/clean-db`
  (en `app/routers/internal.py`, con página en `/internal/tools`) es una
  herramienta interna PERMANENTE y deliberada, protegida por
  `INTERNAL_ADMIN_KEY` (sin esa variable configurada, el endpoint rechaza
  todo). Se creó a propósito bajo un prefijo distinto a `/admin/` para no
  confundirla con la regla de arriba -- no es un olvido de desarrollo, no
  hay que "limpiarla" después. Nunca se enlaza desde dashboard.html (esa
  pantalla es client-facing).
- **Un número raro en el PDF ejecutivo de staging casi siempre es
  staging, no un bug de código** (recordatorio con evidencia real,
  2026-09-17): el PDF v1 generado contra `staging` mostraba a Rappi con
  0.0% de Share of Shelf ("no presente") y valores de Índice de Precio
  extremos en varios retailers. Se investigó cada síntoma directo contra
  PRODUCCIÓN (nunca contra staging, ver "REGLA DE ORO" arriba) antes de
  tocar código: Rappi en producción tiene 12/12 SKUs de marca cliente
  (100% share) -- el 0% era 100% catálogo de staging, no un bug de
  detección de marca. `search_configs` en producción solo tiene 3 filas,
  las 3 con el mismo término "Toallas Higienicas" y activas -- no hay
  ningún término de prueba contaminando producción (si alguna vez
  aparece uno, desactivar con `PATCH /configs/{id}/toggle`, nunca
  borrar). Dos síntomas SÍ resultaron ser hallazgos reales, confirmados
  también contra producción: la contaminación de categoría en Locatel
  (ver "Retailers -- estado actual") y la mezcla de TENA en el promedio
  de precio del cliente (ver bullet siguiente) -- ambos requirieron
  seguir investigando con evidencia real en vez de aceptar el primer
  síntoma o descartarlo de plano.
- **PENDIENTE resuelto (2026-09-17): TENA inflaba `price_index` en 6 de
  7 retailers -- no era contaminación de categoría del lado de la
  competencia (como Colsubsidio/Locatel), sino una marca cliente sin
  competencia comparable bajo el término activo.** Al revisar por qué
  TODOS los retailers con Índice de Precio confiable mostraban valores
  extremos (188.5-227.8) incluso los ya confirmados "limpios" de
  contaminación (Éxito, Carulla, Farmatodo, La Rebaja, Pasteur,
  Coopidrogas), se listaron los productos de cliente más caros/baratos
  en los 2 retailers más extremos (Éxito, Coopidrogas): todos eran
  genuinamente "toallas higiénicas" comparables del lado de la
  competencia, pero del lado del CLIENTE, TENA (paquetes de 30-60
  unidades para "goteos moderados/abundantes" -- terminología de
  incontinencia, no de menstruación) promediaba 2.4x-3.6x el precio de
  Nosotras en los 6 retailers donde aparece bajo el término "Toallas
  Higienicas" (Éxito $47,044 vs $19,836; Coopidrogas $31,000 vs
  $12,313; Carulla $46,944 vs $20,769; Farmatodo $47,650 vs $20,786;
  Pasteur $39,237 vs $13,125 -- La Rebaja no tiene TENA capturado ahí).
  El cliente elegido: separar el índice (`CLIENT_BRANDS_PRICE_EXCLUDED`
  en `client_brands.py`, hoy `["tena"]`) -- price_index ahora se calcula
  solo con marcas comparables (Nosotras/Pequeñín/Zewa); el precio
  promedio de TENA se reporta aparte, informativo, sin índice, vía
  `client_price_excluded_avg_price`/`client_price_excluded_skus` en
  `/executive-summary`, `/insights` (por_retailer) y la sección 5 del
  PDF ejecutivo. TENA SIGUE contando como marca cliente para Share of
  Shelf, % DN/DP y disponibilidad -- el problema era solo de
  comparabilidad de precio bajo este término de búsqueda específico, no
  de presencia. Con Carulla como ejemplo: price_index bajó de 188.5
  (rojo, generaba alerta "precio_fuera_de_mercado") a 118.0 (amarillo,
  ahora genera oportunidad "precio_por_encima_del_mercado") -- un
  cambio real de categoría de severidad, no solo cosmético. Otras
  opciones consideradas y descartadas por el momento (dejarlo como está;
  excluir TENA del término de búsqueda en el scraper) -- ver historial
  de decisión si hace falta revisitarlas.
- **price_index: se agregó `price_index_median` COMO DATO ADICIONAL,
  sin reemplazar al promedio (2026-09-18), tras investigar promedio vs.
  moda vs. mediana con datos reales de producción.** Moda descartada:
  para 4 retailers (Éxito, Carulla, Farmatodo, Coopidrogas), el precio
  "más repetido" resultó venir de 1-2 productos individuales
  re-capturados en corridas sucesivas (ej. Carulla: 236 filas de
  cliente pero solo 13 productos únicos -- la moda con 20 repeticiones
  era UN solo producto), no de varios productos distintos convergiendo
  en un mismo precio -- no es una señal de mercado real, y al
  deduplicar a último snapshot por SKU (mismo criterio que Share of
  Shelf) cada producto casi siempre tiene un precio único, así que la
  moda deja de existir como concepto útil. Promedio vs. mediana sí se
  implementaron ambos (`price_index_median` junto a `price_index` en
  `_build_cell` de insights_engine.py y en `_fetch_summary_metrics` de
  analytics.py, expuesto en `/executive-summary`, `/insights`
  (por_retailer) y sección 5 del PDF ejecutivo) porque el comparativo
  con datos reales (último snapshot por SKU, TENA excluido de ambos
  lados igual que price_index normal) mostró que a veces casi coinciden
  y a veces difieren bastante, dependiendo de qué tan pareja sea la
  dispersión de precios de competencia:
  - Éxito (18 SKUs cliente / 24 competencia): 144.8 (promedio) vs. 145.8
    (mediana) -- casi idénticos, dispersión de competencia pareja.
  - Carulla (13 / 32): 118.0 vs. 150.0 -- bastante distintos. Se revisó
    la distribución completa de precios de competencia (32 productos,
    todos con precio distinto, de $1,650 a $39,900): es una dispersión
    amplia con cola a la derecha por TAMAÑOS DE EMPAQUE (8 unidades vs.
    60 unidades), no un par de outliers puntuales -- la mediana no es
    "más correcta" en sentido absoluto, es menos sensible a los
    paquetes grandes/premium que jalan el promedio hacia arriba.
  - Farmatodo (13 / 2): 130.1 vs. 117.1 -- competencia con solo 2 SKUs
    capturados bajo el término activo, muestra insuficiente para sacar
    ninguna conclusión de cuál métrica es más representativa aquí.
  - Coopidrogas (15 / 9): 133.9 vs. 143.8.
  La muestra de competencia es chica y variable entre retailers (2 a 32
  productos) -- **no se eligió una métrica principal todavía**: hace
  falta ver cómo se comportan ambas con más volumen de datos (más
  días de captura, más retailers con muestra amplia como Carulla) antes
  de decidir cuál usar como definitiva. Ninguna alerta/oportunidad/
  fortaleza del motor de insights usa `price_index_median` todavía
  (solo se generan sobre `price_index`/promedio) -- sigue siendo
  puramente informativo mientras tanto. Se hereda la misma mitigación
  de contaminación de categoría que price_index normal: se fuerza a
  None para Colsubsidio/Locatel (`RETAILERS_WITH_UNRELIABLE_PRICE_INDEX`).

## Retailers -- estado actual

**Producción (main), confirmados y funcionando:**
Éxito, Carulla, Farmatodo, La Rebaja, Locatel*, Colsubsidio*, Pasteur, Cafam*,
Coopidrogas, Rappi*.

*Cafam: posición, precio, marca y disponibilidad funcionan bien, pero
**NO expone descuentos reales vía su endpoint de búsqueda** (limitación
conocida, igual en espíritu a la de Rappi abajo). Confirmado con evidencia
real (2026-09-14): "has_discount" y los precios de la búsqueda AJAX vienen
iguales incluso cuando el producto sí tiene una oferta activa en el sitio
(ej. "Entero Balance": la home real muestra 99.900 -> 69.930, la búsqueda
dice que no hay descuento). El único dato confiable está en la página de
detalle de CADA producto individual -- corregirlo implicaría una petición
HTTP extra por producto, costosa porque Cafam ya está enrutado vía
ScraperAPI por el bloqueo de Cloudflare confirmado. Se decidió no
implementarlo por el costo; discount_price queda en None para Cafam a
propósito, no es un bug silencioso. Detalle completo en
cafam_scraper.py y en "Lecciones aprendidas" más abajo.

*Rappi: **activo en producción**, no pausado -- se reconstruyó por
completo (commit `259be38`, 2026-09-09) y ya NO requiere token de
invitado ni login: la página `/search?query=...` viene renderizada en
servidor (Next.js) con los productos embebidos como datos estructurados
JSON-LD (`schema.org`), pensados para Google pero igual de útiles para
nosotros (ver docstring de `rappi_scraper.py`). Corre sin condición
dentro de `run_all_scraping` en cada captura programada. Tiene filtro
de relevancia para excluir carruseles genéricos ajenos al término
buscado (ver "Filtro de relevancia" en Lecciones aprendidas). Igual que
Cafam, **no expone descuentos reales**: el JSON-LD solo trae un precio
final único, sin distinguir precio de lista vs. oferta -- por eso está
excluido de `pct_promoted` vía `RETAILERS_WITHOUT_RELIABLE_DISCOUNT`
(`{"cafam", "rappi"}` en `app/routers/analytics.py`). No maneja
multi-banner (Turbo, Pasteur, Farmaya) por separado -- si en el futuro
se ve necesario diferenciarlos, seguirá siendo trabajo pendiente, pero
el scraper base ya no está bloqueado ni requiere Playwright.

**Fix de clasificación de marca (Cafam y Colsubsidio, 2026-09-15):**
ambos exponían la razón social del fabricante/distribuidor en el campo
de marca en vez de la marca comercial real, lo que hacía que TODOS los
productos Nosotras/Tena se contaran como competencia (Share of Shelf
0% en ambos, confirmado con datos reales de producción). Corregido:
Cafam vía `_detect_client_brand()` (busca la marca cliente en el título
del producto, ver `cafam_scraper.py`), Colsubsidio vía
`brand_specification_field: "Marca Comercial"` en `RETAILER_CONFIGS`
(ver `vtex_scraper.py`). Verificado con datos reales de producción:
Cafam pasó de 0% a 75% de Share of Shelf; Colsubsidio de 0% a 70%
(snapshot en vivo, mismo término que usa producción). Al corregir esto
se descubrió un problema DISTINTO y sin resolver en Colsubsidio -- ver
el Índice de Precio abajo.

*Colsubsidio: Share of Shelf y clasificación de marca ya son confiables
(ver fix arriba), pero su **Índice de Precio NO es confiable todavía**
-- el buscador VTEX de Colsubsidio mezcla productos de otra categoría
(copas menstruales, kits reutilizables) con toallas desechables reales,
lo que distorsiona el precio promedio de competencia. Mitigado
forzando `price_index` a None para este retailer
(`RETAILERS_WITH_UNRELIABLE_PRICE_INDEX` en `analytics.py`) hasta que
exista un filtro de relevancia de categoría. Detalle completo en
"Lecciones aprendidas" más abajo (pendiente sin resolver).

*Locatel: **mismo problema que Colsubsidio, confirmado con evidencia
real (2026-09-17)** al investigar por qué su Índice de Precio salía
extremo en el PDF ejecutivo -- su buscador VTEX también mezcla copas
menstruales ("Copa Menstrual UVA Talla B" $99.900, "Copa Menstrual
LifeCup 1/2" $78.900 c/u) y toallas reutilizables ("Toallas Higiénicas
Reutilizables LifePad" $79.950) con toallas desechables reales,
inflando el precio promedio de competencia de $14.517 real (solo
Stayfree/Kotex) a $29.232 (2x). Mismo diagnóstico y misma mitigación
que Colsubsidio (`price_index` forzado a None vía
`RETAILERS_WITH_UNRELIABLE_PRICE_INDEX`). Se investigaron con el mismo
método Éxito, Carulla, Farmatodo, La Rebaja, Pasteur y Coopidrogas
(productos de competencia más caros + búsqueda por palabra clave
"copa"/"menstrual"/"reutilizable" en los ~180 productos de competencia
combinados de los 6) y **ninguno mostró contaminación** -- confirma que
el problema es específico de Colsubsidio y Locatel, no genérico de
VTEX. El filtro de relevancia de categoría pendiente (ver "Lecciones
aprendidas") debería ser genérico ahora que se confirmó en 2 retailers,
no hardcodeado a uno solo.

**IMPORTANTE -- `dn_pct`/`dp_pct`/`pct_promoted` de HOY (2026-09-15) están
temporalmente deprimidos, NO es un bug si se ve así en los próximos días.**
El fix de marca de Cafam/Colsubsidio (arriba) corrige la lógica del
SCRAPER hacia adelante -- no reescribe retroactivamente las filas que
ya están guardadas en la base de datos. Confirmado con evidencia real
(2026-09-15, con el fix ya mergeado a `main` y desplegado): una fila de
Cafam ("Toallas Nosotras Buenas Noches...") y otra de Colsubsidio
("Toallas Higiénicas Nosotras Invisible Sensitive") siguen con
`brand = 'PRODUCTOS FAMILIA S.A.'` guardado, porque fueron capturadas
por el scraper viejo. Como consecuencia, Cafam y Colsubsidio son HOY
los únicos 2 de los 10 retailers activos con `client_skus=0`, lo que
deprime `dn_pct` (80.0% hoy, sería 100.0% si ambos tuvieran presencia)
y `dp_pct` (89.4% hoy, sería 100.0%). `pct_promoted` (25.7% hoy) no se
ve afectado por Cafam directamente porque ya está excluido de ese
cálculo (`RETAILERS_WITHOUT_RELIABLE_DISCOUNT`), pero sí subirá o
bajará cuando Colsubsidio aporte sus propios SKUs de cliente con
descuento una vez que se recapture. **Estos 3 números subirán solos
en cuanto corra una captura nueva y exitosa de Cafam y Colsubsidio**
-- no hace falta ni se debe "arreglar" nada más en el código para eso.
Al momento de escribir esto la cuota de ScraperAPI está agotada (ver
"Retailers que dependen de ScraperAPI" en Lecciones aprendidas) y se
espera que renueve en ~11 días desde 2026-09-15 (es decir, alrededor
de 2026-09-26) -- podría ser antes si se resuelve la cuota o se
dispara `/trigger-now` manualmente para esos dos retailers.

**Pausados (investigados, pero bloqueados o de complejidad/costo alto):**
- Cruz Verde: Salesforce Commerce Cloud, protección fuerte en el subdominio
  de API (`api.cruzverde.com.co`) que ni ScraperAPI en modo `ultra_premium`
  logró sortear.
- Mercadolibre: ya no permite búsquedas sin autenticación OAuth 2.0 (requiere
  registrar app de desarrollador + flujo de login real) -- es un proyecto de
  integración de API, no un scraper.
- Farmalisto (confirmado 2026-09-17): dominio real `farmalisto.com.co`,
  plataforma PrestaShop 1.7.4.3 (tema Venedor) -- mismo tipo de plataforma
  que Cafam -- pero el buscador NO usa el motor nativo de PrestaShop
  (esa ruta, `/busqueda?s=...`, da error 500) ni una API HTTP simple de
  terceros: usa Doofinder vía **WebSocket**
  (`wss://us1-layer.doofinder.com/layer/1/websocket`), confirmado con
  captura real de DevTools. Requeriría implementar un cliente de
  WebSocket con un protocolo no documentado -- complejidad similar o
  mayor a la de Cruz Verde. Pausado por ahora.

**Descartados (investigados, técnicamente viables pero sin relevancia de negocio):**
- FarmaCenter (confirmado 2026-09-17): la cadena nacional tiene dos sitios
  distintos, no uno. `farmacenter.com.co` es el sitio institucional real
  de la cadena (Drupal 9, sin carrito/tienda -- sin ninguna tienda
  transaccional, ni siquiera enlazada). `farmacentervirtual.com`
  ("Droguería Farmacenter Virtual MBO") es la tienda transaccional real,
  pero pertenece a un operador/franquiciado regional, no a la cadena
  completa -- y expone WordPress + WooCommerce con la **Store API pública
  y sin autenticación** (`GET /wp-json/wc/store/products?search=<término>`,
  JSON limpio con name/sku/prices/is_in_stock/categories, sin bloqueo,
  sin necesidad de ScraperAPI -- el caso técnicamente más simple de
  todos los que hemos visto). El problema es de catálogo, no técnico:
  se revisaron las 10 categorías (420 productos únicos) buscando
  "toalla(s) higiénica(s)", "Nosotras", "Tena", "Kotex", "compresas" --
  **este catálogo no vende higiene femenina en absoluto**, solo
  "Toallas Húmedas" (toallitas de bebé, categoría distinta). Se
  descarta por ahora; si en el futuro se necesita monitorear otras
  categorías de Essity que si tenga este catálogo (vitaminas,
  medicamentos, cuidado del bebé), el patrón de WooCommerce Store API
  queda documentado y listo para reusar sin más investigación.

**Pendientes de investigar/agregar** (orden de la lista de Daniel):
Merqueo, Surtimax, Super Inter, Jumbo, Uno A droguerías,
Megatiendas, Tiendas D1, Tiendas Ara (D1 y Ara probablemente sin tienda
transaccional -- confirmar antes de invertir tiempo), Homecenter (Sodimac),
Olímpica, Alkosto, Falabella.com.co (tiene integración VTEX para vendedores
externos del marketplace, pero su catálogo propio no está confirmado).

## PDF ejecutivo (`GET /reports/executive-pdf`)

Reporte descargable de 8 secciones fijas (portada, resumen ejecutivo,
cita editorial, distribución por retailer, índice de precio por
retailer, posición dominante por retailer, conclusiones clave,
metodología) -- `app/services/pdf_report.py` (módulo puro, sin DB/
FastAPI) + `app/routers/reports.py` (arma los dicts desde
`/executive-summary`, `/insights`, `/methodology` y llama al generador).

**Librería: reportlab, no fpdf2 ni WeasyPrint** (decisión completa en el
docstring de `pdf_report.py`). Resumen: WeasyPrint da el mejor resultado
visual pero depende de librerías de sistema (Pango/Cairo/GDK-Pixbuf) que
no vienen con `pip install` -- riesgo de build extra en Railway que no
existe en el resto del backend. fpdf2 es puro Python pero sin sistema de
flujo de documento (páginas/tablas con salto automático), habría
significado posicionar todo a mano. reportlab es puro Python (mismo
perfil de riesgo que el resto de `requirements.txt`) y trae Platypus
(flujo/paginación) + `reportlab.graphics` (gráficas nativas para la
etapa 2, sin necesitar matplotlib ni imágenes intermedias).

**Build en dos etapas**: la versión etapa 1 (superada) era solo texto y
tablas con datos reales, sin paleta de marca ni gráficas -- para
confirmar que las 8 secciones traían los números correctos antes de
invertir tiempo en diseño visual.

**Etapa 2, Portada + Resumen Ejecutivo: hecho (2026-09-17, en
`staging`)**. `app/assets/logo_vantic.png` ya existe en el repo (el
usuario lo adjuntó directamente en la conversación, ruta original
`~/Downloads/LogoVantic.png`) -- el pendiente de "falta el logo" de esta
misma fecha quedó resuelto, ya no aplica. Paleta de marca (`COLOR_*` en
`pdf_report.py`) extraída con muestreo real de píxeles del logo (violeta
oscuro ~`#241640`, violeta medio ~`#5B3876`, lila ~`#8A5FA8`/`#D9C9EC`),
no inventada a ojo. Secciones 1-2 ahora usan `BaseDocTemplate` con
`PageTemplate` propio por sección (patrón nuevo en este archivo, no
existía en etapa 1): portada y resumen en horizontal tipo presentación
(fondo lila pálido, franja violeta oscuro, logo embebido, motivo de
círculos decorativo en portada); el resto del documento (secciones 3-8)
sigue en la plantilla vertical de la etapa 1 sin tocar -- la cita
editorial (sección 3) se movió a la misma página horizontal del resumen
como blockquote en vez de tener su propio salto de página, para que la
columna izquierda cuente una sola historia (prosa + cita) junto a la
tarjeta violeta de KPIs (Share of Shelf + DN/DP/Disponibilidad) de la
columna derecha. Verificado primero localmente (no hay `DATABASE_URL`
en el entorno local) generando el PDF con datos de prueba
representativos y renderizando páginas a imagen, y LUEGO contra la URL
real de staging desplegada (`/reports/executive-pdf`, ver "REGLA DE
ORO" arriba) con datos reales de producción-de-pruebas -- ambos pasos
hechos antes de considerar el trabajo terminado, ninguno reemplaza al
otro. Un primer intento de la tarjeta de KPIs tenía las etiquetas
("SHARE OF SHELF", "DN/DP/Disponib.") en lila oscuro sobre fondo
violeta -- casi ilegible por poco contraste, corregido usando el lila
claro (`#D9C9EC`) antes de subir nada.

**Bug real encontrado y corregido contra staging (2026-09-17)**: la
tabla de KPIs (DN/DP/Disponibilidad) anidada dentro de la tarjeta
violeta (`_kpi_stat_card` en `pdf_report.py`) se dimensionaba con el
ancho TOTAL de la tarjeta sin descontar su padding lateral
(`CARD_SIDE_PADDING`) -- invisible con datos de prueba inventados a
mano, pero con datos reales de staging (`availability_pct=100.0`) el
texto "100.0%" se salía físicamente del borde derecho de la tarjeta
violeta. Solo se detectó porque la verificación contra staging se hizo
con datos reales, no con el mock local -- confirma la razón de tener
ambos pasos de verificación, no solo el local. Corregido restando
`CARD_SIDE_PADDING*2` antes de repartir el ancho entre las 3 columnas;
re-verificado contra staging con el mismo dato real (100.0%) para
confirmar.

**Pendiente (etapa 2, resto del documento)**: secciones 4/5/6 siguen en
texto/tabla plano de la etapa 1 (sin gráficas nativas de
`reportlab.graphics` ni paleta de marca) -- a propósito, según el plan
original de aprobar portada+resumen por separado antes de replicar el
diseño al resto.

## Estilo de trabajo esperado

- Verificar SIEMPRE antes de afirmar que algo funciona: compilar, correr
  pruebas con datos reales capturados, no solo revisar visualmente.
- Cambios quirúrgicos: preferir ediciones puntuales sobre reescrituras
  amplias de archivos que ya funcionan.
- Nunca asumir la estructura de un archivo del proyecto sin leerlo primero
  -- puede haber cambiado desde la última vez.