import uuid
import httpx

class RappiScraper:
    def __init__(self):
        self.guest_url = "https://services.grability.rappi.com/api/rocket/v2/guest"
        self.search_url = "https://services.grability.rappi.com/api/ms/search-engine/v2/search"

    def _get_headers(self) -> dict:
        # Generar un device_id dinámico para evitar la expiración/bloqueo de 401
        device_id = str(uuid.uuid4())
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "deviceid": device_id,
            "x-device-id": device_id,
            "app-version": "9.43.0",
            "platform": "web"
        }

    async def get_guest_token(self, client: httpx.AsyncClient) -> str:
        headers = self._get_headers()
        # Rappi requiere un payload básico para autenticar al usuario invitado
        payload = {
            "device_id": headers["deviceid"],
            "need_token": True
        }
        
        response = await client.post(self.guest_url, headers=headers, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token") or data.get("token") or ""
        else:
            print(f"[ERROR RAPPI] HTTP {response.status_code} al obtener token", flush=True)
            return ""