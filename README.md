# Telegram Auto Post SaaS

Fondasi SaaS untuk mengelola jadwal pengiriman pesan Telegram menggunakan FastAPI, aiogram, Telethon, PostgreSQL, Redis, Scheduler, dan Worker.

## Stack
- Python 3.12
- FastAPI
- aiogram
- Telethon
- SQLAlchemy + asyncpg
- PostgreSQL
- Redis
- Alembic
- Docker Compose

## Services
- `api`: REST API dan health check
- `bot`: antarmuka Telegram Bot
- `scheduler`: mencari job yang sudah jatuh tempo dan memasukkannya ke Redis queue
- `worker`: memproses job dan mengirim pesan melalui session Telegram yang terhubung
- `postgres`: data aplikasi
- `redis`: queue, state sementara, dan lock

## Local setup
1. Install Docker Desktop dengan backend WSL 2.
2. Buat file lokal `.env` dari `.env.example`.
3. Isi konfigurasi lokal yang diperlukan. Jangan commit file `.env` atau kredensial.
4. Jalankan `docker compose up -d --build`.
5. Cek kesehatan API di `http://localhost:8000/health`.
6. Jalankan migration: `docker compose exec -w /app api alembic -c /app/alembic.ini upgrade head`.

## Menghubungkan akun Telegram
Aplikasi menggunakan alur QR/deep-link login Telegram untuk menghindari meminta pengguna mengirim kode login ke chat bot. Pengguna harus memulai proses sendiri dan menyetujui login hanya jika mereka mengenali proses tersebut.

- Login berbasis pengiriman kode OTP melalui bot dinonaktifkan.
- Session Telegram disimpan dalam bentuk terenkripsi menggunakan `SESSION_ENCRYPTION_KEY`.
- Password 2FA hanya digunakan untuk menyelesaikan otorisasi yang dimulai pengguna; kode atau password tidak boleh dicatat di log. Bot mencoba menghapus pesan password sesegera mungkin, tetapi untuk deployment SaaS produksi sebaiknya alur password dipindahkan ke halaman HTTPS khusus.
- Jangan membagikan OTP, password, session string, bot token, atau Telegram API hash.

Buat kunci enkripsi Fernet dengan:
```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Masukkan hasilnya sebagai nilai `SESSION_ENCRYPTION_KEY` di `.env` lokal. Jangan ganti kunci setelah session terenkripsi disimpan kecuali semua session akan dihubungkan ulang.

## Data dan backup
Source code GitHub tidak mencadangkan volume PostgreSQL atau Redis. Buat backup database terpisah secara berkala. Jangan commit SQL dump, database volume, session Telegram, atau data pengguna ke repository.
