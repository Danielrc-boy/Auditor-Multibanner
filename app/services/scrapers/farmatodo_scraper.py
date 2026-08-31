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
        clean_term = search_term.strip()
        
        # Parámetros exactos que utiliza la web oficial de Farmatodo para búsquedas por Algolia
        params_str = (
            f"query={clean_term}"
            f"&hitsPerPage={limit}"
            f"&page=0"
            f"&analytics=true"
            f"&clickAnalytics=true"
            f"&typoTolerance=false"
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
                return self._parse_products(hits, clean_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al consultar Algolia para '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, hits: list, search_term: str) -> list:
        parsed_results = []
        position = 1

        for item in hits:
            try:
                # 1. Título real
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                # 2. Búsqueda estricta de la MARCA real en la estructura del JSON de Algolia
                brand_obj = item.get("brand") or item.get("brandName") or item.get("marca") or item.get("brand_name")
                
                real_brand = ""
                if isinstance(brand_obj, dict):
                    real_brand = brand_obj.get("name") or brand_obj.get("label") or ""
                elif isinstance(brand_obj, list) and len(brand_obj) > 0:
                    real_brand = brand_obj[0]
                elif isinstance(brand_obj, str):
                    real_brand = brand_obj

                real_brand = str(real_brand).strip()

                # Si Algolia no entrega marca o entrega un ID numérico/sucio, extraemos por presencia explícita
                is_invalid = not real_brand or real_brand.lower() in ["none", "null", "sin marca"] or bool(re.search(r'\d', real_brand) and '-' in real_brand)

                if is_invalid:
                    # Jamás asignamos la primera palabra del título. Se busca la palabra de búsqueda en el título.
                    if search_term.lower() in title.lower():
                        real_brand = search_term.capitalize()
                    else:
                        real_brand = "Sin Marca"

                # 3. FILTRADO DE SEGMENTACIÓN (Discard basura)
                # Si se buscó una marca explícita, filtramos los resultados irrelevantes que manda Algolia por fuzzy matching
                if search_term.lower() not in title.lower() and search_term.lower() not in real_brand.lower():
                    continue

                # 4. Precios y disponibilidad
                base_price = float(item.get("fullPrice", 0.0) or item.get("price", 0.0))
                offer_price = item.get("offerPrice")
                
                discount_price = None
                if offer_price is not None:
                    offer_val = float(offer_price)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                in_stock = not bool(item.get("outofstore", False))

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=position,
                    title=title,
                    brand=real_brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
                position += 1

            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results