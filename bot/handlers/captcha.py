import asyncio

from aiogram import Router, Bot, F
from aiogram.types import ChatMemberUpdated, CallbackQuery, Message
from aiogram.filters import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.enums import ContentType

from bot.service.captcha_service import CaptchaService, CaptchaCallback
from bot.support.logger import get_logger

router = Router()
service = CaptchaService()
logger = get_logger(__name__)


@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def handle_new_member(event: ChatMemberUpdated, bot: Bot) -> None:
    if event.new_chat_member.user.is_bot:
        return
    
    user_id = event.new_chat_member.user.id
    if user_id in service._pending:
        logger.debug("Duplicate join event ignored | user_id=%d", user_id)
        return
    
    chat_id = event.chat.id
    user_name = event.new_chat_member.user.full_name

    logger.info("New member joined | user_id=%d user=%s chat_id=%d", user_id, user_name, chat_id)

    question, keyboard = service.create_captcha(user_id, chat_id)

    captcha_msg: Message = await bot.send_message(
        chat_id=chat_id,
        text=(
            f"👋 {user_name}, на нашу группу напали индусы!\n"
            f"Реши капчу, чтобы остаться в группе:\n\n"
            f"🔢 {question}\n\n"
            f"У тебя 3 попытки и {service._timeout // 60} минут."
        ),
        reply_markup=keyboard
    )

    service.set_message_ids(user_id, captcha_msg.message_id, join_message_id=None)
    asyncio.create_task(service.auto_kick(bot, user_id, chat_id))


@router.callback_query(CaptchaCallback.filter())
async def handle_captcha_answer(callback: CallbackQuery, callback_data: CaptchaCallback, bot: Bot) -> None:
    user_id = callback_data.user_id
    chat_id = callback.message.chat.id

    if callback.from_user.id != user_id:
        logger.warning("Foreign captcha attempt | from_user=%d target_user=%d", callback.from_user.id, user_id)
        await callback.answer("Это не твоя капча!", show_alert=True)
        return

    result = service.check_answer(user_id, callback_data.answer)

    if result is None:
        await callback.answer("Запрос устарел", show_alert=True)
        return

    if result["status"] == "correct":
        logger.info("Captcha passed | user_id=%d chat_id=%d", user_id, chat_id)
        await callback.answer("✅ Верно!")
        await service._delete_messages(bot, chat_id, result["bot_message_id"], result["join_message_id"])

    elif result["status"] == "wrong":
        attempts_left = result["attempts_left"]
        question, keyboard = service.new_captcha_for_retry(user_id)
        await callback.answer(f"❌ Неверно! Осталось попыток: {attempts_left}", show_alert=True)
        await callback.message.edit_text(
            text=(
                f"❌ Неверный ответ! Осталось попыток: {attempts_left}\n\n"
                f"🔢 {question}"
            ),
            reply_markup=keyboard
        )

    elif result["status"] == "banned":
        logger.info("Captcha failed (button) | user_id=%d chat_id=%d", user_id, chat_id)
        await callback.answer("❌ Попытки исчерпаны!", show_alert=True)
        await service._delete_messages(bot, chat_id, result["bot_message_id"], result["join_message_id"])
        await service._kick_user(bot, chat_id, user_id)
        await bot.send_message(chat_id, "🚫 Пользователь не прошёл капчу и был исключён.")


@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_message_during_captcha(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.from_user.is_bot:
        return
    
    if message.content_type in (
        ContentType.NEW_CHAT_MEMBERS,
        ContentType.LEFT_CHAT_MEMBER,
        ContentType.PINNED_MESSAGE,
    ):
        return
    
    logger.debug(
        "Incoming message | user_id=%s is_bot=%s content_type=%s text=%r",
        message.from_user.id if message.from_user else None,
        message.from_user.is_bot if message.from_user else None,
        message.content_type,
        message.text
    )
    
    user_id = message.from_user.id
    if user_id not in service._pending:
        return

    logger.info("Message sent during captcha | user_id=%d chat_id=%d", user_id, message.chat.id)

    try:
        await message.delete()
    except Exception as e:
        logger.warning("Failed to delete user message | user_id=%d error=%s", user_id, e)

    result = service.check_answer(user_id, answer=-1)

    if result is None:
        return

    if result["status"] == "wrong":
        attempts_left = result["attempts_left"]
        question, keyboard = service.new_captcha_for_retry(user_id)
        bot_msg_id = result["bot_message_id"]
        if bot_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=bot_msg_id,
                    text=(
                        f"⚠️ Не пиши сообщения до прохождения капчи!\n"
                        f"Осталось попыток: {attempts_left}\n\n"
                        f"🔢 {question}"
                    ),
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.warning("Failed to edit captcha message | user_id=%d error=%s", user_id, e)

    elif result["status"] == "banned":
        logger.info("Captcha failed (message) | user_id=%d chat_id=%d", user_id, message.chat.id)
        await service._delete_messages(bot, message.chat.id, result["bot_message_id"], result["join_message_id"])
        await service._kick_user(bot, message.chat.id, user_id)
        await bot.send_message(message.chat.id, "🚫 Пользователь не прошёл капчу и был исключён.")