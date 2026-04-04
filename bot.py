"""
24PEX USERBOT - Automated Telegram Signal Messenger
Sends scheduled trading signal messages to 3 Telegram groups 6x per day
Nigeria Time (WAT = UTC+1)
"""

import asyncio
import base64
import logging
import os
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

# ── Telegram credentials ────────────────────────────────────────────────────
API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_NAME = os.environ.get("SESSION_NAME", "24pex_userbot")

# Restore session from base64 env var (used on Render / cloud deployments)
SESSION_STRING = os.environ.get("SESSION_STRING", "")
if SESSION_STRING:
    session_path = f"{SESSION_NAME}.session"
    if not os.path.exists(session_path):
        logger.info("Restoring session from SESSION_STRING environment variable …")
        with open(session_path, "wb") as f:
            f.write(base64.b64decode(SESSION_STRING))

# Comma-separated group usernames or IDs, e.g. "@mygroup1,@mygroup2,-1001234567890"
RAW_GROUPS = os.environ["TELEGRAM_GROUP_IDS"]
GROUP_IDS = [g.strip() for g in RAW_GROUPS.split(",") if g.strip()]

# Nigeria Time = UTC+1
NIGERIA_TZ = pytz.timezone("Africa/Lagos")

# ── Messages ────────────────────────────────────────────────────────────────
MSG_0650 = (
    "**🚨🚨🚨🚨 The first trading signal will be released in 10 minutes, "
    "be prepared not to miss an order because there is no compensation for "
    "missed signals, always be ready to execute trades**"
)

MSG_0700 = (
    "**The first signal invitation code has been successfully unlocked.\n"
    "Follow the instructions below to execute the trade.\n"
    "Open the 24PEX platform and complete the invitation trade order, "
    "copy the trade, and execute it.\n"
    "🚫🚫🚫Please note: All members are strictly prohibited from conducting "
    "personal trading at any time!**"
)

MSG_0850 = (
    "**🚨🚨🚨🚨 The second signal of today will be released in 10 minutes, "
    "be prepared not to miss an order because there is no compensation for "
    "missed signals, always be ready to execute the trade**"
)

MSG_0900 = (
    "**The second signal invitation code has been successfully unlocked.\n"
    "Follow the instructions below to execute the trade.\n"
    "Open the 24PEX platform and complete the invitation trade order, "
    "copy the trade, and execute it.\n"
    "🚫🚫🚫Please note: All members are strictly prohibited from conducting "
    "personal trading at any time!**"
)

MSG_1250 = (
    "**Get ready to execute the bonus signal, order processing the bonus signal "
    "will be released within 10 minutes, be prepared not to miss it, there is no "
    "compensation for missed signals.**"
)

MSG_1300 = (
    "**Bonus signal invitation code has been successfully unlocked.\n"
    "Follow the instructions below to execute the trade.\n"
    "Open the 24PEX platform and complete the invitation trade order, "
    "copy the trade, and execute it.\n"
    "🚫🚫🚫Please note: All members are strictly prohibited from conducting "
    "personal trading at any time!**"
)

# Schedule: (hour WAT, minute WAT, session_name, message)
SCHEDULE = [
    (6,  50, "First Basic Signal",  MSG_0650),
    (7,   0, "First Basic Signal",  MSG_0700),
    (8,  50, "Second Basic Signal", MSG_0850),
    (9,   0, "Second Basic Signal", MSG_0900),
    (12, 50, "Bonus Signal",        MSG_1250),
    (13,  0, "Bonus Signal",        MSG_1300),
]

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)


async def send_to_all_groups(session_name: str, message: str):
    """Send a message to all configured Telegram groups."""
    now = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d %H:%M:%S WAT")
    logger.info(f"[{session_name}] Sending at {now} to {len(GROUP_IDS)} group(s)")

    for group in GROUP_IDS:
        try:
            entity = await client.get_entity(group)
            await client.send_message(entity, message, parse_mode="md")
            logger.info(f"[{session_name}] ✓ Sent to {group}")
        except Exception as exc:
            logger.error(f"[{session_name}] ✗ Failed to send to {group}: {exc}")

        await asyncio.sleep(1)  # small delay between groups


def make_job(session_name: str, message: str):
    """Return a coroutine factory for the scheduler."""
    async def job():
        await send_to_all_groups(session_name, message)
    return job


async def main():
    logger.info("Starting 24PEX USERBOT …")
    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username})")

    scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)

    for hour, minute, session_name, message in SCHEDULE:
        scheduler.add_job(
            make_job(session_name, message),
            trigger="cron",
            hour=hour,
            minute=minute,
            id=f"job_{hour:02d}{minute:02d}_{session_name.replace(' ', '_')}",
            name=f"{session_name} @ {hour:02d}:{minute:02d}",
        )
        logger.info(f"Scheduled [{session_name}] at {hour:02d}:{minute:02d} WAT")

    scheduler.start()
    logger.info("Scheduler started. Bot is running …")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
