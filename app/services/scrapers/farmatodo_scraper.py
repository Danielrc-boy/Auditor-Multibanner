import os
import urllib.parse
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

class FarmatodoScraper:
    def __init__(self):
        raw_app_id = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")
        self.app_id = raw_app_id.strip()
        self.app_id_lower = self.app_id.lower()
        
        self.api_key = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb").strip()
        self.index_name = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia").strip()
        
        self.endpoint = f"https://{self.app_id_lower}-dsn.algolia.net/1/indexes/*/queries"

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        headers = {
            "x-algolia-application-id": self.app_id,
            "x-algolia-api-key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.farmatodo.com.co",
            "Referer": "https://www.farmatodo.com.co/"
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
                title = item.get("description") or item.get("name") or item.get("title") or item.get("brand", "Sin título")
                
                price_regular = float(item.get("price", 0.0) or item.get("priceRegular", 0.0))
                price_offer = float(item.get("offerPrice", 0.0) or item.get("priceOffer", 0.0) or price_regular)
                
                if price_offer > 0 and price_offer < price_regular:
                    base_price = price_regular
                    discount_price = price_offer
                else:
                    base_price = price_regular if price_regular > 0 else price_offer
                    discount_price = None

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