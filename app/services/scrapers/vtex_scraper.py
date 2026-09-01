import os
import re
import unicodedata
import httpx
from dataclasses import dataclass
from typing import Optional, List

# ==============================================================================
# MODELO DE DATOS UNIFICADO
# ==============================================================================
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


# ==============================================================================
# SCRAPER VTEX GRAPHQL (ÉXITO Y CARULLA - BYPASS COMPLETO 403)
# ==============================================================================
class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.retailer = retailer.lower()
        self.domain = "https://www.carulla.com" if self.retailer == "carulla" else "https://www.exito.com"
        self.graphql_url = f"{self.domain}/_v/public/graphql/v1"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": self.domain,
            "Referer": f"{self.domain}/"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_term = search_term.strip()
        
        # Query GraphQL que utiliza el motor de la tienda sin pasar por WAF rest
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

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.post(self.graphql_url, json=payload, headers=self.headers)
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


# ==============================================================================
# SCRAPER FARMATODO (ALGOLIA ENGINE)
# ==============================================================================
FARMATODO_ALGOLIA_URL = os.getenv("FARMATODO_ALGOLIA_URL", "https://api-search.farmatodo.com/1/indexes/*/queries")
FARMATODO_APP_ID = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO")
FARMATODO_API_KEY = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb")
FARMATODO_INDEX_NAME = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia")

KNOWN_BRANDS = [
    "Nosotras", "Kotex", "Stayfree", "Pequeñín", "Winny", "Farmatodo",
    "Huggies", "Pampers", "Nivea", "Dove", "Protex", "Saba", "Tena",
    "Gillette", "Colgate", "Sensodyne", "Neutrogena", "Cetaphil"
]

class FarmatodoScraper:
    def __init__(self):
        self.endpoint = FARMATODO_ALGOLIA_URL
        self.headers = {
            "x-algolia-application-id": FARMATODO_APP_ID.strip(),
            "x-algolia-api-key": FARMATODO_API_KEY.strip(),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> List[ExtractedProductData]:
        clean_term = search_term.strip()
        
        payload = {
            "requests": [
                {
                    "indexName": FARMATODO_INDEX_NAME,
                    "params": f"query={clean_term}&hitsPerPage={limit}&getRankingInfo=true"
                }
            ]
        }

        # Sin parametro http2 para prevenir bloqueos de despliegue
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.endpoint, headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results")
                if not results or not isinstance(results, list):
                    return []
                
                result_obj = results[0]
                if not isinstance(result_obj, dict):
                    return []
                
                hits = result_obj.get("hits")
                if hits is None or not isinstance(hits, list):
                    hits = []

                banner_campaign = self._extract_banner_negotiation(result_obj)
                return self._parse_products(hits, clean_term, banner_campaign)

            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{clean_term}': {e}", flush=True)
                return []

    def _extract_brand(self, item: dict, title: str) -> str:
        raw_brand = item.get("brandName") or item.get("marca") or item.get("brand_name") or item.get("brand")
        
        if isinstance(raw_brand, dict):
            raw_brand = raw_brand.get("name") or raw_brand.get("label")
        elif isinstance(raw_brand, list) and len(raw_brand) > 0:
            raw_brand = raw_brand[0]

        brand_str = str(raw_brand).strip() if raw_brand else ""
        is_code_brand = bool(re.search(r'\d', brand_str) and '-' in brand_str) or brand_str.startswith("2008")

        first_word_of_title = title.split()[0] if title else ""
        is_title_word_copy = brand_str.lower() == first_word_of_title.lower()

        if brand_str and brand_str.lower() not in ["none", "null", "sin marca"] and not is_code_brand and not is_title_word_copy:
            return brand_str

        for brand in KNOWN_BRANDS:
            if re.search(rf'\b{brand}\b', title, re.IGNORECASE):
                return brand

        return "Sin Marca"

    def _extract_banner_negotiation(self, result_obj: dict) -> str:
        user_data_list = result_obj.get("userData") or []
        if isinstance(user_data_list, list):
            for data_item in user_data_list:
                if isinstance(data_item, dict):
                    banner_title = data_item.get("banner") or data_item.get("title") or data_item.get("campaign")
                    if banner_title:
                        return str(banner_title).strip()
        return ""

    def _detect_discount_percentage(self, item: dict, title: str) -> Optional[float]:
        for key in ["discountPercent", "discount_percent", "percentage", "discount"]:
            val = item.get(key)
            if val is not None:
                try:
                    pct = float(val)
                    if 0 < pct < 100:
                        return pct
                except (ValueError, TypeError):
                    pass

        match_title = re.search(r'(\d{1,2})\s*%\s*(?:dcto|off|descuento)?', title, re.IGNORECASE)
        if match_title:
            try:
                pct = float(match_title.group(1))
                if 0 < pct < 100:
                    return pct
            except ValueError:
                pass

        promos = item.get("promotions") or item.get("badges") or item.get("tags") or []
        match_promo = re.search(r'(\d{1,2})\s*%', str(promos))
        if match_promo:
            try:
                pct = float(match_promo.group(1))
                if 0 < pct < 100:
                    return pct
            except ValueError:
                pass

        return None

    def _extract_prices(self, item: dict, title: str) -> tuple[float, Optional[float]]:
        base_price = float(item.get("fullPrice") or item.get("price") or 0.0)
        if base_price <= 0:
            return 0.0, None

        full_p = item.get("fullPrice")
        curr_p = item.get("price")
        if full_p and curr_p:
            try:
                f_val, c_val = float(full_p), float(curr_p)
                if 0 < c_val < f_val:
                    return f_val, c_val
            except (ValueError, TypeError):
                pass

        pct = self._detect_discount_percentage(item, title)
        discount_price = None

        if pct is not None:
            discount_price = round(base_price * (1.0 - (pct / 100.0)), 2)

        return base_price, discount_price

    def _parse_products(self, raw_hits: list, search_term: str, global_banner: str = "") -> List[ExtractedProductData]:
        parsed_results = []
        valid_position = 1

        for item in raw_hits:
            if not isinstance(item, dict):
                continue
            try:
                title = item.get("mediaDescription") or item.get("description") or item.get("name") or ""
                title = str(title).strip()
                if not title:
                    continue

                final_brand = self._extract_brand(item, title)
                base_price, discount_price = self._extract_prices(item, title)

                is_out_of_store = bool(item.get("outofstore", False))
                in_stock = not is_out_of_store

                ranking_info = item.get("_rankingInfo") or {}
                is_ad = bool(
                    item.get("sponsored") or 
                    item.get("isSponsored") or 
                    item.get("is_ad") or 
                    item.get("isAd") or 
                    item.get("ad") or
                    ranking_info.get("promoted", False)
                )

                banner_campaign = str(item.get("bannerCampaign") or item.get("campaign") or global_banner).strip()

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=valid_position,
                    title=title,
                    brand=final_brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=in_stock,
                    is_ad=is_ad,
                    banner_campaign=banner_campaign
                )
                parsed_results.append(product)
                valid_position += 1

            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results


# ==============================================================================
# EJECUCIÓN GENERAL
# ==============================================================================
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
        if raw_retailer in ["exito", "carulla", "farmatodo"]:
            target_retailers = [raw_retailer]
        elif raw_retailer in ["todos", "all", ""]:
            target_retailers = ["exito", "carulla", "farmatodo"]

        for retailer in target_retailers:
            if retailer == "farmatodo":
                scraper = FarmatodoScraper()
            else:
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