"""
config.py — .env dan ma'lumotlarni oladi
"""
import os
from dotenv import load_dotenv

load_dotenv()


_DEFAULT_SECRET = "change-me-in-production-very-secret-key"


class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", _DEFAULT_SECRET)
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    # ADMIN_PASSWORD_HASH — .env da hash saqlash tavsiya etiladi.
    # Oddiy parol (ADMIN_PASSWORD) faqat birinchi ishga tushirishda hash yaratish uchun.
    ADMIN_PASSWORD_HASH: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")  # hash yaratish uchun vaqtincha

    DB_PATH: str = os.getenv("DB_PATH", "articles.db")

    # Cookie xavfsizligi
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
    PERMANENT_SESSION_LIFETIME: int = 3600 * 8  # 8 soat

    # Rasm yuklash
    MAX_CONTENT_LENGTH: int = 5 * 1024 * 1024  # 5 MB maksimum yuklash hajmi

    # Login brute-force himoyasi
    MAX_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 300  # 5 daqiqa

    # Umumiy cheklov: feedback, kontakt, cofe uchun bitta baham ko'rilgan limit (IP bo'yicha)
    MAX_FEEDBACK_PER_WINDOW: int = 10
    SHARED_WINDOW_MINUTES_CHOICES: tuple = (20, 21, 22, 23, 24, 25)  # haqiqiy oyna shulardan tasodifiy tanlanadi
    SHARED_WINDOW_DISPLAY_MINUTES: int = 25   # foydalanuvchiga har doim shu ko'rsatiladi

    # Majburiy sekinlashtirish (har bir urinishda, botlarni sekinlashtirish uchun)
    FORCED_SLOWDOWN_MIN_SECONDS: float = 1.5
    FORCED_SLOWDOWN_MAX_SECONDS: float = 3.0

    CONTACT_EMAIL: str = os.getenv("CONTACT_EMAIL", "")
    CONTACT_TELEGRAM: str = os.getenv("CONTACT_TELEGRAM", "")
    CONTACT_LINKEDIN: str = os.getenv("CONTACT_LINKEDIN", "")
    CONTACT_GITHUB: str = os.getenv("CONTACT_GITHUB", "")
    TELEGRAM_CHANNEL: str = os.getenv("TELEGRAM_CHANNEL", "")


cfg = Config()

if not cfg.DEBUG and cfg.SECRET_KEY == _DEFAULT_SECRET:
    raise RuntimeError(
        "SECRET_KEY .env faylida o'rnatilmagan! "
        "Ishlab chiqarish muhitida standart kalit bilan ishga tushirish taqiqlangan. "
        "SECRET_KEY ni .env fayliga qo'ying (masalan: python -c \"import secrets; print(secrets.token_hex(32))\")."
    )