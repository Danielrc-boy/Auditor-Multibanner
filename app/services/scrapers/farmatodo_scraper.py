import os
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

# Variables de Algolia capturadas del proxy oficial de Farmatodo
FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("FARMATODO_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("FARMATODO_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("FARMATODO_INDEX_NAME", "products-colombia")

class FarmatodoScraper:
    def __init__(self):
        self.url = FARMATODO_ALGOLIA_URL
        self.headers = {
            "x-algolia-application-id": FARMATODO_APP_ID,
            "x-algolia-api-key": FARMATODO_API_KEY,
            "content-type": "application/json",
            "origin": "https://www.farmatodo.com.co",
            "referer": "https://www.farmatodo.com.co/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        payload = {
            "requests": [
                {
                    "indexName": FARMATODO_INDEX_NAME,
                    "params": f"query={search_term}&hitsPerPage={limit}&page=0"
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.url, json=payload, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                
                # Algolia retorna una lista de resultados dentro de 'results'
                results_list = data.get("results", [])
                if not results_list:
                    return []
                
                hits = results_list[0].get("hits", [])
                return self._parse_products(hits, search_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, hits: list, search_term: str) -> list:
        parsed_results = []

        for index, item in enumerate(hits, start=1):
            try:
                # 1. Título real mapeado desde mediaDescription
                title_val = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title_val = str(title_val).strip() if title_val else "Sin título"

                # 2. Marca (extraída del campo o de la primera palabra del título)
                extracted_brand = item.get("brand") or item.get("brandName") or item.get("marca")
                if isinstance(extracted_brand, dict):
                    extracted_brand = extracted_brand.get("name")

                if not extracted_brand or str(extracted_brand).strip() in ["", "None", "null", "Sin Marca"]:
                    if title_val != "Sin título":
                        extracted_brand = title_val.split()[0].capitalize()
                    else:
                        extracted_brand = "Sin Marca"

                # 3. Mapeo de precios reales de Algolia
                base_price = float(item.get("fullPrice", 0.0) or item.get("price", 0.0))
                offer_price = item.get("offerPrice")
                
                discount_price = None
                if offer_price is not None:
                    offer_val = float(offer_price)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                # 4. Control de stock desde outofstore
                is_out_of_store = bool(item.get("outofstore", False))
                in_stock = not is_out_of_store

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val,
                    brand=str(extracted_brand).strip(),
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results