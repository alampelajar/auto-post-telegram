import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

from backend.app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Akun Telegram"), KeyboardButton(text="📢 Auto Post")],
            [KeyboardButton(text="💬 Pesan"), KeyboardButton(text="👥 Grup")],
            [KeyboardButton(text="📦 Paket"), KeyboardButton(text="📊 Statistik")],
            [KeyboardButton(text="⚙️ Pengaturan")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def api_request(method: str, path: str, **kwargs) -> dict:
    headers = kwargs.pop("headers", {})
    headers["X-Internal-Secret"] = settings.internal_api_secret
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=10.0) as client:
        response = await client.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()


async def upsert_user(message: Message) -> dict:
    user = message.from_user
    if user is None:
        raise RuntimeError("Telegram user tidak tersedia")
    return await api_request(
        "POST",
        "/internal/users/upsert",
        json={
            "telegram_user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
        },
    )


async def render_home(message: Message) -> None:
    await upsert_user(message)
    text = (
        "🏠 <b>Telegram Auto Post</b>\n\n"
        "Kelola akun, pesan, grup, paket, dan Auto Post dari bot ini.\n\n"
        "Pilih menu di bawah untuk mulai."
    )
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


async def render_account(message: Message) -> None:
    await upsert_user(message)
    await message.answer(
        "👤 <b>Akun Telegram</b>\n\n"
        "Status koneksi akun Telegram untuk Auto Post akan tersedia pada Phase 2.\n\n"
        "<i>Jangan pernah mengirim password atau session string ke chat.</i>",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


async def render_autopost(message: Message) -> None:
    await upsert_user(message)
    try:
        sub = await api_request("GET", f"/internal/users/{message.from_user.id}/subscription")
    except httpx.HTTPError:
        await message.answer("⚠️ Backend sedang tidak dapat diakses.", reply_markup=main_keyboard())
        return

    if not sub["active"]:
        await message.answer(
            "📢 <b>Auto Post</b>\n\n"
            "Subscription kamu belum aktif. Beli paket terlebih dahulu untuk mengaktifkan Auto Post.",
            reply_markup=main_keyboard(),
            parse_mode="HTML",
        )
        return

    data = sub["subscription"]
    await message.answer(
        "📢 <b>Auto Post</b>\n\n"
        f"Paket: <b>{data['plan_name']}</b>\n"
        f"Status: <b>{data['status']}</b>\n"
        f"Expired: <code>{data['expired_at']}</code>\n\n"
        "Engine Auto Post akan diaktifkan pada fase berikutnya.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


async def render_plans(message: Message) -> None:
    await upsert_user(message)
    try:
        plans = await api_request("GET", "/internal/plans")
    except httpx.HTTPError:
        await message.answer("⚠️ Gagal mengambil daftar paket.", reply_markup=main_keyboard())
        return

    if not plans:
        await message.answer(
            "📦 Belum ada paket aktif. Owner perlu membuat paket terlebih dahulu.",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["📦 <b>PAKET</b>", ""]
    for plan in plans:
        min_delay = plan["min_delay_seconds"] // 60
        lines.append(
            f"<b>{plan['name']}</b> — {plan['price']}\n"
            f"• Durasi: {plan['duration_days']} hari\n"
            f"• Maks karakter: {plan['max_characters']:,}\n"
            f"• Maks grup: {plan['max_groups']}\n"
            f"• Delay minimum: {min_delay} menit\n"
        )
    lines.append("Pembayaran dan aktivasi otomatis masuk pada Phase 4.")
    await message.answer("\n".join(lines), reply_markup=main_keyboard(), parse_mode="HTML")


async def placeholder(message: Message) -> None:
    await upsert_user(message)
    await message.answer(
        f"{message.text}\n\nModul ini akan diimplementasikan pada phase berikutnya.",
        reply_markup=main_keyboard(),
    )


async def main() -> None:
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN belum diisi di .env")
    if not settings.internal_api_secret:
        raise RuntimeError("INTERNAL_API_SECRET belum diisi di .env")

    bot = Bot(settings.bot_token)
    dp = Dispatcher()

    dp.message.register(render_home, CommandStart())
    dp.message.register(render_account, F.text == "👤 Akun Telegram")
    dp.message.register(render_autopost, F.text == "📢 Auto Post")
    dp.message.register(render_plans, F.text == "📦 Paket")
    dp.message.register(placeholder, F.text.in_({"💬 Pesan", "👥 Grup", "📊 Statistik", "⚙️ Pengaturan"}))

    try:
        logger.info("Bot started")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
