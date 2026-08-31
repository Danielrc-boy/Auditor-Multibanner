import os
import re
import urllib.parse
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

# Proxy oficial de Farmatodo (evita NameResolutionError)
FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia")

class FarmatodoScraper:
    def __init__(self):
        self.endpoint = FARMATODO_ALGOLIA_URL
        self.headers = {
            "x-algolia-application-id": FARMATODO_APP_ID.strip(),
            "x-algolia-api-key": FARMATODO_API_KEY.strip(),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://www.farmatodo.com.co",
            "Referer": "https://www.farmatodo.com.co/"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        clean_term = search_term.strip()
        params_str = f"query={urllib.parse.quote(clean_term)}&hitsPerPage={limit}&page=0"
        payload = {
            "requests": [
                {
                    "indexName": FARMATODO_INDEX_NAME,
                    "params": params_str
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.endpoint, headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results", [])
                if not results:
                    return []
                
                hits = results[0].get("hits", [])
                return self._parse_products(hits, clean_term)

            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{clean_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []
        valid_position = 1

        for item in raw_hits:
            try:
                # 1. Título real mapeado rigurosamente desde mediaDescription
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                # 2. Extracción y saneamiento de Marca
                raw_brand = item.get("brand") or item.get("brandName") or item.get("marca") or item.get("brand_name")
                if isinstance(raw_brand, dict):
                    raw_brand = raw_brand.get("name") or raw_brand.get("label")
                elif isinstance(raw_brand, list) and len(raw_brand) > 0:
                    raw_brand = raw_brand[0]

                brand_str = str(raw_brand).strip() if raw_brand else ""

                # Filtrar códigos de proveedor (ej: 2008M-..., números con guion, o vacíos)
                is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str) or brand_str.startswith("2008")
                is_invalid_brand = not brand_str or brand_str.lower() in ["none", "null", "sin marca"] or is_code_brand

                if is_invalid_brand:
                    if search_term.lower() in title.lower():
                        final_brand = search_term.capitalize()
                    else:
                        final_brand = "Sin Marca"
                else:
                    final_brand = brand_str

                # 3. Precios reales de Algolia (fullPrice y offerPrice)
                base_price = float(item.get("fullPrice", 0.0) or item.get("price", 0.0))
                offer_price = item.get("offerPrice")
                
                discount_price = None
                if offer_price is not None:
                    offer_val = float(offer_price)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                # 4. Control de stock riguroso usando 'outofstore'
                is_out_of_store = bool(item.get("outofstore", False))
                in_stock = not is_out_of_store

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=valid_position,
                    title=title,
                    brand=final_brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
                valid_position += 1

            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results