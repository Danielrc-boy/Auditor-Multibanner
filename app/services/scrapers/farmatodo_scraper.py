import os
import re
import urllib.parse
import unicodedata
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")[cite: 2]
FARMATODO_APP_ID = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")[cite: 2]
FARMATODO_API_KEY = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")[cite: 2]
FARMATODO_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia")[cite: 2]

# Lista priorizada de marcas comunes para fallback cuando el campo 'brand' de Algolia falla
KNOWN_BRANDS = [
    "Nosotras", "Kotex", "Stayfree", "Pequeñín", "Winny", "Farmatodo",
    "Huggies", "Pampers", "Nivea", "Dove", "Protex", "Saba", "Tena",
    "Gillette", "Colgate", "Sensodyne", "Neutrogena", "Cetaphil"
][cite: 2]

def normalize_text(text: str) -> str:
    if not text:
        return ""[cite: 2]
    text = unicodedata.normalize('NFD', text)[cite: 2]
    text = re.sub(r'[\u0300-\u036f]', '', text)[cite: 2]
    return text.lower().strip()[cite: 2]

class FarmatodoScraper:
    def __init__(self):
        self.endpoint = FARMATODO_ALGOLIA_URL[cite: 2]
        self.headers = {
            "x-algolia-application-id": FARMATODO_APP_ID.strip(),
            "x-algolia-api-key": FARMATODO_API_KEY.strip(),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }[cite: 2]

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        clean_term = search_term.strip()[cite: 2]
        
        # Enviar parametros limpios a la API REST de Algolia
        payload = {
            "requests": [
                {
                    "indexName": FARMATODO_INDEX_NAME,
                    "query": clean_term,
                    "hitsPerPage": limit
                }
            ]
        }[cite: 2]

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.endpoint, headers=self.headers, json=payload)[cite: 2]
                response.raise_for_status()[cite: 2]
                data = response.json()[cite: 2]
                
                results = data.get("results", [])[cite: 2]
                if not results:
                    return [][cite: 2]
                
                hits = results[0].get("hits", [])[cite: 2]
                return self._parse_products(hits, clean_term)[cite: 2]

            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{clean_term}': {e}", flush=True)[cite: 2]
                return [][cite: 2]

    def _extract_brand(self, item: dict, title: str) -> str:
        # 1. Intentar obtener de campos explicitos de marca en el payload de Algolia
        raw_brand = item.get("brandName") or item.get("marca") or item.get("brand_name")[cite: 2]
        
        if isinstance(raw_brand, dict):
            raw_brand = raw_brand.get("name") or raw_brand.get("label")[cite: 2]
        elif isinstance(raw_brand, list) and len(raw_brand) > 0:
            raw_brand = raw_brand[0][cite: 2]

        brand_str = str(raw_brand).strip() if raw_brand else ""[cite: 2]
        is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str) or brand_str.startswith("2008")[cite: 2]

        # Verificar si 'brand' viene como la primera palabra del titulo (bug comun en Algolia Farmatodo)
        first_word_of_title = title.split()[0] if title else ""[cite: 2]
        is_title_word_copy = brand_str.lower() == first_word_of_title.lower()[cite: 2]

        if brand_str and brand_str.lower() not in ["none", "null", "sin marca"] and not is_code_brand and not is_title_word_copy:
            return brand_str[cite: 2]

        # 2. Fallback: Buscar marca en la lista de marcas conocidas dentro del titulo
        for brand in KNOWN_BRANDS:
            if re.search(rf'\b{brand}\b', title, re.IGNORECASE):
                return brand[cite: 2]

        return "Sin Marca"[cite: 2]

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = [][cite: 2]
        valid_position = 1[cite: 2]

        for item in raw_hits:
            try:
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""[cite: 2]
                title = str(title).strip()[cite: 2]
                if not title:
                    continue[cite: 2]

                # Extracción robusta de marca
                final_brand = self._extract_brand(item, title)[cite: 2]

                # 1. Extracción del Precio Base (Lista / Pleno)
                base_price = float(
                    item.get("fullPrice") or 
                    item.get("price") or 
                    item.get("originalPrice") or 
                    0.0
                )

                # 2. Extracción directa del precio de oferta si viene ya calculado
                raw_offer = (
                    item.get("offerPrice") or 
                    item.get("priceWithDiscount") or 
                    item.get("discountPrice") or
                    item.get("finalPrice")
                )

                # 3. Extracción de porcentaje de descuento en metadata de promociones
                discount_percent = (
                    item.get("discountPercent") or 
                    item.get("discount_percent") or 
                    item.get("percentage") or 
                    item.get("discount") or 
                    0
                )

                if not discount_percent and isinstance(item.get("promotions"), list) and len(item.get("promotions")) > 0:
                    first_promo = item.get("promotions")[0]
                    discount_percent = first_promo.get("percent") or first_promo.get("value") or 0

                discount_price = None

                # Opción A: Asignar precio de oferta si Algolia lo entrega directamente
                if raw_offer is not None:
                    offer_val = float(raw_offer)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val

                # Opción B: Calcular dinámicamente si Algolia entrega porcentaje (Ej: 15%)
                if discount_price is None and discount_percent and float(discount_percent) > 0:
                    pct = float(discount_percent)
                    if pct > 1:
                        pct = pct / 100.0
                    discount_price = round(base_price * (1.0 - pct), 2)

                # Intercambiar si 'price' en Algolia venía con el valor menor
                if discount_price and base_price < discount_price:
                    base_price, discount_price = discount_price, base_price

                is_out_of_store = bool(item.get("outofstore", False))[cite: 2]
                in_stock = not is_out_of_store[cite: 2]

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=valid_position,
                    title=title,
                    brand=final_brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                )[cite: 2]
                parsed_results.append(product)[cite: 2]
                valid_position += 1[cite: 2]

            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)[cite: 2]
                continue[cite: 2]

        return parsed_results[cite: 2]