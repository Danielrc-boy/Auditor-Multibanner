import httpx
from typing import List
from app.services.scrapers.base import ExtractedProductData

class VTEXScraper:
    def __init__(self, base_url: str = "https://www.exito.com"):
        self.base_url = base_url.rstrip("/")

    async def search_keyword(self, keyword: str, limit: int = 10) -> List[ExtractedProductData]:
        url = f"{self.base_url}/api/catalog_system/pub/products/search/{keyword}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            
            # VTEX responde 200 o 206 (Partial Content) correctamente cuando hay resultados
            if response.status_code not in [200, 206]:
                raise Exception(f"VTEX API Error: Status {response.status_code}")
            
            raw_products = response.json()
            extracted_items = []

            for idx, prod in enumerate(raw_products[:limit], start=1):
                items = prod.get("items", [])
                if not items:
                    continue
                    
                item = items[0]
                sellers = item.get("sellers", [{}])
                comm_offer = sellers[0].get("commertialOffer", {}) if sellers else {}

                base_price = comm_offer.get("ListPrice", 0.0)
                discount_price = comm_offer.get("Price", 0.0)
                
                if discount_price >= base_price:
                    discount_price = None

                in_stock = comm_offer.get("AvailableQuantity", 0) > 0

                extracted_items.append(ExtractedProductData(
                    title=prod.get("productName", "Sin título"),
                    brand=prod.get("brand", "Genérica"),
                    ean_gtin=item.get("ean"),
                    search_keyword=keyword,
                    search_position=idx,
                    base_price=float(base_price),
                    discount_price=float(discount_price) if discount_price else None,
                    is_sponsored=False,
                    in_stock=in_stock
                ))
            
            return extracted_items