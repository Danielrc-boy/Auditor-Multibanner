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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "es-CO,es;q=0.9",
            "Referer": f"{self.base_url}/s?q=toallas+higienicas&sort=score_desc&page=0",
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        # Facets universales que incluyen Marketplace / Terceros
        variables_payload = {
            "first": limit,
            "after": "0",
            "sort": "score_desc",
            "term": keyword,
            "selectedFacets": [
                {
                    "key": "channel",
                    "value": json.dumps({"salesChannel": "1", "regionId": ""})
                },
                {
                    "key": "locale",
                    "value": "es-CO"
                }
            ]
        }

        variables_json = json.dumps(variables_payload)
        encoded_variables = urllib.parse.quote(variables_json)
        
        gql_url = f"{self.base_url}/api/graphql?operationName=SearchQuery&variables={encoded_variables}"
        request_url, params = self._build_request(gql_url, None)

        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)
                if response.status_code == 200:
                    data = response.json()
                    products = self._parse_graphql_response(data, keyword)
                    if products:
                        return products
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] GraphQL SearchQuery falló: {e}", flush=True)

            # Fallback REST Intelligent Search
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{urllib.parse.quote(keyword)}"
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
                if response.status_code in (200, 206):
                    data = response.json()
                    products_raw = data.get("products", []) if isinstance(data, dict) else []
                    if products_raw:
                        return self._parse_intelligent_search(products_raw, keyword, limit)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] REST Intelligent Search falló: {e}", flush=True)

        return []

    def _build_request(self, target_url: str, params_dict: dict = None):
        if SCRAPERAPI_KEY:
            if params_dict:
                query_string = "&".join([f"{k}={v}" for k, v in params_dict.items()])
                full_target = f"{target_url}?{query_string}"
            else:
                full_target = target_url
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": full_target}
        return target_url, params_dict

    def _parse_graphql_response(self, data: dict, search_term: str) -> List[ExtractedProductData]:
        parsed = []
        try:
            edges = data.get("data", {}).get("search", {}).get("products", {}).get("edges", [])
            for idx, edge in enumerate(edges, start=1):
                node = edge.get("node", {})
                offers_wrapper = node.get("offers", {})
                offers = offers_wrapper.get("offers", [{}]) if isinstance(offers_wrapper, dict) else [{}]
                offer = offers[0] if offers else {}

                price = float(offer.get("price", 0.0) or 0.0)
                list_price = float(offer.get("listPrice", 0.0) or price)
                discount_price = price if (0 < price < list_price) else None

                # Extraer el vendedor / seller real (Tercero vs Propio)
                seller_info = offer.get("seller", {})
                seller_name = seller_info.get("sellerName") if isinstance(seller_info, dict) else None
                if not seller_name:
                    seller_name = self.default_seller

                parsed.append(ExtractedProductData(
                    search_keyword=search_term,
                    search_position=idx,
                    title=node.get("name", "Sin título"),
                    brand=node.get("brand", {}).get("name", "Sin Marca") if isinstance(node.get("brand"), dict) else "Sin Marca",
                    base_price=list_price,
                    discount_price=discount_price,
                    in_stock="InStock" in str(offer.get("availability", "")),
                    seller_name=seller_name
                ))
        except Exception as e:
            print(f"[PARSER GQL ERROR] {self.retailer.upper()}: {e}", flush=True)
        return parsed

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
                if not seller_name:
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