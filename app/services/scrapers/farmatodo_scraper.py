import os
import re
import unicodedata
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("FARMATODO_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("FARMATODO_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("FARMATODO_INDEX_NAME", "products-colombia")


def _normalize_text(text: str) -> str:
    """Remueve tildes, signos y convierte a minúsculas para comparaciones limpias."""
    if not text:
        return ""
    text = unicodedata.normalize('NFD', str(text))
    text = re.sub(r'[\u0300-\u036f]', '', text)
    return text.lower().strip()


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
        params_str = f"query={search_term.strip()}&hitsPerPage={limit}&page=0"

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
                    print(f"[FARMATODO] Respuesta vacía de Algolia para '{search_term}'", flush=True)
                    return []
                
                hits = results_list[0].get("hits", [])
                print(f"[FARMATODO] Algolia retornó {len(hits)} hits iniciales para '{search_term}'", flush=True)
                return self._parse_products(hits, search_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, hits: list, search_term: str) -> list:
        parsed_results = []
        
        # Palabras individuales del término buscado
        search_words = [w for w in _normalize_text(search_term).split() if len(w) > 2]

        for index, item in enumerate(hits, start=1):
            try:
                # 1. Título real del producto
                title_val = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title_val = str(title_val).strip() if title_val else "Sin título"

                # 2. Extracción de marca original
                raw_brand = item.get("brand") or item.get("brandName") or item.get("marca")
                if isinstance(raw_brand, dict):
                    raw_brand = raw_brand.get("name")

                brand_str = str(raw_brand).strip() if raw_brand else ""
                is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str)

                # Validar relevancia: al menos una palabra de la búsqueda debe estar contenida en el título o la marca
                combined_target_text = _normalize_text(f"{title_val} {brand_str}")

                if search_words and not any(word in combined_target_text for word in search_words):
                    continue

                # Marca honesta: si no viene en el JSON o es un código, poner "Sin Marca"
                if not brand_str or brand_str in ["None", "null", "Sin Marca"] or is_code_brand:
                    final_brand = "Sin Marca"
                else:
                    final_brand = brand_str

                # 3. Precios
                base_price = float(item.get("fullPrice", 0.0) or item.get("price", 0.0))
                offer_price = item.get("offerPrice")
                
                discount_price = None
                if offer_price is not None:
                    offer_val = float(offer_price)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                # 4. Stock
                is_out_of_store = bool(item.get("outofstore", False))
                in_stock = not is_out_of_store

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val,
                    brand=final_brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        print(f"[FARMATODO] Total guardados tras filtrado: {len(parsed_results)} para '{search_term}'", flush=True)
        return parsed_results