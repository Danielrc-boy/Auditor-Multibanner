import json
import urllib.parse
import httpx
from typing import List, Dict, Any
from app.models.schemas import ExtractedProductData

class VTEXScraper:
    # ... (mantener inicialización de la clase y _build_request)

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        # Payload alineado 1:1 con la Web UI de FastStore VTEX (sin 'after' ruidoso)
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

    def _parse_graphql_product(self, item: Dict[Any, Any], position: int, keyword: str) -> ExtractedProductData:
        """Extrae de forma robusta precios normales, con descuento y posición."""
        node = item.get("node", item)
        
        name = node.get("name") or node.get("productName", "")
        brand = node.get("brand", {}).get("name", "") if isinstance(node.get("brand"), dict) else node.get("brand", "")
        
        # Extracción de Oferta y Precios
        offers = node.get("offers", {}).get("offers", [])
        original_price = 0.0
        discount_price = 0.0
        
        if offers:
            main_offer = offers[0]
            # Price es el precio final de venta (con descuento si aplica)
            discount_price = float(main_offer.get("price", 0.0))
            # listPrice es el precio base sin descuento
            original_price = float(main_offer.get("listPrice", discount_price))
            
            # Si no hay descuento real, el precio con descuento coincide con el original
            if discount_price >= original_price:
                discount_price = original_price

        return ExtractedProductData(
            search_position=position,
            search_term=keyword,
            product_name=name,
            brand=brand,
            original_price=original_price,
            discount_price=discount_price,
            retailer=self.retailer
        )