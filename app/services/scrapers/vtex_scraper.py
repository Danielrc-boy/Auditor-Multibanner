import os
import json
import urllib.parse
import httpx
from typing import List
from app.schemas import ExtractedProductData

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        if self.retailer == "carulla":
            self.base_url = "https://www.carulla.com"
            self.default_seller = "Carulla"
        else:
            self.base_url = "https://www.exito.com"
            self.default_seller = "Exito"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9",
        }

    def _build_request(self, target_url: str, params_dict: dict = None, render_js: bool = False):
        if params_dict:
            query_string = urllib.parse.urlencode(params_dict)
            full_target = f"{target_url}?{query_string}"
        else:
            full_target = target_url

        if SCRAPERAPI_KEY:
            scraper_params = {
                "api_key": SCRAPERAPI_KEY,
                "url": full_target,
                "country_code": "co",
            }
            if render_js:
                scraper_params["render"] = "true"
            return "http://api.scraperapi.com/", scraper_params

        return full_target, None

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        encoded_term = urllib.parse.quote(keyword)

        async with httpx.AsyncClient(timeout=60.0, verify=False, follow_redirects=True) as client:
            
            # -----------------------------------------------------------------
            # INTENTO 1: API REST Intelligent Search
            # -----------------------------------------------------------------
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{encoded_term}"
            is_params = {
                "page": 1,
                "count": limit,
                "query": keyword,
                "sort": "score_desc",
                "locale": "es-CO"
            }
            req_is_url, req_is_params = self._build_request(is_url, is_params)
            
            try:
                response = await client.get(req_is_url, headers=self.headers, params=req_is_params)
                print(f"[{self.retailer.upper()}] HTTP Status (IS): {response.status_code}", flush=True)
                
                if response.status_code in (200, 206):
                    data = response.json()
                    products_raw = data.get("products", []) if isinstance(data, dict) else []
                    if products_raw:
                        results = self._parse_intelligent_search(products_raw, keyword, limit)
                        if results:
                            return results
                else:
                    print(f"[{self.retailer.upper()}] Body (IS): {response.text[:200]}", flush=True)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] REST Intelligent Search falló: {e}", flush=True)

            # -----------------------------------------------------------------
            # INTENTO 2: API Legacy de Catálogo VTEX
            # -----------------------------------------------------------------
            legacy_url = f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_term}"
            legacy_params = {"_from": 0, "_to": limit - 1}
            req_leg_url, req_leg_params = self._build_request(legacy_url, legacy_params)

            try:
                response = await client.get(req_leg_url, headers=self.headers, params=req_leg_params)
                print(f"[{self.retailer.upper()}] HTTP Status (Legacy): {response.status_code}", flush=True)

                if response.status_code in (200, 206):
                    products_raw = response.json()
                    if isinstance(products_raw, list) and len(products_raw) > 0:
                        return self._parse_intelligent_search(products_raw, keyword, limit)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] Legacy Search falló: {e}", flush=True)

            # -----------------------------------------------------------------
            # INTENTO 3: Fallback HTML Scraping mediante ScraperAPI (Render JS)
            # -----------------------------------------------------------------
            site_search_url = f"{self.base_url}/{encoded_term}?map=ft"
            req_html_url, req_html_params = self._build_request(site_search_url, render_js=True)

            try:
                print(f"[{self.retailer.upper()}] Intentando Render JS en Frontend...", flush=True)
                response = await client.get(req_html_url, headers=self.headers, params=req_html_params)
                print(f"[{self.retailer.upper()}] HTTP Status (HTML Render): {response.status_code}", flush=True)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Render JS falló: {e}", flush=True)

        return []

    def _parse_intelligent_search(self, products: list, search_term: str, limit: int) -> List[ExtractedProductData]:
        parsed = []
        for idx, prod in enumerate(products[:limit], start=1):
            try:
                items = prod.get("items", [])
                item = items[0] if items else {}
                sellers = item.get("sellers", [{}])
                seller_obj = sellers[0] if sellers else {}
                comm = seller_obj.get("commertialOffer", {}) if isinstance(seller_obj, dict) else {}

                price = float(prod.get("price", 0.0) or comm.get("Price", 0.0) or 0.0)
                base_price = float(prod.get("listPrice", 0.0) or comm.get("ListPrice", 0.0) or price)
                discount_price = price if (0 < price < base_price) else None
                in_stock = prod.get("isAvailable", True) if "isAvailable" in prod else (comm.get("AvailableQuantity", 0) > 0)

                seller_name = seller_obj.get("sellerName") if isinstance(seller_obj, dict) else None
                if not seller_name or str(seller_name).strip() == "":
                    seller_name = self.default_seller

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=prod.get("productName") or prod.get("name") or "Sin título",
                    brand=prod.get("brand") or prod.get("brandName") or "Sin Marca",
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock,
                    seller_name=seller_name
                ))
            except Exception as e:
                print(f"[PARSER IS ERROR] {self.retailer.upper()}: {e}", flush=True)
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