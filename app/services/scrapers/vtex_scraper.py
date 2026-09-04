import os
import urllib.parse
from typing import List, Optional
import httpx
from pydantic import BaseModel

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


class VTEXScraper:
    def __init__(self, retailer: str, base_url: str = None):
        self.retailer = retailer.lower()
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.retailer == "carulla":
            self.base_url = "https://www.carulla.com"
        else:
            self.base_url = "https://www.exito.com"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        }

    def _build_request(self, target_url: str):
        if SCRAPERAPI_KEY:
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return target_url, None

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        encoded_keyword = urllib.parse.quote(keyword)

        target_url = (
            f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_keyword}"
            f"?_from=0&_to={limit - 1}"
        )
        request_url, params = self._build_request(target_url)

        # DIAGNÓSTICO: confirma en el log exacto qué está pasando en este momento
        key_status = f"SÍ ({SCRAPERAPI_KEY[:6]}...)" if SCRAPERAPI_KEY else "NO - VACÍA"
        via = "ScraperAPI" if SCRAPERAPI_KEY else "DIRECTO (sin proxy)"
        print(f"[DIAG {self.retailer.upper()}] Key cargada: {key_status} | Petición vía: {via}", flush=True)

        extracted_products: List[ExtractedProductData] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                print(f"[DIAG {self.retailer.upper()}] Status recibido: {response.status_code}", flush=True)

                if response.status_code not in (200, 206):
                    fallback_target = (
                        f"{self.base_url}/io/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}"
                        f"?page=1&count={limit}"
                    )
                    fb_url, fb_params = self._build_request(fallback_target)
                    response = await client.get(fb_url, headers=self.headers, params=fb_params)

                if response.status_code not in (200, 206):
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{keyword}' | Body: {response.text[:200]}")
                    return []

                raw_data = response.json()
                items_list = raw_data.get("products", raw_data) if isinstance(raw_data, dict) else raw_data
                if not isinstance(items_list, list):
                    return []

                position_counter = 1
                for product in items_list[:limit]:
                    try:
                        title = product.get("productName") or product.get("productTitle") or ""
                        brand = product.get("brand") or "Sin Marca"

                        base_price = 0.0
                        discount_price = None
                        in_stock = True

                        items = product.get("items", [])
                        if items:
                            sellers = items[0].get("sellers", [])
                            if sellers:
                                offer = sellers[0].get("commertialOffer", {})
                                base_price = float(offer.get("ListPrice", 0.0) or offer.get("Price", 0.0))
                                current_price = float(offer.get("Price", 0.0))
                                if 0 < current_price < base_price:
                                    discount_price = current_price
                                elif base_price == 0 and current_price > 0:
                                    base_price = current_price
                                available_qty = offer.get("AvailableQuantity", 0)
                                in_stock = (available_qty or 0) > 0

                        if not in_stock:
                            continue

                        if title:
                            extracted_products.append(
                                ExtractedProductData(
                                    search_keyword=keyword,
                                    search_position=position_counter,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                            position_counter += 1
                    except Exception as parse_err:
                        print(f"[{self.retailer.upper()} PARSE ERROR]: {parse_err}")
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{keyword}': {req_err}")
                return []

        return extracted_products


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
    for term in search_configs:
        for retailer in ["exito", "carulla"]:
            scraper = VTEXScraper(retailer=retailer)
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer)
                    total_saved += count
                    print(f"[{retailer.upper()}] Guardados {count} para '{term}'.", flush=True)
                else:
                    print(f"[{retailer.upper()}] Sin resultados para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer.upper()} '{term}': {e}", flush=True)

    return total_saved