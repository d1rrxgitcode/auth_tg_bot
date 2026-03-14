import asyncio

from aiogram import Bot, Dispatcher

from bot.support.settings import Settings
from bot.support.logger import setup_logging, get_logger
from bot.handlers import router

logger = get_logger(__name__)


async def main() -> None:
    setup_logging()
    settings = Settings()
    bot = Bot(token=settings.TOKEN)

    dp = Dispatcher()
    await bot.delete_webhook(drop_pending_updates=True)
    dp.include_router(router)

    logger.info("Bot started")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "chat_member"])


if __name__ == "__main__":
    asyncio.run(main())