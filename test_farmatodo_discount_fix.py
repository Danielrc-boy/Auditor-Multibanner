"""
Prueba del fix de discount_price=None en Farmatodo cuando el producto SÍ
tiene una oferta activa.

Causa confirmada con evidencia real (Algolia, búsqueda "toallas higienicas",
2026-09-14): el campo "offerPrice" de nivel superior del hit SIEMPRE viene
en 0, incluso en productos con descuento real -- el precio de oferta real
vive anidado dentro de "offerPriceByStore" (lista de grupos de tiendas).

Item real capturado (recortado a los campos relevantes):
    "Toallas Higiénicas Tena Discreet Súper Paquete..."
    fullPrice: 60250, offerPrice: 0 (siempre 0, engañoso)
    offerPriceByStore[0].offerPrice: 48200 (el descuento real, 20%)
"""
from app.services.scrapers.farmatodo_scraper import FarmatodoScraper

REAL_ITEM_WITH_REAL_DISCOUNT = {
    "mediaDescription": "Toallas Higiénicas Tena Discreet Súper Paquete x 16 Uds",
    "brand": "Tena",
    "fullPrice": 60250,
    "offerPrice": 0,
    "offerPriceByCity": [],
    "offerPriceByStore": [
        {"componentId": 23030173, "offerDescription": "", "offerPrice": 48200, "offerText": "20%", "stores": [26, 80, 53]},
        {"componentId": 23030173, "offerDescription": "", "offerPrice": 48200, "offerText": "20%", "stores": [43, 74]},
    ],
    "outofstore": False,
}

REAL_ITEM_WITHOUT_DISCOUNT = {
    "mediaDescription": "Toallas Higiénicas Farmatodo Nocturna x 10 und",
    "brand": "Farmatodo",
    "fullPrice": 9950,
    "offerPrice": 0,
    "offerPriceByCity": [],
    "offerPriceByStore": [],
    "outofstore": False,
}


def test_offer_price_by_store_se_usa_como_descuento():
    scraper = FarmatodoScraper()
    base_price, discount_price = scraper._extract_prices(REAL_ITEM_WITH_REAL_DISCOUNT)
    assert base_price == 60250.0, f"Se esperaba fullPrice=60250.0, llegó {base_price}"
    assert discount_price == 48200.0, f"Se esperaba discount_price=48200.0 (de offerPriceByStore), llegó {discount_price}"
    print(f"✅ Descuento real extraído de offerPriceByStore: base={base_price} discount={discount_price}")


def test_sin_offer_price_by_store_no_inventa_descuento():
    scraper = FarmatodoScraper()
    base_price, discount_price = scraper._extract_prices(REAL_ITEM_WITHOUT_DISCOUNT)
    assert base_price == 9950.0, f"Se esperaba fullPrice=9950.0, llegó {base_price}"
    assert discount_price is None, f"Se esperaba discount_price=None (sin oferta real), llegó {discount_price}"
    print(f"✅ Sin oferta real -> discount_price sigue en None correctamente: base={base_price}")


if __name__ == "__main__":
    test_offer_price_by_store_se_usa_como_descuento()
    test_sin_offer_price_by_store_no_inventa_descuento()
    print("\n✅ Todas las pruebas del fix de descuento Farmatodo pasaron.")
