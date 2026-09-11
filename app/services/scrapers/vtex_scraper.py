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


# Configuración por retailer: para agregar un VTEX nuevo (Falabella, etc.),
# solo hace falta una entrada nueva aquí -- confirmando antes, con evidencia
# real de navegador, cada uno de estos 4 valores.
RETAILER_CONFIGS = {
    "exito": {
        "base_url": "https://www.exito.com",
        "search_style": "path",
        "use_io_prefix": True,
        "use_scraperapi": True,   # bloqueo 403 confirmado sin proxy
    },
    "carulla": {
        "base_url": "https://www.carulla.com",
        "search_style": "path",
        "use_io_prefix": True,
        "use_scraperapi": True,
    },
    "larebaja": {
        "base_url": "https://www.larebajavirtual.com",
        "search_style": "ft_param",
        "use_io_prefix": False,
        "use_scraperapi": False,
    },
    "locatel": {
        "base_url": "https://www.locatelcolombia.com",
        "search_style": "path",    # confirmado: /api/catalog_system/pub/products/search/{keyword}
        "use_io_prefix": False,    # confirmado: SIN /io/ delante (a diferencia de Exito/Carulla)
        "use_scraperapi": False,   # sin bloqueo confirmado hasta ahora
    },
    "colsubsidio": {
        "base_url": "https://www.drogueriascolsubsidio.com",
        "search_style": "path",    # confirmado: /api/catalog_system/pub/products/search/{keyword}
        "use_io_prefix": False,    # confirmado: SIN /io/ delante
        "use_scraperapi": False,   # sin bloqueo confirmado hasta ahora
    },
    "pasteur": {
        "base_url": "https://www.farmaciaspasteur.com.co",
        "search_style": "path",    # confirmado: /api/catalog_system/pub/products/search/{keyword}
        "use_io_prefix": False,    # confirmado: SIN /io/ delante
        "use_scraperapi": False,   # sin bloqueo confirmado hasta ahora
    },
}

DEFAULT_CONFIG = RETAILER_CONFIGS["exito"]


class VTEXScraper:
    def __init__(self, retailer: str, base_url: str = None):
        self.retailer = retailer.lower()
        self.config = RETAILER_CONFIGS.get(self.retailer, DEFAULT_CONFIG)
        self.base_url = (base_url.rstrip("/") if base_url else self.config["base_url"])
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
        if self.config.get("use_scraperapi") and SCRAPERAPI_KEY:
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return target_url, None

    def _build_search_url(self, encoded_keyword: str, limit: int) -> str:
        io_prefix = "/io" if self.config.get("use_io_prefix") else ""
        if self.config["search_style"] == "ft_param":
            return f"{self.base_url}{io_prefix}/api/catalog_system/pub/products/search?ft={encoded_keyword}&_from=0&_to={limit - 1}"
        return f"{self.base_url}{io_prefix}/api/catalog_system/pub/products/search/{encoded_keyword}?_from=0&_to={limit - 1}"

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        encoded_keyword = urllib.parse.quote(keyword)
        target_url = self._build_search_url(encoded_keyword, limit)
        request_url, params = self._build_request(target_url)

        key_status = f"SÍ ({SCRAPERAPI_KEY[:6]}...)" if (self.config.get("use_scraperapi") and SCRAPERAPI_KEY) else "NO / directo"
        print(f"[DIAG {self.retailer.upper()}] Petición vía: {key_status} | URL base: {target_url}", flush=True)

        extracted_products: List[ExtractedProductData] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                print(f"[DIAG {self.retailer.upper()}] Status recibido: {response.status_code}", flush=True)

                if response.status_code not in (200, 206):
                    io_prefix = "/io" if self.config.get("use_io_prefix") else ""
                    fallback_target = (
                        f"{self.base_url}{io_prefix}/_v/api/intelligent-search/product_search/{encoded_keyword}"
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

    from app.services.scraping_orchestrator import save_scraper_results

    total_saved = 0
    for term in search_configs:
        for retailer in ["exito", "carulla", "larebaja", "locatel", "colsubsidio", "pasteur"]:
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