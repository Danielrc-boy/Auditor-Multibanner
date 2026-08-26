import os
import httpx
from dotenv import load_dotenv

load_dotenv()
WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "")

async def send_price_alert(product_title: str, retailer_name: str, old_price: float, new_price: float):
    if not WEBHOOK_URL:
        return

    payload = {
        "event": "PRICE_CHANGE",
        "product": product_title,
        "retailer": retailer_name,
        "old_price": old_price,
        "new_price": new_price,
        "difference": round(new_price - old_price, 2)
    }

    async with httpx.AsyncClient() as client:
        try:
            await client.post(WEBHOOK_URL, json=payload, timeout=5.0)
        except Exception as e:
            print(f"Error enviando alerta Webhook: {e}")