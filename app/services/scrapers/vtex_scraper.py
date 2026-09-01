import httpx
import re
import urllib.parse
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ExtractedProductData:
    search_keyword: str
    search_position: int
    title: str
    brand: str
    base_price: float
    discount_price: Optional[float]
    in_stock: bool

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        if self.retailer == "carulla":
            self.base_url = "https://www.carulla.com/api/catalog_system/pub/products/search"
            self.origin = "https://www.carulla.com"
        else:
            self.base_url = "https://www.exito.com/api/catalog_system/pub/products/search"
            self.origin = "https://www.exito.com"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9",
            "Origin": self.origin,
            "Referer": f"{self.origin}/",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_term = search_term.strip()
        params = {
            "ft": clean_term,
            "_from": 0,
            "_to": limit - 1
        }
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(self.base_url, params=params, headers=self.headers)
                response.raise_for_status()
                products = response.json()
                return self._parse_products(products, clean_term)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error al scrapear '{clean_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_products: list, search_term: str) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(raw_products, start=1):
            try:
                title = prod.get("productName", "")
                brand = prod.get("brand", "Sin Marca")
                items = prod.get("items", [])
                
                base_price = 0.0
                discount_price = None
                in_stock = False

                if items:
                    sellers = items[0].get("sellers", [])
                    if sellers:
                        comm = sellers[0].get("commertialOffer", {})
                        base_price = float(comm.get("ListPrice", 0.0))
                        price = float(comm.get("Price", 0.0))
                        if price < base_price and price > 0:
                            discount_price = price
                        elif base_price == 0 and price > 0:
                            base_price = price

                        available_qty = comm.get("AvailableQuantity", 0)
                        in_stock = available_qty > 0

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=title,
                    brand=brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                ))
            except Exception as e:
                print(f"[PARSER ERROR] {self.retailer.upper()}: {e}", flush=True)
                continue
        return parsed

async def run_vtex_scraping(conn) -> int:
    search_configs = []
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT search_term, retailer FROM search_configs WHERE is_active = TRUE;")
            rows = cur.fetchall()
            search_configs = rows if rows else []
        except Exception:
            conn.rollback()
            cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
            rows = cur.fetchall()
            search_configs = [{"search_term": r["search_term"], "retailer": "exito"} for r in rows] if rows else []

    if not search_configs:
        return 0

    total_saved = 0
    from app.main import save_scraper_results

    for config in search_configs:
        term = config["search_term"]
        raw_retailer = str(config.get("retailer") or "exito").lower().strip()

        target_retailers = []
        if raw_retailer in ["exito", "carulla"]:
            target_retailers = [raw_retailer]
        elif raw_retailer in ["todos", "all", ""]:
            target_retailers = ["exito", "carulla"]

        for retailer in target_retailers:
            scraper = VTEXScraper(retailer=retailer)
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer)
                    total_saved += count
                    print(f"[{retailer.upper()}] Guardados {count} para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer.upper()} '{term}': {e}", flush=True)

    return total_saved