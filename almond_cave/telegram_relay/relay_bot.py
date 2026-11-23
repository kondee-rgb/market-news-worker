"""
almond_cave/telegram_relay/relay_bot.py
---------------------------------------
Automated Telegram News Sync & Filter Worker:
Syncs filtered financial news updates from source feed to destination channel.
Supports: Rich Text / PageBlocks, Photos, Videos, Documents, and Reply Threads.
"""

import os
import sys
import re
import logging
import asyncio
from pathlib import Path
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaWebPage
import requests

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("telegram_relay")

def load_env():
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k not in os.environ:
                        os.environ[k] = v

load_env()

API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SOURCE_CHAT_ID = os.getenv("SOURCE_CHAT_ID", "")
DEST_CHAT_ID = os.getenv("DEST_CHAT_ID", "")
STRING_SESSION = os.getenv("TELEGRAM_STRING_SESSION")

try:
    SOURCE_CHAT_ID = int(SOURCE_CHAT_ID)
except ValueError:
    pass

try:
    DEST_CHAT_ID = int(DEST_CHAT_ID)
except ValueError:
    pass

msg_map = {}

if STRING_SESSION:
    logger.info("🔐 ใช้การยืนยันตัวตนผ่าน In-Memory StringSession")
    client = TelegramClient(StringSession(STRING_SESSION), int(API_ID), API_HASH)
else:
    session_path = str(Path(__file__).parent / "relay_user_session")
    client = TelegramClient(session_path, int(API_ID), API_HASH)


def extract_rich_text(rich_text_obj):
    if not rich_text_obj:
        return ""
    if hasattr(rich_text_obj, "text"):
        return extract_rich_text(rich_text_obj.text)
    if hasattr(rich_text_obj, "texts"):
        return "".join(extract_rich_text(t) for t in rich_text_obj.texts)
    if isinstance(rich_text_obj, str):
        return rich_text_obj
    return str(rich_text_obj)


def extract_page_block(block):
    if hasattr(block, "text"):
        return extract_rich_text(block.text)
    if hasattr(block, "items"):
        lines = []
        for i, item in enumerate(block.items, 1):
            num_str = getattr(item, "num", str(i))
            item_text = extract_rich_text(getattr(item, "text", ""))
            lines.append(f"{num_str}. {item_text}")
        return "\n".join(lines)
    return ""


def get_message_full_text(message):
    if message.text:
        return message.text
    if message.message:
        return message.message
    
    if hasattr(message, "rich_message") and message.rich_message:
        blocks = getattr(message.rich_message, "blocks", [])
        extracted = []
        for b in blocks:
            t = extract_page_block(b)
            if t.strip():
                extracted.append(t)
        return "\n\n".join(extracted)
        
    return ""



import zlib, base64, json as _json

def _load_filter_rules() -> dict:
    raw_b64 = os.getenv("FILTER_RULES_B64", "").strip()
    if not raw_b64:
        return {}
    try:
        return _json.loads(zlib.decompress(base64.b64decode(raw_b64)).decode("utf-8"))
    except Exception as _e:
        logger.warning(f"Failed to load FILTER_RULES_B64: {_e}")
        return {}

_R = _load_filter_rules()
PUBLIC_FIGURES = set(_R.get("PUBLIC_FIGURES", []))
THAI_KHUN_COMPOUNDS = _R.get("THAI_KHUN_COMPOUNDS", r"(?!)")
OFFICIAL_SENDERS = {int(x) for x in os.getenv("OFFICIAL_SENDERS", "").split(",") if x.strip()}
OPINION_HEADER_PATTERN = _R.get("OPINION_HEADER_PATTERN", r"(?!)")
WRAPUP_HEADER_PATTERN = _R.get("WRAPUP_HEADER_PATTERN", r"(?!)")
AI_PERSONA_PATTERNS = _R.get("AI_PERSONA_PATTERNS", [])
LEADING_CHATTER_LINE_PATTERNS = _R.get("LEADING_CHATTER_LINE_PATTERNS", [])
TRAILING_CHATTER_LINE_PATTERNS = _R.get("TRAILING_CHATTER_LINE_PATTERNS", [])
COMMUNITY_INTERACTION_PATTERNS = _R.get("COMMUNITY_INTERACTION_PATTERNS", [])
PERSONAL_AND_PROMISE_PATTERNS = _R.get("PERSONAL_AND_PROMISE_PATTERNS", [])
CASUAL_OPINION_PATTERNS = _R.get("CASUAL_OPINION_PATTERNS", [])
HARD_RETAIL_ADVICE_PATTERNS = _R.get("HARD_RETAIL_ADVICE_PATTERNS", [])
NEWS_INDICATOR_PATTERNS = _R.get("NEWS_INDICATOR_PATTERNS", [])


PASS2_STATUS_SENT = "SENT"
PASS2_STATUS_BLOCKED = "BLOCKED"
PASS2_STATUS_FAILED = "FAILED"


def strip_quoted_text(text: str) -> str:
    """Strip quoted speech before running opinion/community checks."""
    return re.sub(r'["“][^"”]*["”]', '', text)


