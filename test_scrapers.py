import asyncio
from app.services.scrapers.vtex_scraper import VTEXScraper

async def run_test():
    print("🚀 Probando Motor de Scraping - API Directa VTEX (Éxito)...")
    vtex = VTEXScraper()
    results = await vtex.search_keyword("galletas dulces", limit=3)
    
    print(f"\n✅ Se extrajeron {len(results)} productos exitosamente:\n")
    for prod in results:
        print(f" Posición #{prod.search_position}: {prod.title}")
        print(f"   • Marca: {prod.brand} | EAN: {prod.ean_gtin}")
        print(f"   • Precio Base: ${prod.base_price} | Precio Oferta: ${prod.discount_price}")
        print(f"   • Stock: {'Disponible' if prod.in_stock else 'Agotado'}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(run_test())