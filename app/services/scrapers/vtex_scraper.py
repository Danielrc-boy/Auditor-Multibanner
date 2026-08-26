import os
import httpx
from typing import List
from app.services.scrapers.base import ExtractedProductData

class VTEXScraper:
    def __init__(self, base_url: str = "https://www.exito.com"):
        self.base_url = base_url.rstrip("/")
        # Intenta leer de entorno; usa la nueva API Key como fallback
        self.api_key = os.getenv("SCRAPERAPI_KEY") or "a5b2666ef108f22085116902d58b67ba"

    async def search_keyword(self, keyword: str, limit: int = 10) -> List[ExtractedProductData]:
        if not self.api_key:
            raise Exception("SCRAPERAPI_KEY no está configurada en las variables de entorno.")

        target_url = f"{self.base_url}/io/api/catalog_system/pub/products/search/{keyword}"

        # Configuración del proxy vía API de ScraperAPI
        scraperapi_url = "http://api.scraperapi.com"
        params = {
            "api_key": self.api_key,
            "url": target_url,
            "keep_headers": "true"  # Mantiene los headers del navegador
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": self.base_url,
        }

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(scraperapi_url, params=params, headers=headers)

            print(f"[LOG SCRAPERAPI VTEX] Status: {response.status_code} para palabra: '{keyword}'", flush=True)

            if response.status_code not in [200, 206]:
                raise Exception(f"ScraperAPI Error: Status {response.status_code} - Body: {response.text[:200]}")

            raw_products = response.json()
            extracted_items = []

            for idx, prod in enumerate(raw_products[:limit], start=1):
                items = prod.get("items", [])
                if not items:
                    continue

                item = items[0]
                sellers = item.get("sellers", [{}])
                comm_offer = sellers[0].get("commertialOffer", {}) if sellers else {}

                base_price = comm_offer.get("ListPrice", 0.0)
                discount_price = comm_offer.get("Price", 0.0)

                if discount_price >= base_price:
                    discount_price = None

                in_stock = comm_offer.get("AvailableQuantity", 0) > 0

                extracted_items.append(ExtractedProductData(
                    title=prod.get("productName", "Sin título"),
                    brand=prod.get("brand", "Genérica"),
                    ean_gtin=item.get("ean"),
                    search_keyword=keyword,
                    search_position=idx,
                    base_price=float(base_price),
                    discount_price=float(discount_price) if discount_price else None,
                    is_sponsored=False,
                    in_stock=in_stock
                ))

            return extracted_items