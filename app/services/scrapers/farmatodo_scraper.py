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

    async def search_keyword(self, keyword: str, limit: int = 50):
        all_products = []
        page = 1
        clean_term = normalize_text(keyword)
        
        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            try:
                while len(all_products) < limit:
                    url = f"https://www.farmatodo.com.co/api/search?term={clean_term}&page={page}"
                    response = await client.get(url, headers=self.headers)
                    if response.status_code != 200:
                        break
                    
                    data = response.json()
                    products = data.get("products", [])
                    if not products:
                        break
                        
                    all_products.extend(products)
                    page += 1
                    
                parsed_results = self._parse_products(all_products[:limit], keyword)
                return parsed_results
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

    def _safe_float(self, val) -> float | None:
        """Convierte de forma segura strings, enteros o floats a float puro."""
        if val is None or val == "":
            return None
        try:
            if isinstance(val, str):
                val = re.sub(r'[^\d.]', '', val.replace(',', '.'))
            res = float(val)
            return res if res > 0 else None
        except (ValueError, TypeError):
            return None

    def _extract_prices(self, item: dict) -> tuple[float, float | None]:
        """Extrae el precio base y el precio de descuento escaneando múltiples estructuras posibles."""
        raw_price_obj = item.get("price")
        
        base_price = 0.0
        offer_price = None

        if isinstance(raw_price_obj, dict):
            base_price = self._safe_float(raw_price_obj.get("base") or raw_price_obj.get("full") or raw_price_obj.get("regular")) or 0.0
            offer_price = self._safe_float(raw_price_obj.get("offer") or raw_price_obj.get("discount") or raw_price_obj.get("special"))
        else:
            base_price = self._safe_float(item.get("fullPrice") or item.get("price") or item.get("originalPrice") or item.get("regularPrice")) or 0.0
            offer_price = self._safe_float(item.get("offerPrice") or item.get("priceWithDiscount") or item.get("discountPrice") or item.get("finalPrice") or item.get("specialPrice"))

        if not offer_price:
            promos = item.get("promotions") or item.get("discounts") or item.get("offers")
            if isinstance(promos, list) and len(promos) > 0:
                first_promo = promos[0]
                if isinstance(first_promo, dict):
                    offer_price = self._safe_float(first_promo.get("price") or first_promo.get("offerPrice") or first_promo.get("specialPrice"))
                    
                    if not offer_price and base_price > 0:
                        pct = self._safe_float(first_promo.get("percent") or first_promo.get("percentage") or first_promo.get("value"))
                        if pct:
                            pct_val = pct / 100.0 if pct > 1 else pct
                            offer_price = round(base_price * (1.0 - pct_val), 2)

        if not offer_price and base_price > 0:
            pct = self._safe_float(item.get("discountPercent") or item.get("discount_percent") or item.get("percentage") or item.get("discount"))
            if pct:
                pct_val = pct / 100.0 if pct > 1 else pct
                offer_price = round(base_price * (1.0 - pct_val), 2)

        discount_price = None
        if offer_price and 0 < offer_price < base_price:
            discount_price = offer_price
        elif offer_price and offer_price > base_price:
            discount_price = base_price
            base_price = offer_price

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