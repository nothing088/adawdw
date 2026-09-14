from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from .config import settings
from .db import users


bot = Bot(settings.BOT_TOKEN)
dp = Dispatcher()
router = Router()


@router.message(CommandStart())
async def start(message: Message):
    tg_user = message.from_user

    # Проверяем, запускал ли пользователь бота раньше.
    existing_user = await users.find_one({
        "tg_id": int(tg_user.id)
    })

    # Создаём пользователя только при первом запуске.
    if existing_user is None:
        await users.insert_one({
            "tg_id": int(tg_user.id),
            "username": tg_user.username or "",
            "first_name": tg_user.first_name or "",
            "last_name": tg_user.last_name or "",
        })

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✦ Открыть NothingPC",
                    web_app=WebAppInfo(
                        url=settings.MINI_APP_URL
                    ),
                )
            ]
        ]
    )

    if existing_user is None:
        welcome = (
            "Добро пожаловать в NothingPC. Здесь вы найдете качественную "
            "технику с гарантией, что прослужит вам долгие и счастливые годы.\n\n"
            "Выбирай лучшее. Выбирай NothingPC"
        )
    else:
        welcome = (
            "С возвращением в NothingPC.\n\n"
            "Выбирай лучшее. Выбирай NothingPC"
        )

    await message.answer(
        welcome,
        reply_markup=keyboard,
    )


@router.message()
async def fallback(message: Message):
    await message.answer(
        "Используйте /start, чтобы открыть NothingPC."
    )


dp.include_router(router)


async def configure_webhook():
    webhook_url = (
        settings.PUBLIC_BASE_URL.rstrip("/")
        + "/telegram/webhook"
    )

    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=False,
    )