def is_mentioning_other_members(text: str) -> tuple[bool, str]:
    """Check if text addresses or mentions other chat members (ignoring quoted speech)."""
    # 1. Telegram username mention e.g. @username
    if re.search(r"@\w{3,}", text):
        return True, "Contains Telegram @username mention"

    unquoted = strip_quoted_text(text)

    # 2. Q&A references to questions or members (require word boundary + space before name)
    qa_member_patterns = [
        r"(?<![ก-๙A-Za-z])(ตอบ|สำหรับ|ถึง|เห็นด้วยกับ|ขอบคุณ|ตามที่)\s*(คุณ|สมาชิก|พี่|น้อง|ท่าน)\s+([A-Za-zก-๙]+)",
        r"(ที่มีคนถาม|ที่ถามว่า|สำหรับคำถาม|ตอบคำถาม|มีคำถามว่า)",
        r"ครับคุณ\s*([A-Za-zก-๙]+)",
        r"ค่ะคุณ\s*([A-Za-zก-๙]+)",
        r"(?<![ก-๙A-Za-z])คุณ\s+([A-Za-zก-๙]{2,15})\s*(ครับ|ค่ะ|ถาม|บอก|คิดว่า|แชร์|พิมพ์)",
    ]
    for pat in qa_member_patterns:
        m = re.search(pat, unquoted)
        if m:
            name = m.groups()[-1] if m.groups() else ""
            if name.upper() not in PUBLIC_FIGURES:
                return True, f"Mentions/addresses member pattern '{m.group()}'"

    # 3. Direct general 'คุณ [ชื่อ]' address (skip public figures & Thai compound words like คุณค่า)
    for m in re.finditer(r"(?<![ก-๙A-Za-z])คุณ\s*([A-Za-zก-๙]{2,15})", unquoted):
        full_word = m.group(0)
        if re.match(rf"^({THAI_KHUN_COMPOUNDS})", full_word):
            continue
        name = m.group(1).strip()
        if name.upper() not in PUBLIC_FIGURES:
            pre = unquoted[max(0, m.start() - 15):m.start()]
            post = unquoted[m.end():min(len(unquoted), m.end() + 15)]
            if any(w in pre or w in post for w in ["ครับ", "ค่ะ", "สวัสดี", "ขอบคุณ", "ตามที่", "ตอบ", "ถาม", "เห็นด้วย", "นะ", "\n"]):
                return True, f"Directly addresses member 'คุณ{name}'"

    return False, ""




def is_ai_persona_post(text: str) -> tuple[bool, str]:
    """Detect AI persona disclaimers or meta commentary."""
    for pat in AI_PERSONA_PATTERNS:
        m = re.search(pat, text)
        if m:
            return True, f"Blocked: AI persona/meta commentary '{m.group().strip()}'"
    return False, ""


def sanitize_news_head_and_tail(text: str) -> str:
    """Trim conversational, health, schedule, and Q&A wrappers from mixed news heads/tails (idempotent)."""
    clean_text = (text or "").replace("\u2800", "").strip()
    if not clean_text:
        return ""

    # 1. Cut trailing explicit Personal Opinion section when news body precedes it (>= 50 chars)
    split_match = re.search(OPINION_HEADER_PATTERN, clean_text)
    wrap_match = re.search(WRAPUP_HEADER_PATTERN, clean_text)
    if split_match and split_match.start() >= 50:
        is_explicit_tag = bool(re.search(r"(?:ส่วนตัว|คหสต|^[\(\[\【📌💭💬💡✍️📝🗣️🤔])", split_match.group().strip()))
        if not wrap_match or split_match.start() < wrap_match.start() or is_explicit_tag:
            clean_text = clean_text[:split_match.start()].rstrip()

    # 2. Trim inline Q&A wrapper directly preceding [Source] on line 1
    clean_text = re.sub(
        r"^\s*สาเหตุที่[^\n]{0,140}?เป็นเพราะ(?:รายงาน)?ข่าว[^\n]{0,100}?ครับ\s+(?=\[)",
        "",
        clean_text,
    ).lstrip()

    # 3. Trim leading personal/chatter/unthreaded-answer lines
    while clean_text:
        parts = clean_text.split("\n", 1)
        first_line = parts[0].strip()
        if not first_line:
            clean_text = parts[1].lstrip("\r\n ") if len(parts) > 1 else ""
            continue
        if any(re.search(pat, first_line) for pat in LEADING_CHATTER_LINE_PATTERNS):
            clean_text = parts[1].lstrip("\r\n ") if len(parts) > 1 else ""
            continue
        break

    # 4. Trim trailing chatter/no-new-news/Q&A/sign-off lines (never strip attribution, URLs, or wrap-up headers)
    while clean_text:
        parts = clean_text.rstrip().rsplit("\n", 1)
        last_line = parts[-1].strip()
        if not last_line:
            clean_text = parts[0].rstrip() if len(parts) > 1 else ""
            continue
        if re.search(r"(ที่มา[:\s]|แหล่งข้อมูล|📊\s*ภาพรวมและมุมมอง|https?://)", last_line):
            break
        if any(re.search(pat, last_line) for pat in TRAILING_CHATTER_LINE_PATTERNS):
            clean_text = parts[0].rstrip() if len(parts) > 1 else ""
            continue
        break

    # 5. Trim inline conversational lead-ins & standalone rhetorical question lines when factual news remains
    clean_text = re.sub(
        r"^\s*(?:เผื่อมีใครสับสน(?:นะครับ|นะคะ|ครับ|ค่ะ)?|สำหรับใครที่(?:ยังไม่ทราบ|สงสัย|สับสน)(?:นะครับ|นะคะ|ครับ|ค่ะ)?|อธิบายสั้นๆ\s*(?:นะครับ|นะคะ|ครับ|ค่ะ)?|สรุปให้สั้นๆ\s*(?:นะครับ|นะคะ|ครับ|ค่ะ)?)\s*[,:]?\s+",
        "",
        clean_text,
    ).lstrip()

    if "?" in clean_text:
        kept_lines = []
        removed_rhetorical = False
        for ln in clean_text.splitlines():
            s = ln.strip()
            is_short_rhetorical_q = (
                s.endswith("?")
                and len(s) <= 100
                and not re.search(r"(?:ที่มา[:\s]|https?://|\$[A-Za-z]{1,6}\b|\d+(?:\.\d+)?\s*(?:%|bps|พันล้าน|ล้าน|จุด))", s)
            )
            if is_short_rhetorical_q:
                removed_rhetorical = True
                continue
            if removed_rhetorical and s:
                ln = re.sub(r"^\s*ก็คือ\s+", "", ln)
                removed_rhetorical = False
            kept_lines.append(ln)
        candidate = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
        if candidate and _has_factual_indicators(candidate):
            clean_text = candidate

    return re.sub(r"\n{3,}", "\n\n", clean_text).strip()


