import asyncio
from sqlalchemy.orm import Session
from app.services.scrapers.vtex_scraper import VTEXScraper 

# Mapeo explicito de retail a su URL base
RETAILER_URLS = {
    "exito": "https://www.exito.com",
    "carulla": "https://www.carulla.com"
}

async def run_monitoring_pipeline(session: Session):
    retailers = ["exito", "carulla"]
    search_terms = ["galletas dulces", "leche", "cafe"] 
    
    all_results = []

    for retailer in retailers:
        base_url = RETAILER_URLS.get(retailer, "https://www.exito.com")
        print(f"\n[ORCHESTRATOR] 🚀 Iniciando scraping para retailer: {retailer.upper()} ({base_url})", flush=True)
        
        # Pasamos retailer y su base_url correspondiente
        scraper = VTEXScraper(retailer=retailer, base_url=base_url)
        
        for term in search_terms:
            print(f"[ORCHESTRATOR] Buscando '{term}' en {retailer.upper()}...", flush=True)
            try:
                results = await scraper.search_keyword(term, limit=20)
                
                if isinstance(results, list):
                    all_results.extend(results)
                    print(f"[ORCHESTRATOR] ✅ Se obtuvieron {len(results)} productos de {retailer.upper()} para '{term}'", flush=True)
                else:
                    print(f"[ORCHESTRATOR] ⚠️ Formato inesperado devuelto para '{term}' en {retailer.upper()}", flush=True)

            except Exception as e:
                print(f"[ORCHESTRATOR] ❌ Error en {retailer.upper()} con '{term}': {e}", flush=True)

    # Guardar o procesar resultados
    if all_results:
        print(f"\n[ORCHESTRATOR] 💾 Total de {len(all_results)} productos procesados en pipeline.", flush=True)
        # NOTA: Si vas a guardar en BD con SQLAlchemy, mapea all_results a tu Modelo ORM de BD antes del session.add_all()
        # Ejemplo:
        # db_objects = [ProductModel(**prod.dict()) for prod in all_results]
        # session.add_all(db_objects)
        # session.commit()

    return all_results