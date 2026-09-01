import os
import re
import urllib.parse
import unicodedata
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia")

# Lista priorizada de marcas comunes para fallback cuando el campo 'brand' de Algolia falla
KNOWN_BRANDS = [
    "Nosotras", "Kotex", "Stayfree", "Pequeñín", "Winny", "Farmatodo",
    "Huggies", "Pampers", "Nivea", "Dove", "Protex", "Saba", "Tena",
    "Gillette", "Colgate", "Sensodyne", "Neutrogena", "Cetaphil"
]

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFD', text)
    text = re.sub(r'[\u0300-\u036f]', '', text)
    return text.lower().strip()

class FarmatodoScraper:
    def __init__(self):
        self.endpoint = FARMATODO_ALGOLIA_URL
        self.headers = {
            "x-algolia-application-id": FARMATODO_APP_ID.strip(),
            "x-algolia-api-key": FARMATODO_API_KEY.strip(),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        clean_term = search_term.strip()
        
        # Enviar parametros limpios a la API REST de Algolia
        payload = {
            "requests": [
                {
                    "indexName": FARMATODO_INDEX_NAME,
                    "query": clean_term,
                    "hitsPerPage": limit
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

    def _extract_brand(self, item: dict, title: str) -> str:
        # 1. Intentar obtener de campos explicitos de marca en el payload de Algolia
        raw_brand = item.get("brandName") or item.get("marca") or item.get("brand_name")
        
        if isinstance(raw_brand, dict):
            raw_brand = raw_brand.get("name") or raw_brand.get("label")
        elif isinstance(raw_brand, list) and len(raw_brand) > 0:
            raw_brand = raw_brand[0]

        brand_str = str(raw_brand).strip() if raw_brand else ""
        is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str) or brand_str.startswith("2008")

        # Verificar si 'brand' viene como la primera palabra del titulo (bug comun en Algolia Farmatodo)
        first_word_of_title = title.split()[0] if title else ""
        is_title_word_copy = brand_str.lower() == first_word_of_title.lower()

        if brand_str and brand_str.lower() not in ["none", "null", "sin marca"] and not is_code_brand and not is_title_word_copy:
            return brand_str

        # 2. Fallback: Buscar marca en la lista de marcas conocidas dentro del titulo
        for brand in KNOWN_BRANDS:
            if re.search(rf'\b{brand}\b', title, re.IGNORECASE):
                return brand

        return "Sin Marca"

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []
        valid_position = 1

        for item in raw_hits:
            try:
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                # Extracción robusta de marca
                final_brand = self._extract_brand(item, title)

                # 1. Extracción defensiva del Precio Base (Lista/Pleno)
                base_price = float(
                    item.get("fullPrice") or 
                    item.get("price") or 
                    item.get("originalPrice") or 
                    0.0
                )

                # 2. Extracción del Precio de Oferta / Descuento
                raw_offer = (
                    item.get("offerPrice") or 
                    item.get("priceWithDiscount") or 
                    item.get("discountPrice")
                )

                # Si el payload contiene un arreglo de promociones o descuentos
                if not raw_offer and isinstance(item.get("discounts"), list) and len(item.get("discounts")) > 0:
                    raw_offer = item.get("discounts")[0].get("price")
                elif not raw_offer and isinstance(item.get("promotions"), list) and len(item.get("promotions")) > 0:
                    raw_offer = item.get("promotions")[0].get("price")

                discount_price = None
                if raw_offer is not None:
                    offer_val = float(raw_offer)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val
                    elif offer_val > base_price:
                        # Intercambio de variables si la API invirtio 'price' y 'fullPrice'
                        discount_price = base_price
                        base_price = offer_val

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