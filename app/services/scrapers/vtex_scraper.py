import os
import httpx
from typing import List
from uuid import UUID, uuid4
from app.schemas import ExtractedProductData

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        if self.retailer == "carulla":
            self.base_url = "https://www.carulla.com"
        else:
            self.base_url = "https://www.exito.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        target_url = f"{self.base_url}/io/api/catalog_system/pub/products/search/{keyword}"

        if SCRAPERAPI_KEY:
            request_url = "http://api.scraperapi.com/"
            params = {"api_key": SCRAPERAPI_KEY, "url": target_url}
        else:
            request_url = target_url
            params = None

        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                if response.status_code not in (200, 206):
                    print(f"[ERROR {self.retailer.upper()}] Status {response.status_code}", flush=True)
                    return []
                raw_products = response.json()
                return self._parse_products(raw_products, keyword, limit)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error al scrapear '{keyword}': {e}", flush=True)
                return []

    def _parse_products(self, raw_products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(raw_products[:limit], start=1):
            try:
                items = prod.get("items", [])
                if not items:
                    continue
                item = items[0]
                sellers = item.get("sellers", [{}])
                comm = sellers[0].get("commertialOffer", {}) if sellers else {}
                base_price = float(comm.get("ListPrice", 0.0) or 0.0)
                price = float(comm.get("Price", 0.0) or 0.0)
                discount_price = None
                if 0 < price < base_price:
                    discount_price = price
                elif base_price == 0 and price > 0:
                    base_price = price
                in_stock = comm.get("AvailableQuantity", 0) > 0
                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=prod.get("productName", "Sin título"),
                    brand=prod.get("brand", "Sin Marca"),
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                ))
            except Exception as e:
                print(f"[PARSER ERROR] {self.retailer.upper()}: {e}", flush=True)
                continue
        return parsed


async def run_vtex_scraping(conn) -> int:
    """Función de orquestación consumida directamente por app/main.py"""
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []
    if not search_configs:
        return 0

    from app.main import save_scraper_results
    total_saved = 0
    for retailer_name in ["exito", "carulla"]:
        print(f"\n[SCRAPING] Iniciando extracción para: {retailer_name.upper()}", flush=True)
        scraper = VTEXScraper(retailer=retailer_name)
        for term in search_configs:
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer_name)
                    total_saved += count
                    print(f"[{retailer_name.upper()}] Guardados {count} para '{term}'.", flush=True)
                else:
                    print(f"[{retailer_name.upper()}] Sin resultados para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer_name.upper()} '{term}': {e}", flush=True)
    return total_saved