import os
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
        self.scraper_api_key = os.getenv("SCRAPERAPI_KEY") or os.getenv("SCRAPER_API_KEY")

    def _build_url(self, target_url: str) -> str:
        """Pasa la petición por ScraperAPI para evitar el bloqueo 403."""
        if self.scraper_api_key:
            encoded_target = urllib.parse.quote(target_url, safe="")
            return f"http://api.scraperapi.com?api_key={self.scraper_api_key}&url={encoded_target}"
        return target_url

    def _get_headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
            "Referer": f"{self.base_url}/",
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        extracted_products: List[ExtractedProductData] = []
        encoded_keyword = urllib.parse.quote(keyword)

        # RUTA CORREGIDA: Usamos Intelligent Search v2 (Es la misma API que usa el Front de la Web de Éxito/Carulla)
        target_endpoint = (
            f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}"
            f"?page=1&count={limit}&sort=relevance:desc"
        )
        
        final_url = self._build_url(target_endpoint)

        async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
            try:
                response = await client.get(final_url, headers=self._get_headers())

                # Fallback a la API de catálogo en caso de que Intelligent Search devuelva un código distinto a 200
                if response.status_code != 200:
                    fallback_endpoint = (
                        f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_keyword}"
                        f"?_from=0&_to={limit - 1}"
                    )
                    final_url = self._build_url(fallback_endpoint)
                    response = await client.get(final_url, headers=self._get_headers())

                if response.status_code != 200:
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{keyword}'", flush=True)
                    return []

                raw_data = response.json()
                
                # Intelligent Search estructura los productos dentro de "products"
                if isinstance(raw_data, dict):
                    items_list = raw_data.get("products", [])
                else:
                    items_list = raw_data

                if not isinstance(items_list, list):
                    return []

                visible_position = 1

                for product in items_list:
                    try:
                        title = product.get("productName") or product.get("productTitle") or ""
                        brand = product.get("brand") or "Sin Marca"

                        base_price = 0.0
                        discount_price = None
                        in_stock = True

                        items = product.get("items", [])
                        if items and len(items) > 0:
                            sellers = items[0].get("sellers", [])
                            if sellers and len(sellers) > 0:
                                offer = sellers[0].get("commertialOffer", {})
                                list_p = float(offer.get("ListPrice", 0.0) or 0.0)
                                price_p = float(offer.get("Price", 0.0) or 0.0)

                                if price_p < list_p and price_p > 0:
                                    base_price = list_p
                                    discount_price = price_p
                                else:
                                    base_price = price_p if price_p > 0 else list_p

                                qty = offer.get("AvailableQuantity", 0)
                                in_stock = qty > 0 if qty is not None else True

                        if title:
                            # Solo incrementamos la posición visible si el producto está disponible o
                            # si queremos auditar exactamente el orden de la tienda física/virtual
                            extracted_products.append(
                                ExtractedProductData(
                                    search_keyword=keyword,
                                    search_position=visible_position,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                            visible_position += 1

                    except Exception as parse_err:
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{keyword}': {req_err}", flush=True)
                return []

        return extracted_products