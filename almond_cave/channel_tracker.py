"""
Channel Mention Tracker for destination channel
Automatically monitors and extracts mentioned stock tickers from Telegram messages
and dynamically adds them to the technical radar scanner.
"""

import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Set

logger = logging.getLogger("ChannelTracker")

BASE_DIR = Path(__file__).resolve().parent
DYNAMIC_TICKERS_FILE = BASE_DIR / "dynamic_radar_tickers.json"

STOP_WORDS = {
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'ANY', 'CAN', 'HAD', 'HER', 'WAS', 'ONE',
    'OUR', 'OUT', 'DAY', 'GET', 'HAS', 'HIM', 'HIS', 'HOW', 'MAN', 'NEW', 'NOW', 'OLD', 'SEE', 'TWO',
    'WAY', 'WHO', 'BOY', 'DID', 'ITS', 'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'CEO', 'CFO', 'FED',
    'CPI', 'PPI', 'GDP', 'PCE', 'SEC', 'DOJ', 'FTC', 'FDA', 'WSJ', 'CNBC', 'CNN', 'USD', 'THB', 'B',
    'M', 'K', 'Q1', 'Q2', 'Q3', 'Q4', 'PUC', 'AI', 'US', 'USA', 'FOMC', 'DJI', 'DOW', 'CHAT', 'EST',
    'EPS', 'FCF', 'ATM', 'CAGR', 'IPO', 'UAE', 'NDX', 'FT', 'GBP', 'EUR', 'HDD', 'CBRS', 'IDR', 'VOA',
    'AL', 'AZ', 'GA', 'LA', 'MT', 'NE', 'ND', 'OK', 'SD', 'KS', 'NV', 'ECHO', 'TRUE', 'HOLD', 'POST',
    'NEWS', 'EDIT', 'VIEW', 'WARN', 'NOTE', 'LIVE', 'CALL', 'TECH', 'DATE', 'INFO', 'WEEK', 'YEAR', 'ANT'
}


