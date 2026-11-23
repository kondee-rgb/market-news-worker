"""
almond_cave/telegram_notifier.py
--------------------------------
Module for sending notifications and Scout intelligence briefs to Telegram.
Uses Telegram Bot API (https://api.telegram.org/bot<TOKEN>/sendMessage).
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import requests

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telegram_notifier")


def load_env() -> None:
    """Load environment variables from .env file if available."""
    env_paths = [
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in env_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip('"').strip("'")
                            if key and key not in os.environ:
                                os.environ[key] = val
            except Exception as e:
                logger.warning(f"Failed to read env from {p}: {e}")
            break


# Load env immediately
load_env()


def get_telegram_credentials() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Retrieve Telegram Bot Token, User Chat ID, and Channel ID."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID", "")
    return token, chat_id, channel_id


def is_silent_night_hours() -> bool:
    """
    Check if current Bangkok time falls into the Silent Night Delivery window (01:00 - 07:00 AM).
    During these hours, Telegram messages and photos are sent silently without vibration or sound.
    """
    from datetime import datetime, timezone, timedelta
    if os.getenv("GITHUB_ACTIONS"):
        now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_bkk = datetime.now()
    return 1 <= now_bkk.hour < 7


def send_message(
    text: str,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    parse_mode: Optional[str] = "HTML",
    disable_notification: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Send a message via Telegram Bot API.

    :param text: Message text (supports HTML tags if parse_mode='HTML')
    :param chat_id: Target Chat ID (defaults to TELEGRAM_CHAT_ID from env)
    :param bot_token: Bot token (defaults to TELEGRAM_BOT_TOKEN from env)
    :param reply_to_message_id: Optional message ID to reply to (creates thread/comment)
    :param parse_mode: Formatting mode ('HTML', 'MarkdownV2', or None)
    :param disable_notification: Send silently without ringing/vibrating (defaults to auto 01:00-07:00 silent night)
    :return: Dict response from Telegram API
    """
    env_token, env_chat_id, _ = get_telegram_credentials()
    token = bot_token or env_token
    target_chat = chat_id or env_chat_id

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env")
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not set"}

    if not target_chat or target_chat == "YOUR_TELEGRAM_CHAT_ID_HERE":
        logger.error("Target chat ID is not configured")
        return {"ok": False, "description": "Chat ID not set"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": target_chat,
        "text": text,
        "disable_web_page_preview": False,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    # 🔕 Silent Night Delivery (01:00 - 07:00 AM Bangkok Time)
    is_silent = disable_notification if disable_notification is not None else is_silent_night_hours()
    if is_silent:
        payload["disable_notification"] = True

    try:
        response = requests.post(url, json=payload, timeout=15)
        res_data = response.json()
        if not res_data.get("ok"):
            logger.error(f"Telegram API error: {res_data.get('description')}")
        else:
            logger.info("Message sent successfully to Telegram")
        return res_data
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return {"ok": False, "description": str(e)}


def send_photo(
    photo: str,
    caption: Optional[str] = None,
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_to_message_id: Optional[int] = None,
    parse_mode: Optional[str] = "HTML",
    disable_notification: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Send a photo via Telegram Bot API (supports local file path or web URL).

    :param photo: Local file path or image URL
    :param caption: Photo caption (supports HTML if parse_mode='HTML')
    :param chat_id: Target Chat ID
    :param bot_token: Bot token
    :param reply_to_message_id: Optional message ID to reply to
    :param parse_mode: Formatting mode ('HTML', 'MarkdownV2', or None)
    :param disable_notification: Send silently without ringing/vibrating (defaults to auto 01:00-07:00 silent night)
    :return: Dict response from Telegram API
    """
    env_token, env_chat_id, _ = get_telegram_credentials()
    token = bot_token or env_token
    target_chat = chat_id or env_chat_id

    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("TELEGRAM_BOT_TOKEN is not configured in .env")
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN not set"}

    if not target_chat or target_chat == "YOUR_TELEGRAM_CHAT_ID_HERE":
        logger.error("Target chat ID is not configured")
        return {"ok": False, "description": "Chat ID not set"}

    # 🔕 Silent Night Delivery (01:00 - 07:00 AM Bangkok Time)
    is_silent = disable_notification if disable_notification is not None else is_silent_night_hours()

    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    # 1. Local file upload
    if os.path.exists(photo):
        try:
            with open(photo, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": target_chat}
                if caption:
                    data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode
                if reply_to_message_id:
                    data["reply_to_message_id"] = reply_to_message_id
                if is_silent:
                    data["disable_notification"] = "true"

                response = requests.post(url, data=data, files=files, timeout=25)
                res_data = response.json()
                if not res_data.get("ok"):
                    logger.error(f"Telegram sendPhoto error: {res_data.get('description')}")
                return res_data
        except Exception as e:
            logger.error(f"Failed to send local photo: {e}")
            return {"ok": False, "description": str(e)}

    # 2. Remote URL upload
    payload: Dict[str, Any] = {
        "chat_id": target_chat,
        "photo": photo,
    }
    if caption:
        payload["caption"] = caption
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if is_silent:
        payload["disable_notification"] = True

    try:
        response = requests.post(url, json=payload, timeout=25)
        res_data = response.json()
        if not res_data.get("ok"):
            logger.warning(f"Telegram sendPhoto via URL failed ({res_data.get('description')}), attempting stream download...")
            import urllib.request
            req = urllib.request.Request(photo, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=12) as img_resp:
                img_bytes = img_resp.read()
                files = {"photo": ("image.png", img_bytes, "image/png")}
                data = {"chat_id": target_chat}
                if caption:
                    data["caption"] = caption
                if parse_mode:
                    data["parse_mode"] = parse_mode
                if reply_to_message_id:
                    data["reply_to_message_id"] = reply_to_message_id
                res2 = requests.post(url, data=data, files=files, timeout=25)
                return res2.json()
        return res_data
    except Exception as e:
        logger.error(f"Failed to send photo: {e}")
        return {"ok": False, "description": str(e)}


def send_scout_brief(
    message: str,
    comment_text: Optional[str] = None,
    chat_id: Optional[str] = None,
    post_to_channel: bool = False,
    photo_path_or_url: Optional[str] = None,
    disable_notification: Optional[bool] = None
) -> Dict[str, Any]:
    """
    Send a Scout Intelligence Briefing to Telegram.

    If photo_path_or_url is provided, sends as a rich photo with caption.
    If comment_text is provided, it is posted as a reply/comment under
    the primary brief message, matching the 'สไตล์เพจจาง' format.
    If post_to_channel is True, also cross-posts to TELEGRAM_CHANNEL_ID (ข่าวหุ้น 143).
    During 01:00 - 07:00 AM Bangkok time, all messages are delivered silently without sound.

    :param message: Primary brief headline & structural takeaway
    :param comment_text: Optional detailed commentary/catalyst posted as a reply
    :param chat_id: Optional target chat ID override (defaults to user chat)
    :param post_to_channel: Whether to also post this Grade A+ news into the shared channel
    :param photo_path_or_url: Optional photo file path or web URL (e.g. Finviz chart)
    :param disable_notification: Optional silent delivery override
    :return: Dict summary with primary and optional comment response
    """
    token, env_user_chat, env_channel_id = get_telegram_credentials()
    user_target = chat_id or env_user_chat

    logger.info(f"Dispatching Scout Brief to user chat {user_target}...")
    if photo_path_or_url:
        primary_res = send_photo(photo=photo_path_or_url, caption=message, chat_id=user_target, bot_token=token, disable_notification=disable_notification)
        if not primary_res.get("ok"):
            logger.warning(f"Photo dispatch failed ({primary_res.get('description')}), falling back to text...")
            primary_res = send_message(text=message, chat_id=user_target, bot_token=token, disable_notification=disable_notification)
    else:
        primary_res = send_message(text=message, chat_id=user_target, bot_token=token, disable_notification=disable_notification)

    if not primary_res.get("ok"):
        return {"ok": False, "primary": primary_res}

    result = {"ok": True, "primary": primary_res}

    # If comment_text is provided, reply to user's primary message
    if comment_text:
        main_msg_id = primary_res.get("result", {}).get("message_id")
        if main_msg_id:
            logger.info(f"Posting detail comment to message ID {main_msg_id} in user chat...")
            comment_res = send_message(text=comment_text, chat_id=user_target, reply_to_message_id=main_msg_id, bot_token=token, disable_notification=disable_notification)
            result["comment"] = comment_res

    # 📢 Cross-post to Channel (ข่าวหุ้น 143) if Grade A+ Catalyst
    if post_to_channel and env_channel_id:
        logger.info(f"📢 Major Catalyst detected! Cross-posting to Channel {env_channel_id} (ข่าวหุ้น 143)...")
        if photo_path_or_url:
            chan_primary = send_photo(photo=photo_path_or_url, caption=message, chat_id=env_channel_id, bot_token=token, disable_notification=disable_notification)
            if not chan_primary.get("ok"):
                chan_primary = send_message(text=message, chat_id=env_channel_id, bot_token=token, disable_notification=disable_notification)
        else:
            chan_primary = send_message(text=message, chat_id=env_channel_id, bot_token=token, disable_notification=disable_notification)

        result["channel"] = chan_primary
        if chan_primary.get("ok") and comment_text:
            chan_msg_id = chan_primary.get("result", {}).get("message_id")
            if chan_msg_id:
                chan_comment = send_message(text=comment_text, chat_id=env_channel_id, reply_to_message_id=chan_msg_id, bot_token=token, disable_notification=disable_notification)
                result["channel_comment"] = chan_comment

    return result


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_msg = sys.argv[1]
        comment = sys.argv[2] if len(sys.argv) > 2 else None
        print(f"Testing Telegram Notifier with: {test_msg}")
        res = send_scout_brief(test_msg, comment_text=comment)
        print("Result:", res)
    else:
        print("Usage: python telegram_notifier.py '<headline message>' '[optional comment detail]'")