def is_community_interaction_message(text: str, is_structured: bool = False) -> tuple[bool, str]:
    """Check if message is an admin community Q&A invitation or request for member input."""
    # Never block market news describing market participants / investors ("ทุกคนในตลาด", "นักลงทุนทุกคน")
    market_everyone_pattern = r"(ทุกคน|ทุกท่าน)\s*(ในตลาด|ในวอลล์สตรีท|ต่าง|ที่ลงทุน|ที่ถือครอง|ต้อง|ควร)"
    filtered_text = re.sub(market_everyone_pattern, "นักลงทุน", text)
    filtered_text = re.sub(r"(นักลงทุน|เทรดเดอร์|คนในตลาด)\s*(ทุกคน|ทุกท่าน)", "นักลงทุน", filtered_text)
    filtered_text = strip_quoted_text(filtered_text)

    for pat in COMMUNITY_INTERACTION_PATTERNS:
        m = re.search(pat, filtered_text, re.IGNORECASE | re.MULTILINE)
        if m:
            return True, f"Community interaction/Q&A invitation '{m.group()}'"

    if not is_structured:
        m_q = re.search(r"\?\s*($|\n)", filtered_text)
        if m_q:
            return True, "Conversational question mark ending"
    return False, ""


def is_conversational_chat_answer(text: str) -> tuple[bool, str]:
    """Check if message looks like a conversational answer to an unquoted question."""
    t = text.strip()
    chat_answer_openings = [
        r"^(ถ้าพูดตาม|อีกปัจจัยหนึ่งก็อาจเป็น|ทางฝั่ง.*อยู่แล้วครับ|ไม่ได้มีข่าวลบอะไรเป็นพิเศษ)",
        r"^(ก็ไม่แน่ใจเหมือนกันครับ|เรื่องนี้ผม|อันนี้ผม|เรื่องนี้คือ|เท่าที่ทราบ|ตอบเรื่อง)",
        r"^(ใช่ครับ|ไม่ใช่ครับ|ไม่ครับ|จริงครับ|ตามนั้นเลยครับ|เห็นด้วยครับ|ผมคิดเหมือนกันครับ)",
        r"^(สำหรับเรื่องที่ถาม|เกี่ยวกับเรื่องที่ถาม)",
        r"^(เอ่อ+\.{2,}|อืม+\.{2,}|พอดีผม|เมื่อวานผม)",
        r"^(ยังไม่มีข่าวอะไรเข้ามา|ตอนนี้ยังไม่มีข่าวเพิ่มเติม)",
    ]
    for pat in chat_answer_openings:
        if re.search(pat, t):
            return True, f"Conversational chat answer opening '{pat}'"
    return False, ""


def _has_factual_indicators(text: str) -> bool:
    """Check whether text contains factual financial, macro, entity, or attribution markers."""
    if re.search(r"(?:\$[A-Za-z]{1,6}\b|[\[\(](?!OK\b|FYI\b|LOL\b)[A-Z]{2,5}(?:\s*[/,|&]\s*[A-Z]{2,5})*[\]\)])", text):
        return True
    lower = text.lower()
    return bool(re.search(
        r"((?:\$|€|£|¥|nt\$|฿)\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:%|bps|พันล้าน|ล้านล้าน|หมื่นล้าน|ล้าน|เท่า|จุด|[kmb]\b)|"
        r"futures|yield|พันธบัตร|เดโมแครต|รีพับลิกัน|trump|fed|fomc|cpi|ppi|pce|gdp|pmi|ism|nasdaq|s&p|"
        r"reuters|bloomberg|cnbc|wsj|ft|financial times|axios|abc news|al mayadeen|semianalysis|techcrunch|"
        r"goldman sachs|citigroup|citi|bofa|morgan stanley|อิหร่าน|ช่องแคบฮอร์มุซ|น้ำมัน|คว่ำบาตร|ระดมทุน|"
        r"data center|ผลประกอบการ|กำไร|ขาดทุน|รายได้|ดอกเบี้ย|ipo|ebitda|eps|guidance|capex|backlog|"
        r"ยอดจอง|ยอดขาย|สูงกว่า(?:ตลาด)?คาด|ต่ำกว่า(?:ตลาด)?คาด|ตัวเลขการจ้างงาน|nonfarm|ที่มา:)",
        lower,
    ))


