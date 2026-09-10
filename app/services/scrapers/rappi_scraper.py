"""
Scraper de Rappi, reconstruido desde cero.

Hallazgo clave (confirmado con evidencia real de DevTools): Rappi ya NO
requiere token de invitado ni llamadas a la API de grability para obtener
resultados de búsqueda. La página /search?query=... es renderizada en el
servidor (Next.js) y trae los productos incrustados directamente en el
HTML como datos estructurados schema.org (<script type="application/ld+json">),
pensados originalmente para que Google entienda la página -- pero nos sirven
igual de bien a nosotros.

Ventaja: sin autenticación, sin tokens que expiren, sin bloqueo 401/429.

Limitaciones conocidas de este método (a diferencia de VTEX/Algolia):
- El precio que trae este formato es el precio final único. No distingue
  precio de lista vs. precio con descuento -- discount_price queda en None.
- No trae la marca como campo separado; se infiere buscando coincidencias
  de marcas conocidas dentro del nombre del producto.
- No trae disponibilidad explícita en todos los casos; se asume in_stock=True
  salvo que el propio dato indique lo contrario.
"""
import os
import re
import json
import unicodedata
import httpx
from typing import List, Optional
from pydantic import BaseModel

RAPPI_USE_SCRAPERAPI = os.getenv("RAPPI_USE_SCRAPERAPI", "false").lower() == "true"
SCRAPERAPI_KEY = os.getenv("SCRAPERAPI_KEY", "")

KNOWN_BRANDS = [
    "Nosotras", "Kotex", "Stayfree", "Pequeñín", "Winny", "Familia",
    "Huggies", "Pampers", "Nivea", "Dove", "Protex", "Saba", "Tena",
    "Gillette", "Colgate", "Sensodyne", "Neutrogena", "Cetaphil",
    "Garnier", "Ladysoft", "Pilí", "Pili",
]

LD_JSON_BLOCK_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL,
)


def _normalize(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    return text.lower().strip()


def _infer_brand(name: str) -> str:
    for brand in KNOWN_BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", name, re.IGNORECASE):
            return brand
    return "Sin Marca"


class ExtractedProductData(BaseModel):
    search_keyword: str
    search_position: int
    title: str
    brand: Optional[str] = "Sin Marca"
    base_price: float = 0.0
    discount_price: Optional[float] = None
    in_stock: bool = True


class RappiScraper:
    def __init__(self):
        self.base_url = "https://www.rappi.com.co"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-419,es;q=0.9",
        }

    def _build_request(self, target_url: str):
        if RAPPI_USE_SCRAPERAPI and SCRAPERAPI_KEY:
            return "http://api.scraperapi.com/", {"api_key": SCRAPERAPI_KEY, "url": target_url}
        return target_url, None

    async def search_keyword(self, keyword: str, limit: int = 50) -> List[ExtractedProductData]:
        import urllib.parse

        target_url = f"{self.base_url}/search?query={urllib.parse.quote(keyword)}"
        request_url, params = self._build_request(target_url)

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
                response = await client.get(request_url, headers=self.headers, params=params)
                print(f"[DIAG RAPPI] Status recibido: {response.status_code}", flush=True)

                if response.status_code != 200:
                    print(f"[ERROR RAPPI] HTTP Status {response.status_code} para '{keyword}'", flush=True)
                    return []

                html = response.text
                return self._parse_html(html, keyword, limit)

        except Exception as e:
            print(f"[ERROR RAPPI] Error al scrapear '{keyword}': {e}", flush=True)
            return []

    def _parse_html(self, html: str, search_term: str, limit: int) -> List[ExtractedProductData]:
        blocks = LD_JSON_BLOCK_RE.findall(html)
        seen_urls = set()
        parsed: List[ExtractedProductData] = []
        position_counter = 1

        for raw_block in blocks:
            try:
                data = json.loads(raw_block.strip())
            except (json.JSONDecodeError, ValueError):
                continue

            items = []
            if isinstance(data, dict) and data.get("@type") == "ItemList":
                items = data.get("itemListElement", [])
            elif isinstance(data, list):
                items = data

            for entry in items:
                if position_counter > limit:
                    break
                try:
                    item = entry.get("item", entry) if isinstance(entry, dict) else None
                    if not item or item.get("@type") != "Product":
                        continue

                    url = item.get("url", "")
                    if url in seen_urls:
                        continue  # evita contar el mismo producto dos veces si aparece en varios carruseles
                    seen_urls.add(url)

                    name = (item.get("name") or "").strip()
                    if not name:
                        continue

                    offer = item.get("offers", {}) or {}
                    price = float(offer.get("price", 0.0) or 0.0)
                    availability = offer.get("availability", "")
                    in_stock = True
                    if availability and "outofstock" in availability.lower():
                        in_stock = False

                    parsed.append(
                        ExtractedProductData(
                            search_keyword=search_term,
                            search_position=position_counter,
                            title=name,
                            brand=_infer_brand(name),
                            base_price=price,
                            discount_price=None,  # no disponible en este formato de datos
                            in_stock=in_stock,
                        )
                    )
                    position_counter += 1
                except Exception as e:
                    print(f"[PARSER ERROR] RAPPI: {e}", flush=True)
                    continue

        return parsed