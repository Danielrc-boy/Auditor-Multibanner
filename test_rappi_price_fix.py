"""
Prueba del fix de price=0 en Rappi para productos con offers tipo
"AggregateOffer" (rango de precio entre varias tiendas/darkstores).

Datos reales capturados de:
https://www.rappi.com.co/search?query=nosotras  (2026-09-14)

- "Nosotras Toallas Higiénicas Extra Protección Larga Dia y Noche" venía
  con offers @type "AggregateOffer" (lowPrice/highPrice, SIN "price") ->
  antes del fix se guardaba como price=0.0.
- "Nosotras Protectores Diarios Largos" venía con offers @type "Offer"
  normal (price directo) -> nunca tuvo el bug, debe seguir funcionando igual.
"""
from app.services.scrapers.rappi_scraper import RappiScraper

REAL_AGGREGATE_OFFER_PRODUCT = {
    "@type": "Product",
    "name": "Nosotras Toallas Higiénicas Extra Protección Larga Dia y Noche",
    "url": "https://www.rappi.com.co/p/nosotras-toallas-higienicas-extra-proteccion-larga-dia-y-noche-xxxx",
    "offers": {
        "@type": "AggregateOffer",
        "lowPrice": 5325,
        "highPrice": 7100,
        "priceCurrency": "COP",
    },
}

REAL_NORMAL_OFFER_PRODUCT = {
    "@type": "Product",
    "name": "Nosotras Protectores Diarios Largos",
    "url": "https://www.rappi.com.co/p/nosotras-protectores-diarios-largos-yyyy",
    "offers": {
        "@type": "Offer",
        "price": 24100,
        "priceCurrency": "COP",
    },
}

def test_aggregate_offer_usa_low_price():
    import json as _json

    scraper = RappiScraper()
    html = (
        '<html><body><script type="application/ld+json">'
        + _json.dumps({"@type": "ItemList", "itemListElement": [{"item": REAL_AGGREGATE_OFFER_PRODUCT}]})
        + "</script></body></html>"
    )
    results = scraper._parse_html(html, search_term="nosotras", limit=50)
    assert len(results) == 1, f"Se esperaba 1 producto, llegaron {len(results)}"
    product = results[0]
    assert product.base_price == 5325.0, f"Se esperaba lowPrice=5325.0, llegó {product.base_price}"
    print(f"✅ AggregateOffer -> usa lowPrice correctamente: base_price={product.base_price}")


def test_offer_normal_sigue_funcionando():
    import json as _json

    scraper = RappiScraper()
    html = (
        '<html><body><script type="application/ld+json">'
        + _json.dumps({"@type": "ItemList", "itemListElement": [{"item": REAL_NORMAL_OFFER_PRODUCT}]})
        + "</script></body></html>"
    )
    results = scraper._parse_html(html, search_term="nosotras", limit=50)
    assert len(results) == 1, f"Se esperaba 1 producto, llegaron {len(results)}"
    product = results[0]
    assert product.base_price == 24100.0, f"Se esperaba price=24100.0, llegó {product.base_price}"
    print(f"✅ Offer normal sigue funcionando: base_price={product.base_price}")


if __name__ == "__main__":
    test_aggregate_offer_usa_low_price()
    test_offer_normal_sigue_funcionando()
    print("\n✅ Todas las pruebas del fix de precio Rappi pasaron.")
