import os
import urllib.parse
from typing import Optional
import httpx

RETAILER_URLS = {
    "exito": "https://www.exito.com",
    "carulla": "https://www.carulla.com"
}

SCRAPERAPI_KEY = os.getenv("SCRAPER_API_KEY") or os.getenv("SCRAPERAPI_KEY")

class ExtractedProductData:
    def __init__(
        self, 
        search_keyword: str, 
        search_position: int, 
        title: str, 
        brand: Optional[str] = "Sin Marca", 
        base_price: float = 0.0, 
        discount_price: Optional[float] = None, 
        in_stock: bool = True
    ):
        self.search_keyword = search_keyword
        self.search_position = search_position
        self.title = title
        self.brand = brand if brand and str(brand).strip() not in ["", "None", "null"] else "Sin Marca"
        self.base_price = base_price
        self.discount_price = discount_price
        self.in_stock = in_stock

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.base_url = RETAILER_URLS.get(self.retailer, "https://www.exito.com")

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        # Sanitización y encoding estricto del término de búsqueda
        encoded_term = urllib.parse.quote(search_term.strip())
        target_url = f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_term}?_from=0&_to={limit - 1}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "es-CO,es-ES;q=0.9,es;q=0.8"
        }

        # Si existe ScraperAPI, se envía con keep_headers=true y country_code=co
        if SCRAPERAPI_KEY:
            request_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={urllib.parse.quote(target_url)}&keep_headers=true&country_code=co"
        else:
            request_url = target_url

        async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=headers)
                
                # Fallback: Si responde status diferente a 200, intentar consulta directa sin proxy
                if response.status_code != 200 and SCRAPERAPI_KEY:
                    response = await client.get(target_url, headers=headers)

                response.raise_for_status()
                data = response.json()
                return self._parse_products(data, search_term)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_items: list, search_term: str) -> list:
        parsed_results = []
        if not isinstance(raw_items, list):
            return parsed_results

        for index, item in enumerate(raw_items, start=1):
            try:
                items_list = item.get("items", [])
                if not items_list:
                    continue

                sellers = items_list[0].get("sellers", [])
                price, list_price, available = 0.0, 0.0, True

                if sellers:
                    comm_offer = sellers[0].get("commertialOffer", {})
                    price = float(comm_offer.get("Price", 0.0))
                    list_price = float(comm_offer.get("ListPrice", price))
                    available = comm_offer.get("IsAvailable", True)

                title_val = item.get("productName", "").strip() or "Sin título"
                extracted_brand = item.get("brand") or item.get("brandName")

                if not extracted_brand and title_val != "Sin título":
                    extracted_brand = title_val.split()[0].capitalize()

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val,
                    brand=str(extracted_brand).strip() if extracted_brand else "Sin Marca",
                    base_price=list_price if list_price > 0 else price,
                    discount_price=price if (0 < price < list_price) else None,
                    in_stock=available
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] {self.retailer.upper()}: {e}", flush=True)
                continue

        return parsed_results

async def run_vtex_scraping(conn) -> int:
    search_configs = []
    with conn.cursor() as cur:
        cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
        rows = cur.fetchall()
        search_configs = [r["search_term"] for r in rows] if rows else []

    if not search_configs:
        search_configs = ["leche"]

    total_saved = 0
    from app.main import save_scraper_results

    for retailer in ["exito", "carulla"]:
        print(f"\n[SCRAPING] Iniciando extracción VTEX para: {retailer.upper()}", flush=True)
        scraper = VTEXScraper(retailer=retailer)
        for term in search_configs:
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