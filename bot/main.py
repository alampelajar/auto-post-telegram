import asyncio
import logging
import re

import httpx

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

from backend.app.core.config import get_settings


# ============================================================
# CONFIG
# ============================================================

settings = get_settings()

# Bot dan API berada di Docker Compose.
API_URL = "http://api:8000"


logging.basicConfig(
    level=getattr(
        logging,
        settings.log_level.upper(),
        logging.INFO,
    ),
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)


# ============================================================
# STATES
# ============================================================

class TelegramConnectState(StatesGroup):
    phone = State()
    code = State()
    password = State()


class MessageState(StatesGroup):
    title = State()
    content = State()


# ============================================================
# MAIN KEYBOARD
# ============================================================

def main_keyboard() -> ReplyKeyboardMarkup:

    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="👤 Akun Telegram"
                ),
                KeyboardButton(
                    text="📢 Auto Post"
                ),
            ],
            [
                KeyboardButton(
                    text="💬 Pesan"
                ),
                KeyboardButton(
                    text="👥 Grup"
                ),
            ],
            [
                KeyboardButton(
                    text="📦 Paket"
                ),
                KeyboardButton(
                    text="📊 Statistik"
                ),
            ],
            [
                KeyboardButton(
                    text="⚙️ Pengaturan"
                ),
            ],
        ],
        resize_keyboard=True,
    )


# ============================================================
# API REQUEST
# ============================================================

async def api_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> dict:

    url = f"{API_URL}{path}"

    async with httpx.AsyncClient(
        timeout=30.0
    ) as client:

        response = await client.request(
            method,
            url,
            params=params,
            json=json,
        )

        try:
            data = response.json()

        except Exception:

            data = {
                "detail": response.text
            }

        if response.status_code >= 400:

            detail = data.get(
                "detail",
                "Terjadi kesalahan pada API.",
            )

            if isinstance(detail, list):

                detail = "; ".join(
                    str(item)
                    for item in detail
                )

            raise RuntimeError(
                str(detail)
            )

        return data


# ============================================================
# ACCOUNT KEYBOARD
# ============================================================

def accounts_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Hubungkan Akun Telegram",
                    callback_data="connect_account",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Refresh",
                    callback_data="refresh_accounts",
                )
            ],
        ]
    )


# ============================================================
# GROUP KEYBOARD
# ============================================================

def groups_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Tambah Grup",
                    callback_data="add_group",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Refresh",
                    callback_data="refresh_groups",
                )
            ],
        ]
    )


# ============================================================
# MESSAGE KEYBOARD
# ============================================================

def messages_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ Buat Pesan",
                    callback_data="add_message",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Refresh",
                    callback_data="refresh_messages",
                )
            ],
        ]
    )


# ============================================================
# ACCOUNT MENU
# ============================================================

async def show_accounts(
    message: Message,
) -> None:

    try:

        data = await api_request(
            "GET",
            "/api/telegram/accounts",
            params={
                "telegram_user_id":
                    message.from_user.id,
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal mengambil akun Telegram"
        )

        await message.answer(
            "❌ Gagal mengambil akun Telegram.\n\n"
            f"{exc}"
        )

        return

    accounts = data.get(
        "accounts",
        [],
    )

    if not accounts:

        text = (
            "👤 Akun Telegram\n\n"
            "Belum ada akun Telegram yang terhubung."
        )

    else:

        lines = [
            "👤 Akun Telegram",
            "",
            f"Total akun: {len(accounts)}",
            "",
        ]

        for index, account in enumerate(
            accounts,
            start=1,
        ):

            username = account.get(
                "username"
            )

            phone = account.get(
                "phone_number"
            )

            status = account.get(
                "status",
                "UNKNOWN",
            )

            if username:

                identity = f"@{username}"

            elif phone:

                identity = phone

            else:

                identity = str(
                    account.get(
                        "telegram_user_id",
                        "-",
                    )
                )

            lines.append(
                f"{index}. {identity}"
            )

            lines.append(
                f"   Status: {status}"
            )

            lines.append("")

        text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=accounts_keyboard(),
    )


# ============================================================
# ACCOUNT BUTTON
# ============================================================

async def account_button(
    message: Message,
) -> None:

    await show_accounts(message)


