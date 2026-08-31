import os
import re
import urllib.parse
import unicodedata
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

# Variables de entorno con fallbacks oficiales a las credenciales capturadas de Farmatodo
FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("FARMATODO_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("FARMATODO_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("FARMATODO_INDEX_NAME", "products-colombia")


def normalize_text(text: str) -> str:
    """Remueve tildes, caracteres especiales y convierte a minúsculas para comparaciones limpias."""
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
        clean_term = search_term.strip()
        encoded_term = urllib.parse.quote(clean_term)
        params_str = f"query={encoded_term}&hitsPerPage={limit}&page=0"

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
                    print(f"[FARMATODO] Respuesta vacía de Algolia para '{clean_term}'", flush=True)
                    return []

                hits = results_list[0].get("hits", [])
                print(f"[FARMATODO] Algolia retornó {len(hits)} hits iniciales para '{clean_term}'", flush=True)
                
                return self._parse_products(hits, clean_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{clean_term}': {e}", flush=True)
                return []

    def _parse_products(self, hits: list, search_term: str) -> list:
        parsed_results = []

        # Preparación del filtro de relevancia genérico
        norm_search_term = normalize_text(search_term)
        search_words = [w for w in norm_search_term.split() if len(w) > 2]

        for index, item in enumerate(hits, start=1):
            try:
                # 1. Título con fallback estricto
                title_val = item.get("mediaDescription") or item.get("description") or item.get("name")
                title_val = str(title_val).strip() if title_val else "Sin título"

                # 2. Extracción honesta de Marca
                raw_brand = item.get("brand") or item.get("brandName") or item.get("marca")
                if isinstance(raw_brand, dict):
                    raw_brand = raw_brand.get("name")

                brand_str = str(raw_brand).strip() if raw_brand else ""
                is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str)

                # Validar si existe marca real o asignar "Sin Marca"
                if not brand_str or brand_str in ["None", "null", "Sin Marca"] or is_code_brand:
                    final_brand = "Sin Marca"
                else:
                    final_brand = brand_str

                # 3. Filtro de Relevancia Genérico
                combined_target_text = normalize_text(f"{title_val} {brand_str}")
                if search_words and not any(word in combined_target_text for word in search_words):
                    continue

                # 4. Cálculo de Precio Base
                full_price = item.get("fullPrice")
                price = item.get("price")
                
                base_price = 0.0
                if full_price is not None and float(full_price) > 0:
                    base_price = float(full_price)
                elif price is not None and float(price) > 0:
                    base_price = float(price)

                # 5. Cálculo de Precio de Descuento
                discount_price = None
                
                # Evaluación 1: offerPrice en la raíz
                root_offer = item.get("offerPrice")
                if root_offer is not None and float(root_offer) > 0:
                    offer_val = float(root_offer)
                    if offer_val < base_price:
                        discount_price = offer_val

                # Evaluación 2: offerPriceByStore si raíz no entregó un descuento válido
                if discount_price is None:
                    store_offers = item.get("offerPriceByStore")
                    if isinstance(store_offers, list) and store_offers:
                        valid_prices = []
                        for s_offer in store_offers:
                            try:
                                val = float(s_offer.get("offerPrice", 0))
                                if 0 < val < base_price:
                                    valid_prices.append(val)
                            except (ValueError, TypeError):
                                continue
                        
                        if valid_prices:
                            discount_price = min(valid_prices)

                # 6. Control de Stock
                outofstore = item.get("outofstore")
                if outofstore is not None:
                    in_stock = not bool(outofstore)
                else:
                    in_stock = True

                # Instancia de resultado sin modificar el contrato de VTEXScraper
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
                print(f"[ERROR FARMATODO] Fallo al procesar producto en posición {index}: {e}", flush=True)
                continue

        print(f"[FARMATODO] Total productos válidos procesados tras filtro: {len(parsed_results)} para '{search_term}'", flush=True)
        return parsed_results