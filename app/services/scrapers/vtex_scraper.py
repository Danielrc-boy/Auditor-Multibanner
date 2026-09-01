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
            self.base_url = "https://www.carulla.com/_v/segment/graphql/v1"
            self.domain = "www.carulla.com"
        else:
            self.base_url = "https://www.exito.com/_v/segment/graphql/v1"
            self.domain = "www.exito.com"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": f"https://{self.domain}",
            "Referer": f"https://{self.domain}/"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_term = search_term.strip()
        
        # GraphQL Query nativa de VTEX IO que evade bloqueos WAF 403
        graphql_query = """
        query productSearch($fullText: String, $from: Int, $to: Int) {
          productSearch(fullText: $fullText, from: $from, to: $to) {
            products {
              productName
              brand
              items {
                sellers {
                  commertialOffer {
                    ListPrice
                    Price
                    AvailableQuantity
                  }
                }
              }
            }
          }
        }
        """
        
        payload = {
            "query": graphql_query,
            "variables": {
                "fullText": clean_term,
                "from": 0,
                "to": limit - 1
            }
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                # Intentar primero por GraphQL
                response = await client.post(self.base_url, json=payload, headers=self.headers)
                
                if response.status_code == 200:
                    data = response.json()
                    products = data.get("data", {}).get("productSearch", {}).get("products", [])
                    if products:
                        return self._parse_products(products, clean_term)

                # Fallback REST si GraphQL no responde
                rest_url = f"https://{self.domain}/api/catalog_system/pub/products/search?ft={urllib.parse.quote(clean_term)}&_from=0&_to={limit-1}"
                res_rest = await client.get(rest_url, headers=self.headers)
                if res_rest.status_code == 200:
                    return self._parse_products(res_rest.json(), clean_term)

                print(f"[ERROR {self.retailer.upper()}] Status Code: {response.status_code}", flush=True)
                return []

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