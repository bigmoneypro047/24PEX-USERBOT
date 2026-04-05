"""
24PEX USERBOT - Automated Telegram Signal Messenger

Features:
  - 6 daily signal messages at Nigeria time (WAT = UTC+1)
  - Group lock/unlock around each signal window
  - Night lock 4:00 PM → Morning unlock 5:00 AM
  - Professor Lecture Messages: 5 per session, 4-min gaps
  - Smart message rotation:
      * 7 topics, rotate every 3rd topic across sessions
      * Same topic never repeats within 48 hours (cycles every 7 sessions ≈ 50 hrs)
      * Same message never repeats within 90 days (date-based deterministic selection)
  - Self keep-alive ping every 14 minutes (prevents Render sleep)
"""

import asyncio
import logging
import os
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import urlopen

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

# ── Credentials & config ─────────────────────────────────────────────────────
API_ID       = int(os.environ.get("TELEGRAM_API_ID",  "36539152"))
API_HASH     = os.environ.get("TELEGRAM_API_HASH",    "bf6c8f3ce3171efad7c80d2f72176f23")
SESSION_NAME = os.environ.get("SESSION_NAME",          "24pex_userbot")
# Load session: prefer saved file (survives restarts), then env var
_SESSION_FILE = os.path.join(os.path.dirname(__file__), ".session_string")
if os.path.exists(_SESSION_FILE):
    with open(_SESSION_FILE) as _sf:
        SESSION_STRING = _sf.read().strip()
else:
    SESSION_STRING = os.environ.get("SESSION_STRING", "")
RAW_GROUPS      = os.environ.get("TELEGRAM_GROUP_IDS", "-1003778567819,-1003632439896,-5292682098")
GROUP_IDS       = [g.strip() for g in RAW_GROUPS.split(",") if g.strip()]
INDONESIAN_GROUP = os.environ.get("INDONESIAN_GROUP_ID", "-5292682098")  # messages translated to Indonesian
RENDER_URL   = os.environ.get("RENDER_EXTERNAL_URL",  "")   # set automatically by Render

NIGERIA_TZ   = pytz.timezone("Africa/Lagos")

# Epoch for deterministic session counting (do not change after deployment)
START_DATE   = date(2025, 4, 4)

# ── Topic rotation ───────────────────────────────────────────────────────────
# 7 topics in the message pool; rotation steps by 3 each session:
#   0 → 3 → 6 → 2 → 5 → 1 → 4 → 0 → ...  (period = 7 sessions ≈ 50 hours)
# This guarantees the same topic is never reused within 48 hours.
TOPIC_ROTATION = [0, 3, 6, 2, 5, 1, 4]

# ── Message pool ─────────────────────────────────────────────────────────────
# messages_by_topic[i] = list of message strings for topic i
messages_by_topic: list[list[str]] = []

TOPIC_HEADERS = [
    "TEAM BENEFITS",
    "REWARDS",
    "MONTHLY REBATE",
    "FASTER CAPITAL DOUBLING",
    "TEAM COMMISSIONS REWARDS",
    "TEAM LEADERS REWARDS",
    "PLATFORM AWARENESS AND SAFETY",
]

def load_message_pool() -> list[list[str]]:
    # Search in bot dir, workspace root, and attached_assets
    candidates = [
        Path(__file__).parent / "messages.txt",
        Path(__file__).parent / "attached_assets" / "final_message_pool_2_1775276105326.txt",
    ]
    pool_file = next((p for p in candidates if p.exists()), None)
    if pool_file is None:
        logger.warning("messages.txt not found — professor lectures disabled")
        return [[] for _ in TOPIC_HEADERS]

    raw = pool_file.read_text(encoding="utf-8")
    lines = raw.splitlines()

    # Split into topics by ALL-CAPS header lines
    topic_buckets: list[list[str]] = [[] for _ in TOPIC_HEADERS]
    current_topic = 0
    current_block: list[str] = []

    def flush_block():
        text = " ".join(current_block).strip()
        # Minimum length to be a real message
        if len(text) > 60:
            topic_buckets[current_topic].append(text)
        current_block.clear()

    for line in lines:
        stripped = line.strip()

        # Detect topic header
        if stripped in TOPIC_HEADERS:
            flush_block()
            current_topic = TOPIC_HEADERS.index(stripped)
            continue

        if stripped == "":
            # Blank line = paragraph break
            flush_block()
        else:
            current_block.append(stripped)

    flush_block()

    for i, h in enumerate(TOPIC_HEADERS):
        logger.info(f"Topic [{h}]: {len(topic_buckets[i])} messages loaded")

    return topic_buckets


def get_session_number(session_idx: int) -> int:
    """
    Calculate a global, deterministic session counter.
    session_idx: 0 = 6:20 session, 1 = 8:20 session, 2 = 12:20 session
    """
    today  = datetime.now(NIGERIA_TZ).date()
    days   = (today - START_DATE).days
    return max(0, days) * 3 + session_idx


