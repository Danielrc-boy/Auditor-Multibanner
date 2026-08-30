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

        # Codificación estricta de parámetros para asegurar relevancia exacta de búsqueda
        encoded_term = urllib.parse.quote(search_term)
        params_str = f"query={encoded_term}&hitsPerPage={limit}&page=0&queryType=prefixAll&typoTolerance=true"
        
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
                media_desc = item.get("mediaDescription")
                title_desc = item.get("title")
                item_desc = item.get("description") or ""
                brand = item.get("brand", "")

                if media_desc and not media_desc.startswith("2008"):
                    title = media_desc
                elif title_desc and not title_desc.startswith("2008"):
                    title = title_desc
                else:
                    title = f"{brand} {item_desc}".strip() if brand else item_desc

                # Filtrar items plantilla y asegurar que el título coincida mínimamente con el contexto o marca
                if not title or title.startswith("2008M-") or "2008M-" in item_desc:
                    continue

                price_regular = float(item.get("price", 0.0) or item.get("priceRegular", 0.0))
                price_offer = float(item.get("offerPrice", 0.0) or item.get("priceOffer", 0.0) or price_regular)
                
                if price_offer > 0 and price_offer < price_regular:
                    base_price = price_regular
                    discount_price = price_offer
                else:
                    base_price = price_regular if price_regular > 0 else price_offer
                    discount_price = None

                total_stock = item.get("totalStock")
                stock_val = item.get("stock")
                is_active = item.get("active", True)
                
                if total_stock is not None:
                    available = int(total_stock) > 0
                elif stock_val is not None:
                    available = int(stock_val) > 0
                else:
                    available = bool(is_active)

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