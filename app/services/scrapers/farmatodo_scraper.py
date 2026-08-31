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

    def _extract_prices(self, item: dict) -> tuple[float, float | None]:
        """
        Extracción precisa de Algolia para Farmatodo:
        - `fullPrice`: Precio regular sin descuento.
        - `price`: Precio final tras aplicar ofertas activas en la base de datos de Algolia.
        """
        base_price = 0.0
        discount_price = None

        # 1. Lectura de campos de precio directo de Algolia
        raw_full = item.get("fullPrice")
        raw_current = item.get("price")

        try:
            full_val = float(raw_full) if raw_full is not None else 0.0
            current_val = float(raw_current) if raw_current is not None else 0.0

            if full_val > 0 and current_val > 0:
                if current_val < full_val:
                    base_price = full_val
                    discount_price = current_val
                else:
                    base_price = full_val
            elif current_val > 0:
                base_price = current_val
            elif full_val > 0:
                base_price = full_val

        except (ValueError, TypeError):
            pass

        # 2. Si el descuento viene especificado como un porcentaje de promoción en el objeto `promotions`
        if discount_price is None and base_price > 0:
            promotions = item.get("promotions")
            if isinstance(promotions, list) and len(promotions) > 0:
                promo = promotions[0]
                if isinstance(promo, dict):
                    percent = promo.get("percent") or promo.get("discount") or promo.get("value")
                    try:
                        pct = float(percent)
                        if pct > 0:
                            pct_factor = pct / 100.0 if pct > 1 else pct
                            discount_price = round(base_price * (1.0 - pct_factor), 2)
                    except (ValueError, TypeError):
                        pass

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
                base_price, discount_price = self._extract_prices(item)

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