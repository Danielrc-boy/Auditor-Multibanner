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
        """Enruta la petición a través de ScraperAPI para evitar bloqueos 403 de Cloudflare."""
        if self.scraper_api_key:
            encoded_target = urllib.parse.quote(target_url)
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

        # Ruta confirmada con la estructura /io/ para VTEX
        target_endpoint = (
            f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_keyword}"
            f"?_from=0&_to={limit - 1}"
        )
        
        final_url = self._build_url(target_endpoint)

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                response = await client.get(final_url, headers=self._get_headers())

                if response.status_code != 200:
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{keyword}'", flush=True)
                    return []

                raw_data = response.json()
                items_list = raw_data.get("products", raw_data) if isinstance(raw_data, dict) else raw_data

                if not isinstance(items_list, list):
                    return []

                # Mantener la posición ordinal exacta de la góndola (1..N)
                for real_position, product in enumerate(items_list, start=1):
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
                                    search_keyword=keyword,
                                    # La posición respeta la posición orgánica en la búsqueda
                                    search_position=real_position,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                    except Exception as parse_err:
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{keyword}': {req_err}", flush=True)
                return []

        return extracted_products