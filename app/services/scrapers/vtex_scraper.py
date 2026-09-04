import sys
import json
import urllib.parse
import httpx
from pathlib import Path
from typing import List, Dict, Any

# Resolvemos la importación de ExtractedProductData dinámicamente
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

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        if not isinstance(keyword, str) or not keyword.strip():
            print(f"[WARN {self.retailer.upper()}] Keyword no válida recibida: {type(keyword)}", flush=True)
            return []

        keyword = keyword.strip()

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

        async with httpx.AsyncClient(timeout=30.0, verify=False, follow_redirects=True) as client:
            try:
                response = await client.get(gql_url, headers=self.headers)
                if response.status_code == 200:
                    products = self._parse_graphql_response(response.json(), keyword)
                    if products:
                        return products
            except Exception as e:
                print(f"[WARN {self.retailer.upper()}] GraphQL SearchQuery falló: {e}", flush=True)

            # Fallback a REST Intelligent Search
            is_url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{urllib.parse.quote(keyword)}"
            is_params = {"page": 1, "count": limit, "query": keyword, "locale": "es-CO"}
            
            try:
                response = await client.get(is_url, headers=self.headers, params=is_params)
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
                node = item.get("node", item)
                title = node.get("name") or node.get("productName", "")
                if not title:
                    continue

                brand = node.get("brand", {}).get("name", "") if isinstance(node.get("brand"), dict) else node.get("brand", "Sin Marca")
                offers = node.get("offers", {}).get("offers", [])
                
                base_price = 0.0
                discount_price = None
                seller_name = "Éxito"

                if offers:
                    main_offer = offers[0]
                    curr_discount = float(main_offer.get("price", 0.0))
                    curr_base = float(main_offer.get("listPrice", curr_discount))
                    seller_name = main_offer.get("seller", {}).get("identifier", "Éxito/Carulla")

                    if 0 < curr_discount < curr_base:
                        base_price = curr_base
                        discount_price = curr_discount
                    else:
                        base_price = curr_base if curr_base > 0 else curr_discount

                parsed.append(
                    ExtractedProductData(
                        search_keyword=keyword,
                        search_position=index,
                        title=title,
                        brand=brand if brand else "Sin Marca",
                        base_price=base_price,
                        discount_price=discount_price,
                        in_stock=True,
                        seller_name=seller_name
                    )
                )
        except Exception as e:
            print(f"[PARSER ERROR] {self.retailer.upper()} GraphQL: {e}", flush=True)
        return parsed

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
                    comm = sellers[0].get("commertialOffer", {})
                    
                    # DEBUG TEMPORAL PARA AUDITAR PRECIOS
                    if index <= 3:
                        print(f"[DEBUG PRECIO {self.retailer.upper()}] {prod.get('productName')}: {comm}", flush=True)

                    curr_discount = float(comm.get("Price", 0.0))
                    curr_base = float(comm.get("ListPrice", curr_discount))
                    seller_name = sellers[0].get("sellerName", "Sin Vendedor")

                    if 0 < curr_discount < curr_base:
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


# ==============================================================================
# RUNNER EXHAUSTIVO Y SEGURO PARA EL ORQUESTADOR
# ==============================================================================

def _extract_keyword_from_any(obj: Any) -> str | None:
    """Inspecciona recursivamente el objeto recibido para extraer el texto de búsqueda."""
    if isinstance(obj, str) and not obj.startswith("user="):
        return obj
    if isinstance(obj, dict):
        for key in ["keyword", "search_keyword", "query", "term", "name"]:
            if key in obj and isinstance(obj[key], str):
                return obj[key]
    if hasattr(obj, "search_keyword") and isinstance(obj.search_keyword, str):
        return obj.search_keyword
    if hasattr(obj, "keyword") and isinstance(obj.keyword, str):
        return obj.keyword
    return None

async def run_vtex_scraping(*args, **kwargs) -> List[ExtractedProductData]:
    keyword = None

    # 1. Buscar en kwargs
    for key in ["keyword", "search_keyword", "query", "term"]:
        if key in kwargs and isinstance(kwargs[key], str):
            keyword = kwargs[key]
            break

    # 2. Si no estuvo en kwargs, buscar entre los argumentos posicionales
    if not keyword:
        for arg in args:
            extracted = _extract_keyword_from_any(arg)
            if extracted:
                keyword = extracted
                break

    retailer = kwargs.get("retailer", "exito")
    base_url = kwargs.get("base_url", "https://www.exito.com")
    limit = kwargs.get("limit", 50)

    if not keyword:
        print(f"[RUNNER ERROR] VTEX Scraper ({retailer}): No se recibió una keyword válida.", flush=True)
        return []

    try:
        scraper = VTEXScraper(retailer=retailer, base_url=base_url)
        return await scraper.search_keyword(keyword=keyword, limit=limit)
    except Exception as e:
        print(f"[RUNNER ERROR] Excepción en VTEX Scraper para '{keyword}': {e}", flush=True)
        return []