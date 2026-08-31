import os
import re
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

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
        term_clean = search_term.strip()
        
        # Parámetros estrictos enviando la consulta y deshabilitando la separación difusa
        params_str = (
            f"query={term_clean}"
            f"&hitsPerPage={limit}"
            f"&page=0"
            f"&advancedSyntax=true"
            f"&removeStopWords=false"
        )

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
                response = await client.post(self.url, json=payload, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                
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
        valid_position = 1

        for item in hits:
            try:
                # 1. Título real
                title_val = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title_val = str(title_val).strip() if title_val else ""

                if not title_val:
                    continue

                # 2. Extracción limpia de la MARCA real desde los campos de Algolia
                raw_brand = (
                    item.get("brand") 
                    or item.get("brandName") 
                    or item.get("marca") 
                    or item.get("brand_name")
                )

                if isinstance(raw_brand, dict):
                    raw_brand = raw_brand.get("name") or raw_brand.get("label")
                elif isinstance(raw_brand, list) and len(raw_brand) > 0:
                    raw_brand = raw_brand[0]

                brand_str = str(raw_brand).strip() if raw_brand else ""
                
                # Validar si viene un código sucio o 'None'
                is_invalid_brand = not brand_str or brand_str in ["None", "null", "Sin Marca"] or bool(re.search(r'\d', brand_str) and '-' in brand_str)

                if is_invalid_brand:
                    # Si el término buscado está en el título, esa es la marca. Si no, asignamos "Sin Marca"
                    if search_term.lower() in title_val.lower():
                        final_brand = search_term.capitalize()
                    else:
                        final_brand = "Sin Marca"
                else:
                    final_brand = brand_str

                # 3. FILTRO DE RELEVANCIA
                # Si estamos buscando una marca específica como "Nosotras", ignorar productos que sean bebidas, bolsas o chicles
                if search_term.lower() in ["nosotras", "winny", "huggies", "colgate"]:
                    # Si el producto no contiene el término ni en el título ni en la marca real de Algolia, es Basura de Algolia
                    if (search_term.lower() not in title_val.lower()) and (search_term.lower() not in final_brand.lower()):
                        continue

                # 4. Precios
                base_price = float(item.get("fullPrice", 0.0) or item.get("price", 0.0))
                offer_price = item.get("offerPrice")
                
                discount_price = None
                if offer_price is not None:
                    offer_val = float(offer_price)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                # 5. Stock
                is_out_of_store = bool(item.get("outofstore", False))
                in_stock = not is_out_of_store

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=valid_position,
                    title=title_val,
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