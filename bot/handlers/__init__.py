from aiogram import Router
from .captcha import router as captcha_router


router = Router()
router.include_router(captcha_router)