def load_dynamic_tickers() -> Dict[str, Any]:
    """Load dynamically tracked tickers from JSON file."""
    if not DYNAMIC_TICKERS_FILE.exists():
        return {}
    try:
        with open(DYNAMIC_TICKERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Error loading dynamic_radar_tickers.json: {e}")
        return {}


def save_dynamic_tickers(data: Dict[str, Any]) -> None:
    """Save dynamically tracked tickers to JSON file."""
    try:
        with open(DYNAMIC_TICKERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving dynamic_radar_tickers.json: {e}")


def extract_tickers_from_text(text: str) -> Set[str]:
    """Extract stock tickers like $TICKER or (TICKER) from text."""
    if not text:
        return set()

    found = set()

    # 1. Look for Cashtags e.g. $NVDA, $CRWD
    cashtags = re.findall(r'\$([A-Za-z]{1,6})\b', text)
    for t in cashtags:
        sym = t.upper()
        if sym not in STOP_WORDS and len(sym) >= 2:
            found.add(sym)

    # 2. Look for tickers in parentheses e.g. (MRVL), (ARM)
    paren_matches = re.findall(r'\(([A-Z]{2,5})\)', text)
    for t in paren_matches:
        if t not in STOP_WORDS:
            found.add(t)

    return found


def record_channel_mentions(text: str, source: str = "destination channel") -> List[str]:
    """
    Extract tickers from message text and record/increment mention counts.
    Returns list of newly discovered or updated tickers.
    """
    tickers = extract_tickers_from_text(text)
    if not tickers:
        return []

    data = load_dynamic_tickers()
    now_iso = datetime.now().isoformat()
    updated = []

    for sym in tickers:
        if sym in data:
            data[sym]["mention_count"] = data[sym].get("mention_count", 0) + 1
            data[sym]["last_seen"] = now_iso
            updated.append(sym)
        else:
            data[sym] = {
                "first_seen": now_iso,
                "last_seen": now_iso,
                "mention_count": 1,
                "source": source
            }
            logger.info(f"✨ Dynamically added new stock ticker: ${sym} from {source}")
            updated.append(sym)

    save_dynamic_tickers(data)
    return updated


def get_all_dynamic_tickers() -> List[str]:
    """Return all valid dynamic tickers discovered from the channel."""
    data = load_dynamic_tickers()
    # Sort by mention count descending
    sorted_items = sorted(data.items(), key=lambda x: x[1].get("mention_count", 0), reverse=True)
    return [sym for sym, _ in sorted_items if sym not in STOP_WORDS]


def sync_channel_mentions_from_telegram(limit: int = 100) -> List[str]:
    """
    Scan recent messages directly from destination channel using Telethon user session (if available).
    """
    session_path = BASE_DIR / "telegram_relay" / "relay_user_session.session"
    if not session_path.exists():
        return get_all_dynamic_tickers()

    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / "telegram_relay" / ".env")
        api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
        api_hash = os.getenv("TELEGRAM_API_HASH", "")
        dest_chat_id = int(os.getenv("DEST_CHAT_ID", ""))

        if not api_id or not api_hash:
            return get_all_dynamic_tickers()

        import asyncio
        from telethon import TelegramClient

        async def _scan():
            client = TelegramClient(str(BASE_DIR / "telegram_relay" / "relay_user_session"), api_id, api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return

            all_new = []
            async for msg in client.iter_messages(dest_chat_id, limit=limit):
                if msg.text:
                    added = record_channel_mentions(msg.text, source="destination channel")
                    all_new.extend(added)

            await client.disconnect()
            return all_new

        # Run async in existing or new loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Avoid nested loop crash in asyncio
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _scan()).result()
            else:
                return loop.run_until_complete(_scan())
        except Exception:
            return asyncio.run(_scan())

    except Exception as e:
        logger.warning(f"Failed to sync channel mentions: {e}")
        return get_all_dynamic_tickers()


CHANNEL_143_RECENT_FILE = BASE_DIR / "channel_143_recent.json"


def record_channel_143_message(text: str, msg_id: int = None, date_iso: str = None) -> None:
    """Store recent message from channel destination channel for fast deduplication."""
    if not text:
        return
    now_iso = date_iso or datetime.now().isoformat()
    entries = []
    if CHANNEL_143_RECENT_FILE.exists():
        try:
            with open(CHANNEL_143_RECENT_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []

    entries.append({
        "id": msg_id,
        "date": now_iso,
        "text": text[:500]
    })

    # Keep last 150 messages
    if len(entries) > 150:
        entries = entries[-150:]

    try:
        with open(CHANNEL_143_RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save channel_143_recent.json: {e}")


def is_news_already_covered_in_channel(
    title: str,
    ticker: Any = None,
    hours_lookback: int = 18
) -> tuple[bool, str]:
    """
    Check if a news topic or ticker catalyst has already been reported in channel destination channel
    (especially relayed from source feed) within the specified lookback window (default 18 hours).
    Returns (is_covered, reason).
    """
    if not title:
        return False, ""

    from datetime import datetime, timezone
    now_utc = datetime.now(timezone.utc)
    t_upper = str(ticker).upper() if ticker else ""
    title_words = set(re.findall(r'[A-Za-z0-9ก-๙]{3,}', title.lower()))

    # 1. First check via Telethon session if available (most accurate live check)
    session_path = BASE_DIR / "telegram_relay" / "relay_user_session.session"
    if session_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(BASE_DIR / "telegram_relay" / ".env")
            api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
            api_hash = os.getenv("TELEGRAM_API_HASH", "")
            dest_chat_id = int(os.getenv("DEST_CHAT_ID", ""))

            if api_id and api_hash:
                import asyncio
                from telethon import TelegramClient

                async def _check_live():
                    client = TelegramClient(str(BASE_DIR / "telegram_relay" / "relay_user_session"), api_id, api_hash)
                    await client.connect()
                    if not await client.is_user_authorized():
                        await client.disconnect()
                        return False, ""

                    async for m in client.iter_messages(dest_chat_id, limit=40):
                        if not m.text or not m.date:
                            continue
                        age_hours = (now_utc - m.date).total_seconds() / 3600.0
                        if age_hours > hours_lookback:
                            continue

                        m_txt = m.text
                        m_lower = m_txt.lower()

                        # Check Ticker match
                        if t_upper:
                            has_ticker = any(p in m_txt for p in [f"${t_upper}", f"({t_upper})", f"[{t_upper}]", f" {t_upper} "])
                            if has_ticker:
                                is_both_earnings = any(k in title.lower() for k in ["earnings", "revenue", "q1", "q2", "q3", "q4", "งบ", "ผลประกอบการ"]) and any(k in m_lower for k in ["งบ", "ผลประกอบการ", "รายได้", "ไตรมาส", "earnings", "q1", "q2", "q3", "q4"])
                                matched_words = title_words.intersection(set(re.findall(r'[A-Za-z0-9ก-๙]{3,}', m_lower)))
                                if is_both_earnings or len(matched_words) >= 1:
                                    await client.disconnect()
                                    return True, f"Ticker ${t_upper} covered in destination channel {age_hours:.1f}h ago (Msg {m.id}): {m_txt[:50]}..."

                        # Check Topic keyword overlap
                        matched_words = title_words.intersection(set(re.findall(r'[A-Za-z0-9ก-๙]{3,}', m_lower)))
                        meaningful_matches = [w for w in matched_words if w.upper() not in STOP_WORDS and len(w) >= 3]
                        if len(meaningful_matches) >= 2:
                            await client.disconnect()
                            return True, f"Topic overlap {meaningful_matches} covered {age_hours:.1f}h ago in destination channel (Msg {m.id}): {m_txt[:50]}..."

                    await client.disconnect()
                    return False, ""

                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    covered, reason = pool.submit(asyncio.run, _check_live()).result()
                    if covered:
                        return True, reason
        except Exception as e:
            logger.debug(f"Live Telethon channel check error: {e}")

    # 2. Fallback check from local cache channel_143_recent.json
    if CHANNEL_143_RECENT_FILE.exists():
        try:
            with open(CHANNEL_143_RECENT_FILE, "r", encoding="utf-8") as f:
                recent_entries = json.load(f)
            for entry in reversed(recent_entries):
                dt_str = entry.get("date", "")
                try:
                    entry_dt = datetime.fromisoformat(dt_str)
                    age_hours = (datetime.now() - entry_dt).total_seconds() / 3600.0
                    if age_hours > hours_lookback:
                        continue
                except Exception:
                    pass

                m_txt = entry.get("text", "")
                m_lower = m_txt.lower()
                if t_upper and any(p in m_txt for p in [f"${t_upper}", f"({t_upper})", f"[{t_upper}]"]):
                    return True, f"Ticker ${t_upper} covered in recent channel cache: {m_txt[:50]}..."

                matched_words = [w for w in title_words.intersection(set(re.findall(r'[A-Za-z0-9ก-๙]{3,}', m_lower))) if w.upper() not in STOP_WORDS]
                if len(matched_words) >= 2:
                    return True, f"Topic overlap {matched_words} in channel cache: {m_txt[:50]}..."
        except Exception as e:
            logger.debug(f"Cache check error: {e}")

    return False, ""
