import uuid
import httpx
from .config import settings


API = "https://api.yookassa.ru/v3"


def _receipt_for_order(order: dict):
    if not settings.YOOKASSA_RECEIPT_ENABLED:
        return None

    if settings.YOOKASSA_TAX_SYSTEM_CODE is None or settings.YOOKASSA_VAT_CODE is None:
        raise RuntimeError(
            "YOOKASSA_RECEIPT_ENABLED=true, but tax_system_code/vat_code are not configured"
        )

    items = []
    subtotal = float(order["subtotal"] or 0)
    discount = float(order.get("discount") or 0)

    for item in order["items"]:
        raw_total = float(item["total"])
        share = (raw_total / subtotal) if subtotal else 0
        discounted_total = raw_total - (discount * share)
        discounted_total = max(0.01, round(discounted_total, 2))
        items.append({
            "description": str(item["name"])[:128],
            "quantity": f'{int(item["quantity"]):.2f}',
            "amount": {
                "value": f'{discounted_total / int(item["quantity"]):.2f}',
                "currency": "RUB",
            },
            "vat_code": settings.YOOKASSA_VAT_CODE,
            "payment_mode": settings.YOOKASSA_PAYMENT_MODE,
            "payment_subject": settings.YOOKASSA_PAYMENT_SUBJECT,
        })

    if order.get("delivery_price", 0) > 0:
        items.append({
            "description": str(order.get("delivery_name") or "Доставка")[:128],
            "quantity": "1.00",
            "amount": {
                "value": f'{float(order["delivery_price"]):.2f}',
                "currency": "RUB",
            },
            "vat_code": settings.YOOKASSA_VAT_CODE,
            "payment_mode": settings.YOOKASSA_PAYMENT_MODE,
            "payment_subject": "service",
        })

    return {
        "customer": {"email": order["customer_email"]},
        "items": items,
        "tax_system_code": settings.YOOKASSA_TAX_SYSTEM_CODE,
    }


async def create_payment(order: dict):
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YooKassa credentials are not configured")

    payload = {
        "amount": {
            "value": f'{float(order["total"]):.2f}',
            "currency": "RUB",
        },
        "capture": True,
        "description": f'Заказ #{order["order_id"]}',
        "metadata": {"order_id": order["order_id"]},
        "confirmation": {
            "type": "redirect",
            "return_url": settings.YOOKASSA_RETURN_URL or settings.MINI_APP_URL,
        },
    }

    if settings.YOOKASSA_RECEIPT_ENABLED:
        if not order.get("customer_email"):
            raise RuntimeError("Email is required for the configured YooKassa receipt flow")
        payload["receipt"] = _receipt_for_order(order)

    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.post(
            f"{API}/payments",
            auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            headers={
                "Idempotence-Key": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def get_payment(payment_id: str):
    async with httpx.AsyncClient(timeout=20) as http:
        response = await http.get(
            f"{API}/payments/{payment_id}",
            auth=(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
        )
        response.raise_for_status()
        return response.json()