def is_structured_news_article(text: str) -> bool:
    """Check if text is a substantial, structured factual news article."""
    t = text.strip()
    if len(t) < 180:
        return False
    if re.search(r"^(?:ผม|ส่วนตัว|เอ่อ|อืม|พอดี|เมื่อวานผม|วันนี้ผม|ถ้าในนี้)", t):
        return False
    if is_ai_persona_post(t)[0]:
        return False

    has_strong_structure = bool(
        re.search(r"━━━━━━━━━━━━", t)
        or re.search(r"(^|\n)\s*ที่มา[:\s]", t)
        or re.search(r"(^|\n)\s*(📌\s*สรุปประเด็นสำคัญ|📊\s*ภาพรวมและมุมมอง)", t)
        or (
            re.search(r"^(📊|🇺🇸|📉|📌|🏛|🔎|🔴|🟢|🏢|🤖|🖥|📈|🚨|🏦|🚀|🌍|📰|📆|📅|🏗)", t)
            and re.search(r"\n\s*(?:[\U0001F300-\U0001FAFF]\s*)?\d+\)", t)
        )
        or (
            re.search(r"^([^\n]*[\[\(][A-Za-zก-๙\s|,&]+[\]\)]|\s*(?:📊|🇺🇸|📉|📌|🏛|🔎|🔴|🟢|🏢|🤖|🖥|📈|🚨|🏦|🚀|🌍|📰|📆|📅))", t)
            and bool(re.search(r"\n\s*(?:🔹|🟢|🔴|⚠️|•|-|\d+\))", t))
        )
    )
    if not has_strong_structure:
        return False

    return _has_factual_indicators(t)


def has_substantive_wrapup(text: str) -> tuple[bool, str, str]:
    """Verify `📊 ภาพรวมและมุมมอง` is preceded by substantive attributed/quantified news before relaxing first-person checks."""
    wrap_match = re.search(WRAPUP_HEADER_PATTERN, text)
    if not wrap_match:
        return False, text, ""
    pre_wrap = text[:wrap_match.start()].strip()
    wrap_tail = text[wrap_match.start():].strip()
    if len(pre_wrap) < 35:
        return False, text, ""
    if re.search(r"^(?:ผม|ส่วนตัว|เอ่อ|อืม|พอดี|เมื่อวานผม|วันนี้ผม|ถ้าในนี้|📊\s*มุมมองของ|มุมมอง(?:ของ)?(?:ผม|เรา|แอด))", pre_wrap):
        return False, text, ""

    has_attribution = bool(re.search(
        r"(?:^|\n)\s*(?:ที่มา[:\s]|📌\s*สรุปประเด็นสำคัญ)|ตามรายงาน|"
        r"\b(?:reuters|bloomberg|cnbc|wsj|ft|financial times|axios|abc news|al mayadeen|semianalysis|techcrunch|"
        r"sec|fed|fomc|citadel|jpmorgan|goldman sachs|citigroup|citi|bofa|morgan stanley)\b",
        pre_wrap,
        re.IGNORECASE,
    ))
    has_quant = bool(re.search(
        r"(?:(?:\$|€|£|¥|nt\$|฿)\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:%|bps|พันล้าน|ล้านล้าน|หมื่นล้าน|ล้าน|แสน|หมื่น|เท่า|จุด|[kmb]\b))",
        pre_wrap,
        re.IGNORECASE,
    ))
    if _has_factual_indicators(pre_wrap) and (has_attribution or has_quant):
        return True, pre_wrap, wrap_tail
    return False, text, ""


NON_TICKER_UPPERCASE = {
    "AI", "US", "UK", "EU", "UN", "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "GDP",
    "CPI", "PPI", "PCE", "PMI", "ISM", "NFP", "FED", "FOMC", "SEC", "FDA", "DOJ",
    "FBI", "FTC", "FCC", "NRC", "IRS", "BIS", "APEC", "OPEC", "NATO", "BRICS",
    "NYT", "WSJ", "CNBC", "CNN", "BBC", "FT", "AP", "TV", "TH", "THB", "USD",
    "EUR", "JPY", "CNY", "RMB", "KRW", "BPS", "YOY", "QOQ", "MOM", "EPS", "FCF",
    "SBC", "NIM", "TCV", "EBITDA", "EBIT", "PE", "PB", "ROE", "ROA", "ROI",
    "USA", "USSR", "UAE", "IMF", "WTO", "WHO", "AM", "PM", "EST", "EDT", "PST",
    "BKK", "UTC", "GMT", "OK", "FYI", "LOL", "VIP", "VS", "OR", "AND", "THE",
    "FOR", "IN", "ON", "AT", "TO", "OF", "BY", "IT", "IS", "AS", "Q1", "Q2", "Q3", "Q4",
    "H1", "H2", "FY", "YTD", "MTD", "ALL", "NEW", "TOP", "MAX", "MIN", "AVG",
    "CAPEX", "OPEX", "SAAS", "HPC", "GPU", "CPU", "TPU", "HBM", "LLM", "API",
    "KYC", "PR", "IR", "HR", "RD", "MA", "SP", "DJI", "IXIC", "VIX", "DXY",
    "NOTE", "NO", "YES", "PART", "PDF",
}


