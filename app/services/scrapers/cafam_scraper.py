"""
Scraper de Droguerías Cafam.

Plataforma confirmada con evidencia real: PrestaShop (Alysum AMP Template)
-- distinta a VTEX, Algolia, y Salesforce Commerce Cloud.

El endpoint de búsqueda estándar de PrestaShop:
    https://www.drogueriascafam.com.co/index.php?controller=search&s={termino}&ajax=1&resultsPerPage={limit}

devuelve un JSON con una lista "products" ya estructurada (no hace falta
parsear HTML) -- confirmado con datos reales: id_product, price_amount,
regular_price_amount, has_discount, manufacturer_name (marca), position.

Limitación conocida: este JSON no expone un campo explícito de stock/
disponibilidad (a diferencia del HTML de la misma página, que sí marca
la clase "out-of-stock" en cada producto). Por ahora in_stock siempre
se reporta como True -- si más adelante se necesita disponibilidad real,
habría que complementar con el HTML (rendered_products) en vez del JSON.
"""
import os
import urllib.parse
import httpx
from typing import List, Optional
from pydantic import BaseModel

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
CAFAM_USE_SCRAPERAPI = os.getenv("CAFAM_USE_SCRAPERAPI", "false").lower() == "true"


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


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
        if CAFAM_USE_SCRAPERAPI and SCRAPERAPI_KEY:
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

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
                response = await client.get(request_url, headers=self.headers, params=request_params)
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

                brand = (item.get("manufacturer_name") or "Sin Marca").strip()

                base_price = float(item.get("regular_price_amount") or item.get("price_amount") or 0.0)
                discount_price = None
                if item.get("has_discount") and item.get("price_amount") is not None:
                    discount_price = float(item["price_amount"])

                # Usa la posicion que reporta la propia plataforma (ordenada
                # por relevancia); si no viene, se numera por orden de llegada.
                try:
                    position = int(item.get("position", idx))
                except (TypeError, ValueError):
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