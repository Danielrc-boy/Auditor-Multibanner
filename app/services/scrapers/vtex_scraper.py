import os
import urllib.parse
import httpx
from typing import List
from app.schemas import ExtractedProductData

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.domain = "www.carulla.com" if self.retailer == "carulla" else "www.exito.com"
        self.base_url = f"https://{self.domain}"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es-419;q=0.9,es;q=0.8",
            "Referer": f"{self.base_url}/",
            "Origin": self.base_url,
            "Cookie": "vtex_segment=eyJjdXJyZW5jeUNvZGUiOiJDT1AiLCJjdXJyZW5jeVN5bWJvbCI6IiQiLCJjb3VudHJ5Q29kZSI6IkNPTCJ9"
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_keyword = keyword.strip()
        encoded_keyword = urllib.parse.quote(clean_keyword)

        async with httpx.AsyncClient(timeout=45.0, verify=False, follow_redirects=True) as client:
            
            # --- ESTRATEGIA 1: Intelligent Search V2 (Endpoint nativo de Éxito/Carulla) ---
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}?page=1&count={limit}&query={encoded_keyword}&sort=score_desc&locale=es-CO"
            req_url, params = self._build_request(is_url)

            try:
                res = await client.get(req_url, headers=self.headers, params=params)
                if res.status_code == 200:
                    data = res.json()
                    products = data.get("products", [])
                    if products:
                        return self._parse_intelligent_search(products, clean_keyword, limit)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] Intelligent Search V2 falló: {e}", flush=True)

            # --- ESTRATEGIA 2: Catalog System Traditional API (SC=1 Colombia) ---
            legacy_url = f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_keyword}?_from=0&_to={limit-1}&sc=1"
            req_leg_url, leg_params = self._build_request(legacy_url)

            try:
                res_leg = await client.get(req_leg_url, headers=self.headers, params=leg_params)
                if res_leg.status_code in (200, 206):
                    data = res_leg.json()
                    if isinstance(data, list) and len(data) > 0:
                        return self._parse_catalog_search(data, clean_keyword)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] Legacy Catalog Search falló: {e}", flush=True)

        return []

    def _build_request(self, target_url: str):
        if SCRAPERAPI_KEY:
            # Importante: Codificar la URL completa para evitar romper los parámetros internos
            encoded_target = urllib.parse.quote_plus(target_url)
            proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPERAPI_KEY}&url={encoded_target}&keep_headers=true"
            return proxy_url, {}
        return target_url, {}

    def _parse_intelligent_search(self, products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(products[:limit], start=1):
            try:
                items = prod.get("items", [])
                item = items[0] if items else {}
                sellers = item.get("sellers", [{}])
                comm = sellers[0].get("commertialOffer", {}) if sellers else {}

                price = float(comm.get("Price", 0.0) or prod.get("price", 0.0) or 0.0)
                list_price = float(comm.get("ListPrice", 0.0) or prod.get("listPrice", 0.0) or price)
                discount_price = price if (0 < price < list_price) else None
                in_stock = comm.get("AvailableQuantity", 0) > 0 if "AvailableQuantity" in comm else prod.get("isAvailable", True)

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=prod.get("productName") or prod.get("name") or "Sin título",
                    brand=prod.get("brand") or prod.get("brandName") or "Sin Marca",
                    base_price=list_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                ))
            except Exception:
                continue
        return parsed

    def _parse_catalog_search(self, products: list, search_term: str) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(products, start=1):
            try:
                items = prod.get("items", [])
                item = items[0] if items else {}
                sellers = item.get("sellers", [{}])
                comm = sellers[0].get("commertialOffer", {}) if sellers else {}

                price = float(comm.get("Price", 0.0) or 0.0)
                list_price = float(comm.get("ListPrice", 0.0) or price)
                discount_price = price if (0 < price < list_price) else None
                in_stock = comm.get("AvailableQuantity", 0) > 0

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=prod.get("productName", "Sin título"),
                    brand=prod.get("brand", "Sin Marca"),
                    base_price=list_price,
                    discount_price=discount_price,
                    in_stock=in_stock
                ))
            except Exception:
                continue
        return parsed

async def run_vtex_scraping(conn) -> int:
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