# ============================================================
# CONNECT ACCOUNT WITH TELEGRAM QR LOGIN
# ============================================================

def qr_login_keyboard(login_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Buka Telegram untuk menyetujui",
                    url=login_url,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Cek Status Koneksi",
                    callback_data="check_qr_login",
                )
            ],
        ]
    )


async def start_connect(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await callback.answer()
    await state.clear()

    try:
        data = await api_request(
            "POST",
            "/api/telegram/accounts/connect/qr/request",
            json={
                "telegram_user_id": callback.from_user.id,
            },
        )
    except Exception as exc:
        logger.exception("Gagal membuat QR login Telegram")
        await callback.message.answer(
            "❌ Gagal memulai koneksi Telegram.\n\n"
            f"{exc}"
        )
        return

    login_url = data.get("login_url")
    if not login_url:
        await callback.message.answer(
            "❌ Telegram tidak mengembalikan link login. "
            "Coba mulai koneksi lagi."
        )
        return

    expires = data.get("expires_in", 600)

    await callback.message.answer(
        "🔐 Hubungkan Akun Telegram\n\n"
        "1. Tekan tombol untuk membuka aplikasi Telegram.\n"
        "2. Setujui login hanya jika kamu sendiri yang memulainya.\n"
        "3. Kembali ke sini dan tekan Cek Status Koneksi.\n\n"
        "Jangan kirim kode login/OTP ke bot.\n"
        f"Link berlaku sekitar {expires} detik.",
        reply_markup=qr_login_keyboard(login_url),
    )


async def check_qr_login(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    try:
        data = await api_request(
            "GET",
            "/api/telegram/accounts/connect/qr/status",
            params={
                "telegram_user_id": callback.from_user.id,
            },
        )
    except Exception as exc:
        logger.exception("Gagal mengecek status QR login")
        await callback.answer(
            "Gagal mengecek status koneksi.",
            show_alert=True,
        )
        await callback.message.answer(
            f"❌ Gagal mengecek status koneksi.\n{exc}"
        )
        return

    status = data.get("status", "UNKNOWN")

    if status == "WAITING":
        await callback.answer(
            "Login masih menunggu persetujuan di Telegram."
        )
        return

    if status == "REQUIRES_PASSWORD":
        await state.set_state(
            TelegramConnectState.password
        )
        await callback.answer(
            "Telegram meminta verifikasi 2 langkah."
        )
        await callback.message.answer(
            "🔐 Akun ini memerlukan password verifikasi dua langkah.\n\n"
            "Kirim password hanya jika kamu memahami bahwa layanan ini "
            "akan menggunakannya sesaat untuk menyelesaikan login. "
            "Pesan password akan dihapus segera setelah bot menerimanya.\n\n"
            "Ketik /cancel untuk membatalkan."
        )
        return

    if status == "CONNECTED":
        account = data.get("account") or {}
        username = account.get("username")
        identity = (
            f"@{username}"
            if username
            else account.get("phone_number")
            or str(account.get("telegram_user_id", "-"))
        )
        await state.clear()
        await callback.answer("Akun berhasil terhubung.")
        try:
            await callback.message.edit_text(
                "✅ Akun Telegram berhasil terhubung!\n\n"
                f"👤 {identity}\n"
                "🟢 Status: CONNECTED"
            )
        except Exception:
            await callback.message.answer(
                "✅ Akun Telegram berhasil terhubung!\n\n"
                f"👤 {identity}\n"
                "🟢 Status: CONNECTED"
            )
        await callback.message.answer(
            "Kembali ke menu utama untuk melanjutkan.",
            reply_markup=main_keyboard(),
        )
        return

    if status in {"EXPIRED", "FAILED", "CANCELLED", "NOT_FOUND"}:
        await state.clear()
        await callback.answer(
            "Sesi QR sudah tidak aktif.",
            show_alert=True,
        )
        await callback.message.answer(
            "❌ " + data.get(
                "message",
                "Koneksi QR sudah tidak aktif.",
            ) + "\n\nTekan Akun Telegram lalu Hubungkan Akun untuk mencoba lagi.",
            reply_markup=main_keyboard(),
        )
        return

    await callback.answer(
        "Status koneksi belum dikenali. Coba refresh.",
        show_alert=True,
    )


# ============================================================
# RECEIVE PHONE
# ============================================================

async def receive_phone(
    message: Message,
    state: FSMContext,
) -> None:

    phone = (
        message.text or ""
    ).strip()

    normalized = phone.replace(
        " ",
        "",
    )

    if not re.fullmatch(
        r"\+?[0-9]{8,15}",
        normalized,
    ):

        await message.answer(
            "❌ Format nomor tidak valid.\n\n"
            "Contoh:\n"
            "+6281234567890"
        )

        return

    if not normalized.startswith("+"):

        normalized = (
            "+"
            + normalized
        )

    await message.answer(
        "⏳ Mengirim kode login Telegram..."
    )

    try:

        data = await api_request(
            "POST",
            "/api/telegram/accounts/connect/request",
            json={
                "telegram_user_id":
                    message.from_user.id,
                "phone_number":
                    normalized,
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal request kode Telegram"
        )

        await message.answer(
            "❌ Gagal mengirim kode.\n\n"
            f"{exc}"
        )

        return

    await state.update_data(
        phone_number=normalized
    )

    await state.set_state(
        TelegramConnectState.code
    )

    expires = data.get(
        "expires_in",
        600,
    )

    await message.answer(
        "✅ Kode login Telegram sudah dikirim.\n\n"
        "Masukkan kode yang kamu terima.\n\n"
        f"⏱️ Berlaku sekitar {expires} detik.\n\n"
        "⚠️ Jangan bagikan kode login kepada siapa pun."
    )


# ============================================================
# RECEIVE CODE
# ============================================================

async def receive_code(
    message: Message,
    state: FSMContext,
) -> None:

    code = (
        message.text or ""
    ).strip().replace(
        " ",
        "",
    )

    if not re.fullmatch(
        r"[0-9]{3,10}",
        code,
    ):

        await message.answer(
            "❌ Kode tidak valid."
        )

        return

    await message.answer(
        "⏳ Memverifikasi kode Telegram..."
    )

    try:

        data = await api_request(
            "POST",
            "/api/telegram/accounts/connect/verify",
            json={
                "telegram_user_id":
                    message.from_user.id,
                "code":
                    code,
                "password":
                    None,
            },
        )

    except Exception as exc:

        logger.exception(
            "Verifikasi Telegram gagal"
        )

        await message.answer(
            "❌ Verifikasi gagal.\n\n"
            f"{exc}"
        )

        return

    if data.get(
        "requires_password",
        False,
    ):

        await state.set_state(
            TelegramConnectState.password
        )

        await message.answer(
            "🔐 Akun Telegram menggunakan "
            "verifikasi 2 langkah.\n\n"
            "Masukkan password 2FA untuk "
            "menyelesaikan proses login.\n\n"
            "Ketik /cancel untuk membatalkan."
        )

        return

    if data.get("ok"):

        account = data.get(
            "account",
            {},
        )

        username = account.get(
            "username"
        )

        identity = (
            f"@{username}"
            if username
            else account.get(
                "phone_number",
                "-",
            )
        )

        await state.clear()

        await message.answer(
            "✅ Akun Telegram berhasil terhubung!\n\n"
            f"👤 {identity}\n"
            "🟢 Status: CONNECTED",
            reply_markup=main_keyboard(),
        )

        return

    await message.answer(
        data.get(
            "message",
            "Verifikasi gagal.",
        )
    )


# ============================================================
# RECEIVE 2FA
# ============================================================

async def receive_password(
    message: Message,
    state: FSMContext,
) -> None:

    password = message.text or ""

    # Remove the password message from the bot chat immediately.
    # Never log the password or include it in error messages.
    try:
        await message.delete()
    except Exception:
        logger.warning(
            "Could not delete the received 2FA password message; refusing to submit it."
        )
        await message.answer(
            "❌ Demi keamanan, password tidak dikirim karena pesan tidak berhasil dihapus. "
            "Pastikan kamu memakai chat pribadi dengan bot, lalu coba lagi."
        )
        return

    if not password:

        await message.answer(
            "❌ Password 2FA tidak boleh kosong."
        )

        return

    await message.answer(
        "⏳ Memverifikasi 2FA..."
    )

    try:

        data = await api_request(
            "POST",
            "/api/telegram/accounts/connect/qr/2fa",
            json={
                "telegram_user_id":
                    message.from_user.id,
                "password":
                    password,
            },
        )

    except Exception as exc:

        logger.exception(
            "Verifikasi 2FA gagal"
        )

        await message.answer(
            "❌ Verifikasi 2FA gagal.\n\n"
            f"{exc}"
        )

        return

    if not data.get("ok"):

        await message.answer(
            data.get(
                "message",
                "Verifikasi 2FA gagal.",
            )
        )

        return

    account = data.get(
        "account",
        {},
    )

    username = account.get(
        "username"
    )

    identity = (
        f"@{username}"
        if username
        else account.get(
            "phone_number",
            "-",
        )
    )

    await state.clear()

    await message.answer(
        "✅ Akun Telegram berhasil terhubung!\n\n"
        f"👤 {identity}\n"
        "🟢 Status: CONNECTED",
        reply_markup=main_keyboard(),
    )


# ============================================================
# GROUP MENU
# ============================================================

async def show_groups(
    message: Message,
) -> None:

    try:

        data = await api_request(
            "GET",
            "/api/groups",
            params={
                "telegram_user_id":
                    message.from_user.id,
                "status":
                    "ACTIVE",
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal mengambil grup"
        )

        await message.answer(
            "❌ Gagal mengambil grup.\n\n"
            f"{exc}"
        )

        return

    groups = data.get(
        "groups",
        [],
    )

    if not groups:

        text = (
            "👥 Grup Kamu\n\n"
            "Belum ada grup yang dipilih."
        )

    else:

        lines = [
            "👥 Grup Kamu",
            "",
            f"Total: {len(groups)}",
            "",
        ]

        for index, group in enumerate(
            groups,
            start=1,
        ):

            title = group.get(
                "title",
                "-",
            )

            category = (
                group.get(
                    "category"
                )
                or "Umum"
            )

            lines.append(
                f"{index}. {title}"
            )

            lines.append(
                f"   🏷️ {category}"
            )

            if group.get("username"):

                lines.append(
                    f"   @{group['username']}"
                )

            lines.append("")

        text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=groups_keyboard(),
    )


# ============================================================
# GROUP BUTTON
# ============================================================

async def group_button(
    message: Message,
) -> None:

    await show_groups(message)


# ============================================================
# ADD GROUP
# ============================================================

async def start_add_group(
    callback: CallbackQuery,
) -> None:

    await callback.answer()

    try:

        data = await api_request(
            "GET",
            "/api/telegram/accounts",
            params={
                "telegram_user_id":
                    callback.from_user.id,
            },
        )

    except Exception as exc:

        await callback.message.answer(
            "❌ Gagal mengambil akun Telegram.\n\n"
            f"{exc}"
        )

        return

    accounts = data.get(
        "accounts",
        [],
    )

    if not accounts:

        await callback.message.answer(
            "📱 Belum ada akun Telegram yang terhubung.\n\n"
            "Hubungkan akun terlebih dahulu "
            "melalui menu 👤 Akun Telegram."
        )

        return

    buttons = []

    for account in accounts:

        username = account.get(
            "username"
        )

        phone = account.get(
            "phone_number",
            "-",
        )

        status = account.get(
            "status",
            "UNKNOWN",
        )

        label = (
            f"@{username}"
            if username
            else phone
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"📱 {label} · {status}"
                    ),
                    callback_data=(
                        "group_account:"
                        f"{account['id']}"
                    ),
                )
            ]
        )

    await callback.message.answer(
        "📱 Pilih Akun Telegram\n\n"
        "Sistem akan mengambil daftar grup "
        "dari akun yang kamu pilih.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )


# ============================================================
# AVAILABLE GROUPS
# ============================================================

async def show_available_groups(
    callback: CallbackQuery,
) -> None:

    await callback.answer(
        "Mengambil grup..."
    )

    try:

        account_id = int(
            callback.data.split(":")[1]
        )

        data = await api_request(
            "GET",
            "/api/groups/available",
            params={
                "telegram_user_id":
                    callback.from_user.id,
                "account_id":
                    account_id,
                "limit":
                    50,
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal mengambil grup Telegram"
        )

        await callback.message.answer(
            "❌ Gagal mengambil grup.\n\n"
            f"{exc}"
        )

        return

    groups = data.get(
        "groups",
        [],
    )

    if not groups:

        await callback.message.answer(
            "👥 Tidak menemukan grup baru."
        )

        return

    buttons = []

    for group in groups:

        title = group.get(
            "title",
            "Unnamed Group",
        )

        chat_id = group.get(
            "telegram_chat_id"
        )

        username = group.get(
            "username"
        )

        if username:

            label = (
                f"👥 {title} (@{username})"
            )

        else:

            label = (
                f"👥 {title}"
            )

        buttons.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=(
                        "group_import:"
                        f"{account_id}:"
                        f"{chat_id}"
                    ),
                )
            ]
        )

    await callback.message.answer(
        "👥 Pilih Grup\n\n"
        "Pilih grup yang ingin kamu tambahkan.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        ),
    )


