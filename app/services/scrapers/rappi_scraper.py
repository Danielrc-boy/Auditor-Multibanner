import os
import time
import httpx
from app.schemas import ExtractedProductData


class RappiScraper:
    """
    Scraper de Rappi (búsqueda general, sin necesidad de login) vía:
      1. POST /api/rocket/v2/guest -> obtiene access_token de invitado (dura ~7 días)
      2. POST /api/pns-global-search-api/v1/unified-search -> productos por keyword

    Mantiene el token en memoria y lo renueva automáticamente cuando expira
    o cuando una búsqueda responde 401.
    """

    GUEST_URL = "https://services.grability.rappi.com/api/rocket/v2/guest"
    SEARCH_URL = (
        "https://services.grability.rappi.com/api/pns-global-search-api/v1/unified-search"
        "?is_prime=false&unlimited_shipping=false"
    )

    def __init__(self, lat: float = None, lng: float = None):
        # Coordenadas de referencia para la búsqueda (por defecto, Bogotá centro).
        # Puedes sobreescribirlas por variable de entorno o al instanciar la clase.
        self.lat = lat or float(os.getenv("RAPPI_LAT", "4.676777"))
        self.lng = lng or float(os.getenv("RAPPI_LNG", "-74.056748"))

        self.guest_api_key = os.getenv(
            "RAPPI_GUEST_API_KEY",
            "fXK7FkuFXM+3ThX4gUjAuDIzyAeZrUO6dJ3pQHQOlj4ZXKT66FHKKaiECps7jLRKyjC9fppdDpCbbfmRZuoFnDkwL1/"
            "V6Z7n5rAu/oM6atqJcqmUSTP0oHbJx4mClsv9afH9uI6rhJcnz1fMvGMrtzJNciTNgBs96V68aDw7TIqZv5ugq1Th0Rj6"
            "NZxY0QlAG1yrAEneO6cHYyk9amDusk44XOe629QXVB37ENzSxQUKUEePGs4VBxWhdwJBZfU20tV2E/"
            "ybO2D5r8wknT/Bc6y8ELqThSGGkI7EuOYrdh2ZkS88X+ARwfif6VFqKDwzjnURTivtcFx91jC6qp9yTw==",
        ).strip()

        self.device_id = os.getenv("RAPPI_DEVICE_ID", "8f929473-4456-4f2c-a09c-a6df8380b94f").strip()

        self._access_token = None
        self._token_expires_at = 0  # timestamp unix

        self.base_headers = {
            "accept": "application/json",
            "accept-language": "es-CO",
            "content-type": "application/json",
            "deviceid": self.device_id,
            "origin": "https://www.rappi.com.co",
            "referer": "https://www.rappi.com.co/",
            "vendor": "rappi",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def _get_guest_token(self, client: httpx.AsyncClient, force: bool = False) -> str:
        """Obtiene (o reutiliza) el access_token de invitado."""
        if not force and self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        headers = {**self.base_headers, "x-guest-api-key": self.guest_api_key, "content-length": "0"}
        response = await client.post(self.GUEST_URL, headers=headers)
        response.raise_for_status()
        data = response.json()

        self._access_token = data["access_token"]
        # Restamos un margen de seguridad (1 hora) al tiempo de expiración real.
        self._token_expires_at = time.time() + data.get("expires_in", 604800) - 3600
        return self._access_token

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                token = await self._get_guest_token(client)
                payload = {
                    "lat": self.lat,
                    "lng": self.lng,
                    "query": search_term,
                    "options": {},
                }
                headers = {**self.base_headers, "authorization": f"Bearer {token}", "auth_user": "-1"}

                response = await client.post(self.SEARCH_URL, headers=headers, json=payload)

                # Si el token expiró antes de lo esperado, forzamos uno nuevo y reintentamos una vez.
                if response.status_code == 401:
                    token = await self._get_guest_token(client, force=True)
                    headers["authorization"] = f"Bearer {token}"
                    response = await client.post(self.SEARCH_URL, headers=headers, json=payload)

                response.raise_for_status()
                data = response.json()
                return self._parse_products(data, search_term, limit)
            except Exception as e:
                print(f"[ERROR RAPPI] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_data, search_term: str, limit: int) -> list:
        parsed_results = []
        index = 0

        stores = raw_data.get("stores", []) if isinstance(raw_data, dict) else []

        for store in stores:
            for item in store.get("products", []):
                if index >= limit:
                    return parsed_results
                try:
                    index += 1

                    title = item.get("name", "Sin título")
                    real_price = float(item.get("real_price", 0.0) or 0.0)
                    price = float(item.get("price", 0.0) or 0.0)

                    have_discount = item.get("have_discount", False)
                    if have_discount and price > 0 and price < real_price:
                        base_price = real_price
                        discount_price = price
                    else:
                        base_price = real_price if real_price > 0 else price
                        discount_price = None

                    available = item.get("is_available", item.get("in_stock", True))

                    product = ExtractedProductData(
                        search_keyword=search_term,
                        search_position=index,
                        title=title,
                        base_price=base_price,
                        discount_price=discount_price,
                        in_stock=available,
                    )
                    parsed_results.append(product)
                except Exception as e:
                    print(f"[PARSER ERROR] RAPPI: {e}", flush=True)
                    continue

        return parsed_results