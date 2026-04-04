"""
24PEX USERBOT - Automated Telegram Signal Messenger
Sends scheduled trading signal messages to 3 Telegram groups 6x per day
Nigeria Time (WAT = UTC+1)
"""

import asyncio
import logging
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ── Telegram credentials ────────────────────────────────────────────────────
API_ID = int(os.environ.get("TELEGRAM_API_ID", "33221652"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "411e8d91d21982395e94134d8f444954")
SESSION_NAME = os.environ.get("SESSION_NAME", "24pex_userbot")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

RAW_GROUPS = os.environ.get("TELEGRAM_GROUP_IDS", "-5054733988,-5231385589,-5152295937")
GROUP_IDS = [g.strip() for g in RAW_GROUPS.split(",") if g.strip()]

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

SCHEDULE = [
    (6,  50, "First Basic Signal",  MSG_0650),
    (7,   0, "First Basic Signal",  MSG_0700),
    (8,  50, "Second Basic Signal", MSG_0850),
    (9,   0, "Second Basic Signal", MSG_0900),
    (12, 50, "Bonus Signal",        MSG_1250),
    (13,  0, "Bonus Signal",        MSG_1300),
]


# ── Simple HTTP health-check server (required by Render) ───────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"24PEX USERBOT is running")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info(f"Health server listening on port {port}")
    server.serve_forever()


# ── Bot logic ───────────────────────────────────────────────────────────────
async def main():
    # Start health server in background thread
    thread = threading.Thread(target=start_health_server, daemon=True)
    thread.start()

    # Create client inside the async function so the event loop exists
    if SESSION_STRING:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    else:
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    logger.info("Starting 24PEX USERBOT …")
    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username})")

    # Load dialogs so group entities can be resolved by ID
    logger.info("Loading dialogs …")
    async for _ in client.iter_dialogs():
        pass
    logger.info("Dialogs loaded.")

    async def send_to_all_groups(session_name: str, message: str):
        now = datetime.now(NIGERIA_TZ).strftime("%Y-%m-%d %H:%M:%S WAT")
        logger.info(f"[{session_name}] Sending at {now} to {len(GROUP_IDS)} group(s)")
        for group in GROUP_IDS:
            try:
                entity = await client.get_entity(
                    int(group) if group.lstrip('-').isdigit() else group
                )
                await client.send_message(entity, message, parse_mode="md")
                logger.info(f"[{session_name}] ✓ Sent to {group}")
            except Exception as exc:
                logger.error(f"[{session_name}] ✗ Failed to send to {group}: {exc}")
            await asyncio.sleep(1)

    def make_job(session_name: str, message: str):
        async def job():
            await send_to_all_groups(session_name, message)
        return job

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
    logger.info("Scheduler running. Bot is live!")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