# ============================================================
# IMPORT GROUP
# ============================================================

async def import_selected_group(
    callback: CallbackQuery,
) -> None:

    await callback.answer(
        "Menambahkan grup..."
    )

    try:

        parts = callback.data.split(":")

        account_id = int(
            parts[1]
        )

        chat_id = int(
            parts[2]
        )

        result = await api_request(
            "POST",
            "/api/groups/import",
            json={
                "telegram_user_id":
                    callback.from_user.id,
                "account_id":
                    account_id,
                "telegram_chat_id":
                    chat_id,
            },
        )

    except Exception as exc:

        logger.exception(
            "Import group gagal"
        )

        await callback.message.answer(
            "❌ Gagal menambahkan grup.\n\n"
            f"{exc}"
        )

        return

    group = result.get(
        "group",
        {},
    )

    await callback.message.answer(
        "✅ Grup berhasil ditambahkan!\n\n"
        f"👥 {group.get('title', '-')}\n"
        "🟢 Status: ACTIVE",
        reply_markup=groups_keyboard(),
    )


# ============================================================
# REFRESH ACCOUNT
# ============================================================

async def refresh_accounts(
    callback: CallbackQuery,
) -> None:

    await callback.answer(
        "Memuat ulang..."
    )

    try:

        data = await api_request(
            "GET",
            "/api/telegram/accounts",
            params={
                "telegram_user_id":
                    callback.from_user.id,
            },
        )

        accounts = data.get(
            "accounts",
            [],
        )

        if not accounts:

            text = (
                "👤 Akun Telegram\n\n"
                "Belum ada akun terhubung."
            )

        else:

            lines = [
                "👤 Akun Telegram",
                "",
                f"Total: {len(accounts)}",
                "",
            ]

            for index, account in enumerate(
                accounts,
                start=1,
            ):

                username = account.get(
                    "username"
                )

                identity = (
                    f"@{username}"
                    if username
                    else account.get(
                        "phone_number",
                        "-",
                    )
                )

                lines.append(
                    f"{index}. {identity}"
                )

                lines.append(
                    f"   Status: "
                    f"{account.get('status', '-')}"
                )

                lines.append("")

            text = "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=accounts_keyboard(),
        )

    except Exception as exc:

        await callback.message.answer(
            "❌ Gagal refresh akun.\n\n"
            f"{exc}"
        )


