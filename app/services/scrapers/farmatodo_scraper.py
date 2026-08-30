import os
import httpx
from app.services.scrapers.vtex_scraper import ExtractedProductData


class FarmatodoScraper:
    """
    Scraper de Farmatodo vía su proxy propio de Algolia (api-search.farmatodo.com).
    Sigue el mismo contrato que VTEXScraper: search_keyword() devuelve una lista
    de ExtractedProductData.
    """

    def __init__(self):
        self.app_id = os.getenv("ALGOLIA_APP_ID", "VCOJEYD2PO").strip()
        self.api_key = os.getenv("ALGOLIA_API_KEY", "eb9544fe7bfe7ec4c1aa5e5bf7740feb").strip()
        self.index_name = os.getenv("ALGOLIA_INDEX_NAME", "products-colombia").strip()

        # Dominio propio de Farmatodo (proxy hacia Algolia) — NO usar algolianet.com directo,
        # ese dominio no resuelve de forma confiable desde fuera de Farmatodo.
        self.endpoint = "https://api-search.farmatodo.com/1/indexes/*/queries"

        self.headers = {
            "x-algolia-application-id": self.app_id,
            "x-algolia-api-key": self.api_key,
            "content-type": "application/json",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "origin": "https://www.farmatodo.com.co",
            "referer": "https://www.farmatodo.com.co/",
        }

    async def search_keyword(self, search_term: str, limit: int = 50) -> list:
        payload = {
            "requests": [
                {
                    "indexName": self.index_name,
                    "params": f"query={search_term}&hitsPerPage={limit}&page=0",
                }
            ]
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.endpoint, headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                if not results:
                    return []

                hits = results[0].get("hits", [])
                return self._parse_products(hits, search_term)
            except Exception as e:
                print(f"[ERROR FARMATODO] Error al scrapear '{search_term}': {e}", flush=True)
                return []

    def _parse_products(self, raw_hits: list, search_term: str) -> list:
        parsed_results = []

        for index, item in enumerate(raw_hits, start=1):
            try:
                # Título real confirmado: mediaDescription. Sin fallback a brand/description
                # (esos campos no son nombres de producto y generaban códigos SKU como título).
                title = item.get("mediaDescription") or "Sin título"

                # Precio real confirmado: fullPrice = precio base, offerPrice = precio con oferta.
                base_price = float(item.get("fullPrice", 0.0) or 0.0)
                offer_price = float(item.get("offerPrice", 0.0) or 0.0)

                if offer_price > 0 and offer_price < base_price:
                    discount_price = offer_price
                else:
                    discount_price = None

                # Disponibilidad real confirmada: outofstore (booleano invertido).
                # No existe un campo "stock" numérico en la respuesta.
                available = not item.get("outofstore", False)

                product = ExtractedProductData(
                    search_keyword=search_term,
                    search_position=index,
                    title=title,
                    base_price=base_price if base_price > 0 else offer_price,
                    discount_price=discount_price,
                    in_stock=available,
                )
                parsed_results.append(product)
            except Exception as e:
                print(f"[PARSER ERROR] FARMATODO: {e}", flush=True)
                continue

        return parsed_results