import os
import urllib.parse
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

SCRAPERAPI_KEY = os.getenv("SCRAPER_API_KEY") or os.getenv("SCRAPERAPI_KEY")

class FarmatodoScraper:
    def __init__(self):
        self.base_url = "https://www.farmatodo.com.co/api/v1/products/search"

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        encoded_term = urllib.parse.quote(search_term)
        target_url = f"{self.base_url}?query={encoded_term}&limit={limit}"
        
        if SCRAPERAPI_KEY:
            request_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={urllib.parse.quote(target_url)}"
            headers = {"Accept": "application/json"}
        else:
            request_url = target_url
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json"
            }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return self._parse_products(data, search_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, data: dict, search_term: str) -> list:
        parsed_results = []
        raw_items = data.get("products", []) if isinstance(data, dict) else []

        for index, item in enumerate(raw_items, start=1):
            try:
                title_val = item.get("name", "").strip() or "Sin título"
                extracted_brand = item.get("brand") or item.get("brandName")

                if not extracted_brand and title_val != "Sin título":
                    extracted_brand = title_val.split()[0].capitalize()

                price = float(item.get("price", 0.0))
                disc_price = float(item.get("discountPrice", 0.0)) if item.get("discountPrice") else None
                in_stock = bool(item.get("inStock", True))

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val,
                    brand=str(extracted_brand).strip() if extracted_brand else "Sin Marca",
                    base_price=price,
                    discount_price=disc_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results