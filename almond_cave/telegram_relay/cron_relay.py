# -*- coding: utf-8 -*-
"""
almond_cave/telegram_relay/cron_relay.py
----------------------------------------
Stateless/Git-backed Telegram News Relay runner for GitHub Actions (5-min cron).
Reuses the EXACT same filter, sanitizer, Pass 2/3, and 4,000-char splitter from relay_bot.py,
and deduplicates against recent DEST messages so local real-time relay_bot.py and GitHub cron
never double-post.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from telethon.tl.types import MessageMediaWebPage
from almond_cave.telegram_relay.relay_bot import (
    client,
    SOURCE_CHAT_ID,
    DEST_CHAT_ID,
    OFFICIAL_SENDERS,
    PASS2_STATUS_BLOCKED,
    BOT_TOKEN,
    msg_map,
    get_message_full_text,
    is_worthy_news_item,
    _send_via_bot_status,
    _relay_text_message,
    handle_new_message,
)
from almond_cave.channel_tracker import record_channel_mentions, record_channel_143_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cron_relay")

STATE_FILE = Path(__file__).resolve().parent / "relay_state.json"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return {
                "last_src_id": int(data.get("last_src_id", 0)),
                "msg_map": {int(k): int(v) for k, v in (data.get("msg_map") or {}).items()},
            }
        except Exception as e:
            logger.warning(f"Failed to read state file: {e}")
    return {"last_src_id": 0, "msg_map": {}}


def save_state(last_src_id: int, cur_map: dict):
    # Keep only the most recent 200 mappings to keep state compact
    sorted_keys = sorted(cur_map.keys())[-200:]
    compact_map = {str(k): cur_map[k] for k in sorted_keys}
    STATE_FILE.write_text(
        json.dumps({"last_src_id": last_src_id, "msg_map": compact_map}, indent=2),
        encoding="utf-8",
    )


async def run_cron_cycle(loop_count: int = 1, interval_sec: int = 60):
    state = load_state()
    last_src_id = state["last_src_id"]
    msg_map.update(state["msg_map"])

    try:
        client.remove_event_handler(handle_new_message)
    except Exception:
        pass

    await client.connect()
    if not await client.is_user_authorized():
        logger.error("❌ Telethon session is not authorized. Check TELEGRAM_STRING_SESSION.")
        return

    temp_dir = Path(__file__).resolve().parent / "temp_media"
    temp_dir.mkdir(exist_ok=True)
    max_seen_id = last_src_id
    total_relayed = 0

    for iteration in range(max(1, loop_count)):
        if not client.is_connected():
            await client.connect()
        # Fetch recent DEST messages for deduplication against local real-time relay
        dest_texts = []
        async for dm in client.iter_messages(DEST_CHAT_ID, limit=60):
            txt = get_message_full_text(dm) or ""
            if txt:
                dest_texts.append(txt)

        # Fetch new SOURCE messages since max_seen_id
        new_msgs = []
        if max_seen_id > 0:
            async for m in client.iter_messages(SOURCE_CHAT_ID, min_id=max_seen_id, limit=100):
                new_msgs.append(m)
        else:
            async for m in client.iter_messages(SOURCE_CHAT_ID, limit=15):
                new_msgs.append(m)

        if new_msgs:
            new_msgs.reverse()  # chronological order
            for m in new_msgs:
                if m.id > max_seen_id:
                    max_seen_id = m.id

                if m.sender_id not in OFFICIAL_SENDERS:
                    continue

                raw_text = get_message_full_text(m)
                is_wp = isinstance(getattr(m, "media", None), MessageMediaWebPage)
                has_media = bool(m.media) and not is_wp

                parent_sender_id = None
                is_parent_official = False
                parent_src_id = None
                if m.reply_to and hasattr(m.reply_to, "reply_to_msg_id"):
                    parent_src_id = m.reply_to.reply_to_msg_id
                    try:
                        pm = await m.get_reply_message()
                        if pm:
                            parent_sender_id = pm.sender_id
                            is_parent_official = parent_sender_id in OFFICIAL_SENDERS
                    except Exception:
                        pass

                is_ok, reason, cleaned_text = is_worthy_news_item(
                    raw_text, has_media=has_media, parent_sender_id=parent_sender_id, is_parent_channel=is_parent_official
                )
                if not is_ok:
                    logger.info(f"🚫 [Filter Skip] SRC {m.id}")
                    continue

                # Deduplicate against DEST messages (use 65-char probe so generic openings don't collide)
                lines = [ln.strip() for ln in (cleaned_text or "").splitlines() if len(ln.strip()) >= 12]
                probe = lines[0][:65] if lines else (cleaned_text or "")[:65]
                if probe and any(probe in dt for dt in dest_texts):
                    logger.info(f"⏭️ [Dedup Skip] SRC {m.id}")
                    continue

                reply_to_id = msg_map.get(parent_src_id) if parent_src_id else None
                dest_msg_id = None
                pass2_blocked = False

                if has_media:
                    file_path = await m.download_media(file=str(temp_dir))
                    if file_path:
                        try:
                            cap = cleaned_text if len(cleaned_text or "") <= 1020 else ""
                            send_status, dest_msg_id = _send_via_bot_status(
                                media_path=file_path,
                                caption=cap,
                                reply_to_message_id=reply_to_id,
                            )
                            if send_status == PASS2_STATUS_BLOCKED:
                                pass2_blocked = True
                            elif not dest_msg_id:
                                sent = await client.send_file(DEST_CHAT_ID, file_path, caption=cap, reply_to=reply_to_id)
                                dest_msg_id = getattr(sent, "id", None)
                            if not pass2_blocked and dest_msg_id and cleaned_text and not cap:
                                await asyncio.sleep(0.5)
                                await _relay_text_message(cleaned_text, dest_msg_id)
                        finally:
                            try:
                                os.remove(file_path)
                            except Exception:
                                pass
                    elif cleaned_text:
                        pass2_blocked, dest_msg_id = await _relay_text_message(cleaned_text, reply_to_id)
                elif cleaned_text:
                    pass2_blocked, dest_msg_id = await _relay_text_message(cleaned_text, reply_to_id)

                if pass2_blocked:
                    logger.warning(f"🚨 [Pass 2 Abort] SRC {m.id}")
                    continue

                if dest_msg_id:
                    msg_map[m.id] = dest_msg_id
                    if cleaned_text:
                        dest_texts.append(cleaned_text)
                    total_relayed += 1
                    logger.info(f"✅ [Cron Relay] SRC {m.id} -> DEST {dest_msg_id}")
                    try:
                        if cleaned_text:
                            record_channel_mentions(cleaned_text, source="channel_143")
                            record_channel_143_message(cleaned_text, msg_id=dest_msg_id)
                    except Exception:
                        pass
                    await asyncio.sleep(1.0)

        save_state(max_seen_id, msg_map)
        if iteration < loop_count - 1:
            await asyncio.sleep(interval_sec)

    logger.info(f"🏁 Cron Relay finished: seen_up_to={max_seen_id}, relayed={total_relayed}")
    await client.disconnect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", type=int, default=1)
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    asyncio.run(run_cron_cycle(loop_count=args.loop, interval_sec=args.interval))
