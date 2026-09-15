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

`app/main.py` es intencionalmente corto (~45 líneas): solo arranca la app,
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

## Retailers -- estado actual

**Producción (main), confirmados y funcionando:**
Éxito, Carulla, Farmatodo, La Rebaja, Locatel, Colsubsidio, Pasteur, Cafam*.

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

**Pausados (investigados, pero bloqueados o de complejidad/costo alto):**
- Rappi: multi-banner (Turbo, Pasteur, Farmaya...), requiere login para
  algunos banners, probablemente necesite Playwright (navegador real) en
  vez de peticiones HTTP simples.
- Cruz Verde: Salesforce Commerce Cloud, protección fuerte en el subdominio
  de API (`api.cruzverde.com.co`) que ni ScraperAPI en modo `ultra_premium`
  logró sortear.
- Mercadolibre: ya no permite búsquedas sin autenticación OAuth 2.0 (requiere
  registrar app de desarrollador + flujo de login real) -- es un proyecto de
  integración de API, no un scraper.

**Pendientes de investigar/agregar** (orden de la lista de Daniel):
Coopidrogas (confirmado VTEX, vía dominio real farmaexpress.com -- listo
para agregar), FarmaCenter, Farmalisto (sospecha PrestaShop, sitio bloqueó
el acceso directo), Merqueo, Surtimax, Super Inter, Jumbo, Uno A droguerías,
Megatiendas, Tiendas D1, Tiendas Ara (D1 y Ara probablemente sin tienda
transaccional -- confirmar antes de invertir tiempo), Homecenter (Sodimac),
Olímpica, Alkosto, Falabella.com.co (tiene integración VTEX para vendedores
externos del marketplace, pero su catálogo propio no está confirmado).

## Estilo de trabajo esperado

- Verificar SIEMPRE antes de afirmar que algo funciona: compilar, correr
  pruebas con datos reales capturados, no solo revisar visualmente.
- Cambios quirúrgicos: preferir ediciones puntuales sobre reescrituras
  amplias de archivos que ya funcionan.
- Nunca asumir la estructura de un archivo del proyecto sin leerlo primero
  -- puede haber cambiado desde la última vez.