def pick_messages_for_session(session_num: int) -> list[str]:
    """
    Return 5 unique messages for the session.
    - Topic is determined by rotating every 3rd through 7 topics.
    - Messages advance sequentially within the topic so no message
      repeats until the entire topic pool is exhausted (90+ days).
    """
    if not any(messages_by_topic):
        return []

    topic_slot  = session_num % 7
    topic_idx   = TOPIC_ROTATION[topic_slot]
    pool        = messages_by_topic[topic_idx]

    if not pool:
        return []

    # Which "round" for this topic (how many times has this topic been used)
    topic_round = session_num // 7
    base        = (topic_round * 5) % len(pool)

    result = []
    for slot in range(5):
        result.append(pool[(base + slot) % len(pool)])

    logger.info(
        f"Session {session_num}: topic [{TOPIC_HEADERS[topic_idx]}] "
        f"msgs {base}–{(base+4) % len(pool)} (pool size {len(pool)})"
    )
    return result


# ── Pre-selected lecture messages (filled at session start) ──────────────────
_lecture_queue: dict[int, list[str]] = {}   # session_idx → [msg0..msg4]


# ── Signal messages ───────────────────────────────────────────────────────────
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


# ── HTTP health-check server (required by Render) ─────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"24PEX USERBOT is running")
    def log_message(self, *a):
        pass

def start_health_server():
    # Render sets PORT automatically; fall back to BOT_PORT or 9000
    port = int(os.environ.get("PORT", os.environ.get("BOT_PORT", 9000)))
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


# ── Self keep-alive ping (prevents container sleep) ───────────────────────────
async def keep_alive_loop():
    """Ping every 5 minutes to keep the container alive."""
    ping_url = RENDER_URL if RENDER_URL else "http://localhost:8080/healthz"
    logger.info(f"Keep-alive loop started — pinging {ping_url} every 5 minutes")
    while True:
        await asyncio.sleep(5 * 60)
        try:
            urlopen(ping_url, timeout=10)
            logger.info("Keep-alive ping ✓")
        except Exception as e:
            logger.warning(f"Keep-alive ping failed: {e}")


