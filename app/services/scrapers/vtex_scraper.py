import httpx
from typing import List
from app.services.scrapers.base import ExtractedProductData

class VTEXScraper:
    def __init__(self, base_url: str = "https://www.exito.com"):
        self.base_url = base_url.rstrip("/")

async def search_keyword(self, keyword: str, limit: int = 10) -> List[ExtractedProductData]:
        url = f"{self.base_url}/io/api/catalog_system/pub/products/search/{keyword}"
        
        # Headers limpios (evitan compresión manual y emulan navegador estándar)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Referer": "https://www.exito.com/",
            "Origin": "https://www.exito.com"
        }

        # Usamos httpx.AsyncClient con soporte de redirecciones y timeout adecuado
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            # Primero visitamos la home rápida para obtener cookies válidas de VTEX
            try:
                await client.get(self.base_url, headers={"User-Agent": headers["User-Agent"]})
            except Exception:
                pass  # Si falla la home, intentamos la consulta directa

            # Realizamos la petición real con la sesión con cookies
            response = await client.get(url, headers=headers)

            print(f"[LOG VTEX RAW] Status: {response.status_code} para URL: {url}", flush=True)

            if response.status_code not in [200, 206]:
                # Usamos response.content para evitar errores de decodificación si viene binario
                raise Exception(f"VTEX API Error: Status {response.status_code} - Body: {response.text[:150]}")

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