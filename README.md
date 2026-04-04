# 24PEX USERBOT

Automated Telegram userbot that sends 24PEX trading signal messages to 3 groups **6 times per day** on Nigeria Time (WAT, UTC+1).

## Schedule

| Time (WAT) | Session Name | Message |
|---|---|---|
| 06:50 AM | First Basic Signal | Warning: signal in 10 minutes |
| 07:00 AM | First Basic Signal | First signal unlocked |
| 08:50 AM | Second Basic Signal | Warning: signal in 10 minutes |
| 09:00 AM | Second Basic Signal | Second signal unlocked |
| 12:50 PM | Bonus Signal | Warning: bonus signal in 10 minutes |
| 01:00 PM | Bonus Signal | Bonus signal unlocked |

## Setup

### 1. Get Telegram API Credentials

1. Go to [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Log in with your Telegram account
3. Create a new application
4. Copy your **API ID** and **API Hash**

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
SESSION_NAME=24pex_userbot
TELEGRAM_GROUP_IDS=@group1,@group2,@group3
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. First Run (Generate Session)

Run the bot once locally to authenticate:

```bash
python bot.py
```

It will prompt you for your phone number and the verification code. After that, a `.session` file is created. **Keep this file safe — it is your login.**

### 5. Deploy to Render

See [RENDER_DEPLOY.md](RENDER_DEPLOY.md) for step-by-step Render deployment instructions.

## How It Works

- Uses **Telethon** (a Telegram MTProto client) to send messages as your user account
- Uses **APScheduler** to fire jobs at the exact times in Nigeria Time (WAT)
- Messages are formatted with Telegram **bold markdown** (`**text**`) so they appear large and bold
- All groups receive each message within seconds of each other

## Important Notes

- This is a **userbot** — it runs as your personal Telegram account, not a bot account
- Do **not** share your `.session` file or API credentials with anyone
- Keep the bot running 24/7 on a server (Render, Railway, VPS, etc.)