def append_telegram_hashtags(text: str, has_media: bool = False) -> str:
    """Append clean, clickable Telegram hashtags (#TICKER #EARNINGS #MACRO #FED etc.) idempotently."""
    t = (text or "").strip()
    if not t:
        return t
    if re.search(r"(?:^|\n)🏷️\s*#[A-Za-z0-9_]+", t):
        return t

    tags = []
    seen = set()

    def add_tag(tag: str):
        clean = re.sub(r"[^A-Za-z0-9_]", "", tag).upper()
        if clean and clean not in seen and len(clean) >= 2:
            seen.add(clean)
            tags.append(f"#{clean}")

    # 1. Extract tickers ($NVDA, (NVDA), [NVDA], (NVDA/AMD))
    for m in re.finditer(r"\$([A-Za-z]{1,5})\b", t):
        sym = m.group(1).upper()
        if sym not in NON_TICKER_UPPERCASE:
            add_tag(sym)

    for m in re.finditer(r"[\[\(]([A-Z]{2,5}(?:\s*[/,|&]\s*[A-Z]{2,5})*)[\]\)]", t):
        for part in re.split(r"[/,|&\s]+", m.group(1)):
            sym = part.strip().upper()
            if sym and sym not in NON_TICKER_UPPERCASE:
                add_tag(sym)

    # Cap ticker hashtags at 6 per post to keep messages clean
    tags = tags[:6]
    seen = {tg[1:] for tg in tags}
    has_ticker = bool(tags)

    # 2. Category tags
    low = t.lower()
    if any(k in low for k in ["ผลประกอบการ", "earnings", "adjusted eps", "eps", "guidance", "รายได้ไตรมาส", "q1", "q2", "q3", "q4"]):
        add_tag("EARNINGS")
    if any(k in low for k in ["fed", "fomc", "พาวเวลล์", "powell", "ดอกเบี้ย", "waller", "barr", "cook", "beige book", "ธนาคารกลางสหรัฐ"]):
        add_tag("FED")
    if any(k in low for k in ["cpi", "ppi", "pce", "gdp", "nonfarm", "เงินเฟ้อ", "การจ้างงาน", "ว่างงาน", "ตัวเลขเศรษฐกิจ", "สรุปตลาดสหรัฐ", "ยอดขายบ้าน", "ค้าปลีก", "pmi", "ism", "yield", "พันธบัตร"]):
        add_tag("MACRO")
    if any(k in low for k in ["trump", "xi ", "xi jinping", "ปูติน", "putin", "อิหร่าน", "อิสราเอล", "ช่องแคบฮอร์มุซ", "คว่ำบาตร", "apec", "ภาษีศุลกากร", "tariff", "สงคราม", "ไต้หวัน"]):
        add_tag("GEOPOLITICS")
    if any(k in low for k in ["bitcoin", "btc", "ethereum", "eth", "คริปโต", "crypto"]):
        add_tag("CRYPTO")
    if re.search(r"\bipo\b", low):
        add_tag("IPO")

    if not tags:
        if has_media:
            add_tag("FILE" if any(k in low for k in ["tutorial", "guide", "report", "pdf", "part"]) else "CHART")
        else:
            add_tag("MARKET")
    elif has_ticker and not any(cat in seen for cat in ("EARNINGS", "FED", "MACRO", "GEOPOLITICS", "CRYPTO", "IPO")):
        add_tag("STOCKS")

    return f"{t}\n\n🏷️ {' '.join(tags)}"


