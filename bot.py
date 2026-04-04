"""
24PEX USERBOT - Automated Telegram Signal Messenger
Features:
  - 6 daily signal messages at Nigeria time (WAT = UTC+1)
  - Group lock/unlock around each signal window
  - Night lock 4:00 PM → Morning unlock 5:00 AM
  - Professor Lecture Messages (5 random msgs per session, 4-min gaps)
"""

import asyncio
import logging
import os
import random
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import EditChatDefaultBannedRightsRequest
from telethon.tl.types import ChatBannedRights

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

# ── Load professor lecture message pool ─────────────────────────────────────
def load_message_pool() -> list[str]:
    pool_file = Path(__file__).parent / "messages.txt"
    if not pool_file.exists():
        logger.warning("messages.txt not found — professor lecture disabled")
        return []
    raw = pool_file.read_text(encoding="utf-8")
    # Split on blank lines, strip each paragraph, filter empties and headers
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    # Remove short lines that look like section headers (< 30 chars, no spaces mid-line)
    messages = [p for p in paragraphs if len(p) > 40]
    logger.info(f"Loaded {len(messages)} professor lecture messages from pool")
    return messages

MESSAGE_POOL: list[str] = []

# ── Signal messages ─────────────────────────────────────────────────────────
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


# ── HTTP health-check server (required by Render) ───────────────────────────
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
    logger.info(f"Health server on port {port}")
    server.serve_forever()


# ── Main bot ─────────────────────────────────────────────────────────────────
async def main():
    global MESSAGE_POOL
    MESSAGE_POOL = load_message_pool()

    threading.Thread(target=start_health_server, daemon=True).start()

    if SESSION_STRING:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    else:
        client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username})")

    logger.info("Loading dialogs …")
    async for _ in client.iter_dialogs():
        pass
    logger.info("Dialogs loaded.")

    # ── Helpers ──────────────────────────────────────────────────────────────
    async def get_entities():
        entities = []
        for group in GROUP_IDS:
            try:
                gid = int(group) if group.lstrip('-').isdigit() else group
                entities.append(await client.get_entity(gid))
            except Exception as e:
                logger.error(f"Could not get entity for {group}: {e}")
        return entities

    async def send_to_all(label: str, message: str):
        now = datetime.now(NIGERIA_TZ).strftime("%H:%M:%S WAT")
        logger.info(f"[{label}] Sending at {now}")
        for group in GROUP_IDS:
            try:
                gid = int(group) if group.lstrip('-').isdigit() else group
                entity = await client.get_entity(gid)
                await client.send_message(entity, message, parse_mode="md")
                logger.info(f"[{label}] ✓ {group}")
            except Exception as e:
                logger.error(f"[{label}] ✗ {group}: {e}")
            await asyncio.sleep(1)

    async def set_group_lock(locked: bool):
        action = "LOCKING" if locked else "UNLOCKING"
        logger.info(f"{action} all groups …")
        for group in GROUP_IDS:
            try:
                gid = int(group) if group.lstrip('-').isdigit() else group
                entity = await client.get_entity(gid)
                await client(EditChatDefaultBannedRightsRequest(
                    peer=entity,
                    banned_rights=ChatBannedRights(
                        until_date=None,
                        send_messages=locked,
                        send_media=locked,
                        send_stickers=locked,
                        send_gifs=locked,
                        send_games=locked,
                        send_inline=locked,
                        embed_links=locked,
                    )
                ))
                logger.info(f"{'🔒' if locked else '🔓'} {group}")
            except Exception as e:
                logger.error(f"Lock/unlock failed for {group}: {e}")
            await asyncio.sleep(1)

    async def send_professor_lecture():
        if not MESSAGE_POOL:
            logger.warning("No messages in pool — skipping professor lecture")
            return
        msg = random.choice(MESSAGE_POOL)
        formatted = f"**📚 PROFESSOR LECTURE\n\n{msg}**"
        await send_to_all("PROFESSOR LECTURE", formatted)

    # ── Job factories ────────────────────────────────────────────────────────
    def lock_job():
        async def _():
            await set_group_lock(True)
        return _

    def unlock_job():
        async def _():
            await set_group_lock(False)
        return _

    def signal_job(label, message):
        async def _():
            await send_to_all(label, message)
        return _

    def lecture_job():
        async def _():
            await send_professor_lecture()
        return _

    # ── Schedule ─────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)

    jobs = [
        # Morning unlock
        (5,  0,  "morning_unlock",         unlock_job()),

        # ── First Basic Signal session ────────────────────────────────────
        (6, 20,  "lock_s1",                lock_job()),
        (6, 20,  "lecture_s1_1",           lecture_job()),
        (6, 24,  "lecture_s1_2",           lecture_job()),
        (6, 28,  "lecture_s1_3",           lecture_job()),
        (6, 32,  "lecture_s1_4",           lecture_job()),
        (6, 36,  "lecture_s1_5",           lecture_job()),
        (6, 50,  "signal_warning_1",       signal_job("First Basic Signal", MSG_0650)),
        (7,  0,  "signal_unlock_1",        signal_job("First Basic Signal", MSG_0700)),
        (7,  5,  "unlock_s1",              unlock_job()),

        # ── Second Basic Signal session ───────────────────────────────────
        (8, 20,  "lock_s2",                lock_job()),
        (8, 20,  "lecture_s2_1",           lecture_job()),
        (8, 24,  "lecture_s2_2",           lecture_job()),
        (8, 28,  "lecture_s2_3",           lecture_job()),
        (8, 32,  "lecture_s2_4",           lecture_job()),
        (8, 36,  "lecture_s2_5",           lecture_job()),
        (8, 50,  "signal_warning_2",       signal_job("Second Basic Signal", MSG_0850)),
        (9,  0,  "signal_unlock_2",        signal_job("Second Basic Signal", MSG_0900)),
        (9,  5,  "unlock_s2",              unlock_job()),

        # ── Bonus Signal session ──────────────────────────────────────────
        (12, 20, "lock_s3",                lock_job()),
        (12, 20, "lecture_s3_1",           lecture_job()),
        (12, 24, "lecture_s3_2",           lecture_job()),
        (12, 28, "lecture_s3_3",           lecture_job()),
        (12, 32, "lecture_s3_4",           lecture_job()),
        (12, 36, "lecture_s3_5",           lecture_job()),
        (12, 50, "signal_warning_3",       signal_job("Bonus Signal", MSG_1250)),
        (13,  0, "signal_unlock_3",        signal_job("Bonus Signal", MSG_1300)),
        (13,  5, "unlock_s3",              unlock_job()),

        # Night lock
        (16,  0, "night_lock",             lock_job()),
    ]

    for hour, minute, job_id, coro_factory in jobs:
        scheduler.add_job(
            coro_factory,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=job_id,
        )
        logger.info(f"Scheduled [{job_id}] at {hour:02d}:{minute:02d} WAT")

    scheduler.start()
    logger.info("✅ Scheduler running. Bot is live!")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
