import asyncio
from sqlalchemy.orm import Session
# Ajusta esta importación según el nombre real de tu clase o función de scraper en scrapers/
from app.services.scrapers.vtex_scraper import VTEXScraper 

async def run_monitoring_pipeline(session: Session):
    # 1. Definir los retailers a monitorear
    retailers = ["exito", "carulla"]
    
    # 2. Términos de búsqueda (o léelos desde la BD si tienes un modelo SearchConfig)
    search_terms = ["galletas dulces", "leche", "cafe"] 
    
    all_results = []

    for retailer in retailers:
        print(f"\n[ORCHESTRATOR] 🚀 Iniciando scraping para retailer: {retailer.upper()}", flush=True)
        scraper = VTEXScraper(retailer=retailer)
        
        for term in search_terms:
            print(f"[ORCHESTRATOR] Buscando '{term}' en {retailer.upper()}...", flush=True)
            try:
                # Ejecuta la búsqueda de cada término
                results = await scraper.search_keyword(term, limit=20)
                
                # Guarda o adjunta los resultados
                all_results.extend(results)
                print(f"[ORCHESTRATOR] ✅ Se obtuvieron {len(results)} productos de {retailer.upper()} para '{term}'", flush=True)
            except Exception as e:
                print(f"[ORCHESTRATOR] ❌ Error en {retailer.upper()} con '{term}': {e}", flush=True)

    # 3. Guardar todos los resultados en la base de datos
    if all_results:
        session.add_all(all_results)
        session.commit()
        print(f"\n[ORCHESTRATOR] 💾 {len(all_results)} registros guardados exitosamente en la BD.", flush=True)

    return all_results