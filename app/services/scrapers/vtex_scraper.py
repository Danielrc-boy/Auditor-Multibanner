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
        self.domain = "www.carulla.com" if self.retailer == "carulla" else "www.exito.com"
        self.base_url = f"https://{self.domain}"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9",
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/",
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_keyword = keyword.strip()

        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            
            # --- ESTRATEGIA 1: GraphQL VTEX IO (Search Resolver - Usado por la Web) ---
            gql_url = f"{self.base_url}/_v/segment/graphql/v1"
            gql_query = {
                "query": """query productSearch($query: String, $from: Int, $to: Int) {
                    productSearch(query: $query, from: $from, to: $to) {
                        products {
                            productName
                            brand
                            items {
                                sellers {
                                    commertialOffer {
                                        Price
                                        ListPrice
                                        AvailableQuantity
                                    }
                                }
                            }
                        }
                    }
                }""",
                "variables": {"query": clean_keyword, "from": 0, "to": limit - 1}
            }

            req_url, params = self._build_request(gql_url)
            
            try:
                if params and "api_key" in params:
                    # Si usamos ScraperAPI en POST
                    res = await client.post(req_url, json=gql_query, headers=self.headers, params=params)
                else:
                    res = await client.post(gql_url, json=gql_query, headers=self.headers)

                if res.status_code == 200:
                    data = res.json()
                    products = data.get("data", {}).get("productSearch", {}).get("products", [])
                    if products:
                        return self._parse_catalog_search(products, clean_keyword)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] GraphQL Search falló: {e}", flush=True)

            # --- ESTRATEGIA 2: Catalog System Public API con Sales Channel ---
            encoded_term = urllib.parse.quote(clean_keyword)
            catalog_url = f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_term}?_from=0&_to={limit-1}&sc=1"
            req_cat_url, cat_params = self._build_request(catalog_url)

            try:
                res_cat = await client.get(req_cat_url, headers=self.headers, params=cat_params)
                if res_cat.status_code in (200, 206):
                    data = res_cat.json()
                    if isinstance(data, list) and len(data) > 0:
                        return self._parse_catalog_search(data, clean_keyword)
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] Catalog Search falló: {e}", flush=True)

        return []

    def _build_request(self, target_url: str):
        if SCRAPERAPI_KEY:
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url, "ultra_premium": "true"}
        return target_url, {}

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