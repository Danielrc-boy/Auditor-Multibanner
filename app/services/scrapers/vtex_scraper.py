import unicodedata
# (Mantén los imports existentes al inicio de tu archivo)

async def run_vtex_scraping(conn) -> int:
    search_configs = []
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT search_term, retailer FROM search_configs WHERE is_active = TRUE;")
            rows = cur.fetchall()
            search_configs = rows if rows else []
        except Exception:
            conn.rollback()
            cur.execute("SELECT search_term FROM search_configs WHERE is_active = TRUE;")
            rows = cur.fetchall()
            search_configs = [{"search_term": r["search_term"], "retailer": "exito"} for r in rows] if rows else []

    if not search_configs:
        return 0

    total_saved = 0
    from app.main import save_scraper_results

    for config in search_configs:
        term = config["search_term"]
        raw_retailer = str(config.get("retailer") or "exito").lower().strip()

        # Si no se especifica retailer o es 'exito'/'carulla', ejecuta los scrapers correspondientes
        target_retailers = []
        if raw_retailer in ["exito", "carulla"]:
            target_retailers = [raw_retailer]
        elif raw_retailer == "todos" or not raw_retailer:
            target_retailers = ["exito", "carulla"]

        for retailer in target_retailers:
            scraper = VTEXScraper(retailer=retailer)
            try:
                results = await scraper.search_keyword(term, limit=50)
                if results:
                    count = save_scraper_results(conn, results, retailer=retailer)
                    total_saved += count
                    print(f"[{retailer.upper()}] Guardados {count} para '{term}'.", flush=True)
            except Exception as e:
                print(f"[SCRAPING ERROR] {retailer.upper()} '{term}': {e}", flush=True)

    return total_saved