# ── Main bot ──────────────────────────────────────────────────────────────────
async def main():
    global messages_by_topic
    messages_by_topic = load_message_pool()

    threading.Thread(target=start_health_server, daemon=True).start()

    client = (
        TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        if SESSION_STRING else
        TelegramClient(SESSION_NAME, API_ID, API_HASH)
    )

    await client.start()
    me = await client.get_me()
    logger.info(f"Logged in as: {me.first_name} (@{me.username})")

    logger.info("Loading dialogs …")
    async for _ in client.iter_dialogs():
        pass
    logger.info("Dialogs loaded.")

    # Start keep-alive background task
    asyncio.create_task(keep_alive_loop())

    # ── Helpers ───────────────────────────────────────────────────────────────
    def translate_to_indonesian(text: str) -> str:
        try:
            from deep_translator import GoogleTranslator
            return GoogleTranslator(source="en", target="id").translate(text)
        except Exception as e:
            logger.warning(f"Translation failed, sending English: {e}")
            return text

    async def send_to_all(label: str, message: str):
        now = datetime.now(NIGERIA_TZ).strftime("%H:%M:%S WAT")
        logger.info(f"[{label}] Sending at {now}")
        for group in GROUP_IDS:
            try:
                gid = int(group) if group.lstrip('-').isdigit() else group
                entity = await client.get_entity(gid)
                if str(group) == str(INDONESIAN_GROUP):
                    msg = translate_to_indonesian(message)
                    logger.info(f"[{label}] 🇮🇩 Translated for {group}")
                else:
                    msg = message
                await client.send_message(entity, msg, parse_mode="md")
                logger.info(f"[{label}] ✓ {group}")
            except Exception as e:
                logger.error(f"[{label}] ✗ {group}: {e}")
            await asyncio.sleep(1)

    async def set_lock(locked: bool):
        label = "🔒 LOCKING" if locked else "🔓 UNLOCKING"
        logger.info(f"{label} groups …")
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
                logger.info(f"  {'🔒' if locked else '🔓'} {group}")
            except Exception as e:
                logger.error(f"  Lock/unlock failed for {group}: {e}")
            await asyncio.sleep(1)

    # ── Job factories ──────────────────────────────────────────────────────────
    def lock_job():
        async def _(): await set_lock(True)
        return _

    def unlock_job():
        async def _(): await set_lock(False)
        return _

    def signal_job(label, message):
        async def _(): await send_to_all(label, message)
        return _

    def prep_lecture_job(session_idx: int):
        """Pre-select today's 5 lecture messages at session start (6:20 / 8:20 / 12:20)."""
        async def _():
            session_num = get_session_number(session_idx)
            msgs = pick_messages_for_session(session_num)
            _lecture_queue[session_idx] = msgs
            logger.info(f"Professor lecture queue loaded for session {session_idx}: {len(msgs)} messages")
        return _

    def lecture_job(session_idx: int, slot: int):
        """Send the pre-selected lecture message for this slot."""
        async def _():
            msgs = _lecture_queue.get(session_idx, [])
            if not msgs:
                # Fallback: load now if prep job was missed
                session_num = get_session_number(session_idx)
                msgs = pick_messages_for_session(session_num)
                _lecture_queue[session_idx] = msgs

            if slot < len(msgs):
                text = f"**{msgs[slot]}**"
                await send_to_all("Lecture", text)
            else:
                logger.warning(f"No lecture message for session {session_idx} slot {slot}")
        return _

    # ── Schedule ───────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone=NIGERIA_TZ)

    jobs = [
        # Morning unlock
        ( 5,  0, "morning_unlock",    unlock_job()),

        # ── First Basic Signal ─────────────────────────────────────────────
        ( 6, 20, "lock_s1",           lock_job()),
        ( 6, 20, "prep_lecture_s1",   prep_lecture_job(0)),
        ( 6, 20, "lecture_s1_1",      lecture_job(0, 0)),
        ( 6, 24, "lecture_s1_2",      lecture_job(0, 1)),
        ( 6, 28, "lecture_s1_3",      lecture_job(0, 2)),
        ( 6, 32, "lecture_s1_4",      lecture_job(0, 3)),
        ( 6, 36, "lecture_s1_5",      lecture_job(0, 4)),
        ( 6, 50, "warning_s1",        signal_job("First Basic Signal",  MSG_0650)),
        ( 7,  0, "signal_s1",         signal_job("First Basic Signal",  MSG_0700)),
        ( 7,  5, "unlock_s1",         unlock_job()),

        # ── Second Basic Signal ────────────────────────────────────────────
        ( 8, 20, "lock_s2",           lock_job()),
        ( 8, 20, "prep_lecture_s2",   prep_lecture_job(1)),
        ( 8, 20, "lecture_s2_1",      lecture_job(1, 0)),
        ( 8, 24, "lecture_s2_2",      lecture_job(1, 1)),
        ( 8, 28, "lecture_s2_3",      lecture_job(1, 2)),
        ( 8, 32, "lecture_s2_4",      lecture_job(1, 3)),
        ( 8, 36, "lecture_s2_5",      lecture_job(1, 4)),
        ( 8, 50, "warning_s2",        signal_job("Second Basic Signal", MSG_0850)),
        ( 9,  0, "signal_s2",         signal_job("Second Basic Signal", MSG_0900)),
        ( 9,  5, "unlock_s2",         unlock_job()),

        # ── Bonus Signal ───────────────────────────────────────────────────
        (12, 20, "lock_s3",           lock_job()),
        (12, 20, "prep_lecture_s3",   prep_lecture_job(2)),
        (12, 20, "lecture_s3_1",      lecture_job(2, 0)),
        (12, 24, "lecture_s3_2",      lecture_job(2, 1)),
        (12, 28, "lecture_s3_3",      lecture_job(2, 2)),
        (12, 32, "lecture_s3_4",      lecture_job(2, 3)),
        (12, 36, "lecture_s3_5",      lecture_job(2, 4)),
        (12, 50, "warning_s3",        signal_job("Bonus Signal",        MSG_1250)),
        (13,  0, "signal_s3",         signal_job("Bonus Signal",        MSG_1300)),
        (13,  5, "unlock_s3",         unlock_job()),

        # Night lock
        (16,  0, "night_lock",        lock_job()),
    ]

    for hour, minute, job_id, coro_factory in jobs:
        scheduler.add_job(
            coro_factory,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=job_id,
        )

    # ── Startup: apply correct lock state immediately ──────────────────────────
    # If the bot restarts mid-window it would miss a lock/unlock job.
    # Check current WAT time and enforce the right state right now.
    async def apply_startup_lock_state():
        now_wat  = datetime.now(NIGERIA_TZ)
        minutes  = now_wat.hour * 60 + now_wat.minute
        # Lock windows (start_min, end_min): time >= start AND time < end
        # Night window crosses midnight: handle separately
        night_lock  = (minutes >= 16 * 60) or (minutes < 5 * 60)   # 4 PM – 5 AM
        signal_lock = (6 * 60 + 20 <= minutes < 7 * 60 + 5) or \
                      (8 * 60 + 20 <= minutes < 9 * 60 + 5) or \
                      (12 * 60 + 20 <= minutes < 13 * 60 + 5)
        should_lock = night_lock or signal_lock
        state_label = "🔒 LOCKED (startup enforcement)" if should_lock else "🔓 UNLOCKED (startup enforcement)"
        logger.info(f"Startup state check at {now_wat.strftime('%H:%M WAT')} → {state_label}")
        await set_lock(should_lock)

    await apply_startup_lock_state()

    scheduler.start()
    logger.info(f"✅ Scheduler running — {len(jobs)} jobs scheduled. Bot is live!")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
