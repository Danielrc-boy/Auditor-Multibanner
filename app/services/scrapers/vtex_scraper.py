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
        # Garantizar que la base_url siempre tenga esquema https://
        url = base_url.strip().rstrip("/")
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        self.base_url = url
        self.scraper_api_key = os.getenv("SCRAPERAPI_KEY") or os.getenv("SCRAPER_API_KEY")

    def _build_url(self, target_url: str) -> str:
        """Enruta la petición a través de ScraperAPI con encoding seguro."""
        if self.scraper_api_key:
            encoded_target = urllib.parse.quote(target_url, safe="")
            return f"http://api.scraperapi.com?api_key={self.scraper_api_key.strip()}&url={encoded_target}"
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
        }

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        extracted_products: List[ExtractedProductData] = []
        clean_keyword = keyword.strip()
        encoded_keyword = urllib.parse.quote(clean_keyword)

        # Target 1: Intelligent Search v2 (el motor comercial visual)
        target_endpoint = (
            f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}"
            f"?page=1&count={limit}&query={encoded_keyword}&locale=es-CO"
        )
        
        final_url = self._build_url(target_endpoint)

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            try:
                response = await client.get(final_url, headers=self._get_headers())

                # Target 2 (Fallback): Catalog API /io/ si el endpoint v2 no devuelve 200
                if response.status_code != 200:
                    fallback_endpoint = (
                        f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_keyword}"
                        f"?_from=0&_to={limit - 1}"
                    )
                    final_url = self._build_url(fallback_endpoint)
                    response = await client.get(final_url, headers=self._get_headers())

                if response.status_code != 200:
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{clean_keyword}'", flush=True)
                    return []

                raw_data = response.json()
                
                # Normalizar la estructura según el endpoint que haya respondido
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
                            extracted_products.append(
                                ExtractedProductData(
                                    search_keyword=clean_keyword,
                                    search_position=visible_position,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                            # Incremento directo alineado con la parrilla visual
                            if in_stock:
                                visible_position += 1

                    except Exception as parse_err:
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{clean_keyword}': {req_err}", flush=True)
                return []

        return extracted_products