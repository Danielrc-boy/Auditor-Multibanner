import urllib.parse
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData

class FarmatodoScraper:
    def __init__(self):
        self.base_url = "https://www.farmatodo.com.co/api/v1/products/search"

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        encoded_term = urllib.parse.quote(search_term)
        url = f"{self.base_url}?query={encoded_term}&limit={limit}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                return self._parse_products(data, search_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, data: dict, search_term: str) -> list:
        parsed_results = []
        raw_items = data.get("products", []) if isinstance(data, dict) else []

        for index, item in enumerate(raw_items, start=1):
            try:
                # --- PASO 2: LOG DE EVIDENCIA CRUDA ---
                if index == 1:
                    print(f"[DEBUG FARMATODO] {item}", flush=True)

                title_val = item.get("name", "").strip()
                extracted_brand = item.get("brand") or item.get("brandName")

                if not extracted_brand or str(extracted_brand).strip() in ["", "None", "null"]:
                    if title_val:
                        extracted_brand = title_val.split()[0].capitalize()
                    else:
                        extracted_brand = "Sin Marca"

                price = float(item.get("price", 0.0))
                disc_price = float(item.get("discountPrice", 0.0)) if item.get("discountPrice") else None
                in_stock = bool(item.get("inStock", True))

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val if title_val else "Sin título",
                    brand=str(extracted_brand).strip(),
                    base_price=price,
                    discount_price=disc_price,
                    in_stock=in_stock
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results