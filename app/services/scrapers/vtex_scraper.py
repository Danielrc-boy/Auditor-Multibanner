import urllib.parse
from typing import List, Optional
import httpx
from pydantic import BaseModel


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


class VTEXScraper:
    def __init__(self, retailer: str, base_url: str):
        self.retailer = retailer.lower()
        self.base_url = base_url.rstrip("/")
        # Headers para evitar bloqueos de Cloudflare/VTEX
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Referer": self.base_url,
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        # Codificar de forma segura términos con espacios o caracteres especiales
        encoded_keyword = urllib.parse.quote(keyword)
        
        # Endpoint nativo de catálogo VTEX
        endpoint = (
            f"{self.base_url}/api/catalog_system/pub/products/search/{encoded_keyword}"
            f"?_from=0&_to={limit - 1}"
        )

        extracted_products: List[ExtractedProductData] = []

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                response = await client.get(endpoint, headers=self.headers)

                # Si el endpoint clásico devuelve 404 o falla, probar el fallback de búsqueda inteligente
                if response.status_code != 200:
                    fallback_endpoint = (
                        f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}"
                        f"?page=1&count={limit}"
                    )
                    response = await client.get(fallback_endpoint, headers=self.headers)

                if response.status_code != 200:
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{keyword}'")
                    return []

                raw_data = response.json()
                
                # Manejar respuesta si viene en formato Intelligent Search (dict con key 'products')
                items_list = raw_data.get("products", raw_data) if isinstance(raw_data, dict) else raw_data

                if not isinstance(items_list, list):
                    return []

                for idx, product in enumerate(items_list, start=1):
                    try:
                        title = product.get("productName") or product.get("productTitle") or ""
                        brand = product.get("brand") or "Sin Marca"

                        # Parseo de Precios y Stock desde la jerarquía de VTEX (items -> sellers -> commertialOffer)
                        base_price = 0.0
                        discount_price = None
                        in_stock = True

                        items = product.get("items", [])
                        if items and len(items) > 0:
                            sellers = items[0].get("sellers", [])
                            if sellers and len(sellers) > 0:
                                offer = sellers[0].get("commertialOffer", {})
                                base_price = float(offer.get("ListPrice", 0.0) or offer.get("Price", 0.0))
                                current_price = float(offer.get("Price", 0.0))
                                
                                if current_price < base_price and current_price > 0:
                                    discount_price = current_price
                                else:
                                    base_price = current_price
                                
                                available_qty = offer.get("AvailableQuantity", 0)
                                in_stock = available_qty > 0 if available_qty is not None else True

                        if title:
                            extracted_products.append(
                                ExtractedProductData(
                                    search_keyword=keyword,
                                    search_position=idx,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                    except Exception as parse_err:
                        print(f"[{self.retailer.upper()} PARSE ERROR] Item {idx}: {parse_err}")
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{keyword}': {req_err}")
                return []

        return extracted_products