def is_worthy_news_item(text: str, has_media: bool, parent_sender_id: int = None, is_parent_channel: bool = False) -> tuple[bool, str, str]:
    """
    Strict Precision Filter (Fail-Closed):
    - Blocks replies to regular group members (Q&A isolation).
    - Keeps captionless media/photos ALLOWED when sent by official publishers.
    - Blocks AI persona/meta disclaimers before sanitization.
    - Trims conversational/personal/health/admin-schedule/Q&A wrappers from heads & tails via sanitize_news_head_and_tail().
    - Allows legitimate `📊 ภาพรวมและมุมมอง` analytical wrap-ups ONLY when preceded by substantive attributed/quantified news (`has_substantive_wrapup`).
    - Enforces community Q&A, personal-life, hard retail advice, and casual-opinion checks against unquoted content.
    """
    clean_text = (text or "").strip()

    # 0. Check if replying to a regular user in the chat (Q&A conversation)
    if parent_sender_id is not None and not is_parent_channel:
        return False, f"Blocked: Reply to regular group user (ID {parent_sender_id})", ""

    if has_media and not clean_text:
        return True, "Allowed: Media without text", clean_text
    if not clean_text:
        return False, "Blocked: Empty text", ""

    # 1. Block AI persona/meta disclaimers before any sanitization
    is_ai, ai_reason = is_ai_persona_post(clean_text)
    if is_ai:
        return False, ai_reason, ""

    # 1.5 Reject message early if it opens directly with a Personal Opinion header
    split_match = re.search(OPINION_HEADER_PATTERN, clean_text)
    if split_match and split_match.start() < 50:
        return False, f"Blocked: Personal Opinion header '{split_match.group().strip()}'", ""

    # 2. Sanitize mixed messages by trimming conversational heads/tails & trailing explicit opinion blocks
    clean_text = sanitize_news_head_and_tail(clean_text)
    if not clean_text:
        return False, "Blocked: No substantive news remaining after trimming", ""

    # 3. Check if mentioning other group members (@username, คุณ [ชื่อ])
    is_mention, mention_reason = is_mentioning_other_members(clean_text)
    if is_mention:
        return False, f"Blocked: {mention_reason}", ""

    # 4. Check if conversational chat answer ("ถ้าพูดตาม...", "ใช่ครับ...", etc.)
    is_chat_ans, ans_reason = is_conversational_chat_answer(clean_text)
    if is_chat_ans:
        return False, f"Blocked: {ans_reason}", ""

    # 5. Pure chat banter
    pure_banter_patterns = [
        r"^(no|yes|ok|yep|nope|thanks?|ty|thx|k|lol|555+|ฮ่า\w*)$",
        r"^(ขอบคุณ(ครับ|ค่ะ)?|โอเค(ครับ|ค่ะ)?|รับทราบ(ครับ|ค่ะ)?|ใช่(ครับ|ค่ะ)?|จริง(ครับ|ค่ะ)?|เห็นด้วย(ครับ|ค่ะ)?)$",
        r"^(กราบ|สุดยอด|สวย(ครับ|ค่ะ)?|เยี่ยม(ครับ|ค่ะ)?|ตาม(ครับ|ค่ะ)?|รอ(ครับ|ค่ะ)?|สวัสดี(ครับ|ค่ะ)?|ยินดี(ครับ|ค่ะ)?)$",
        r"^(ดีครับ|ดีค่ะ|บวกแล้ว|ดอย|ขายแล้ว|ซื้อแล้ว|กำไรแล้ว)$",
    ]
    for pat in pure_banter_patterns:
        if re.search(pat, clean_text, re.IGNORECASE):
            return False, f"Blocked: Pure chat banter: '{clean_text}'", ""

    # 6. Check structural news eligibility & block community Q&A invitations
    is_struct = is_structured_news_article(clean_text)

    is_comm, comm_reason = is_community_interaction_message(clean_text, is_structured=is_struct)
    if is_comm:
        return False, f"Blocked: {comm_reason}", ""

    # 7. Scope first-person/personal opinion checks cleanly around substantive wrap-ups
    has_valid_wrapup, pre_wrap, _ = has_substantive_wrapup(clean_text)
    unquoted_full = strip_quoted_text(clean_text)
    scope_for_personal = strip_quoted_text(pre_wrap if has_valid_wrapup else clean_text)

    for pat in HARD_RETAIL_ADVICE_PATTERNS:
        m = re.search(pat, unquoted_full)
        if m:
            return False, f"Blocked: Retail trading advice/opinion '{m.group()}'", ""

    for pat in PERSONAL_AND_PROMISE_PATTERNS:
        m = re.search(pat, scope_for_personal)
        if m:
            return False, f"Blocked: Personal life/action '{m.group()}'", ""

    if not is_struct:
        for pat in CASUAL_OPINION_PATTERNS:
            m = re.search(pat, scope_for_personal)
            if m:
                return False, f"Blocked: Personal opinion '{m.group()}'", ""

    # 8. Allow substantive structured news articles (with verified wrap-up or clean body)
    if is_struct:
        return True, "Allowed: Substantive structured news report", append_telegram_hashtags(clean_text, has_media)

    # 9. Detect Hard News & Market Catalysts (Factual Indicators) for concise news updates
    lower_text = clean_text.lower()
    has_news_indicators = (
        any(re.search(pat, lower_text) for pat in NEWS_INDICATOR_PATTERNS)
        or bool(re.search(r"[\[\(](?!OK\b|FYI\b|LOL\b)[A-Z]{2,5}(?:\s*[/,|&]\s*[A-Z]{2,5})*[\]\)]", clean_text))
    )

    # 10. Short non-news filter (allow clean attached files/documents when has_media=True)
    if len(clean_text) < 35 and not has_news_indicators:
        if has_media and not re.search(r"(ครับ|ค่ะ|นะ|555|ฮ่า|lol|😂|👍|🙏)", clean_text, re.IGNORECASE):
            return True, "Allowed: Media/File attachment with title", append_telegram_hashtags(clean_text, has_media)
        return False, f"Blocked: Short chatter without news ({len(clean_text)} chars): '{clean_text}'", ""

    # 11. Conversational chat without any news indicators
    if not has_news_indicators:
        if any(w in clean_text for w in ["ผม", "ครับ", "ค่ะ"]):
            return False, "Blocked: Conversational chatter without news indicators", ""

    # Otherwise, it has factual/market news indicators -> ALLOW
    return True, "Allowed: Factual news / Market update", append_telegram_hashtags(clean_text, has_media)


def _send_via_bot_status(text=None, media_path=None, caption=None, reply_to_message_id=None) -> tuple[str, int | None]:
    """ส่งข้อความหรือมีเดียผ่าน Telegram Bot API พร้อมคืนสถานะ (SENT / BLOCKED / FAILED)"""
    # 🛡️ Pass 2 (Egress Pre-flight Double Check): ตรวจสอบความถูกต้องของข้อความก่อนตรวจ Token หรือยิง API ทุกครั้ง
    verify_text = caption if media_path else text
    is_ok_pass2, pass2_reason, cleaned_p2 = is_worthy_news_item(verify_text or "", has_media=bool(media_path))
    if not is_ok_pass2:
        logger.warning(f"🚨 [Pass 2 Egress Blocked] บล็อกก่อนส่ง: {pass2_reason}")
        return PASS2_STATUS_BLOCKED, None
    if media_path:
        caption = cleaned_p2
    else:
        text = cleaned_p2

    if not BOT_TOKEN:
        logger.warning("ไม่ได้ระบุ TELEGRAM_BOT_TOKEN")
        return PASS2_STATUS_FAILED, None

    base_url = f"https://api.telegram.org/bot{BOT_TOKEN}"

    try:
        if media_path and os.path.exists(media_path):
            file_ext = Path(media_path).suffix.lower()
            data = {"chat_id": DEST_CHAT_ID, "caption": caption or ""}
            if reply_to_message_id:
                data["reply_to_message_id"] = reply_to_message_id

            if file_ext in [".jpg", ".jpeg", ".png", ".webp"]:
                endpoint = f"{base_url}/sendPhoto"
                field_name = "photo"
            elif file_ext in [".mp4", ".mov"]:
                endpoint = f"{base_url}/sendVideo"
                field_name = "video"
            else:
                endpoint = f"{base_url}/sendDocument"
                field_name = "document"

            with open(media_path, "rb") as media_file:
                res = requests.post(endpoint, data=data, files={field_name: media_file}, timeout=60)
            res_json = res.json()
            if res_json.get("ok"):
                return PASS2_STATUS_SENT, res_json.get("result", {}).get("message_id")
            logger.error(f"Telegram Bot API Error: {res_json}")
            return PASS2_STATUS_FAILED, None

        elif text:
            endpoint = f"{base_url}/sendMessage"
            payload = {
                "chat_id": DEST_CHAT_ID,
                "text": text,
                "disable_web_page_preview": False
            }
            if reply_to_message_id:
                payload["reply_to_message_id"] = reply_to_message_id

            res = requests.post(endpoint, json=payload, timeout=20)
            res_json = res.json()
            if res_json.get("ok"):
                return PASS2_STATUS_SENT, res_json.get("result", {}).get("message_id")
            logger.error(f"Telegram Bot API Error: {res_json}")
            return PASS2_STATUS_FAILED, None

        return PASS2_STATUS_FAILED, None

    except Exception as e:
        logger.error(f"Error sending via bot API: {e}")
        return PASS2_STATUS_FAILED, None


