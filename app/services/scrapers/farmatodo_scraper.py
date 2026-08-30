import os
import urllib.parse
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

class FarmatodoScraper:
    def __init__(self):
        self.app_id = os.getenv("ALGOLIA_APP_ID", "118C283I39")
        self.api_key = os.getenv("ALGOLIA_API_KEY", "d1ae8a2bd887460e48119ae4cf14022c")
        self.index_name = os.getenv("ALGOLIA_INDEX_NAME", "products_COL_price_asc")
        self.endpoint = f"https://{self.app_id}-1.algolianet.com/1/indexes/*/queries"

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        headers = {
            "x-algolia-application-id": self.app_id,
            "x-algolia-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        params_str = f"query={urllib.parse.quote(search_term)}&hitsPerPage={limit}&page=0"
        payload = {
            "requests": [
                {
                    "indexName": self.index_name,
                    "params": params_str
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.endpoint, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results", [])
                if not results:
                    return []
                
                hits = results[0].get("hits", [])
                return self._parse_products(hits, search_term)

            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []
        for index, item in enumerate(raw_hits, start=1):
            try:
                # Titulo y descripción del producto en Algolia
                title = item.get("mediaDescription") or item.get("description") or item.get("brand", "Sin título")
                
                # Manejo de precios
                price_regular = float(item.get("priceRegular", 0.0) or item.get("price", 0.0))
                price_offer = float(item.get("priceOffer", 0.0) or price_regular)
                
                if price_offer > 0 and price_offer < price_regular:
                    base_price = price_regular
                    discount_price = price_offer
                else:
                    base_price = price_regular if price_regular > 0 else price_offer
                    discount_price = None

                # Disponibilidad y stock
                stock = item.get("stock", 0)
                available = stock > 0 if stock is not None else True

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=available
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results