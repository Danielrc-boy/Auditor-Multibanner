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

# 1. Ajuste en VTEXScraper para evitar el 403 de Éxito
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

        # Headers mínimos necesarios para superar el filtro WAF de VTEX
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": self.domain,
            "Referer": f"{self.domain}/"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.post(self.graphql_url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                products_data = data.get("data", {}).get("productSearch", {}).get("products", [])
                return self._parse_products(products_data, clean_term)

            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error al scrapear '{clean_term}': {e}", flush=True)
                return []


# 2. Ajuste en run_vtex_scraping para asegurar que procese Carulla y Éxito
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
            search_configs = [{"search_term": r["search_term"], "retailer": "todos"} for r in rows] if rows else []

    if not search_configs:
        return 0

    total_saved = 0
    from app.main import save_scraper_results

    for config in search_configs:
        term = config["search_term"]
        raw_retailer = str(config.get("retailer") or "todos").lower().strip()

        # Si no especifica un retailer único, recorre la lista completa
        if raw_retailer in ["exito", "carulla"]:
            target_retailers = [raw_retailer]
        else:
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