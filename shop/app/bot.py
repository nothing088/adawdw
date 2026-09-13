from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from .config import settings


bot = Bot(settings.BOT_TOKEN)
dp = Dispatcher()
router = Router()


@router.message(CommandStart())
async def start(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="🛍 Открыть магазин",
                web_app=WebAppInfo(url=settings.MINI_APP_URL),
            )
        ]]
    )
    await message.answer(
        "Добро пожаловать! Откройте магазин кнопкой ниже.",
        reply_markup=keyboard,
    )


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Используйте /start, чтобы открыть магазин."
    )


dp.include_router(router)


async def configure_webhook():
    webhook_url = settings.PUBLIC_BASE_URL.rstrip("/") + "/telegram/webhook"
    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )
