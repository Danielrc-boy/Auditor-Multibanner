import os
import re
import httpx
from typing import List
from uuid import UUID, uuid4
from app.schemas import ExtractedProductData

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
        payload = {"requests": [{"indexName": FARMATODO_INDEX_NAME, "query": clean_term, "hitsPerPage": limit}]}
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
        first_word = title.split()[0] if title else ""
        is_title_copy = brand_str.lower() == first_word.lower()
        if brand_str and brand_str.lower() not in ["none", "null", "sin marca"] and not is_code_brand and not is_title_copy:
            return brand_str
        for brand in KNOWN_BRANDS:
            if re.search(rf'\b{brand}\b', title, re.IGNORECASE):
                return brand
        return "Sin Marca"

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []
        position = 1
        for item in raw_hits:
            try:
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                final_brand = self._extract_brand(item, title)
                term_lower = search_term.lower()
                if term_lower not in title.lower() and term_lower not in final_brand.lower():
                    continue

                base_price = float(item.get("fullPrice") or item.get("price") or item.get("originalPrice") or 0.0)
                raw_offer = item.get("offerPrice") or item.get("priceWithDiscount") or item.get("discountPrice")
                if not raw_offer and isinstance(item.get("discounts"), list) and item.get("discounts"):
                    raw_offer = item["discounts"][0].get("price")
                elif not raw_offer and isinstance(item.get("promotions"), list) and item.get("promotions"):
                    raw_offer = item["promotions"][0].get("price")

                discount_price = None
                if raw_offer is not None:
                    offer_val = float(raw_offer)
                    if 0 < offer_val < base_price:
                        discount_price = offer_val
                    elif offer_val > base_price:
                        discount_price = base_price
                        base_price = offer_val

                in_stock = not bool(item.get("outofstore", False))

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=position,
                    title=title,
                    brand=final_brand,
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