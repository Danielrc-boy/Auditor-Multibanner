import os
import urllib.parse
from typing import List, Optional
import httpx
from pydantic import BaseModel

SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")


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
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        }

    def _build_request(self, target_url: str):
        """Enruta la petición a través de ScraperAPI si hay una key configurada."""
        if SCRAPERAPI_KEY:
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return target_url, None

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        encoded_keyword = urllib.parse.quote(keyword)

        # Ruta verificada con evidencia real (con /io/ delante) — sin esto, Éxito/Carulla
        # responden 403/406 detrás de su protección Cloudflare.
        target_url = (
            f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_keyword}"
            f"?_from=0&_to={limit - 1}"
        )
        request_url, params = self._build_request(target_url)

        extracted_products: List[ExtractedProductData] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
            try:
                response = await client.get(request_url, headers=self.headers, params=params)

                if response.status_code not in (200, 206):
                    fallback_target = (
                        f"{self.base_url}/io/api/io/_v/api/intelligent-search/product_search/{encoded_keyword}"
                        f"?page=1&count={limit}"
                    )
                    fb_url, fb_params = self._build_request(fallback_target)
                    response = await client.get(fb_url, headers=self.headers, params=fb_params)

                if response.status_code not in (200, 206):
                    print(f"[{self.retailer.upper()} ERROR] HTTP Status {response.status_code} para '{keyword}'")
                    return []

                raw_data = response.json()
                items_list = raw_data.get("products", raw_data) if isinstance(raw_data, dict) else raw_data
                if not isinstance(items_list, list):
                    return []

                position_counter = 1
                for product in items_list[:limit]:
                    try:
                        title = product.get("productName") or product.get("productTitle") or ""
                        brand = product.get("brand") or "Sin Marca"

                        base_price = 0.0
                        discount_price = None
                        in_stock = True

                        items = product.get("items", [])
                        if items:
                            sellers = items[0].get("sellers", [])
                            if sellers:
                                offer = sellers[0].get("commertialOffer", {})
                                base_price = float(offer.get("ListPrice", 0.0) or offer.get("Price", 0.0))
                                current_price = float(offer.get("Price", 0.0))
                                if 0 < current_price < base_price:
                                    discount_price = current_price
                                elif base_price == 0 and current_price > 0:
                                    base_price = current_price
                                available_qty = offer.get("AvailableQuantity", 0)
                                in_stock = (available_qty or 0) > 0

                        # Igual que en Farmatodo: solo numeramos posición sobre
                        # productos disponibles, como los ve un comprador real.
                        if not in_stock:
                            continue

                        if title:
                            extracted_products.append(
                                ExtractedProductData(
                                    search_keyword=keyword,
                                    search_position=position_counter,
                                    title=title.strip(),
                                    brand=str(brand).strip(),
                                    base_price=base_price,
                                    discount_price=discount_price,
                                    in_stock=in_stock,
                                )
                            )
                            position_counter += 1
                    except Exception as parse_err:
                        print(f"[{self.retailer.upper()} PARSE ERROR]: {parse_err}")
                        continue

            except Exception as req_err:
                print(f"[{self.retailer.upper()} REQUEST ERROR] '{keyword}': {req_err}")
                return []

        return extracted_products