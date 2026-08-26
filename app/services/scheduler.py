from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.services.scrapers.vtex_scraper import VTEXScraper
from app.services.alert_service import send_price_alert
import asyncio

scheduler = AsyncIOScheduler()

async def execute_monitoring_job():
    print("⏰ [Scheduler] Iniciando ciclo de monitoreo programado...")
    db: Session = SessionLocal()
    try:
        active_configs = db.query(models.MonitoringConfig).filter(models.MonitoringConfig.is_active == True).all()
        
        for config in active_configs:
            retailer = db.query(models.Retailer).filter(models.Retailer.id == config.retailer_id).first()
            if not retailer:
                continue
                
            print(f"🔎 Procesando: {config.name} en {retailer.name}")
            
            # Instanciar el scraper adecuado según el retailer
            if retailer.code == "exito":
                scraper = VTEXScraper(base_url=retailer.base_url)
                if config.search_keyword:
                    products = await scraper.search_keyword(config.search_keyword, limit=5)
                    
                    for prod in products:
                        # Guardar la métrica en la Base de Datos
                        metric = models.MetricLog(
                            config_id=config.id,
                            retailer_id=retailer.id,
                            search_position=prod.search_position,
                            base_price=prod.base_price,
                            discount_price=prod.discount_price,
                            is_available=prod.in_stock
                        )
                        db.add(metric)
                        
                        # Disparar alerta si hay descuento significativo (> 10%)
                        if prod.discount_price and prod.base_price > 0:
                            discount_pct = ((prod.base_price - prod.discount_price) / prod.base_price) * 100
                            if discount_pct >= 10.0:
                                await send_price_alert(prod.title, retailer.name, prod.base_price, prod.discount_price)
                                
                    db.commit()
                    print(f"✅ [{retailer.name}] {len(products)} métricas registradas en DB.")
                    
    except Exception as e:
        db.rollback()
        print(f"❌ Error durante la ejecución del job: {e}")
    finally:
        db.close()

def start_scheduler():
    # Programar la ejecución cada 6 horas (o ajustar según necesidad)
    scheduler.add_job(execute_monitoring_job, 'interval', hours=6, id='ecommerce_monitoring_job')
    scheduler.start()
    print("🚀 APScheduler iniciado correctamente.")