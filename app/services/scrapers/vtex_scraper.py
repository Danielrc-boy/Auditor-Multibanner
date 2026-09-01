import os
import httpx
from typing import List, Optional
from dataclasses import dataclass

@dataclass
class ExtractedProductData:
    search_keyword: str
    search_position: int
    title: str
    brand: str
    base_price: float
    discount_price: Optional[float]
    in_stock: bool
    is_ad: bool = False
    banner_campaign: str = ""

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.domain = "https://www.carulla.com" if self.retailer == "carulla" else "https://www.exito.com"
        self.graphql_url = f"{self.domain}/_v/public/graphql/v1"

    async def search_keyword(self, search_term: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_term = search_term.strip()
        
        query = """
        query ProductSearch($fullText: String, $from: Int, $to: Int) {
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
            "query": query,
            "variables": {
                "fullText": clean_term,
                "from": 0,
                "to": limit - 1
            }
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.graphql_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                products_data = data.get("data", {}).get("productSearch", {}).get("products", [])
                return self._parse_products(products_data, clean_term)

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
                    in_stock=in_stock,
                    is_ad=False,
                    banner_campaign=""
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