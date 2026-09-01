import os
import re
import unicodedata
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia")

KNOWN_BRANDS = [
    "Nosotras", "Kotex", "Stayfree", "Pequeñín", "Winny", "Farmatodo",
    "Huggies", "Pampers", "Nivea", "Dove", "Protex", "Saba", "Tena",
    "Gillette", "Colgate", "Sensodyne", "Neutrogena", "Cetaphil"
]

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
        raw_brand = item.get("brandName") or item.get("marca") or item.get("brand_name")
        
        if isinstance(raw_brand, dict):
            raw_brand = raw_brand.get("name") or raw_brand.get("label")
        elif isinstance(raw_brand, list) and len(raw_brand) > 0:
            raw_brand = raw_brand[0]

        brand_str = str(raw_brand).strip() if raw_brand else ""
        is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str) or brand_str.startswith("2008")

        first_word_of_title = title.split()[0] if title else ""
        is_title_word_copy = brand_str.lower() == first_word_of_title.lower()

        if brand_str and brand_str.lower() not in ["none", "null", "sin marca"] and not is_code_brand and not is_title_word_copy:
            return brand_str

        for brand in KNOWN_BRANDS:
            if re.search(rf'\b{brand}\b', title, re.IGNORECASE):
                return brand

        return "Sin Marca"

    def _detect_discount_percentage(self, item: dict, title: str) -> float | None:
        """Extrae el porcentaje dinámicamente mediante Regex desde textos y metadatos."""
        
        # 1. Buscar porcentaje numérico directo en campos planos de Algolia
        for key in ["discountPercent", "discount_percent", "percentage", "discount"]:
            val = item.get(key)
            if val is not None:
                try:
                    pct = float(val)
                    if 0 < pct < 100:
                        return pct
                except (ValueError, TypeError):
                    pass

        # 2. Extraer desde el texto del título (ej: "Toallas 15% DCTO", "-20% OFF")
        match_title = re.search(r'(\d{1,2})\s*%\s*(?:dcto|off|descuento)?', title, re.IGNORECASE)
        if match_title:
            try:
                pct = float(match_title.group(1))
                if 0 < pct < 100:
                    return pct
            except ValueError:
                pass

        # 3. Buscar patrones en etiquetas o campos de promociones anidados
        promos = item.get("promotions") or item.get("badges") or item.get("tags") or []
        promos_text = str(promos)
        match_promo = re.search(r'(\d{1,2})\s*%', promos_text)
        if match_promo:
            try:
                pct = float(match_promo.group(1))
                if 0 < pct < 100:
                    return pct
            except ValueError:
                pass

        return None

    def _extract_prices(self, item: dict, title: str) -> tuple[float, float | None]:
        # Obtener precio base
        base_price = float(item.get("fullPrice") or item.get("price") or 0.0)
        if base_price <= 0:
            return 0.0, None

        # Intento A: Verificar si 'price' en Algolia ya venía menor que 'fullPrice'
        full_p = item.get("fullPrice")
        curr_p = item.get("price")
        if full_p and curr_p:
            try:
                f_val, c_val = float(full_p), float(curr_p)
                if 0 < c_val < f_val:
                    return f_val, c_val
            except (ValueError, TypeError):
                pass

        # Intento B: Detección dinámica del % de descuento en texto/metadatos
        pct = self._detect_discount_percentage(item, title)
        discount_price = None

        if pct is not None:
            discount_price = round(base_price * (1.0 - (pct / 100.0)), 2)

        return base_price, discount_price

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []
        valid_position = 1

        for item in raw_hits:
            try:
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                final_brand = self._extract_brand(item, title)
                base_price, discount_price = self._extract_prices(item, title)

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