# ============================================================
# REFRESH GROUPS
# ============================================================

async def refresh_groups(
    callback: CallbackQuery,
) -> None:

    await callback.answer(
        "Memuat ulang..."
    )

    try:

        data = await api_request(
            "GET",
            "/api/groups",
            params={
                "telegram_user_id":
                    callback.from_user.id,
                "status":
                    "ACTIVE",
            },
        )

        groups = data.get(
            "groups",
            [],
        )

        if not groups:

            text = (
                "👥 Grup Kamu\n\n"
                "Belum ada grup."
            )

        else:

            lines = [
                "👥 Grup Kamu",
                "",
                f"Total: {len(groups)}",
                "",
            ]

            for index, group in enumerate(
                groups,
                start=1,
            ):

                lines.append(
                    f"{index}. {group.get('title', '-')}"
                )

                lines.append("")

            text = "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=groups_keyboard(),
        )

    except Exception as exc:

        await callback.message.answer(
            "❌ Gagal refresh grup.\n\n"
            f"{exc}"
        )


# ============================================================
# MESSAGE MENU
# ============================================================

async def show_messages(
    message: Message,
) -> None:

    try:

        data = await api_request(
            "GET",
            "/api/messages",
            params={
                "telegram_user_id":
                    message.from_user.id,
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal mengambil pesan"
        )

        await message.answer(
            "❌ Gagal mengambil pesan.\n\n"
            f"{exc}"
        )

        return

    messages = data.get(
        "messages",
        [],
    )

    if not messages:

        text = (
            "💬 Pesan Kamu\n\n"
            "Belum ada pesan yang dibuat."
        )

    else:

        lines = [
            "💬 Pesan Kamu",
            "",
            f"Total: {len(messages)}",
            "",
        ]

        for index, item in enumerate(
            messages,
            start=1,
        ):

            title = item.get(
                "title",
                "-",
            )

            status = item.get(
                "status",
                "-",
            )

            content = item.get(
                "content",
                "",
            )

            preview = content.replace(
                "\n",
                " ",
            )

            if len(preview) > 80:

                preview = (
                    preview[:80]
                    + "..."
                )

            lines.append(
                f"{index}. {title}"
            )

            lines.append(
                f"   {preview}"
            )

            lines.append(
                f"   Status: {status}"
            )

            lines.append("")

        text = "\n".join(lines)

    await message.answer(
        text,
        reply_markup=messages_keyboard(),
    )


# ============================================================
# MESSAGE BUTTON
# ============================================================

async def message_button(
    message: Message,
) -> None:

    await show_messages(message)


# ============================================================
# START ADD MESSAGE
# ============================================================

async def start_add_message(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:

    await callback.answer()

    await state.set_state(
        MessageState.title
    )

    await callback.message.answer(
        "💬 Buat Pesan Baru\n\n"
        "Masukkan judul pesan.\n\n"
        "Contoh:\n"
        "Promo Hari Ini\n\n"
        "Ketik /cancel untuk membatalkan."
    )


# ============================================================
# RECEIVE MESSAGE TITLE
# ============================================================

async def receive_message_title(
    message: Message,
    state: FSMContext,
) -> None:

    title = (
        message.text or ""
    ).strip()

    if not title:

        await message.answer(
            "❌ Judul tidak boleh kosong."
        )

        return

    if len(title) > 255:

        await message.answer(
            "❌ Judul maksimal 255 karakter."
        )

        return

    await state.update_data(
        title=title
    )

    await state.set_state(
        MessageState.content
    )

    await message.answer(
        "📝 Sekarang masukkan isi pesan.\n\n"
        "Pesan bisa terdiri dari beberapa baris.\n\n"
        "Ketik /cancel untuk membatalkan."
    )


# ============================================================
# RECEIVE MESSAGE CONTENT
# ============================================================

async def receive_message_content(
    message: Message,
    state: FSMContext,
) -> None:

    content = (
        message.text or ""
    ).strip()

    if not content:

        await message.answer(
            "❌ Isi pesan tidak boleh kosong."
        )

        return

    data = await state.get_data()

    try:

        result = await api_request(
            "POST",
            "/api/messages",
            json={
                "telegram_user_id":
                    message.from_user.id,
                "title":
                    data["title"],
                "content":
                    content,
            },
        )

    except Exception as exc:

        logger.exception(
            "Gagal membuat pesan"
        )

        await message.answer(
            "❌ Gagal membuat pesan.\n\n"
            f"{exc}"
        )

        return

    created = result.get(
        "data",
        {},
    )

    await state.clear()

    await message.answer(
        "✅ Pesan berhasil dibuat!\n\n"
        f"Judul: {created.get('title', '-')}\n"
        f"Status: {created.get('status', 'ACTIVE')}",
        reply_markup=main_keyboard(),
    )


# ============================================================
# REFRESH MESSAGES
# ============================================================

async def refresh_messages(
    callback: CallbackQuery,
) -> None:

    await callback.answer(
        "Memuat pesan..."
    )

    try:

        data = await api_request(
            "GET",
            "/api/messages",
            params={
                "telegram_user_id":
                    callback.from_user.id,
            },
        )

        messages = data.get(
            "messages",
            [],
        )

        if not messages:

            text = (
                "💬 Pesan Kamu\n\n"
                "Belum ada pesan."
            )

        else:

            lines = [
                "💬 Pesan Kamu",
                "",
                f"Total: {len(messages)}",
                "",
            ]

            for index, item in enumerate(
                messages,
                start=1,
            ):

                lines.append(
                    f"{index}. {item.get('title', '-')}"
                )

                lines.append(
                    f"   Status: "
                    f"{item.get('status', '-')}"
                )

                lines.append("")

            text = "\n".join(lines)

        await callback.message.edit_text(
            text,
            reply_markup=messages_keyboard(),
        )

    except Exception as exc:

        await callback.message.answer(
            "❌ Gagal refresh pesan.\n\n"
            f"{exc}"
        )


# ============================================================
# PLACEHOLDER
# ============================================================

async def placeholder(
    message: Message,
) -> None:

    await message.answer(
        f"📌 {message.text}\n\n"
        "Modul ini belum diaktifkan.",
        reply_markup=main_keyboard(),
    )


# ============================================================
# CANCEL
# ============================================================

async def cancel(
    message: Message,
    state: FSMContext,
) -> None:

    await state.clear()

    await message.answer(
        "❌ Proses dibatalkan.",
        reply_markup=main_keyboard(),
    )


# ============================================================
# START
# ============================================================

async def start(
    message: Message,
    state: FSMContext,
) -> None:

    await state.clear()

    await message.answer(
        "Selamat datang di "
        "Telegram Auto Post SaaS.\n\n"
        "Kelola akun Telegram, grup, pesan, "
        "dan Auto Post dari satu tempat.",
        reply_markup=main_keyboard(),
    )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    if not settings.bot_token:

        raise RuntimeError(
            "BOT_TOKEN belum diisi di .env"
        )

    bot = Bot(
        token=settings.bot_token
    )

    dp = Dispatcher()

    # ========================================================
    # COMMANDS
    # ========================================================

    dp.message.register(
        start,
        CommandStart(),
    )

    dp.message.register(
        cancel,
        Command("cancel"),
    )

    # ========================================================
    # ACCOUNT
    # ========================================================

    dp.message.register(
        account_button,
        F.text == "👤 Akun Telegram",
    )

    # ========================================================
    # GROUP
    # ========================================================

    dp.message.register(
        group_button,
        F.text == "👥 Grup",
    )

    # ========================================================
    # MESSAGE
    # ========================================================

    dp.message.register(
        message_button,
        F.text == "💬 Pesan",
    )

    # ========================================================
    # ACCOUNT CALLBACKS
    # ========================================================

    dp.callback_query.register(
        start_connect,
        F.data == "connect_account",
    )

    dp.callback_query.register(
        check_qr_login,
        F.data == "check_qr_login",
    )

    dp.callback_query.register(
        refresh_accounts,
        F.data == "refresh_accounts",
    )

    # ========================================================
    # GROUP CALLBACKS
    # ========================================================

    dp.callback_query.register(
        start_add_group,
        F.data == "add_group",
    )

    dp.callback_query.register(
        refresh_groups,
        F.data == "refresh_groups",
    )

    dp.callback_query.register(
        show_available_groups,
        F.data.startswith(
            "group_account:"
        ),
    )

    dp.callback_query.register(
        import_selected_group,
        F.data.startswith(
            "group_import:"
        ),
    )

    # ========================================================
    # MESSAGE CALLBACKS
    # ========================================================

    dp.callback_query.register(
        start_add_message,
        F.data == "add_message",
    )

    dp.callback_query.register(
        refresh_messages,
        F.data == "refresh_messages",
    )

    # ========================================================
    # TELEGRAM ACCOUNT FSM
    # ========================================================

    # QR flow no longer asks users to send login codes to the bot.
    dp.message.register(
        receive_password,
        TelegramConnectState.password,
    )

    # ========================================================
    # MESSAGE FSM
    # ========================================================

    dp.message.register(
        receive_message_title,
        MessageState.title,
    )

    dp.message.register(
        receive_message_content,
        MessageState.content,
    )

    # ========================================================
    # PLACEHOLDER MENU
    # ========================================================

    dp.message.register(
        placeholder,
        F.text.in_(
            {
                "📢 Auto Post",
                "📦 Paket",
                "📊 Statistik",
                "⚙️ Pengaturan",
            }
        ),
    )

    logger.info(
        "Telegram Auto Post bot starting..."
    )

    try:

        await dp.start_polling(
            bot
        )

    finally:

        await bot.session.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())