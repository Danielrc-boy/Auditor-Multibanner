from playwright.async_api import async_playwright
from typing import List
from app.services.scrapers.base import ExtractedProductData

class PlaywrightScraper:
    async def search_carulla_keyword(self, keyword: str) -> List[ExtractedProductData]:
        url = f"https://www.carulla.com/{keyword}?map=ft"
        
        async with async_playwright() as p:
            # Lanzamos Chromium en modo headless
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = await context.new_page()
            
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Esperar hidratación de Next.js
            await page.wait_for_timeout(3000) 
            
            products = []
            # Selector genérico para tarjetas de producto en Next.js/VTEX IO
            cards = await page.query_selector_all("section vtex-product-summary-2-x-container")
            
            for idx, card in enumerate(cards[:5], start=1):
                title_elem = await card.query_selector("span.vtex-product-summary-2-x-productBrand")
                price_elem = await card.query_selector("span.vtex-product-price-1-x-currencyInteger")
                
                title = await title_elem.inner_text() if title_elem else "Producto Carulla"
                price_text = await price_elem.inner_text() if price_elem else "0"
                
                # Limpiar texto de precio
                clean_price = float(price_text.replace(".", "").replace("$", "").strip() or 0)

                products.append(ExtractedProductData(
                    title=title,
                    brand="Carulla",
                    search_keyword=keyword,
                    search_position=idx,
                    base_price=clean_price if clean_price > 0 else 1000.0,
                    in_stock=True
                ))
                
            await browser.close()
            return products