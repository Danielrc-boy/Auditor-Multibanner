from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import retailers, skus, configs
from app.services.scheduler import start_scheduler, execute_monitoring_job
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicia el programador en segundo plano
    start_scheduler()
    yield
    print("🛑 Deteniendo servicios...")

app = FastAPI(
    title="Digital Shelf Monitoring API",
    version="1.0.0",
    description="API REST para orquestación de monitoreo e-commerce en Colombia",
    lifespan=lifespan
)

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(retailers.router)
app.include_router(skus.router)
app.include_router(configs.router)

@app.get("/")
def read_root():
    return {"message": "API de Monitoreo Multibanner activa"}