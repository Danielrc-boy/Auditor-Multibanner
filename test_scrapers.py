import os
import urllib.parse
import httpx

RETAILER_URLS = {
    "exito": "https://www.exito.com",
    "carulla": "https://www.carulla.com"
}

class ExtractedProductData:
    """Objeto que encapsula los campos requeridos por main.py"""
    def __init__(self, search_keyword: str, search_position: int, title: str, base_price: float, discount_price: float, in_stock: bool):
        self.search_keyword = search_keyword
        self.search_position = search_position
        self.title = title
        self.base_price = base_price
        self.discount_price = discount_price
        self.in_stock = in_stock

class VTEXScraper:
    def __init__(self, retailer: str = "exito"):
        self.api_key = os.getenv("SCRAPERAPI_KEY")
        self.retailer = retailer.lower()
        self.base_url = RETAILER_URLS.get(self.retailer, "https://www.exito.com")

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        encoded_term = urllib.parse.quote(search_term)
        target_url = (
            f"{self.base_url}/io/api/catalog_system/pub/products/search/{encoded_term}"
            f"?_from=0&_to={limit - 1}"
        )
        
        scraperapi_url = (
            f"http://api.scraperapi.com?api_key={self.api_key}"
            f"&url={urllib.parse.quote(target_url)}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.get(scraperapi_url)
                response.raise_for_status()
                data = response.json()
                return self._parse_products(data, search_term)
            except Exception as e:
                print(f"[ERROR {self.retailer.upper()}] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_items: list, search_term: str) -> list:
        parsed_results = []
        for index, item in enumerate(raw_items, start=1):
            try:
                items_list = item.get("items", [])
                if not items_list:
                    continue
                
                first_item = items_list[0]
                sellers = first_item.get("sellers", [])
                
                price = 0.0
                list_price = 0.0
                available = True
                
                if sellers:
                    comm_offer = sellers[0].get("commertialOffer", {})
                    price = float(comm_offer.get("Price", 0.0))
                    list_price = float(comm_offer.get("ListPrice", price))
                    available = comm_offer.get("IsAvailable", True)

                # Instancia con los atributos requeridos por getattr() en main.py
                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=item.get("productName", "Sin título"),
                    base_price=list_price if list_price > 0 else price,
                    discount_price=price if (price > 0 and price < list_price) else None,
                    in_stock=available
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] {self.retailer.upper()}: {e}", flush=True)
                continue
                
        return parsed_results