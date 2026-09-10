"""
Scraper de Cruz Verde.

Plataforma confirmada con evidencia real: Salesforce Commerce Cloud
(Demandware) -- NO es VTEX ni Algolia, tiene su propia API de búsqueda:
    https://api.cruzverde.com.co/product-service/products/search

A diferencia de Rappi (que devolvía carruseles genéricos sin relación
con el término buscado), este SÍ es un endpoint de búsqueda real --
el parámetro "q" filtra server-side. Por eso, a diferencia de Rappi/
Farmatodo, NO se aplica un filtro de relevancia adicional aquí: se
confía en que la API ya está devolviendo resultados relacionados al
término.

Nota importante: la petición captura usa inventoryId/inventoryZone
fijos en "COCV_zona64" (una zona/bodega específica, probablemente
asociada a Bogotá). Si en producción los resultados salen vacíos o
distintos a lo esperado en otras ciudades, este es el primer parámetro
a revisar.
"""
import os
import urllib.parse
import httpx
from typing import List, Optional
from pydantic import BaseModel

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")
CRUZVERDE_USE_SCRAPERAPI = os.getenv("CRUZVERDE_USE_SCRAPERAPI", "false").lower() == "true"

# Confirmado por captura real de DevTools -- zona de inventario de Bogotá.
DEFAULT_INVENTORY_ZONE = "COCV_zona64"


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


class CruzVerdeScraper:
    def __init__(self, inventory_zone: str = DEFAULT_INVENTORY_ZONE):
        self.base_url = "https://api.cruzverde.com.co/product-service/products/search"
        self.inventory_zone = inventory_zone
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

    def _build_request(self, params: dict):
        if CRUZVERDE_USE_SCRAPERAPI and SCRAPERAPI_KEY:
            target_url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return self.base_url, params

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        params = {
            "limit": limit,
            "offset": 0,
            "sort": "",
            "q": keyword,
            "inventoryId": self.inventory_zone,
            "inventoryZone": self.inventory_zone,
        }
        request_url, request_params = self._build_request(params)

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
                response = await client.get(request_url, headers=self.headers, params=request_params)
                print(f"[DIAG CRUZVERDE] Status recibido: {response.status_code}", flush=True)

                if response.status_code != 200:
                    print(f"[ERROR CRUZVERDE] HTTP Status {response.status_code} para '{keyword}'", flush=True)
                    return []

                data = response.json()
                return self._parse_response(data, keyword, limit)

        except Exception as e:
            print(f"[ERROR CRUZVERDE] Error al scrapear '{keyword}': {e}", flush=True)
            return []

    def _extract_prices(self, prices: dict):
        """
        El objeto 'prices' trae claves variables segun el producto:
        - price-list-col: precio de lista (siempre presente)
        - price-club-col: precio para miembros del Club Cruz Verde (si aplica)
        - price-sale-col: precio en oferta (si aplica)
        Se toma el menor entre club/sale como descuento, si existe y es
        menor al precio de lista.
        """
        base_price = float(prices.get("price-list-col", 0.0) or 0.0)

        candidate_discounts = [
            v for k, v in prices.items()
            if k in ("price-club-col", "price-sale-col") and v is not None
        ]
        discount_price = None
        if candidate_discounts:
            lowest = min(float(v) for v in candidate_discounts)
            if 0 < lowest < base_price:
                discount_price = lowest

        if base_price == 0 and discount_price:
            base_price = discount_price
            discount_price = None

        return base_price, discount_price

    def _parse_response(self, data: dict, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed: List[ExtractedProductData] = []
        hits = data.get("hits", [])

        for idx, hit in enumerate(hits[:limit], start=1):
            try:
                if hit.get("hitType") != "product":
                    continue

                title = (hit.get("productName") or "").strip()
                if not title:
                    continue

                brand = (hit.get("brand") or "Sin Marca").strip()
                stock = hit.get("stock", 0) or 0
                in_stock = stock > 0

                prices = hit.get("prices", {}) or {}
                base_price, discount_price = self._extract_prices(prices)

                parsed.append(
                    ExtractedProductData(
                        search_keyword=search_term,
                        search_position=idx,
                        title=title,
                        brand=brand,
                        base_price=base_price,
                        discount_price=discount_price,
                        in_stock=in_stock,
                    )
                )
            except Exception as e:
                print(f"[PARSER ERROR] CRUZVERDE: {e}", flush=True)
                continue

        return parsed