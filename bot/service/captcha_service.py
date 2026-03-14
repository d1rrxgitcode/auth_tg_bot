import asyncio
import random

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData

from bot.support.logger import get_logger


logger = get_logger(__name__)


class CaptchaCallback(CallbackData, prefix="captcha"):
    user_id: int
    answer: int


class CaptchaService:
    def __init__(self):
        self._pending: dict[int, dict] = {}
        self._timeout: int = 300

    def create_captcha(self, user_id: int, chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
        a, b = random.randint(1, 10), random.randint(1, 10)
        correct = a + b

        options = {correct}
        while len(options) < 4:
            options.add(random.randint(1, 20))
        options = list(options)
        random.shuffle(options)

        buttons = [
            InlineKeyboardButton(
                text=str(opt),
                callback_data=CaptchaCallback(user_id=user_id, answer=opt).pack()
            )
            for opt in options
        ]

        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])

        self._pending[user_id] = {
            "chat_id": chat_id,
            "correct": correct,
            "attempts": 3,
            "bot_message_id": None,
            "join_message_id": None,
        }

        logger.info("Captcha created | user_id=%d chat_id=%d correct=%d", user_id, chat_id, correct)
        return f"{a} + {b} = ?", keyboard

    def set_message_ids(self, user_id: int, bot_message_id: int, join_message_id: int | None) -> None:
        if user_id in self._pending:
            self._pending[user_id]["bot_message_id"] = bot_message_id
            self._pending[user_id]["join_message_id"] = join_message_id
            logger.debug("Message IDs set | user_id=%d bot_msg=%d join_msg=%s", user_id, bot_message_id, join_message_id)

    def check_answer(self, user_id: int, answer: int) -> dict | None:
        if user_id not in self._pending:
            logger.warning("check_answer: no pending captcha | user_id=%d", user_id)
            return None

        data = self._pending[user_id]
        is_correct = answer == data["correct"]

        if is_correct:
            self._pending.pop(user_id)
            logger.info("Captcha solved | user_id=%d", user_id)
            return {
                "status": "correct",
                "chat_id": data["chat_id"],
                "attempts_left": 0,
                "bot_message_id": data["bot_message_id"],
                "join_message_id": data["join_message_id"],
            }

        data["attempts"] -= 1
        attempts_left = data["attempts"]
        logger.info("Wrong answer | user_id=%d answer=%d attempts_left=%d", user_id, answer, attempts_left)

        if attempts_left <= 0:
            self._pending.pop(user_id)
            logger.info("Captcha failed (no attempts left) | user_id=%d", user_id)
            return {
                "status": "banned",
                "chat_id": data["chat_id"],
                "attempts_left": 0,
                "bot_message_id": data["bot_message_id"],
                "join_message_id": data["join_message_id"],
            }

        return {
            "status": "wrong",
            "chat_id": data["chat_id"],
            "attempts_left": attempts_left,
            "bot_message_id": data["bot_message_id"],
            "join_message_id": data["join_message_id"],
        }

    def new_captcha_for_retry(self, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        a, b = random.randint(1, 10), random.randint(1, 10)
        correct = a + b

        options = {correct}
        while len(options) < 4:
            options.add(random.randint(1, 20))
        options = list(options)
        random.shuffle(options)

        buttons = [
            InlineKeyboardButton(
                text=str(opt),
                callback_data=CaptchaCallback(user_id=user_id, answer=opt).pack()
            )
            for opt in options
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[:2], buttons[2:]])
        self._pending[user_id]["correct"] = correct

        logger.debug("New captcha for retry | user_id=%d correct=%d", user_id, correct)
        return f"{a} + {b} = ?", keyboard

    async def auto_kick(self, bot: Bot, user_id: int, chat_id: int) -> None:
        await asyncio.sleep(self._timeout)
        if user_id in self._pending:
            data = self._pending.pop(user_id)
            logger.info("Auto-kick (timeout) | user_id=%d chat_id=%d", user_id, chat_id)
            await self._kick_user(bot, chat_id, user_id)
            await self._delete_messages(bot, chat_id, data["bot_message_id"], data["join_message_id"])
            try:
                await bot.send_message(chat_id, "⏰ Пользователь не прошёл капчу вовремя и был исключён.")
            except Exception:
                pass

    @staticmethod
    async def _kick_user(bot: Bot, chat_id: int, user_id: int) -> None:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
            logger.info("User kicked | user_id=%d chat_id=%d", user_id, chat_id)
        except Exception as e:
            logger.error("Failed to kick user | user_id=%d chat_id=%d error=%s", user_id, chat_id, e)

    @staticmethod
    async def _delete_messages(bot: Bot, chat_id: int, *message_ids: int | None) -> None:
        for mid in message_ids:
            if mid is not None:
                try:
                    await bot.delete_message(chat_id, mid)
                    logger.debug("Message deleted | chat_id=%d message_id=%d", chat_id, mid)
                except Exception as e:
                    logger.warning("Failed to delete message | chat_id=%d message_id=%d error=%s", chat_id, mid, e)