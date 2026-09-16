"""
Scraper de Droguerías Cafam.

Plataforma confirmada con evidencia real: PrestaShop (Alysum AMP Template)
-- distinta a VTEX, Algolia, y Salesforce Commerce Cloud.

El endpoint de búsqueda estándar de PrestaShop:
    https://www.drogueriascafam.com.co/index.php?controller=search&s={termino}&ajax=1&resultsPerPage={limit}

devuelve un JSON con una lista "products" ya estructurada (no hace falta
parsear HTML) -- confirmado con datos reales: id_product, price_amount,
regular_price_amount, has_discount, manufacturer_name, position.

Limitación conocida (brand): confirmado con evidencia real (2026-09-15)
que "manufacturer_name" NO es la marca comercial -- es la razón social
del fabricante/distribuidor (ej. "PRODUCTOS FAMILIA S.A.",
"OPERADOR LOGISTICO INT DE MEDI"). Este endpoint no expone NINGÚN campo
de marca comercial real; la única señal disponible es el nombre del
producto ("name"), donde la marca sí aparece como texto libre (ej.
"Toallas Nosotras Buenas Noches..."). Por eso _detect_client_brand()
busca las marcas cliente (CLIENT_BRANDS) como palabra completa dentro de
"name" ANTES de usar manufacturer_name -- corrige la clasificación
cliente-vs-competencia (Share of Shelf, Índice de Precio, motor de
insights), pero es un fix parcial a propósito: para productos de
competencia, "brand" sigue siendo la razón social, no una marca real --
eso no se intenta arreglar aquí porque requeriría un mapeo mucho más
amplio y frágil, y no es lo que rompía la clasificación del cliente.

Limitación conocida: este JSON no expone un campo explícito de stock/
disponibilidad (a diferencia del HTML de la misma página, que sí marca
la clase "out-of-stock" en cada producto). Por ahora in_stock siempre
se reporta como True -- si más adelante se necesita disponibilidad real,
habría que complementar con el HTML (rendered_products) en vez del JSON.

Limitación conocida (discount_price): confirmado con evidencia real
(2026-09-14) que "has_discount" y "price_amount"/"regular_price_amount"
de este endpoint de búsqueda NO reflejan descuentos reales activos --
ej. "Entero Balance" mostraba has_discount=False y ambos precios iguales
($99.900) en la búsqueda, mientras que la home real del sitio mostraba
$99.900 -> $69.930 (30% off) para el mismo producto. El precio real solo
está disponible en la página de detalle de CADA producto individual
(microdata itemprop="price"), lo que implicaría una petición HTTP extra
POR PRODUCTO -- costoso porque Cafam ya está enrutado vía ScraperAPI por
el bloqueo de Cloudflare confirmado. Decisión (2026-09-14): no
implementar por ahora por el costo; discount_price se deja en None para
Cafam de forma consistente, igual que la limitación ya documentada de
Rappi. Revisar esta decisión si el costo de ScraperAPI deja de ser un
problema o si el descuento se vuelve crítico para el negocio.
"""
import os
import re
import urllib.parse
import httpx
from typing import List, Optional
from pydantic import BaseModel
from app.services.client_brands import CLIENT_BRANDS

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


def _detect_client_brand(title: str) -> Optional[str]:
    """Busca una marca cliente (CLIENT_BRANDS) como palabra completa
    dentro del nombre del producto -- ver limitación documentada arriba
    sobre por qué manufacturer_name no sirve para esto."""
    title_lower = title.lower()
    for b in CLIENT_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", title_lower):
            return b
    return None


class CafamScraper:
    def __init__(self):
        self.base_url = "https://www.drogueriascafam.com.co/index.php"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _build_request(self, params: dict):
        if SCRAPERAPI_KEY:
            target_url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return self.base_url, params

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        params = {
            "controller": "search",
            "s": keyword,
            "ajax": "1",
            "resultsPerPage": limit,
        }
        request_url, request_params = self._build_request(params)
        # Al pasar por ScraperAPI no se envian nuestros headers propios
        # (esos son para el sitio destino, no para el proxy).
        request_headers = None if SCRAPERAPI_KEY else self.headers

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
                response = await client.get(request_url, headers=request_headers, params=request_params)
                print(f"[DIAG CAFAM] Status recibido: {response.status_code}", flush=True)

                if response.status_code != 200:
                    print(f"[ERROR CAFAM] HTTP Status {response.status_code} para '{keyword}' | Body: {response.text[:300]}", flush=True)
                    return []

                data = response.json()
                products = data.get("products", [])
                print(f"[DIAG CAFAM] Productos encontrados: {len(products)}", flush=True)
                return self._parse_products(products, keyword, limit)

        except Exception as e:
            print(f"[ERROR CAFAM] Error al scrapear '{keyword}': {type(e).__name__}: {e!r}", flush=True)
            return []

    def _parse_products(self, products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed: List[ExtractedProductData] = []

        for idx, item in enumerate(products[:limit], start=1):
            try:
                title = (item.get("name") or "").strip()
                if not title:
                    continue

                brand = _detect_client_brand(title) or (item.get("manufacturer_name") or "Sin Marca").strip()

                base_price = float(item.get("regular_price_amount") or item.get("price_amount") or 0.0)
                discount_price = None
                if item.get("has_discount") and item.get("price_amount") is not None:
                    discount_price = float(item["price_amount"])

                # NOTA: se descarto usar el campo "position" que trae la
                # propia plataforma -- confirmado con datos reales que no
                # refleja el orden de aparicion en la busqueda (varios
                # productos distintos venian con el mismo valor). Se numera
                # por el orden real en que llegan los resultados, igual
                # que se hace con Rappi.
                position = idx

                parsed.append(
                    ExtractedProductData(
                        search_keyword=search_term,
                        search_position=position,
                        title=title,
                        brand=brand,
                        base_price=base_price,
                        discount_price=discount_price,
                        in_stock=True,  # ver limitacion documentada arriba
                    )
                )
            except Exception as e:
                print(f"[PARSER ERROR] CAFAM: {e}", flush=True)
                continue

        return parsed