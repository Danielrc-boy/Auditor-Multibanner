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
    """Objeto que encapsula los campos requeridos por main.py"""
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
        self.brand = brand
        self.base_price = base_price
        self.discount_price = discount_price
        self.in_stock = in_stock

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.base_url = RETAILER_URLS.get(self.retailer, "https://www.exito.com")

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        encoded_term = urllib.parse.quote(search_term)
        target_url = (
            f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_term}"
            f"?_from=0&_to={limit - 1}"
        )

        if self.retailer == "exito" and SCRAPERAPI_KEY:
            request_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={urllib.parse.quote(target_url)}"
            headers = {"Accept": "application/json"}
        else:
            request_url = target_url
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json"
            }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=headers)
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
                # --- PASO 2: LOG DE EVIDENCIA CRUDA ---
                if index == 1:
                    print(f"[DEBUG {self.retailer.upper()}] {item}", flush=True)

                items_list = item.get("items", [])
                if not items_list:
                    continue

                first_item = items_list[0]
                sellers = first_item.get("sellers", [])

                price = 0.0
                list_price = 0.0
                available = True

                if sellers:
                    comm_offer = sellers[0].get("commertialOffer", {})
                    price = float(comm_offer.get("Price", 0.0))
                    list_price = float(comm_offer.get("ListPrice", price))
                    available = comm_offer.get("IsAvailable", True)

                extracted_brand = item.get("brand") or item.get("brandName")
                title_val = item.get("productName", "").strip()

                if not extracted_brand or str(extracted_brand).strip() in ["", "None", "null"]:
                    if title_val:
                        first_word = title_val.split()[0]
                        extracted_brand = first_word.capitalize()
                    else:
                        extracted_brand = "Sin Marca"

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title_val if title_val else "Sin título",
                    brand=str(extracted_brand).strip(),
                    base_price=list_price if list_price > 0 else price,
                    discount_price=price if (price > 0 and price < list_price) else None,
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
    from main import save_scraper_results

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