def send_via_bot(text=None, media_path=None, caption=None, reply_to_message_id=None):
    """ส่งข้อความหรือมีเดียผ่าน Telegram Bot API ไปยัง DEST_CHAT_ID รองรับ Thread / Reply"""
    _, msg_id = _send_via_bot_status(
        text=text,
        media_path=media_path,
        caption=caption,
        reply_to_message_id=reply_to_message_id,
    )
    return msg_id


def split_long_message(text: str, limit: int = 4000) -> list[str]:
    """Split text exceeding Telegram's 4096-char limit cleanly on paragraph/line boundaries."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
                current = ""
            if len(para) <= limit:
                current = para
            else:
                for line in para.splitlines():
                    cand_line = f"{current}\n{line}" if current else line
                    if len(cand_line) <= limit:
                        current = cand_line
                    else:
                        if current:
                            chunks.append(current)
                        current = line[:limit]
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


async def _relay_text_message(text: str, reply_to_id: int | None) -> tuple[bool, int | None]:
    """Send text via Bot API first (splitting >4000-char messages) and fall back to Telethon only on transport failure."""
    is_ok_pass2, pass2_reason, cleaned_p2 = is_worthy_news_item(text or "", has_media=False)
    if not is_ok_pass2:
        logger.warning(f"🚨 [Pass 2 Egress Blocked] บล็อกก่อนส่ง: {pass2_reason}")
        return True, None

    chunks = split_long_message(cleaned_p2, limit=4000)
    first_msg_id = None
    cur_reply = reply_to_id

    for chunk in chunks:
        dest_msg_id = None
        if BOT_TOKEN:
            try:
                payload = {
                    "chat_id": DEST_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": False,
                }
                if cur_reply:
                    payload["reply_to_message_id"] = cur_reply
                res = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json=payload,
                    timeout=20,
                ).json()
                if res.get("ok"):
                    dest_msg_id = res.get("result", {}).get("message_id")
                else:
                    logger.error(f"Telegram Bot API Error: {res}")
            except Exception as e:
                logger.error(f"Error sending via bot API: {e}")

        if not dest_msg_id:
            sent = await client.send_message(DEST_CHAT_ID, chunk, reply_to=cur_reply)
            dest_msg_id = getattr(sent, "id", None)

        if first_msg_id is None and dest_msg_id:
            first_msg_id = dest_msg_id
            cur_reply = first_msg_id

    return False, first_msg_id


@client.on(events.NewMessage(chats=SOURCE_CHAT_ID))
async def handle_new_message(event):
    message = event.message

    # 0. Check message author: must be the official news channel or linked discussion admin bot
    if message.sender_id not in OFFICIAL_SENDERS:
        logger.info(f"🚫 [Filter Skip] Blocked: Message sent by regular group member (sender {message.sender_id}) (ID: {message.id})")
        return

    raw_text = get_message_full_text(message)
    is_webpage_preview = isinstance(getattr(message, "media", None), MessageMediaWebPage)
    has_media = bool(message.media) and not is_webpage_preview

    # Check parent reply info to isolate chat Q&A from official channel news
    parent_sender_id = None
    is_parent_official = False
    if message.reply_to and hasattr(message.reply_to, "reply_to_msg_id"):
        try:
            parent_msg = await event.get_reply_message()
            if parent_msg:
                parent_sender_id = parent_msg.sender_id
                # Official source channel (official channel) or linked discussion admin bot (linked admin bot)
                is_parent_official = parent_sender_id in OFFICIAL_SENDERS
        except Exception as e:
            logger.debug(f"Could not fetch parent reply sender: {e}")

    # 🛡️ Precision Quality Gate: Filter out pure chat banter, member Q&A, and casual chatter
    is_allowed, filter_reason, cleaned_text = is_worthy_news_item(
        raw_text, has_media, parent_sender_id=parent_sender_id, is_parent_channel=is_parent_official
    )
    if not is_allowed:
        logger.info(f"🚫 [Filter Skip] {filter_reason} (ID: {message.id})")
        return

    logger.info(f"📥 ข้อความใหม่ผ่านเกณฑ์ (ID: {message.id}): {cleaned_text[:40]}...")

    reply_to_id = None
    if message.reply_to and hasattr(message.reply_to, "reply_to_msg_id"):
        parent_src_id = message.reply_to.reply_to_msg_id
        reply_to_id = msg_map.get(parent_src_id)
        if reply_to_id:
            logger.info(f"↪️ ตรวจพบ Reply ไปยังข้อความ ID {parent_src_id} -> ผูกเป็น Reply ปลายทาง ID {reply_to_id}")

    temp_dir = Path(__file__).parent / "temp_media"
    temp_dir.mkdir(exist_ok=True)

    dest_msg_id = None
    pass2_blocked = False
    try:
        if has_media:
            logger.info("📦 กำลังดาวน์โหลดไฟล์มีเดีย...")
            file_path = await message.download_media(file=str(temp_dir))
            if file_path:
                try:
                    logger.info(f"📤 ส่งมีเดียต่อผ่าน Bot: {file_path}")
                    send_status, dest_msg_id = _send_via_bot_status(
                        media_path=file_path,
                        caption=cleaned_text,
                        reply_to_message_id=reply_to_id,
                    )
                    if send_status == PASS2_STATUS_BLOCKED:
                        pass2_blocked = True
                    elif not dest_msg_id:
                        sent = await client.send_file(DEST_CHAT_ID, file_path, caption=cleaned_text, reply_to=reply_to_id)
                        dest_msg_id = getattr(sent, "id", None)
                finally:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
            elif cleaned_text:
                logger.info("📤 ส่งข้อความต่อผ่าน Bot...")
                pass2_blocked, dest_msg_id = await _relay_text_message(cleaned_text, reply_to_id)
        elif cleaned_text:
            logger.info("📤 ส่งข้อความต่อผ่าน Bot...")
            pass2_blocked, dest_msg_id = await _relay_text_message(cleaned_text, reply_to_id)

        if pass2_blocked:
            logger.warning(f"🚨 [Pass 2 Abort] ยกเลิกการส่งต่อข้อความ ID {message.id} (ไม่ fallback ไปยัง Telethon Client)")
            return

        if dest_msg_id:
            # 🛡️ Pass 3 (Post-Send Watchdog Safety Net):
            # ตรวจสอบซ้ำทันทีที่ข้อความส่งออกไป หากพบว่าหลุดเกณฑ์ให้สั่ง Auto-Delete ทิ้งทันทีใน 0.5 วินาที!
            is_audit_ok, audit_fail_reason, _ = is_worthy_news_item(
                cleaned_text,
                has_media=has_media,
                parent_sender_id=parent_sender_id,
                is_parent_channel=is_parent_official,
            )
            if not is_audit_ok:
                logger.critical(f"🚨 [WATCHDOG AUTO-DELETE] Dest Msg ID {dest_msg_id} ไม่ผ่านเกณฑ์ตรวจสอบหลังส่ง ({audit_fail_reason})! กำลังลบทิ้งfrom destination channel...")
                try:
                    if BOT_TOKEN:
                        del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                        requests.post(del_url, json={"chat_id": DEST_CHAT_ID, "message_id": dest_msg_id}, timeout=10)
                    await client.delete_messages(DEST_CHAT_ID, dest_msg_id)
                    logger.info(f"🗑️ ลบข้อความ ID {dest_msg_id} removed from destination channel.")
                except Exception as del_err:
                    logger.error(f"Failed to auto-delete: {del_err}")
                return

            msg_map[message.id] = dest_msg_id
            logger.info(f"✅ ส่งต่อสำเร็จ! (Source ID {message.id} -> Dest ID {dest_msg_id})")
            
            # 📡 บันทึกชื่อหุ้นที่ถูกเมนชันเข้าเรดาร์เทคนิคอลอัตโนมัติ และบันทึกประวัติข้อความสำหรับ Deduplication
            try:
                from almond_cave.channel_tracker import record_channel_mentions, record_channel_143_message
                record_channel_mentions(cleaned_text, source="destination channel")
                record_channel_143_message(cleaned_text, msg_id=dest_msg_id)
            except Exception as e:
                logger.warning(f"Failed to record channel ticker mentions/message: {e}")
        else:
            logger.warning(f"⚠️ ไม่สามารถส่งต่อข้อความ ID {message.id}")
        
    except Exception as e:
        logger.error(f"❌ เกิดข้อผิดพลาดในการส่งต่อข่าว: {e}")


async def main():
    logger.info("🚀 กำลังเริ่มต้นTelegram News Sync Worker...")
    while True:
        try:
            await client.connect()

            if not await client.is_user_authorized():
                await client.start()

            source_name = str(SOURCE_CHAT_ID)
            try:
                entity = await client.get_entity(SOURCE_CHAT_ID)
                source_name = getattr(entity, 'title', getattr(entity, 'username', str(SOURCE_CHAT_ID)))
            except Exception:
                pass

            logger.info(f"👂 Listening to configured source feed...")
            logger.info(f"🎯 ปลายทางที่จะส่งต่อ: ID {DEST_CHAT_ID}")
            logger.info("✨ ระบบพร้อมทำงาน 100% รอรับข่าวสารใหม่...")

            await client.run_until_disconnected()
        except Exception as e:
            logger.warning(f"⚠️ การเชื่อมต่อหลุดชั่วคราว ({e}) — กำลังเชื่อมต่อใหม่ใน 10 วินาที...")
            try:
                await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
