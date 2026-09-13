from .config import settings
from .bot import bot


STATUS_TEXT = {
    "new": "Новый",
    "waiting_payment": "Ожидает оплаты",
    "paid": "Оплачен",
    "processing": "В обработке",
    "shipped": "Передан в доставку",
    "delivered": "Доставлен",
    "cancelled": "Отменён",
}


async def notify_status(tg_id: int, order_id: str, status: str):
    try:
        await bot.send_message(
            tg_id,
            f"📦 Заказ #{order_id}\n"
            f"Статус: {STATUS_TEXT.get(status, status)}",
        )
    except Exception:
        pass


async def notify_admins(text: str):
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            pass
