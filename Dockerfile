# Imagen base oficial con Playwright y Python preinstalados
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /app

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código del backend
COPY . .

# Exponer el puerto predeterminado
EXPOSE 8000

# Comando de arranque para FastAPI en producción
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]