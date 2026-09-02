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
        # 1. Primer intento: API Intelligent Search (Reflejo exacto del Frontend moderno)
        is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{keyword}"
        is_params = {
            "page": 1,
            "count": limit,
            "sort": "",
            "locale": "es-CO"
        }

        request_url, params = self._build_request(is_url, is_params)

        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                if response.status_code in (200, 206):
                    data = response.json()
                    products_raw = data.get("products", []) if isinstance(data, dict) else []
                    if products_raw:
                        return self._parse_intelligent_search(products_raw, keyword, limit)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] Intelligent Search no disponible, aplicando fallback legacy: {e}", flush=True)

            # 2. Fallback: API Legacy optimizada con politica comercial (sc=1) y relevancia
            legacy_params = f"_from=0&_to={limit-1}&O=OrderByScoreDESC&sc=1"
            legacy_url = f"{self.base_url}/io/api/catalog_system/pub/products/search/{keyword}?{legacy_params}"
            req_legacy_url, req_legacy_params = self._build_request(legacy_url, None)

            try:
                response = await client.get(req_legacy_url, headers=self.headers, params=req_legacy_params)
                if response.status_code in (200, 206):
                    raw_products = response.json()
                    if isinstance(raw_products, list):
                        return self._parse_legacy_products(raw_products, keyword, limit)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error en Fallback Legacy '{keyword}': {e}", flush=True)

        return []

    def _build_request(self, target_url: str, params_dict: dict = None):
        if SCRAPERAPI_KEY:
            if params_dict:
                query_string = "&".join([f"{k}={v}" for k, v in params_dict.items()])
                full_target = f"{target_url}?{query_string}"
            else:
                full_target = target_url
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": full_target}
        return target_url, params_dict

    def _parse_intelligent_search(self, products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(products[:limit], start=1):
            try:
                items = prod.get("items", [])
                item = items[0] if items else {}
                sellers = item.get("sellers", [{}])
                comm = sellers[0].get("commertialOffer", {}) if sellers else {}

                price = float(prod.get("price", 0.0) or comm.get("Price", 0.0) or 0.0)
                base_price = float(prod.get("listPrice", 0.0) or comm.get("ListPrice", 0.0) or price)
                
                discount_price = price if (0 < price < base_price) else None
                in_stock = prod.get("isAvailable", True) if "isAvailable" in prod else (comm.get("AvailableQuantity", 0) > 0)

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=prod.get("productName") or prod.get("name") or "Sin título",
                    brand=prod.get("brand") or prod.get("brandName") or "Sin Marca",
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                ))
            except Exception as e:
                print(f"[PARSER IS ERROR] {self.retailer.upper()}: {e}", flush=True)
                continue
        return parsed

    def _parse_legacy_products(self, raw_products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
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
                discount_price = price if (0 < price < base_price) else None
                if base_price == 0 and price > 0:
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
                print(f"[PARSER LEGACY ERROR] {self.retailer.upper()}: {e}", flush=True)
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