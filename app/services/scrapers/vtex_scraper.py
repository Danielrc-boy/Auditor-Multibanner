import sys
import json
import urllib.parse
import httpx
from pathlib import Path
from typing import List, Dict, Any

# Resolvemos la importación de ExtractedProductData dinámicamente para evitar fallas
root_path = Path(__file__).resolve().parent.parent.parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

try:
    from app.schemas import ExtractedProductData
except ModuleNotFoundError:
    from app.models.schemas import ExtractedProductData

class VTEXScraper:
    def __init__(self, retailer: str = "exito", base_url: str = "https://www.exito.com"):
        self.retailer = retailer
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }

    def _build_request(self, url: str, params: dict | None) -> tuple[str, dict | None]:
        return url, params

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        # Payload idéntico a la UI de FastStore VTEX
        variables_payload = {
            "first": limit,
            "sort": "score_desc",
            "term": keyword,
            "selectedFacets": [
                {"key": "channel", "value": '{"salesChannel":"1","regionId":""}'},
                {"key": "locale", "value": "es-CO"}
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

            # Fallback a REST Intelligent Search
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{urllib.parse.quote(keyword)}"
            is_params = {
                "page": 1,
                "count": limit,
                "query": keyword,
                "sort": "",
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

    def _parse_graphql_response(self, data: dict, keyword: str) -> List[ExtractedProductData]:
        parsed = []
        try:
            products = data.get("data", {}).get("search", {}).get("products", {}).get("edges", [])
            for index, item in enumerate(products, start=1):
                prod = self._parse_graphql_product(item, index, keyword)
                if prod:
                    parsed.append(prod)
        except Exception as e:
            print(f"[PARSER ERROR] {self.retailer.upper()} GraphQL: {e}", flush=True)
        return parsed

    def _parse_graphql_product(self, item: Dict[Any, Any], position: int, keyword: str) -> ExtractedProductData:
        node = item.get("node", item)
        title = node.get("name") or node.get("productName", "")
        brand = node.get("brand", {}).get("name", "") if isinstance(node.get("brand"), dict) else node.get("brand", "Sin Marca")
        
        offers = node.get("offers", {}).get("offers", [])
        base_price = 0.0
        discount_price = None
        seller_name = "Sin Vendedor"
        in_stock = True

        if offers:
            main_offer = offers[0]
            curr_discount = float(main_offer.get("price", 0.0))
            curr_base = float(main_offer.get("listPrice", curr_discount))
            seller_name = main_offer.get("seller", {}).get("identifier", "Éxito/Carulla")
            
            if curr_discount < curr_base and curr_discount > 0:
                base_price = curr_base
                discount_price = curr_discount
            else:
                base_price = curr_base if curr_base > 0 else curr_discount

        return ExtractedProductData(
            search_keyword=keyword,
            search_position=position,
            title=title,
            brand=brand if brand else "Sin Marca",
            base_price=base_price,
            discount_price=discount_price,
            in_stock=in_stock,
            seller_name=seller_name
        )

    def _parse_intelligent_search(self, products_raw: list, keyword: str, limit: int) -> List[ExtractedProductData]:
        parsed = []
        for index, prod in enumerate(products_raw[:limit], start=1):
            title = prod.get("productName", "")
            brand = prod.get("brand", "Sin Marca")
            items = prod.get("items", [])
            
            base_price = 0.0
            discount_price = None
            seller_name = "Sin Vendedor"

            if items:
                sellers = items[0].get("sellers", [])
                if sellers:
                    comm_offer = sellers[0].get("commertialOffer", {})
                    curr_discount = float(comm_offer.get("Price", 0.0))
                    curr_base = float(comm_offer.get("ListPrice", curr_discount))
                    seller_name = sellers[0].get("sellerName", "Sin Vendedor")

                    if curr_discount < curr_base and curr_discount > 0:
                        base_price = curr_base
                        discount_price = curr_discount
                    else:
                        base_price = curr_base if curr_base > 0 else curr_discount

            parsed.append(
                ExtractedProductData(
                    search_keyword=keyword,
                    search_position=index,
                    title=title,
                    brand=brand,
                    base_price=base_price,
                    discount_price=discount_price,
                    in_stock=True,
                    seller_name=seller_name
                )
            )
        return parsed