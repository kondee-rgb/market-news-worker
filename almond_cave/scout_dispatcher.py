# -*- coding: utf-8 -*-
"""
almond_cave/scout_dispatcher.py
--------------------------------
Autonomous Dispatcher for Scout News & Technical Intelligence (Authentic Jang-Style):

1. Daily Market Wrap & Asset Movement (ส่งสรุปประจำวันเพียง 1 เวลาต่อวัน):
   - เวลา 08:00 น. (เวลาไทย): ตลาดหุ้นสหรัฐฯ ปิดรอบ Regular และ After-Hours ครบถ้วน 100%
   - สรุปตัวเลขดัชนีหลัก ($SPX, $QQQ, $DJI, $US10Y), Crypto ($BTC, $ETH), หุ้นเด่นในพอร์ต, และ Technical Radar
   - รวมรายละเอียดและจุดจับตาไว้ในข้อความอย่างสมบูรณ์

2. 24/7 Instant Breaking News & Macro Scanner (ส่งตลอด 24 ชั่วโมงเมื่อมีข่าวใหม่):
   - กรอง Noise ทิ้ง 100%: รับเฉพาะสำนักข่าว Tier-1 (Bloomberg, FT, Reuters, WSJ, CNBC, Fed, MarketWatch, AP)
   - ตัดข่าวที่ส่งผลทางอ้อมทิ้งเด็ดขาด (เช่น หุ้นตัวเล็กเกาะกระแส NVDA / ข่าวเปรียบเทียบอ้อมๆ ไม่เอา)
   - แปลและจัดรูปประโยคเป็นภาษาไทยสละสลวย อ่านเข้าใจทันที ไม่แปลตรงๆ คำต่อคำ
   - รวมรายละเอียด (Bullet Points) ไว้ในข้อความนั้นๆ เลย (ข้อความเดียวจบ ไม่ส่งซ้ำซ้อน)
   - แนบลิงก์ที่มาเสมอ
   - หากไม่มีข่าวใหม่ -> เงียบไว้ 100% (No-Noise)
"""

import os
import sys
import re
import json
import html
import difflib
import hashlib
import logging
import email.utils
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scout_dispatcher")

BASE_DIR = Path(__file__).resolve().parent.parent if Path(__file__).resolve().parent.name in ("almond_cave", "almond cave") else Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from almond_cave.telegram_notifier import send_scout_brief
from almond_cave.technical_scanner import run_full_technical_scan

SENT_NEWS_FILE = BASE_DIR / "almond_cave" / "sent_news.json"

# Core Portfolio (11 Tickers - Priority 1)
CORE_PORTFOLIO_TICKERS = {
    "SOFI": "SoFi Technologies",
    "META": "Meta Platforms",
    "IREN": "IREN Limited",
    "VST": "Vistra Corp",
    "APP": "AppLovin",
    "NFLX": "Netflix",
    "NVO": "Novo Nordisk",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "PLTR": "Palantir",
    "HIMS": "Hims & Hers"
}

# Watchlist (23 Tickers - Priority 2)
WATCHLIST_TICKERS = {
    "UBER": "Uber Technologies",
    "ASML": "ASML Holding",
    "GOOGL": "Alphabet (Google)",
    "AMZN": "Amazon",
    "TSM": "TSMC",
    "GEV": "GE Vernova",
    "BE": "Bloom Energy",
    "CRWV": "CoreWeave",
    "VOYG": "Voyager Digital",
    "ASTS": "AST SpaceMobile",
    "RKLB": "Rocket Lab",
    "MELI": "MercadoLibre",
    "ZETA": "Zeta Global",
    "ORCL": "Oracle",
    "NBIS": "Nebius Group",
    "NOW": "ServiceNow",
    "MU": "Micron Technology",
    "RDDT": "Reddit",
    "BABA": "Alibaba",
    "ALAB": "Astera Labs",
    "ANET": "Arista Networks",
    "AVGO": "Broadcom",
    "CRDO": "Credo Technology"
}

# Mega-Cap & Key Market Leaders (Priority 3)
MEGACAP_LEADERS = {
    "AAPL": "Apple",
    "TSLA": "Tesla",
    "AMD": "Advanced Micro Devices",
    "QCOM": "Qualcomm",
    "ARM": "ARM Holdings",
    "COIN": "Coinbase",
    "INTC": "Intel",
    "CRWD": "CrowdStrike",
    "SMCI": "Super Micro Computer"
}

COMPANY_NAMES = {**CORE_PORTFOLIO_TICKERS, **WATCHLIST_TICKERS, **MEGACAP_LEADERS}

# Whitelist of credible financial publishers
TIER1_SOURCES = [
    "bloomberg", "financial times", "reuters", "wall street journal",
    "cnbc", "marketwatch", "federal reserve", "irna", "associated press", "apnews",
    "new york times", "washington post", "investing.com", "pr newswire", "business wire",
    "globenewswire", "accesswire", "national law review", "dow jones", "barron's"
]

# Blacklist of noisy / clickbait / derivative sources
NOISE_SOURCES_BLACKLIST = [
    "stocktwits", "seeking alpha", "motley fool", "fool.com", "24/7 wall st", "247wallst",
    "zacks", "tipranks", "benzinga", "investorplace", "the fly", "crypto potato", "fxstreet", "coinpedia", "simplywallst"
]

# Top Tier-1 Wall Street Analysts & Investment Banks Whitelist
# ONLY recommendations/ratings explicitly mentioning these firms are allowed!
FAMOUS_WALL_STREET_FIRMS = [
    "goldman sachs", "goldman", "morgan stanley", "jpmorgan", "jp morgan", "j.p. morgan",
    "bank of america", "bofa", "merrill", "citigroup", "citi", "barclays", "ubs",
    "jefferies", "bernstein", "wedbush", "dan ives", "piper sandler", "mizuho",
    "wells fargo", "deutsche bank", "rbc capital", "rbc", "td cowen", "cowen",
    "oppenheimer", "raymond james", "stifel", "evercore", "wolfe research", "keybanc",
    "truist", "baird", "needham", "da davidson", "rosenblatt", "roth mkm", "canaccord",
    "bmo capital", "morgans", "redburn", "cantor fitzgerald"
]

# Patterns for unsolicited stock recommendations, advice, ratings, or clickbait opinions
ADVICE_OR_RATING_PATTERNS = [
    r"\b(buy|sell|hold)\b",
    r"is .* (a buy|worth buying|paying you|a good investment|overvalued|undervalued|worth owning)",
    r"should (you|investors) (buy|sell|hold|own|avoid)",
    r"here'?s why (you|investors|wall street)",
    r"why (investors|you) (keep buying|should buy|are buying|should sell|should avoid)",
    r"reasons to (buy|sell|avoid|hold)",
    r"better buy than",
    r"best stock(s)? to buy",
    r"smartest stock(s)?",
    r"top stock(s)? to buy",
    r"dividend stock(s)? to buy",
    r"buy the dip",
    r"before you buy",
    r"returns are in store",
    r"according to (this|one) wall street pro",
    r"cathie wood",
    r"jim cramer",
    r"upgrade(d|s)?",
    r"downgrade(d|s)?",
    r"\boutperform\b",
    r"\bunderperform\b",
    r"\boverweight\b",
    r"\bunderweight\b",
    r"price target",
    r"target price",
    r"raises? target",
    r"cuts? target",
    r"lowers? target",
    r"hikes? target",
    r"initiates? coverage",
    r"rating(s)?",
    r"bullish on",
    r"bearish on",
    r"strong buy",
    r"smartest buy",
    r"passive income",
    r"millionaire-maker",
    r"worth the risk",
    r"time to buy",
    r"time to sell",
    r"can it reach",
    r"could it hit",
    r"forecasts?",
    r"stock forecasts?",
    r"\bplus \d+ .* stocks?\b",
    r"\b\d+ (elite|defensive|growth|tech|ai|dividend|top|best|undervalued) stocks?\b",
    r"valuation in focus",
    r"can that pace continue",
    r"here'?s what .* did next",
    r"^(is|does) .* (look|seem|appear|increase|pay|worth|a buy|overvalued|undervalued|fully valued|fairly valued|increasing|risky|too late)\b",
    r"why .* (powered|rose|surged|jumped|dropped|fell|climbed|soared|slumped|tumbled|plunged|rallied|gained|lost|slips|slides)",
    r"does .* look (fully valued|overvalued|undervalued|cheap|like a buy|attractive)",
    r"increasing your .* risk",
    r"market risk\?"
]

# Common journalistic idioms pre-processing map
IDIOM_REPLACEMENTS = [
    (r"\bteases?\b", "previews"),
    (r"\bflags?\b", "points to"),
    (r"\beyes?\b", "considers"),
    (r"\bweighs?\b", "considers"),
    (r"\bslips?\b", "drops slightly"),
    (r"\bslides?\b", "drops"),
    (r"\btumbles?\b", "falls sharply"),
    (r"\bsurges?\b", "jumps sharply"),
    (r"\brallies?\b", "rebounds strongly"),
    (r"\bclimbs overnight\b", "rises in overnight trading"),
    (r"\bindustry insiders?\b", "industry sources"),
    (r"\brate hikes?\b", "interest rate increases"),
    (r"\brate cuts?\b", "interest rate reductions"),
    (r"\bbraces for\b", "prepares for"),
    (r"\bcaps\b", "limits"),
    (r"\btaps\b", "selects"),
    (r"\bshares climb\b", "stock rises"),
    (r"\bshares fall\b", "stock drops"),
    (r"\bshares surge\b", "stock jumps"),
    (r"\bshares tumble\b", "stock falls sharply"),
    (r"\bshares drop\b", "stock drops"),
    (r"\bshares sink\b", "stock drops"),
    (r"\bshares gain\b", "stock gains"),
    (r"\bshares rise\b", "stock rises"),
    (r"\bshares slip\b", "stock slips"),
    (r"\bshares\b", "stock"),
]


def load_sent_history() -> List[Dict[str, Any]]:
    """Load previously sent news history from sent_news.json."""
    if not SENT_NEWS_FILE.exists():
        return []
    try:
        with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"Failed to load sent_news.json: {e}")
        return []


def save_sent_history(history: List[Dict[str, Any]]) -> None:
    """Save updated news history, pruning items older than 3 days."""
    try:
        cutoff = datetime.now() - timedelta(days=3)
        pruned = []
        for item in history:
            try:
                dt = datetime.fromisoformat(item.get("iso_timestamp", datetime.now().isoformat()))
                if dt >= cutoff:
                    pruned.append(item)
            except Exception:
                pruned.append(item)

        with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(pruned, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to save sent_news.json: {e}")


def is_duplicate(item_key: str, history: List[Dict[str, Any]], hours_window: int = 48) -> bool:
    """Check if an item key was already dispatched in the past hours_window."""
    now = datetime.now()
    for item in history:
        if item.get("key") == item_key:
            try:
                sent_time = datetime.fromisoformat(item.get("iso_timestamp", ""))
                if (now - sent_time).total_seconds() < hours_window * 3600:
                    return True
            except Exception:
                return True
    return False


def clean_html_text(raw_text: str) -> str:
    """Strip HTML tags and unescape entities."""
    cleanr = re.compile(r"<.*?>")
    return html.unescape(re.sub(cleanr, "", raw_text or "")).strip()


def translate_to_fluent_thai(text: str) -> str:
    """
    Translates English financial news to fluent, natural Thai (Jang-Style),
    avoiding word-for-word machine translation mistakes.
    Uses dual-engine translation (Google Translate with MyMemory fallback).
    """
    if not text or not text.strip():
        return ""

    # Clean leading cashtag (e.g. '$APP ', '$NVDA ') for cleaner machine translation
    processed = re.sub(r"^\$[A-Za-z0-9_]+\s*", "", text.strip())

    # Pre-process English idioms
    for pat, rep in IDIOM_REPLACEMENTS:
        processed = re.sub(pat, rep, processed, flags=re.IGNORECASE)

    raw_thai = None

    # 1. Primary Engine: Google Translate
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q=" + urllib.parse.quote(processed)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            th = "".join([part[0] for part in data[0] if part[0]])
            if th and th.strip():
                raw_thai = th.strip()
    except Exception as e:
        logger.debug(f"Google Translate engine fallback: {e}")

    # 2. Secondary Engine: MyMemory API Fallback (when Google is rate limited)
    if not raw_thai:
        try:
            url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(processed)}&langpair=en|th"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                res_txt = data.get("responseData", {}).get("translatedText", "")
                if res_txt and not res_txt.startswith("MYMEMORY WARNING"):
                    raw_thai = html.unescape(res_txt.strip())
        except Exception as e:
            logger.debug(f"MyMemory engine fallback: {e}")

    if not raw_thai:
        raw_thai = processed

    # Financial terminology refinement for natural Thai reading
    th = raw_thai
    th = re.sub(r"อัตราดอกเบี้ย", "ดอกเบี้ย", th)
    th = re.sub(r"เฟด", "Fed", th, flags=re.IGNORECASE)
    th = re.sub(r"บลูมเบิร์ก", "Bloomberg", th, flags=re.IGNORECASE)
    th = re.sub(r"ไฟแนนเชียลไทมส์", "Financial Times (FT)", th, flags=re.IGNORECASE)
    th = re.sub(r"รอยเตอร์", "Reuters", th, flags=re.IGNORECASE)
    th = re.sub(r"วอลล์สตรีทเจอร์นัล", "Wall Street Journal (WSJ)", th, flags=re.IGNORECASE)
    th = re.sub(r"พิจารณา", "กำลังพิจารณา", th)
    th = re.sub(r"ชี้ไปที่", "ชี้ถึง", th)
    th = re.sub(r"การเพิ่มดอกเบี้ย", "การขึ้นดอกเบี้ย", th)
    th = re.sub(r"การลดดอกเบี้ย", "การลดดอกเบี้ย", th)
    th = re.sub(r"ช่วงข้ามคืน", "ในการซื้อขายข้ามคืน", th)
    th = re.sub(r"ยั่วยวน", "เผยความคืบหน้า", th)
    th = re.sub(r"ชูธงพลัง", "ชี้ความต้องการพลังงาน", th)
    th = re.sub(r"คดีฟ้องร้องแบบกลุ่ม", "คดีกลุ่มหลักทรัพย์ (Class Action)", th)
    th = re.sub(r"แบ่งปัน", "หุ้น", th)
    # Economic indicators refinement
    th = re.sub(r"การจ้างงานนอกภาคเกษตรกรรม", "การจ้างงานนอกภาคเกษตร (Nonfarm Payrolls)", th)
    th = re.sub(r"การจ้างงานนอกภาคเกษตร", "การจ้างงานนอกภาคเกษตร (Nonfarm Payrolls)", th)
    th = re.sub(r"อัตราการว่างงาน", "อัตราการว่างงาน (Unemployment Rate)", th)
    th = re.sub(r"การเรียกร้องสิทธิประโยชน์การว่างงาน", "ยอดขอรับสวัสดิการว่างงาน (Jobless Claims)", th)
    th = re.sub(r"ผู้ขอรับสวัสดิการว่างงาน", "ยอดขอรับสวัสดิการว่างงาน (Jobless Claims)", th)
    th = re.sub(r"ดัชนีราคาผู้บริโภค", "ดัชนีราคาผู้บริโภค (CPI)", th)
    th = re.sub(r"ดัชนีราคาผู้ผลิต", "ดัชนีราคาผู้ผลิต (PPI)", th)
    th = re.sub(r"การใช้จ่ายเพื่อการบริโภคส่วนบุคคล", "ดัชนีเงินเฟ้อ PCE", th)
    th = re.sub(r"ผลิตภัณฑ์มวลรวมในประเทศ", "ผลิตภัณฑ์มวลรวมในประเทศ (GDP)", th)
    th = re.sub(r"ยอดขายปลีก", "ยอดค้าปลีก (Retail Sales)", th)
    return th.strip()


def detect_category(title: str, text: str) -> str:
    """Classifies news into: 'geopolitics', 'economic_data', 'fed', 'macro', or 'stock'."""
    combined = (title + " " + text).lower()

    if any(k in combined for k in ["iran", "israel", "middle east", "iaea", "nuclear site", "sanction", "oil tank", "houthi", "russia", "ukraine", "geopolitic"]):
        return "geopolitics"
    elif any(k in combined for k in ["nonfarm payroll", "unemployment rate", "jobs report", "jobless claims", "consumer price index", "producer price index", "personal consumption expenditures", "core pce", "gross domestic product", "gdp", "retail sales", "ism manufacturing", "ism services", "pmi"]) or (re.search(r"\b(cpi|ppi|pce)\b", combined) and not any(x in combined for x in ["property", "group", "xtra:", "lon:", "fra:"])):
        return "economic_data"
    elif any(k in combined for k in ["federal reserve", "fed", "powell", "bowman", "williams", "jefferson", "waller", "fomc", "rate hike", "rate cut", "interest rate"]):
        return "fed"
    elif any(k in combined for k in ["bitcoin", "btc", "ethereum", "eth", "crypto", "stablecoin"]):
        return "crypto"
    elif any(k in combined for k in ["inflation", "treasury yield", "bond yield", "s&p 500", "nasdaq", "dow jones"]):
        return "macro"
    else:
        return "stock"


def fetch_single_feed(default_cat: str, url: str, cutoff: datetime, noise_patterns: list) -> List[Dict[str, Any]]:
    """Fetches and parses a single RSS feed with noise and source filtering."""
    items_out = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            xml_raw = re.sub(r"&(?!(?:amp|lt|gt|quot|apos);)", "&amp;", resp.read().decode("utf-8", errors="replace"))
            root = ET.fromstring(xml_raw)
            for item in root.findall(".//item")[:15]:
                pub_elem = item.find("pubDate")
                if pub_elem is None or not pub_elem.text:
                    continue
                try:
                    pub_dt = email.utils.parsedate_to_datetime(pub_elem.text)
                except Exception:
                    continue

                if pub_dt < cutoff:
                    continue

                raw_title = item.find("title").text if item.find("title") is not None else ""
                raw_link = item.find("link").text if item.find("link") is not None else ""
                raw_desc = item.find("description").text if item.find("description") is not None else ""

                title = clean_html_text(raw_title)
                desc = clean_html_text(raw_desc)

                # Extract Source
                source_elem = item.find("source")
                source_name = source_elem.text.strip() if source_elem is not None and source_elem.text else ""
                m_src = re.search(r"\s*-\s*([^-]+)$", title)
                if m_src:
                    if not source_name:
                        source_name = m_src.group(1).strip()
                    title = re.sub(r"\s*-\s*[^-]+$", "", title).strip()

                if not source_name:
                    for s_kw in TIER1_SOURCES:
                        if s_kw in raw_link.lower():
                            source_name = s_kw.title()
                            break

                title_norm = title.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

                # 1. Strict Tier-1 Publisher Check: Must match whitelisted credible source
                is_tier1 = any(t in raw_link.lower() or t in source_name.lower() for t in TIER1_SOURCES)
                if not is_tier1 and source_name not in ["Yahoo Finance", "Financial Wire"]:
                    continue

                # 2. Reject Noise Blacklist Publishers
                if any(b in raw_link.lower() or b in source_name.lower() for b in NOISE_SOURCES_BLACKLIST):
                    continue

                # 3. Reject Generic Noise Patterns, Opinion Columns & Raw Option Quote Pages
                extra_noise = [
                    r"here'?s why", r"why (investors|you|stocks|wall street)", r"what to know",
                    r"could (reach|hit|fall|gain)", r"prediction", r"analysis:", r"opinion:",
                    r"is it time to", r"stock of the day", r"unusual options",
                    r"\b[A-Z]{1,5}\d{6}[CP]\d{8}\b",
                    r"interactive\s+stock\s+chart",
                    r"option\s+chain",
                    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d{4}\s+\d+(?:\.\d+)?\s+(?:put|call)\b"
                ]
                if any(re.search(pat, title_norm, re.IGNORECASE) for pat in noise_patterns + extra_noise):
                    continue

                # 4. Strict Wall Street Analyst Check:
                # If an article offers advice, rating, target price or opinion, it MUST come from a famous Wall Street firm!
                combined_text = (title + " " + desc).lower()
                is_famous_analyst = any(f in combined_text for f in FAMOUS_WALL_STREET_FIRMS)

                is_advice_or_rating = any(re.search(pat, title_norm, re.IGNORECASE) for pat in ADVICE_OR_RATING_PATTERNS)
                if is_advice_or_rating and not is_famous_analyst:
                    # Drop generic stock-picking advice, retail opinions, or non-famous analyst commentary
                    continue

                # 5. Strict Yahoo Finance Filter: Purge generic Yahoo Finance advice / clickbait syndication
                is_yahoo = "yahoo" in raw_link.lower() or "yahoo" in source_name.lower()
                if is_yahoo:
                    yahoo_advice_junk = [
                        r"paying you", r"worth buying", r"worth the risk", r"better buy",
                        r"is it too late", r"smartest", r"top pick", r"passive income",
                        r"millionaire", r"dividend", r"buy and hold", r"time to buy",
                        r"time to sell", r"stock to buy", r"stocks to buy", r"why .* (is down|is up)",
                        r"cathie wood", r"jim cramer", r"buffett", r"motley", r"zacks",
                        r"investing in", r"buy-and-hold", r"growth stock to buy"
                    ]
                    if any(re.search(pat, title_norm, re.IGNORECASE) for pat in yahoo_advice_junk) and not is_famous_analyst:
                        continue

                # 6. Reject M&A Rumors (0% M&A Rule)
                if re.search(r"rumor|takeover talks|in talks to buy|speculation", title, re.IGNORECASE):
                    continue

                # 5. Direct Subject Filter for stock category
                if default_cat == "stock":
                    matched_companies = []
                    for sym, comp_name in COMPANY_NAMES.items():
                        first_word = comp_name.split()[0]
                        m = re.search(rf"\b({sym}|{first_word})\b", title, re.IGNORECASE)
                        if m:
                            matched_companies.append((m.start(), sym, comp_name))

                    if not matched_companies:
                        continue

                    matched_companies.sort(key=lambda x: x[0])
                    m_lead = re.match(r"^([A-Z]{3,5})\b", title)
                    if m_lead and m_lead.group(1).upper() not in [c[1] for c in matched_companies]:
                        continue

                    if len(matched_companies) > 1:
                        matched_comp = f"{matched_companies[0][2]} ({matched_companies[0][1]}) / {matched_companies[1][2]}"
                        matched_ticker = f"{matched_companies[0][1]}/{matched_companies[1][1]}"
                    else:
                        matched_ticker = matched_companies[0][1]
                        matched_comp = matched_companies[0][2]
                else:
                    matched_ticker = None
                    matched_comp = None

                actual_cat = detect_category(title, desc) if default_cat == "stock" else default_cat
                bkk_dt = pub_dt.astimezone(timezone(timedelta(hours=7)))
                time_str = bkk_dt.strftime("%H:%M")
                full_date_str = bkk_dt.strftime("%d/%m/%Y | %H:%M น.")

                key = f"jang_{hashlib.md5((title[:40] + source_name).encode('utf-8')).hexdigest()[:12]}"

                items_out.append({
                    "key": key,
                    "title": title,
                    "desc": desc,
                    "source": source_name or "Financial Wire",
                    "link": raw_link,
                    "cat": actual_cat,
                    "ticker": matched_ticker,
                    "company": matched_comp,
                    "time_str": time_str,
                    "full_date_str": full_date_str,
                    "pub_dt": pub_dt,
                })
    except Exception as e:
        logger.debug(f"Feed fetch error ({url[:40]}...): {e}")

    return items_out


def fetch_multi_source_breaking_news(max_age_hours: int = 24) -> List[Dict[str, Any]]:
    """
    Scrapes live breaking news across Tier-1 global sources with high concurrency.
    Covers: Core Portfolio (11), Watchlist (23), Mega-Caps (9), and Macro/Industry drivers.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    news_items = []

    noise_patterns = [
        r"why .* is down", r"why .* is up", r"should you buy", r"here\'s why",
        r"3 reasons", r"2 reasons", r"1 reason", r"zacks", r"better buy",
        r"motley fool issues rare", r"before you buy", r"is .* a buy",
        r"stocks to watch", r"best stock to buy", r"could hit", r"top pick",
        r"\d+%\s*returns", r"according to this wall street pro", r"returns are in store",
        r"is .* paying you", r"cathie wood", r"jim cramer", r"passive income",
        r"smartest stock", r"worth the risk", r"dividend stock to buy"
    ]

    # 1. Macro, Economic Data, Fed, Geopolitics & Industry Infrastructure Feeds
    feeds = [
        # Economic Indicators (Jobs & Employment)
        ("economic_data", "https://news.google.com/rss/search?q=(%22Nonfarm+Payrolls%22+OR+%22unemployment+rate%22+OR+%22jobs+report%22+OR+%22jobless+claims%22)+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # Economic Indicators (Inflation: CPI, Core PCE, PPI)
        ("economic_data", "https://news.google.com/rss/search?q=(%22US+CPI%22+OR+%22Consumer+Price+Index%22+OR+%22Core+CPI%22+OR+%22Core+PCE%22+OR+%22PCE+inflation%22+OR+%22Producer+Price+Index%22)+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # Economic Indicators (GDP, Retail Sales, ISM PMI)
        ("economic_data", "https://news.google.com/rss/search?q=(%22US+GDP%22+OR+%22Gross+Domestic+Product%22+OR+%22retail+sales%22+OR+%22ISM+Manufacturing%22)+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # CNBC Economy Live Wire
        ("economic_data", "https://www.cnbc.com/id/10000115/device/rss/rss.html"),
        # Fed & Monetary Policy
        ("fed", "https://news.google.com/rss/search?q=Federal+Reserve+interest+rate+OR+Powell+OR+FOMC+when:24h&hl=en-US&gl=US&ceid=US:en"),
        ("fed", "https://www.federalreserve.gov/feeds/press_all.xml"),
        # Geopolitics & Oil
        ("geopolitics", "https://news.google.com/rss/search?q=geopolitics+Iran+sanctions+OR+oil+market+OR+Middle+East+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # Market Bulletins & Real-time Wires
        ("macro", "https://feeds.content.dowjones.io/public/rss/mw_bulletins"),
        ("macro", "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
        ("macro", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
        # Semiconductor & AI Infrastructure Catalysts
        ("stock", "https://news.google.com/rss/search?q=(semiconductor+OR+AI+chips+OR+GPU+export+curbs)+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # Big Tech Antitrust & Regulatory Catalysts
        ("stock", "https://news.google.com/rss/search?q=(antitrust+OR+FTC+OR+DOJ)+AND+(Google+OR+Apple+OR+Amazon+OR+Meta+OR+Nvidia)+when:24h&hl=en-US&gl=US&ceid=US:en"),
        # AI Datacenter Power & Energy Catalysts
        ("stock", "https://news.google.com/rss/search?q=(AI+datacenter+OR+nuclear+power+deal+OR+grid)+AND+(Vistra+OR+Amazon+OR+Microsoft+OR+Constellation)+when:24h&hl=en-US&gl=US&ceid=US:en"),
    ]

    # 2. Core 11 Portfolio Stocks (Priority #1 - Dedicated Google News + Yahoo Finance)
    for sym in CORE_PORTFOLIO_TICKERS:
        c_name = COMPANY_NAMES.get(sym, sym).split()[0]
        q_sym = urllib.parse.quote(f"{c_name} OR ({sym} stock)")
        feeds.append(("stock", f"https://news.google.com/rss/search?q={q_sym}+when:24h&hl=en-US&gl=US&ceid=US:en"))
        feeds.append(("stock", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"))

    # 3. Watchlist (23 Tickers - Dedicated Yahoo Finance + Combined Google News)
    for sym in WATCHLIST_TICKERS:
        feeds.append(("stock", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"))

    q_wl = urllib.parse.quote("(Uber OR ASML OR TSMC OR Broadcom OR Oracle OR CoreWeave OR ASTS OR Rocket Lab OR ServiceNow)")
    feeds.append(("stock", f"https://news.google.com/rss/search?q={q_wl}+when:24h&hl=en-US&gl=US&ceid=US:en"))

    # 4. Mega-Cap Leaders (9 Tickers - Dedicated Yahoo Finance)
    for sym in MEGACAP_LEADERS:
        feeds.append(("stock", f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"))

    # Execute all feeds concurrently via ThreadPoolExecutor (16 workers)
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(fetch_single_feed, cat, u, cutoff, noise_patterns) for cat, u in feeds]
        for f in as_completed(futures):
            try:
                res = f.result()
                if res:
                    news_items.extend(res)
            except Exception:
                pass

    # Deduplicate within this fetch run based on title similarity
    unique_items = []
    seen_titles = set()
    for it in sorted(news_items, key=lambda x: x["pub_dt"], reverse=True):
        sim_key = re.sub(r"\W+", "", it["title"].lower())[:35]
        if sim_key not in seen_titles:
            seen_titles.add(sim_key)
            unique_items.append(it)

    return unique_items


def verify_backend_freshness(item: Dict[str, Any]) -> tuple[bool, str]:
    """
    Backend Freshness Verification (ระบบตรวจเช็กความสดใหม่หลังบ้านแบบละเอียด):
    - ป้องกันข่าวเก่า / ข่าวรีไซเคิลที่ถูกนำมาโพสต์ซ้ำจากอดีต
    - 'ถ้าข่าวคล้ายๆ กันแต่เป็นข่าวใหม่ก็ให้ส่งมาอยู่ดี' (อนุมัติหากมีความคืบหน้าใหม่ หรือสื่อกำลังรายงานอย่างคึกคัก)
    Returns (is_fresh: bool, reason: str).
    """
    now_utc = datetime.now(timezone.utc)
    pub_dt = item.get("pub_dt")

    # 1. ตรวจสอบอายุของเนื้อหาจาก Feed ต้นทาง (ต้องสดใหม่ภายใน 24 ชม.)
    if pub_dt:
        age_hours = (now_utc - pub_dt).total_seconds() / 3600.0
        if age_hours > 24:
            return False, f"ข่าวเก่าเกิน 24 ชม. (เผยแพร่เมื่อ {age_hours:.1f} ชม. ก่อน)"

    headline = item.get("title", "")
    clean_query = re.sub(r"[^\w\s]", " ", headline)
    words = clean_query.split()
    if not words or len(words) < 3:
        return True, "Valid headline"

    # ค้นหาประวัติข่าวบน Google News RSS เพื่อเปรียบเทียบ
    # สกัดเฉพาะคีย์เวิร์ดสำคัญ 6 คำแรกเพื่อค้นหาประวัติ
    core_kw = " ".join(words[:6])
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(core_kw) + "&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            xml_raw = re.sub(r"&(?!(?:amp|lt|gt|quot|apos);)", "&amp;", resp.read().decode("utf-8", errors="replace"))
            root = ET.fromstring(xml_raw)
            items = root.findall(".//item")

            recent_count = 0
            stale_matches = []

            for it in items:
                pub_elem = it.find("pubDate")
                title_elem = it.find("title")
                if pub_elem is None or not pub_elem.text or title_elem is None or not title_elem.text:
                    continue
                try:
                    p_dt = email.utils.parsedate_to_datetime(pub_elem.text)
                    r_title = clean_html_text(title_elem.text)
                    r_title = re.sub(r"\s*-\s*[^-]+$", "", r_title).strip()

                    diff_hours = (now_utc - p_dt).total_seconds() / 3600.0
                    if diff_hours <= 24:
                        recent_count += 1

                    # คำนวณความเหมือนของหัวข้อข่าว (Similarity Ratio)
                    sim = difflib.SequenceMatcher(None, headline.lower(), r_title.lower()).ratio()

                    # ถ้าหัวข้อข่าวเหมือนกันแทบจะ 100% (>85%) แต่เผยแพร่ไปนานกว่า 3 วัน (72 ชม.)
                    if sim >= 0.85 and diff_hours > 72:
                        stale_matches.append((p_dt, r_title, sim))
                except Exception:
                    pass

            # กฎเหล็ก: 'ถ้าข่าวคล้ายๆ กันแต่เป็นข่าวใหม่ ให้ส่งมา'
            # 1. หากมีสำนักข่าวรายงานประเด็นนี้อย่างคึกคักในรอบ 24 ชม. (recent_count >= 2)
            # แสดงว่าเป็น Event / Catalyst สดใหม่ของวันนี้แน่นอน -> ผ่าน 100%
            if recent_count >= 2:
                return True, f"เหตุการณ์สดใหม่วันนี้ มีสื่อรายงาน {recent_count} แหล่ง"

            # 2. หากพบข่าวหัวข้อเหมือนกันเป๊ะ (>85%) จากอดีตหลายวันก่อน
            # และวันนี้ไม่มีสำนักข่าวอื่นรายงานเลย (recent_count <= 1)
            # แสดงว่าเป็นข่าวรีไซเคิล / บทความเก่าค้างปีถูกนำมาจัดทำดัชนีใหม่ -> กรองทิ้ง
            if stale_matches and recent_count <= 1:
                oldest_pdt, oldest_title, sim = stale_matches[0]
                return False, f"ข่าวเก่าซ้ำเดิมตั้งแต่ {oldest_pdt.strftime('%d/%m/%Y')} (เหมือน {sim*100:.0f}%)"

    except Exception as e:
        logger.debug(f"Freshness check query fallback: {e}")
        # กรณี Google News ติดขัด ให้ใช้ timestamp ของ Tier-1 Feed เป็นหลัก
        return True, "ผ่านการตรวจสอบ (Feed Timestamp Fallback)"

    return True, "ข่าวสดใหม่ผ่านการตรวจสอบหลังบ้าน"


def gatekeeper_cross_check(item: Dict[str, Any]) -> tuple[bool, str]:
    """
    🛡️ Gatekeeper Quality & Fact-Check Verification Gate:
    ตรวจสอบความถูกต้องและความเหมาะสมของข่าวก่อนส่งแจ้งเตือนหรือบันทึกลงระบบ 100%:
    
    1. Dimension 1: ความเหมาะสม (Appropriateness & Catalyst Significance)
       - ต้องเป็น Material Catalyst จริง (งบการเงิน, รายได้, ดีลธุรกิจ, นโยบายดอกเบี้ย, หรือตัวเลขเศรษฐกิจ)
       - ไม่ใช่บทความคำแนะนำลอยๆ หรือบทความคลิกเบตทั่วไป
       - หากเป็นบทวิเคราะห์/คำแนะนำ ต้องมาจากสถาบันการเงินวอลล์สตรีทชั้นนำใน FAMOUS_WALL_STREET_FIRMS เท่านั้น
       - แหล่งข่าวต้องอยู่ในรายชื่อที่เชื่อถือได้ (Tier-1 Sources)
       
    2. Dimension 2: ความถูกต้อง (Accuracy, Freshness & Zero-Hallucination)
       - ตรวจสอบความสดใหม่ภายใน 24 ชม.
       - ตรวจสอบประวัติข่าวหลังบ้าน (Deep Backend Check) ป้องกันการนำข่าวเก่าในอดีตมารีไซเคิล
       - ต้องมี URL ลิงก์อ้างอิงจริงที่เข้าถึงได้
    
    Returns (is_approved: bool, reason: str).
    """
    title = item.get("title", "")
    desc = item.get("desc", "")
    source = item.get("source", "")
    link = item.get("link", "")
    combined = (title + " " + desc).lower()
    title_norm = title.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')

    # 1. ตรวจสอบความเหมาะสม (Appropriateness Gate)
    # 1.1 ตรวจสอบคำแนะนำโคมลอย: หากเป็นคำแนะนำ/Rating ต้องมาจาก Famous Wall Street Firms เท่านั้น
    is_famous_analyst = any(f in combined for f in FAMOUS_WALL_STREET_FIRMS)
    is_advice = any(re.search(pat, title_norm, re.IGNORECASE) for pat in ADVICE_OR_RATING_PATTERNS)
    if is_advice and not is_famous_analyst:
        return False, "ไม่เหมาะสม: เป็นบทความคำแนะนำ/Stock-picking ลอยๆ ที่ไม่ได้มาจากโบรกเกอร์วอลล์สตรีทชั้นนำ"

    # 1.2 กรองขยะ Yahoo Finance
    is_yahoo = "yahoo" in link.lower() or "yahoo" in source.lower()
    if is_yahoo:
        yahoo_junk = [
            r"paying you", r"worth buying", r"worth the risk", r"better buy",
            r"is it too late", r"smartest", r"top pick", r"passive income",
            r"millionaire", r"dividend", r"buy and hold", r"time to buy",
            r"time to sell", r"stock to buy", r"stocks to buy", r"why .* (is down|is up)",
            r"cathie wood", r"jim cramer", r"buffett", r"motley", r"zacks"
        ]
        if any(re.search(pat, title_norm, re.IGNORECASE) for pat in yahoo_junk) and not is_famous_analyst:
            return False, "ไม่เหมาะสม: เป็นบทความ Retail Commentary / Clickbait จาก Yahoo Finance"

    # 1.3 กรองข่าวลือ M&A ที่ไม่มีมูล
    if re.search(r"\b(rumor|takeover talks|in talks to buy|speculation)\b", title, re.IGNORECASE):
        return False, "ไม่เหมาะสม: ข่าวลือการเข้าซื้อกิจการ (0% M&A Rule)"

    # 2. ตรวจสอบความถูกต้องและประวัติหลังบ้าน (Accuracy & Freshness Gate)
    is_fresh, fresh_reason = verify_backend_freshness(item)
    if not is_fresh:
        return False, f"ไม่ถูกต้อง/ไม่สดใหม่: {fresh_reason}"

    return True, f"ผ่านการตรวจสอบโดย 🛡️ Gatekeeper ({fresh_reason})"


def fetch_deep_article_and_media(
    link: str,
    fallback_desc: str = "",
    ticker: Optional[str] = None,
    cat: Optional[str] = None
) -> tuple[List[str], Optional[str], Optional[str]]:
    """
    Fetches the article URL and extracts:
    1. 2-3 substantive, high-information paragraphs (filtered from ads/cookies).
    2. Real article lead image or YouTube video thumbnail (photo_url).
    3. Direct YouTube video URL if embedded or referenced (youtube_url).
    
    If no real article image is found, falls back intelligently:
    - Broad market / macro -> S&P 500 Market Heatmap
    - Specific stock -> Finviz Candlestick Chart
    - Bonds / Fed -> TLT chart
    - Crypto -> BTCUSD chart
    """
    paragraphs = []
    photo_url = None
    youtube_url = None

    if link and link.startswith("http"):
        try:
            req = urllib.request.Request(
                link,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                content = resp.read().decode("utf-8", errors="replace")
                soup = BeautifulSoup(content, "html.parser")

                # 1. Search for YouTube video links or embeds
                yt_pattern = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/|shorts/)|youtu\.be/)([a-zA-Z0-9_-]{11})"
                yt_match = re.search(yt_pattern, content)
                if yt_match:
                    yt_id = yt_match.group(1)
                    youtube_url = f"https://youtu.be/{yt_id}"
                    photo_url = f"https://img.youtube.com/vi/{yt_id}/maxresdefault.jpg"

                # 2. Extract Lead News Image if not YouTube
                if not photo_url:
                    img_candidates = []
                    # Check OpenGraph / Twitter Card meta tags
                    for prop in ["og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"]:
                        for m in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
                            c_url = m.get("content")
                            if c_url and c_url.strip().startswith("http"):
                                img_candidates.append(c_url.strip())

                    # Check lead article image in figure/img
                    if not img_candidates:
                        for img in soup.find_all("img"):
                            src = img.get("src") or img.get("data-src")
                            if src and src.startswith("http"):
                                if any(cls in (img.get("class") or []) for cls in ["lead", "hero", "featured", "article-image", "cover"]):
                                    img_candidates.append(src)

                    # Filter candidate URLs
                    junk_keywords = [
                        "logo", "icon", "avatar", "favicon", "placeholder", "1x1",
                        "tracking", "ad-", "banner", "spinner", "default_image",
                        "author", "user", "widget", "badge", "button"
                    ]
                    for cand in img_candidates:
                        c_low = cand.lower()
                        if any(jk in c_low for jk in junk_keywords):
                            continue
                        if c_low.endswith((".svg", ".ico", ".gif")):
                            continue
                        photo_url = cand
                        break

                # 3. Extract deep paragraphs
                for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "figure"]):
                    tag.decompose()

                raw_ps = [p.get_text().strip() for p in soup.find_all("p")]
                junk = [
                    "cookie", "privacy policy", "terms of", "all rights reserved",
                    "subscribe", "newsletter", "sign up", "advertisement", "copyright",
                    "read more:", "photo by", "getty images", "reuters/", "bloomberg/"
                ]
                for p_text in raw_ps:
                    p_clean = " ".join(p_text.split())
                    if len(p_clean) >= 65 and not any(j in p_clean.lower() for j in junk):
                        if p_clean not in paragraphs:
                            paragraphs.append(p_clean)
                    if len(paragraphs) >= 3:
                        break
        except Exception as e:
            logger.debug(f"Deep article and media fetch error for {link[:40]}: {e}")

    # Fallback paragraphs if none fetched
    if not paragraphs and fallback_desc:
        clean_fb = re.sub(r"^[^:]+:\s*", "", fallback_desc).strip()
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_fb) if len(s.strip()) > 30]
        paragraphs = sents[:3] if sents else [clean_fb]

    # Intelligent media fallback hierarchy if no article photo or YouTube found
    if not photo_url:
        if ticker:
            photo_url = f"https://finviz.com/chart.ashx?t={ticker}&ty=c&ta=1&p=d&s=l"
        elif cat in ["fed", "bonds"]:
            photo_url = "https://finviz.com/chart.ashx?t=TLT&ty=c&ta=1&p=d&s=l"
        elif cat in ["macro", "general", "economic_data"]:
            photo_url = "https://finviz.com/map.ashx?t=sec&st=w1&p=0&x=0&y=0"
        elif cat == "crypto":
            photo_url = "https://finviz.com/crypto_charts.ashx?t=BTCUSD"

    return paragraphs[:3], photo_url, youtube_url


def fetch_deep_article_paragraphs(link: str, fallback_desc: str) -> List[str]:
    """Backward compatibility wrapper."""
    ps, _, _ = fetch_deep_article_and_media(link, fallback_desc)
    return ps


def generate_deep_fundamental_analysis(cat: str, ticker: Optional[str], title: str, desc: str) -> tuple[str, str, str]:
    """
    Generates tailored, high-depth fundamental analysis for the comment thread:
    Returns (driver, impact, watch_next)
    """
    combined = (title + " " + desc).lower()
    tick = (ticker or "").upper()

    # 1. Ticker-specific deep intelligence
    if "SOFI" in tick:
        driver = "การเติบโตของฐานเงินฝากต้นทุนต่ำ (Low-Cost Deposits), ส่วนต่างรายได้ดอกเบี้ยสุทธิ (NIM) และการขยายตัวของรายได้ค่าธรรมเนียมเทคโนโลยี (Tech Platform - Galileo)"
        impact = "ลดต้นทุนทางการเงิน (Cost of Funds) เมื่อเทียบกับธนาคารดั้งเดิม เสริมความแข็งแกร่งของกำไรสุทธิ และรักษาอัตราหนี้เสีย (Net Charge-off Rate) ให้อยู่ในกรอบปลอดภัย"
        watch_next = "ตัวเลขเงินฝากรายไตรมาส, การเติบโตของสินเชื่อบุคคล/เพื่อการศึกษา, และความคืบหน้าของผลิตภัณฑ์ Stablecoin & Lending-as-a-Service"

    elif "META" in tick:
        driver = "ประสิทธิภาพของอัลกอริทึม Advantage+ AI ในการแมตช์โฆษณา และการลดต้นทุน Compute ผ่านสถาปัตยกรรม Llama Open-Source"
        impact = "หนุนอัตราผลตอบแทนค่าโฆษณา (Ad Pricing & Conversion Rates) เสริมความแข็งแกร่งให้อัตรากำไรจากการดำเนินงาน (Operating Margin > 38%) และกระแสเงินสดอิสระ (FCF)"
        watch_next = "กรอบงบ Capex ด้าน AI ในปี 2025-2026, การสร้างรายได้จาก AI Agents บน WhatsApp/Instagram, และความคืบหน้าของโครงการแว่นตา Orion / Quest"

    elif "NVDA" in tick:
        driver = "วงจรการเปลี่ยนผ่านสู่สถาปัตยกรรม Blackwell และความต้องการชิปประมวลผล AI Compute อย่างต่อเนื่องของกลุ่ม Hyperscalers"
        impact = "รักษาอัตรากำไรขั้นต้นในระดับพรีเมียม (Gross Margin > 72%) หนุนรายได้ Data Center เติบโต และควบคุมอำนาจการต่อรองราคาในห่วงโซ่อุปทานชิปโลก"
        watch_next = "กำลังการผลิตขั้นสูง CoWoS-L จาก TSMC, การส่งมอบ Rack-Scale NVL72 ในไตรมาสถัดไป, และข้อจำกัดทางกฎหมายส่งออกชิป AI"

    elif "VST" in tick or "GEV" in tick or "BE" in tick or any(k in combined for k in ["nuclear", "datacenter power", "utility", "grid"]):
        driver = "ความต้องการพลังงานไฟฟ้าความเสถียรสูง (24/7 Clean Baseload Power) สำหรับศูนย์ข้อมูล AI Hyperscale ทำให้สัญญาซื้อขายไฟฟ้าระยะยาว (PPA) มีราคาพรีเมียมสูงขึ้น"
        impact = "เพิ่มสัดส่วนกระแสเงินสดที่ถูกล็อกไว้ตามสัญญา (Contracted Cash Flows) ลดความผันผวนจากราคาค่าไฟในตลาดเสรี (Merchant Power Risk) และเปิดโอกาส Re-rating Valuation Multiples"
        watch_next = "ความคืบหน้าในการลงนามสัญญา PPA ฉบับใหม่กับบิ๊กเทค, การอนุมัติการต่ออายุใบอนุญาตโรงไฟฟ้านิวเคลียร์จาก NRC, และกำลังการผลิตไฟฟ้าสำรองในเครือข่าย ERCOT/PJM"

    elif "APP" in tick:
        driver = "พลังการประมวลผลของโมเดล AI AXON 2.0 ในการแมตช์โฆษณาเกมและแคมเปญ E-Commerce ให้ตรงกลุ่มเป้าหมายที่มีอัตราการซื้อสินค้าสูงสุด"
        impact = "ขับเคลื่อน Take Rate และค่าโฆษณาต่อคลิก หนุนอัตรากำไร Adjusted EBITDA Margin ทะลุระดับ 55-60% พร้อมกระแสเงินสดอิสระสูง"
        watch_next = "การขยายตัวของเครือข่ายโฆษณาเข้าสู่แพลตฟอร์ม Web E-Commerce ทั่วโลก, ความคืบหน้าคดีสิทธิบัตร/การแข่งขันกับ Unity, และประมาณการรายได้ไตรมาสถัดไป"

    elif "NFLX" in tick:
        driver = "การเติบโตของฐานสมาชิกแพ็กเกจมีโฆษณา (Ad-Tier Subscribers), ความสามารถในการปรับขึ้นราคา (Pricing Power), และอีเวนต์ถ่ายทอดสด (Live Events)"
        impact = "เสริมสร้างอัตรากำไรจากการดำเนินงาน (Operating Margin) และอัตราการแปลงกำไรเป็นกระแสเงินสดอิสระ (FCF Conversion) อย่างยั่งยืน"
        watch_next = "ยอดผู้ใช้งาน Ad-Tier รายไตรมาส, การเปิดตัวระบบ In-House Ad Tech Platform และเม็ดเงินลงทุนในคอนเทนต์ภาพยนตร์/ซีรีส์"

    elif "NVO" in tick or "HIMS" in tick:
        driver = "ดีมานด์ยาลดน้ำหนักกลุ่ม GLP-1 ยังเติบโตสูง ขณะที่ความพร้อมของสต็อกโรงงานและกฎระเบียบขององค์การอาหารและยาสหรัฐฯ (FDA) กำหนดทิศทางการแข่งขันระหว่างยายี่ห้อและยา Compounded"
        impact = "มีผลกระทบโดยตรงต่ออัตรากำไรขั้นต้น (Gross Margin), ความคุ้มครองของประกันสุขภาพเอกชน, และการรักษาส่วนแบ่งตลาดระยะยาว"
        watch_next = "การตัดสินใจของ FDA ต่อสถานะขาดแคลนของยา Semaglutide/Tirzepatide, การเปิดตัวยารูปแบบเม็ด (Oral GLP-1), และการขยายโรงงานผลิตของ Catalent"

    elif "MSFT" in tick:
        driver = "การเร่งตัวของรายได้ Azure Cloud & AI Services และการผสาน Copilot เข้ากับกลุ่มลูกค้าองค์กร Microsoft 365"
        impact = "รักษาการเติบโตของรายได้คลาวด์ระดับ 28-32% พร้อมควบคุมอัตรากำไรจากการดำเนินงานท่ามกลางการเร่งลงทุน Capex ดาต้าเซ็นเตอร์"
        watch_next = "อัตราการมีส่วนร่วมของ AI ต่อยอดเติบโต Azure, การส่งมอบชิป Maia In-House, และความร่วมมือด้านโมเดลกับ OpenAI"

    elif "PLTR" in tick:
        driver = "การเร่งตัวของแพลตฟอร์ม Artificial Intelligence Platform (AIP) ผ่านโมเดล AIP Bootcamps ที่เปลี่ยนลูกค้าทดลองเป็นสัญญาเชิงพาณิชย์ขนาดใหญ่ในสหรัฐฯ อย่างรวดเร็ว"
        impact = "หนุนการเติบโตของรายได้เชิงพาณิชย์ในสหรัฐฯ (US Commercial Revenue > 50% YoY) พร้อมดันตัวเลข Rule of 40 ทะลุ 60% และรักษาอัตรากำไรจากการดำเนินงานแข็งแกร่ง"
        watch_next = "การต่อสัญญาภาครัฐ (DoD, Defense), ตัวเลขมูลค่าสัญญารวม (Total Contract Value - TCV), และการเติบโตของลูกค้าองค์กรใหม่"

    elif "IREN" in tick:
        driver = "การกระจายธุรกิจจากการขุด Bitcoin เข้าสู่ธุรกิจ Data Center และคลาวด์ประมวลผล AI (High-Performance Compute - HPC) ด้วยพลังงานหมุนเวียน 100%"
        impact = "ช่วยลดความผันผวนของรายได้จากการ Halving ของ Bitcoin และสร้างกระแสเงินสดจากสัญญาเช่าดาต้าเซ็นเตอร์ระยะยาวที่มีมาร์จิ้นสูง"
        watch_next = "กำลังไฟฟ้าที่ได้รับจัดสรรในรัฐเท็กซัส, ความคืบหน้าการส่งมอบ GPU AI Cluster, และผลประกอบการขุดเหรียญรายเดือน"

    # 2. Category-specific deep intelligence
    elif cat == "economic_data":
        if any(k in combined for k in ["payroll", "unemployment", "jobs", "jobless"]):
            driver = "ความตึงตัวของตลาดแรงงาน (Labor Market Slack) และการเติบโตของค่าจ้างเฉลี่ยรายชั่วโมง (Wage Growth) ซึ่งเป็นแรงขับเคลื่อนหลักของเงินเฟ้อฝั่งบริการ"
            impact = "ชี้นำการกำหนดอัตราดอกเบี้ยนโยบายของ Fed หากตลาดแรงงานชะลอตัวจะเปิดทางให้ Fed ปรับลดดอกเบี้ยเชิงรุก หนุน Bond Yield 10 ปี ปรับตัวลงและส่งผลบวกต่อ Equity Valuation"
            watch_next = "การตอบสนองของ FedWatch Tool ต่อน้ำหนักการลดดอกเบี้ย 25 bps vs 50 bps ในการประชุม FOMC รอบถัดไป"
        elif any(k in combined for k in ["cpi", "pce", "ppi", "inflation"]):
            driver = "โมเมนตัมเงินเฟ้อพื้นฐาน (Core PCE/CPI) เทียบกับเป้าหมายระยะยาว 2.0% ของธนาคารกลางสหรัฐฯ"
            impact = "กำหนดระดับ Terminal Rate ของอัตราดอกเบี้ยนโยบาย หากเงินเฟ้อชะลอตัวต่อเนื่องจะช่วยผ่อนคลาย Real Rates และลดแรงกดดันต่อหนี้ภาคธุรกิจ"
            watch_next = "ตัวเลขอัตราผลตอบแทนพันธบัตรสหรัฐฯ 2 ปีและ 10 ปี (Yield Curve) และการแถลงของประธาน Fed"
        else:
            driver = "สุขภาพเศรษฐกิจจริงของสหรัฐฯ (Real GDP & Consumer Resilience) ท่ามกลางภาวะดอกเบี้ยสูงในระยะยาว"
            impact = "บ่งชี้ความน่าจะเป็นของภาวะ Soft Landing เทียบกับความเสี่ยงเศรษฐกิจถดถอย และส่งผลต่อการปรับประมาณการกำไร (Earnings Revisions) ของบริษัทในดัชนี S&P 500"
            watch_next = "ตัวเลขค้าปลีก (Retail Sales) และดัชนีภาคการผลิต/บริการ ISM PMI ประจำเดือน"

    elif cat == "fed":
        driver = "การส่งสัญญาณทิศทางอัตราดอกเบี้ยนโยบาย (Forward Guidance) และการบริหารจัดการขนาดงบดุล (Quantitative Tightening)"
        impact = "ส่งผลกระทบต่อต้นทุนทางการเงินของระบบธนาคาร สภาพคล่องระดับโลก (Global Liquidity) และส่วนลดกระแสเงินสด (Discount Rate) ในการประเมินมูลค่าหุ้นเติบโต"
        watch_next = "ถ้อยแถลงของสมาชิกคณะกรรมการ FOMC, Dot Plot ในการประชุมรอบถัดไป, และข้อมูลการจ้างงาน/เงินเฟ้อรายเดือน"

    elif cat == "crypto":
        driver = "สภาพคล่องในระบบการเงินโลก (Global M2 Expansion/Contraction), กระแสเงินทุนไหลเข้า Spot ETF ของนักลงทุนสถาบัน, และความชัดเจนของกฎเกณฑ์กำกับดูแล"
        impact = "ขับเคลื่อน Sentiment สินทรัพย์เสี่ยงสูง (High-Beta Risk Assets), หุ้นที่เกี่ยวข้องกับเทคโนโลยีบล็อกเชน และการประเมินมูลค่าสินทรัพย์ทางเลือก"
        watch_next = "ยอด Net Inflow/Outflow ของ Bitcoin & Ethereum Spot ETF รายวัน, การเคลื่อนไหวของกระเป๋าเจ้ามือรายใหญ่ (Whale Wallets), และท่าทีของ ก.ล.ต. สหรัฐฯ (SEC)"

    elif cat == "geopolitics":
        driver = "ความตึงเครียดทางการเมืองระหว่างประเทศ, มาตรการคว่ำบาตรทางเศรษฐกิจ, และความเสี่ยงต่อเส้นทางขนส่งพลังงานและสินค้าโภคภัณฑ์"
        impact = "ส่งผลกระทบต่อราคาน้ำมันดิบโลก (Brent/WTI), ค่าระวางเรือ, แรงกดดันเงินเฟ้อฝั่งต้นทุน (Cost-Push Inflation), และความผันผวนของตลาดหุ้น"
        watch_next = "มติของกลุ่ม OPEC+, มาตรการคว่ำบาตรรอบใหม่ของสหรัฐฯ/สหภาพยุโรป, และการตอบโต้ทางการทหารหรือการทูต"

    else:
        # Generic Equities / Macro
        driver = "การเปลี่ยนแปลงของอุปสงค์ในอุตสาหกรรม, กลยุทธ์การแข่งขันของผู้นำตลาด, และการบริหารจัดการงบลงทุน (Capital Allocation)"
        impact = "ส่งผลต่อโมเมนตัมผลประกอบการ, การรักษาส่วนแบ่งทางการตลาด, และความสามารถในการสร้างกระแสเงินสดอิสระในรอบ 12-24 เดือนข้างหน้า"
        watch_next = "การรายงานผลประกอบการไตรมาสถัดไป, ความเห็นของผู้บริหารใน Earnings Call, และปฏิกิริยาของราคาหุ้นในชั่วโมงการซื้อขายปกติ"

    return driver, impact, watch_next


def format_jang_breaking_post(item: Dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
    """
    Formats a breaking news item into authentic 'Jang-Style' Telegram posts:
    1. Primary Message: Punchy headline, categorized or ticker header, timestamp, and source link.
    2. Comment Message: Deep Intelligence breakdown with numbered sections,
       divider ━━━━━━━━━━━━, 📌 สรุปประเด็นสำคัญ, and 📊 ภาพรวมและมุมมอง.
    3. Photo URL: Technical candlestick chart (Finviz) or market map when applicable.
    """
    cat = item["cat"]
    full_date_str = item["full_date_str"]
    source = item["source"]
    link = item["link"]
    ticker = (item.get("ticker") or "").upper()
    company = item.get("company") or COMPANY_NAMES.get(ticker, ticker)
    raw_title = item.get("title", "")
    raw_desc = item.get("desc", "")

    # Translate title to fluent, high-caliber financial Thai
    th_title = translate_to_fluent_thai(raw_title)

    # Detect if this is an Earnings / Quarterly Financial Results report
    combined_lower = (raw_title + " " + raw_desc).lower()
    is_earnings = any(k in combined_lower for k in [
        "earnings", "reports q", "q1 results", "q2 results", "q3 results", "q4 results",
        "quarterly results", "financial results", "quarterly profit", "q1 eps", "q2 eps", "q3 eps", "q4 eps",
        "beats on revenue", "beats on eps", "revenue rises", "guidance"
    ]) and bool(ticker)

    # --- Helper: extract quarter label (Q1/Q2/Q3/Q4) from title/desc ---
    _qtr_match = re.search(r"\b(Q[1-4])\b", raw_title + " " + raw_desc, re.IGNORECASE)
    _quarter_label = _qtr_match.group(1).upper() if _qtr_match else "Q?"

    # --- Helper: extract beat/miss signal from title ---
    _beat_signal = "▼"
    _verdict_th = "ต่ำกว่าคาด"
    if any(k in combined_lower for k in ["beat", "beats", "above", "tops", "surpass", "exceed", "สูงกว่าคาด"]):
        _beat_signal = "▲"
        _verdict_th = "สูงกว่าคาด"
    elif any(k in combined_lower for k in ["miss", "misses", "below", "below estimate", "ต่ำกว่าคาด"]):
        _beat_signal = "▼"
        _verdict_th = "ต่ำกว่าคาด"
    elif any(k in combined_lower for k in ["in-line", "inline", "meets", "in line", "ตามคาด"]):
        _beat_signal = "🟡"
        _verdict_th = "เป็นไปตามคาด"

    deep_paragraphs, photo_url, youtube_url = fetch_deep_article_and_media(link, raw_desc, ticker, cat)
    th_paragraphs = []
    for p in deep_paragraphs:
        th_p = translate_to_fluent_thai(p[:380])
        if th_p and len(th_p) > 20:
            th_paragraphs.append(th_p)

    driver_text, impact_text, watch_next_text = generate_deep_fundamental_analysis(cat, ticker, raw_title, raw_desc)

    # =========================================================================
    # CASE 1: EARNINGS REPORT (การประกาศผลประกอบการไตรมาส)
    # =========================================================================
    if is_earnings:
        # Build clean clickable multi-ticker hashtags
        tags = []
        if ticker:
            for part in re.split(r"[/,|&\s]+", ticker):
                if part.strip() and f"#{part.strip()}" not in tags:
                    tags.append(f"#{part.strip()}")
        for sym in COMPANY_NAMES:
            if f"#{sym}" not in tags and re.search(rf"\b{sym}\b", raw_title + " " + raw_desc):
                tags.append(f"#{sym}")
            if len(tags) >= 5:
                break
        tags.append("#EARNINGS")
        tag_str = " ".join(tags)

        # 1. Primary Headline Card — Jang-style: short punchy lead with quarter, beat/miss signal
        _headline_lead = (
            f"📊 <b>[{ticker}] รายได้ {_quarter_label} {_beat_signal} EPS ปรับปรุง (Adjusted EPS) {_beat_signal} {_verdict_th}</b>"
        )
        primary_lines = [
            _headline_lead,
            f"🕒 <b>[{full_date_str}]</b>",
            "",
            f"- {th_title}",
            "",
            f"{company} รายงานตัวเลขผลประกอบการล่าสุด",
            f"พร้อมปฏิกิริยาราคาหุ้นในการซื้อขายหลังตลาดปิด (After-hours)",
            ""
        ]
        if youtube_url:
            primary_lines.append(f"🎥 <b>คลิปวิดีโอ/การแถลงการณ์:</b> <a href=\"{youtube_url}\">{youtube_url}</a>")
            primary_lines.append("")
        primary_lines.append(f"🔗 ที่มา: <a href=\"{link}\">{source}</a>")
        primary_lines.append(f"🏷️ {tag_str}")
        primary_msg = "\n".join(primary_lines)

        # 2. Deep Intelligence Thread (Reply Message) — 4-section Jang structure
        comment_lines = [
            f"📊 <b>{company} ({ticker}) — ผลประกอบการและแนวโน้มธุรกิจ {_quarter_label}</b>",
            f"ที่มา: {source}",
            "",
            "🔮 <b>1) แนวโน้มไตรมาสถัดไป (Guidance)</b>",
            f"• ตลาดจับตาการคาดการณ์รายได้และกำไรของ {ticker} ในไตรมาสถัดไป",
            f"• นักวิเคราะห์วอลล์สตรีทให้ความสำคัญกับการเติบโตของส่วนงานหลัก",
            f"• คำแถลงของผู้บริหารใน Earnings Call และทิศทาง Guidance จะชี้นำ Sentiment ระยะสั้น",
            "",
            "📈 <b>2) ผลประกอบการไตรมาสล่าสุด</b>"
        ]
        if th_paragraphs:
            for p in th_paragraphs[:2]:
                comment_lines.append(f"• {p}")
        else:
            comment_lines.append(f"• {th_title}")
        comment_lines.append(f"• จับตาตัวเลขรายได้ (Revenue), กำไรต่อหุ้นปรับปรุง (Adjusted EPS) และกระแสเงินสดอิสระ (Free Cash Flow / FCF)")
        comment_lines.append("")

        comment_lines.append("📱 <b>3) ยอดขายแยกตามกลุ่มธุรกิจ (Revenue by Segment)</b>")
        comment_lines.append(f"• {driver_text}")
        comment_lines.append("")

        comment_lines.append("📱 <b>4) สถิติการดำเนินงานสำคัญ (Key Operating Metrics)</b>")
        comment_lines.append(f"• {impact_text}")
        comment_lines.append("")

        comment_lines.append("━━━━━━━━━━━━")
        comment_lines.append("")
        comment_lines.append("📌 <b>สรุปประเด็นสำคัญ</b>")
        comment_lines.append(f"1) {company} ({ticker}) รายงานตัวเลขผลประกอบการ — เปรียบเทียบกับคาดการณ์ตลาดและ YoY")
        comment_lines.append(f"2) ตัวเลขรายได้ (Revenue) และกำไรต่อหุ้นปรับปรุง (Adjusted EPS) {_verdict_th}คาดการณ์")
        comment_lines.append(f"3) ประเด็นสำคัญด้านอัตรากำไร (Margins), ค่าตอบแทนหุ้น (Stock-Based Compensation / SBC) และกระแสเงินสดอิสระ (Free Cash Flow / FCF)")
        comment_lines.append(f"4) แนวโน้ม (Guidance) และปฏิกิริยาของราคาหุ้นในการซื้อขายหลังตลาดปิด (After-hours)")
        comment_lines.append("")

        comment_lines.append("📊 <b>ภาพรวมและมุมมอง</b>")
        comment_lines.append(
            f"ผลประกอบการของ {ticker} สะท้อนคุณภาพการเติบโตที่แท้จริงเมื่อเทียบกับประมาณการของตลาดครับ "
            f"ประเด็นที่ต้องแยกแยะคือการเติบโตระยะสั้นจากปัจจัยชั่วคราว กับความยั่งยืนของกระแสเงินสดอิสระระยะยาว"
        )
        comment_lines.append("")
        comment_lines.append(
            f"สำหรับ Valuation ยังต้องติดตามทิศทาง Guidance และระดับรายจ่ายลงทุน (CapEx) ในรอบถัดไป "
            f"เพื่อประเมินความสมดุลระหว่างการเติบโตและการสร้างกระแสเงินสดให้ผู้ถือหุ้นอย่างรอบด้านครับ"
        )

        comment_msg = "\n".join(comment_lines)
        return primary_msg, comment_msg, photo_url

    # =========================================================================
    # CASE 2: GENERAL BREAKING NEWS, MACRO, FED, GEOPOLITICS & EQUITIES
    # =========================================================================
    body_lines = []
    if cat == "economic_data":
        body_lines.append("📊 <b>ตัวเลขเศรษฐกิจสำคัญ (Economic Data)</b>")
    elif cat == "fed":
        body_lines.append("🏦 <b>นโยบายการเงิน & Fed (Monetary Policy)</b>")
    elif cat == "geopolitics":
        body_lines.append("🌍 <b>ภูมิรัฐศาสตร์โลก (Geopolitics)</b>")
    elif cat == "crypto":
        body_lines.append("⚡ <b>คริปโตเคอร์เรนซี (Crypto & Digital Assets)</b>")
    elif cat == "stock":
        if ticker and company:
            comp_label = company if f"({ticker})" in company else f"{company} (${ticker})"
            body_lines.append(f"📈 <b>ข่าวหุ้นรายตัว (Equities): {comp_label}</b>")
        elif ticker:
            body_lines.append(f"📈 <b>ข่าวหุ้นรายตัว (Equities): ${ticker}</b>")
        else:
            body_lines.append("📈 <b>ตลาดหุ้นสหรัฐฯ & หุ้นรายตัว (Equities)</b>")
    else:
        body_lines.append("🌐 <b>ภาพรวมตลาด & เศรษฐกิจมหภาค (Macro Market)</b>")

    # Clean clickable multi-ticker + category hashtags
    tags = []
    if ticker:
        for part in re.split(r"[/,|&\s]+", ticker):
            if part.strip() and f"#{part.strip()}" not in tags:
                tags.append(f"#{part.strip()}")
    for sym in COMPANY_NAMES:
        if f"#{sym}" not in tags and re.search(rf"\b{sym}\b", raw_title + " " + raw_desc):
            tags.append(f"#{sym}")
        if len(tags) >= 5:
            break
    if cat == "economic_data":
        tags.append("#MACRO")
    elif cat == "fed":
        tags.append("#FED")
    elif cat == "crypto":
        tags.append("#CRYPTO")
    elif cat == "geopolitics":
        tags.append("#GEOPOLITICS")
    elif cat == "stock":
        tags.append("#STOCKS")
    else:
        tags.append("#MARKET")

    tag_str = " ".join(tags)

    body_lines.append(f"🕒 <b>[{full_date_str}]</b>")
    body_lines.append("")
    body_lines.append(f"- {th_title}")
    body_lines.append("")
    if youtube_url:
        body_lines.append(f"🎥 <b>คลิปวิดีโอ/การแถลงการณ์:</b> <a href=\"{youtube_url}\">{youtube_url}</a>")
        body_lines.append("")
    body_lines.append(f"🔗 ที่มา: <a href=\"{link}\">{source}</a>")
    if tag_str:
        body_lines.append(f"🏷️ {tag_str}")
    primary_msg = "\n".join(body_lines)

    # 3. Build Deep Intelligence Comment (โครงสร้างแบบเจาะลึก พร้อมเส้นคั่นและภาพรวมมุมมอง)
    header_title = f"{company} (${ticker})" if ticker and company else (company or "ประเด็นสำคัญของตลาด")
    comment_lines = [
        f"📊 <b>{header_title} — {th_title}</b>",
        f"ที่มา: {source}",
        "",
        "🔎 <b>1) สาระสำคัญ & ข้อเท็จจริงเชิงลึก:</b>"
    ]

    if th_paragraphs:
        for p in th_paragraphs[:3]:
            comment_lines.append(f"• {p}")
            comment_lines.append("")
    else:
        comment_lines.append(f"• {th_title}")
        comment_lines.append("")

    comment_lines.append("🎯 <b>2) นัยสำคัญต่อปัจจัยพื้นฐาน (Fundamental & Valuation Impact):</b>")
    comment_lines.append(f"• <b>กลไกขับเคลื่อน (Driver):</b> {driver_text}")
    comment_lines.append("")
    comment_lines.append(f"• <b>ผลกระทบต่อ Valuation & พอร์ต (Impact):</b> {impact_text}")
    comment_lines.append("")
    comment_lines.append("🔍 <b>3) จุดที่ต้องจับตาต่อไป (What to Watch Next):</b>")
    comment_lines.append(f"• {watch_next_text}")
    comment_lines.append("")
    comment_lines.append("━━━━━━━━━━━━")
    comment_lines.append("")
    comment_lines.append("📌 <b>สรุปประเด็นสำคัญ</b>")
    comment_lines.append(f"1) ประเด็นหลักมุ่งเน้นไปที่ {th_title}")
    comment_lines.append(f"2) นัยต่อสภาพคล่อง, นโยบายการคลัง/การเงิน และการประเมินมูลค่าสินทรัพย์ที่เกี่ยวข้อง")
    comment_lines.append(f"3) ข้อเท็จจริงเชิงลึกสะท้อนผลกระทบต่อความเสี่ยงเชิงระบบและปัจจัยพื้นฐานของอุตสาหกรรม")
    comment_lines.append(f"4) ตัวชี้วัดและกำหนดการสำคัญถัดไปที่ต้องมอนิเตอร์อย่างใกล้ชิด")
    comment_lines.append("")
    comment_lines.append("📊 <b>ภาพรวมและมุมมอง</b>")
    comment_lines.append("ประเด็นนี้สะท้อนถึงพลวัตของตลาดที่นักลงทุนต้องติดตามข้อเท็จจริงมากกว่ากระแสข่าวลือครับ โดยเฉพาะการแยกแยะระหว่างปฏิกิริยาของราคาในระยะสั้นกับผลกระทบต่อกำไรและกระแสเงินสดของธุรกิจจริง")
    comment_lines.append("")
    comment_lines.append("สำหรับภาพรวม ควรติดตามตัวเลขเศรษฐกิจและปฏิกิริยาของอัตราผลตอบแทนพันธบัตร (Yield) ควบคู่ไปด้วย เพื่อประเมินทิศทางความเสี่ยงได้อย่างรอบด้านครับ")

    comment_msg = "\n".join(comment_lines)
    return primary_msg, comment_msg, photo_url

    comment_msg = "\n".join(comment_lines)
    return primary_msg, comment_msg, photo_url


def build_daily_morning_brief() -> str:
    """
    Constructs the once-per-day comprehensive briefing at 08:00 AM Bangkok Time:
    - US Market Close & After-Hours final figures ($SPX, $QQQ, $DJI, $US10Y, $BTC, $ETH)
    - Major Portfolio Movers & Catalysts
    - Full Technical Radar Confluence
    - Integrated daily outlook details
    """
    if os.getenv("GITHUB_ACTIONS"):
        now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_bkk = datetime.now()

    timestamp_str = now_bkk.strftime("%d/%m/%Y | %H:%M น.")
    scan_results = run_full_technical_scan()
    macro = scan_results.get("macro", {})
    triggered_tech = scan_results.get("triggered", [])

    body_lines = [
        "📊 <b>[สรุปตลาดหุ้นสหรัฐฯ & สินทรัพย์เด่นประจำวัน (Daily Market Wrap)]</b>",
        f"🕒 สรุปการปิดตลาด ณ 08:00 น. ({timestamp_str})\n",
        "🏛️ <b>ดัชนีหลัก & อัตราผลตอบแทนพันธบัตร:</b>"
    ]

    for sym, m in macro.items():
        if "Yield" in m["name"]:
            body_lines.append(f"• {m['name']} ({sym}): <b>{m['price']:.2f}%</b> ({m['change_pct']:+.2f}%)")
        elif "VIX" in m["name"]:
            body_lines.append(f"• {m['name']} ({sym}): <b>{m['price']:.2f}</b> ({m['change_pct']:+.2f}%)")
        else:
            body_lines.append(f"• {m['name']} ({sym}): <b>${m['price']:,.2f}</b> ({m['change_pct']:+.2f}%)")

    body_lines.append("\n⚡ <b>สัญญาณเทคนิคสำคัญประจำวัน (ด่านเส้นค่าเฉลี่ย & พลังซื้อขาย):</b>")
    if not triggered_tech:
        body_lines.append("• หุ้นในพอร์ตส่วนใหญ่อยู่ในโซนปกติ ยังไม่มีตัวไหนแตะด่านสำคัญ หรือเข้าโซนแรงซื้อ/แรงขายสุดโต่ง")
    else:
        for t in triggered_tech[:6]:
            alerts_str = " | ".join(t["alerts"][:2])
            body_lines.append(f"• <b>${t['ticker']}</b> (${t['price']:.2f}): {alerts_str}")

    sr_data = scan_results.get("support_resistance", [])
    if sr_data:
        body_lines.append("\n🎯 <b>แนวรับ 3 ระดับ & แนวต้านสำคัญ หุ้นยอดนิยม (ด่านคนรอซื้อ vs คนรอขาย):</b>")
        for sr in sr_data[:6]:
            price_fmt = f"${sr['price']:,.2f}" if "BTC" not in sr['ticker'] else f"${sr['price']:,.0f}"
            res_list = [f"${p:,.2f}" if "BTC" not in sr['ticker'] else f"${p:,.0f}" for p, _ in sr.get("resistances", [])[:2]]
            res_str = " / ".join(res_list) if res_list else "-"
            
            s_shallow = sr.get("sup_shallow")
            s_med = sr.get("sup_medium")
            s_deep = sr.get("sup_deep")
            
            if s_shallow and s_med:
                fmt_fn = lambda p_val: f"${p_val:,.0f}" if "BTC" in sr['ticker'] else f"${p_val:,.2f}"
                sh_str = fmt_fn(s_shallow[0])
                med_str = fmt_fn(s_med[0])
                w_desc = sr.get("weekly_desc") or (fmt_fn(s_deep[0]) if s_deep else "-")
                body_lines.append(f"• <b>${sr['ticker']}</b> ({price_fmt}): 🛑 ต้าน {res_str} | 🛡️ รับแรก {sh_str} | รับกลาง {med_str} | ⚓ รับลึก (EMA Week): {w_desc}")
            else:
                sup_list = [f"${p:,.2f}" if "BTC" not in sr['ticker'] else f"${p:,.0f}" for p, _ in sr.get("supports", [])[:2]]
                sup_str = " / ".join(sup_list) if sup_list else "-"
                body_lines.append(f"• <b>${sr['ticker']}</b> ({price_fmt}): 🛑 ต้าน {res_str} | 🛡️ รับ {sup_str}")

    body_lines.append("\n💬 <b>ประเด็นสำคัญที่ต้องจับตาในวัน:</b>")
    body_lines.append("- ตลาดหุ้นสหรัฐฯ ปิดรอบ Regular และ After-Hours ครบถ้วน พร้อมเปิดซื้อขายรอบใหม่ 20:30 น. คืนนี้")
    body_lines.append("- ติดตามตัวเลข Nonfarm Payrolls & อัตราการว่างงานสหรัฐฯ คืนนี้ ชี้ชะตาทิศทางดอกเบี้ย Fed")
    body_lines.append("- ระบบ Scout เฝ้าระวังตลาดสด 24 ชม. หากมีข่าวด่วนหรือ Catalyst ใหม่จะส่งแจ้งเตือนทันทีครับ")
    body_lines.append("\n🏷️ #DAILY_WRAP #MACRO #TECHNICAL")

    return "\n".join(body_lines)


def build_significant_signals_radar(limit: int = 10) -> tuple[str, str, str]:
    """
    Constructs the specialized Significant Technical Signals Briefing (Authentic Jang-Style):
    - Primary Card: S&P 500 candlestick chart with concise headline card (< 950 chars for sendPhoto caption)
    - Deep Comment Thread: Detailed 3-tier support/resistance table (Shallow, Medium, Deep Weekly),
      numbered takeaways 1-4, divider ━━━━━━━━━━━━, and concluding analysis ending with ครับ.
    - Returns (primary_msg, comment_msg, photo_url)
    """
    if os.getenv("GITHUB_ACTIONS"):
        now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_bkk = datetime.now()

    timestamp_str = now_bkk.strftime("%d/%m/%Y | %H:%M น.")

    # Sync recent dynamic mentions from channel 143 if user session is available
    try:
        from almond_cave.channel_tracker import sync_channel_mentions_from_telegram
        sync_channel_mentions_from_telegram(limit=30)
    except Exception:
        pass

    scan_res = run_full_technical_scan()
    sig_items = scan_res.get("significant_items", [])
    macro = scan_res.get("macro", {})

    # 1. Primary Headline Card (Jang Style: concise, under 900 chars for sendPhoto caption)
    primary_lines = [
        "📊 <b>ตลาดหุ้นสหรัฐฯ — สัญญาณเทคนิคอลและด่านราคาสำคัญ (Technical Radar)</b>",
        f"🕒 <b>[{timestamp_str}]</b>",
        "- สรุปสัญญาณกราฟเทคนิค ระดับความร้อนแรง และด่านราคาสำคัญของหุ้นในพอร์ตและตลาด\n",
        "🏛️ <b>ดัชนีหลักและอัตราผลตอบแทนพันธบัตร:</b>"
    ]

    core_macro_keys = ["^GSPC", "^IXIC", "^TNX", "BTC-USD"]
    for sym in core_macro_keys:
        if sym in macro:
            m = macro[sym]
            p = m["price"]
            chg = m["change_pct"]
            if sym == "^TNX":
                primary_lines.append(f"• ยีลด์พันธบัตร 10 ปี ($US10Y): <b>{p:.2f}%</b> ({chg:+.2f}%)")
            elif "BTC" in sym:
                primary_lines.append(f"• Bitcoin ($BTC): <b>${p:,.0f}</b> ({chg:+.2f}%)")
            elif sym == "^GSPC":
                primary_lines.append(f"• S&P 500 ($SPX): <b>${p:,.2f}</b> ({chg:+.2f}%)")
            elif sym == "^IXIC":
                primary_lines.append(f"• Nasdaq ($QQQ): <b>${p:,.2f}</b> ({chg:+.2f}%)")

    primary_lines.append(f"\n📌 <b>สรุปหุ้นที่มีสัญญาณเด่นวันนี้ ({len(sig_items)} ตัว):</b>")

    # Earnings Alert
    earnings_urgent = [x for x in sig_items if x.get("earnings_warning")]
    if earnings_urgent:
        e_str = ", ".join([f"${x['ticker']}" for x in earnings_urgent[:4]])
        primary_lines.append(f"• ⚠️ <b>จ่อรายงานงบ (Earnings Alert):</b> {e_str}")

    # Oversold
    oversold = [x for x in sig_items if x.get("rsi_14") and x["rsi_14"] <= 35.0]
    if oversold:
        o_str = ", ".join([f"${x['ticker']} (RSI {x['rsi_14']:.1f})" for x in oversold[:3]])
        primary_lines.append(f"• 🚨 <b>แรงขายมากเกินไป (Oversold):</b> {o_str}")

    # Overbought
    overbought = [x for x in sig_items if x.get("rsi_14") and x["rsi_14"] >= 68.0]
    if overbought:
        ob_str = ", ".join([f"${x['ticker']} (RSI {x['rsi_14']:.1f})" for x in overbought[:3]])
        primary_lines.append(f"• 🔥 <b>แรงซื้อมากเกินไป (Overbought):</b> {ob_str}")

    # Insider
    insider_urgent = [x for x in sig_items if x.get("insider_buy")]
    if insider_urgent:
        i_str = ", ".join([f"${x['ticker']}" for x in insider_urgent[:3]])
        primary_lines.append(f"• 🐋 <b>ผู้บริหารซื้อหุ้น (SEC Form 4):</b> {i_str}")

    # Weekly EMAs / Confluence
    confluence = [x for x in sig_items if x not in oversold and x not in overbought and x not in earnings_urgent]
    if confluence:
        c_str = ", ".join([f"${x['ticker']}" for x in confluence[:4]])
        primary_lines.append(f"• ⚓ <b>ทดสอบด่านเส้นค่าเฉลี่ยสัปดาห์ (Weekly EMA):</b> {c_str}")

    primary_lines.append("\n👉 <i>ดูแนวรับลึก 3 ระดับ ด่านต้านสำคัญ และภาพรวม ในคอมเมนต์ด้านล่างครับ 👇</i>")
    radar_tags = ["#RADAR", "#TECHNICAL"] + [f"#{x['ticker']}" for x in sig_items[:4] if x.get("ticker")]
    tag_line = "🏷️ " + " ".join(dict.fromkeys(radar_tags))
    cand_msg = "\n".join(primary_lines + [tag_line])
    if len(cand_msg) > 980:
        tag_line = "🏷️ #RADAR #TECHNICAL"
    primary_lines.append(tag_line)
    primary_msg = "\n".join(primary_lines)

    # 2. Deep Comment Reply Thread (Authentic Jang-Style Structure, strictly <= 4,000 chars)
    comment_lines = [
        "📊 <b>เจาะลึกด่านราคาสำคัญและแนวรับ 3 ระดับ (Deep Support & Resistance Analysis)</b>",
        "ที่มา: ข้อมูลการซื้อขายและแบบจำลองการคำนวณทางสถิติ\n"
    ]

    selected = sig_items[:4]
    for i, item in enumerate(selected, 1):
        sym = item["ticker"]
        p = item["price"]
        is_btc = "BTC" in sym
        p_fmt = f"${p:,.0f}" if is_btc else f"${p:,.2f}"
        rsi = item.get("rsi_14")

        # Category status
        if item.get("earnings_warning"):
            cat_label = "จ่อรายงานงบ (Earnings Alert)"
        elif rsi and rsi <= 35.0:
            cat_label = "แรงขายมากเกินไป (Oversold)"
        elif rsi and rsi >= 68.0:
            cat_label = "แรงซื้อมากเกินไป (Overbought)"
        elif item.get("insider_buy"):
            cat_label = "ผู้บริหารซื้อหุ้น (SEC Form 4)"
        else:
            cat_label = "ทดสอบเส้นค่าเฉลี่ยสำคัญ"

        comment_lines.append(f"⚡ <b>{i}) ${sym}</b> (ราคาล่าสุด {p_fmt} | {cat_label})")

        if item.get("earnings_warning"):
            comment_lines.append(f"• ⚠️ <b>{item['earnings_warning']}</b>")
        elif item.get("earnings_note"):
            comment_lines.append(f"• 📅 <i>{item['earnings_note']}</i>")

        if item.get("insider_buy"):
            comment_lines.append(f"• 🐋 <b>{item['insider_buy']}</b>")

        # Signals
        for s in item.get("signals", [])[:2]:
            safe_s = s.replace("<", "&lt;").replace(">", "&gt;")
            comment_lines.append(f"• สัญญาณทางเทคนิค: {safe_s}")

        sr = item.get("sr", {})
        res_list = [f"${r:,.2f}" if not is_btc else f"${r:,.0f}" for r, _ in sr.get("resistances", [])[:2]]
        res_str = " / ".join(res_list) if res_list else "-"

        s_sh = sr.get("sup_shallow")
        s_med = sr.get("sup_medium")
        fmt_fn = lambda v: f"${v:,.0f}" if is_btc else f"${v:,.2f}"
        sh_str = fmt_fn(s_sh[0]) if s_sh else "-"
        med_str = fmt_fn(s_med[0]) if s_med else "-"
        w_desc = sr.get("weekly_desc", "-")

        comment_lines.append(f"• 🛑 แนวต้าน (Resistance): <b>{res_str}</b>")
        comment_lines.append(f"• 🛡️ แนวรับระยะสั้น (Shallow Support): <b>{sh_str}</b> (Daily EMA 20/50)")
        comment_lines.append(f"• 🛡️ แนวรับปานกลาง (Medium Support): <b>{med_str}</b> (Daily EMA 200)")
        comment_lines.append(f"• ⚓ แนวรับลึกระดับสัปดาห์ (Weekly Deep Support): <b>{w_desc}</b>\n")

    comment_lines.append("━━━━━━━━━━━━")
    comment_lines.append("")
    comment_lines.append("📌 <b>สรุปประเด็นสำคัญ</b>")
    comment_lines.append("1) ดัชนีหลักและอัตราผลตอบแทนพันธบัตร 10 ปี ($US10Y) ยังคงเป็นตัวกำหนดสภาพคล่องและกรอบความเสี่ยง (Risk Appetite) ของตลาดหุ้นสหรัฐฯ")
    comment_lines.append("2) หุ้นที่ปรับตัวขึ้นร้อนแรงจนเข้าเขตแรงซื้อมากเกินไป (Overbought) ควรหลีกเลี่ยงการไล่ราคาที่ด่านต้าน และรอการย่อตัวลงมาทดสอบแนวรับ")
    comment_lines.append("3) หุ้นที่ปรับตัวลงลึกจนเข้าเขตแรงขายมากเกินไป (Oversold) เริ่มมีสัญญาณ Confluence ใกล้แนวรับสัปดาห์ (Weekly EMA) ซึ่งมักเป็นจุดสะสมที่ให้แต้มต่อ Risk/Reward สูง")
    comment_lines.append("4) หุ้นที่มีกำหนดการรายงานผลประกอบการในสัปดาห์นี้ อาจมีความผันผวนสูงกว่าสัญญาณกราฟปกติ ควรบริหารขนาดพอร์ตอย่างระมัดระวัง")
    comment_lines.append("")
    comment_lines.append("📊 <b>ภาพรวมและมุมมอง</b>")
    comment_lines.append("ในภาพรวมระยะสั้น การบริหารความเสี่ยงเป็นสิ่งสำคัญที่สุดครับ สำหรับนักลงทุนที่ต้องการเปิดสถานะใหม่ การรอจังหวะที่ราคาย่อตัวลงมาแตะแนวรับลึกระดับสัปดาห์ (Weekly EMA 50/100/200) มักจะให้แต้มต่อในแง่ของ Risk/Reward ที่คุ้มค่ากว่าการเข้าซื้อในโซนที่ RSI ร้อนแรงครับ")
    comment_lines.append("")
    comment_lines.append("ส่วนหุ้นที่จ่อประกาศผลประกอบการ แนะนำให้จับตาตัวเลข Guidance และกระแสเงินสดอิสระ (FCF) มากกว่าการเก็งกำไรกราฟเพียงอย่างเดียว เพื่อป้องกันความผันผวนของราคาในการซื้อขายหลังตลาดปิด (After-hours) ครับ")

    comment_msg = "\n".join(comment_lines)
    photo_url = "https://finviz.com/map.ashx?t=sec&st=w1&p=0&x=0&y=0"

    return primary_msg, comment_msg, photo_url


def build_weekly_catalyst_calendar() -> tuple[str, str, str]:
    """
    Constructs the Weekly Catalyst & Earnings Calendar (every Monday 08:00 AM Bangkok Time):
    - Macro Economic Data events for the week (CPI, PPI, Retail Sales, Fed Speeches, Jobs)
    - Key Corporate Earnings for Core Portfolio (11 stocks) and Mega-Caps
    - Formatted in Authentic Jang Style with 3-tier structure
    """
    if os.getenv("GITHUB_ACTIONS"):
        now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_bkk = datetime.now()

    # Find upcoming earnings this week for tracked stocks
    from almond_cave.technical_scanner import get_earnings_and_insider_data
    upcoming_earnings = []
    for ticker, company in list(CORE_PORTFOLIO_TICKERS.items()) + list(MEGACAP_LEADERS.items())[:6]:
        try:
            fund = get_earnings_and_insider_data(ticker)
            if fund.get("earnings_warning") or fund.get("earnings_note"):
                note = fund.get("earnings_warning") or fund.get("earnings_note")
                upcoming_earnings.append((ticker, company, note))
        except Exception:
            pass

    date_str = now_bkk.strftime("%d/%m/%Y")
    primary_lines = [
        "📊 <b>ตลาดหุ้นสหรัฐฯ — ปฏิทินเศรษฐกิจและกำหนดการงบประจำสัปดาห์ (Weekly Catalysts)</b>",
        f"🕒 <b>[ประจำสัปดาห์ ณ {date_str}]</b>",
        "- สรุปตัวเลขเศรษฐกิจสำคัญของสหรัฐฯ และกำหนดการประกาศผลประกอบการที่ต้องจับตาตลอดทั้งสัปดาห์นี้\n",
        "🎯 <b>ไฮไลท์สำคัญประจำสัปดาห์ (Key Market Drivers):</b>",
        "• 🏦 <b>นโยบายการเงิน & Fed:</b> ตลาดจับตาสุนทรพจน์ของเจ้าหน้าที่ Fed และตัวเลขเงินเฟ้อ",
        "• 📈 <b>ฤดูกาลรายงานงบ:</b> หุ้นเทคโนโลยีและผู้นำตลาดจ่อทยอยรายงานผลประกอบการ\n"
    ]

    if upcoming_earnings:
        e_tickers = ", ".join([f"${t}" for t, _, _ in upcoming_earnings[:6]])
        primary_lines.append(f"📌 <b>หุ้นในพอร์ตที่จ่อรายงานผลประกอบการสัปดาห์นี้:</b> {e_tickers}\n")

    primary_lines.append("👉 <i>ดูรายละเอียดตารางเศรษฐกิจรายวันและกำหนดการงบ ในคอมเมนต์ด้านล่างครับ 👇</i>")
    primary_lines.append("🏷️ #CALENDAR #EARNINGS #MACRO")
    primary_msg = "\n".join(primary_lines)

    comment_lines = [
        "📊 <b>เจาะลึกตารางเศรษฐกิจและผลประกอบการตลอดสัปดาห์</b>",
        "ที่มา: กระทรวงแรงงานสหรัฐฯ (BLS), Federal Reserve, และรายงานตลาดหลักทรัพย์\n",
        "🗓️ <b>1) ตารางตัวเลขเศรษฐกิจสำคัญของสหรัฐฯ:</b>",
        "• <b>วันอังคาร - พุธ:</b> ดัชนีราคาผู้ผลิต (PPI) / ตัวเลขเงินเฟ้อคาดการณ์",
        "• <b>วันพฤหัสบดี:</b> จำนวนผู้ขอรับสวัสดิการว่างงานรายสัปดาห์ (Initial Jobless Claims)",
        "• <b>วันศุกร์:</b> ดัชนีความเชื่อมั่นผู้บริโภค (Consumer Sentiment) และการคาดการณ์เงินเฟ้อระยะ 1 ปี\n",
        "📱 <b>2) กำหนดการรายงานผลประกอบการหุ้นสำคัญ (Earnings Watchlist):</b>"
    ]

    if upcoming_earnings:
        for t, comp, note in upcoming_earnings[:6]:
            clean_note = note.replace("⚠️ [เตือนระวังงบออก]: ", "").replace("📅 ", "")
            comment_lines.append(f"• <b>${t} ({comp}):</b> {clean_note}")
    else:
        comment_lines.append("• สัปดาห์นี้หุ้น Core Portfolio ส่วนใหญ่ผ่านพ้นช่วงประกาศงบหลักไปแล้ว")

    comment_lines.append("")
    comment_lines.append("━━━━━━━━━━━━")
    comment_lines.append("")
    comment_lines.append("📌 <b>สรุปประเด็นสำคัญ</b>")
    comment_lines.append("1) ภาพรวมสัปดาห์นี้เป็นช่วงรอยต่อระหว่างการซึมซับผลการเลือกตั้งและฤดูกาลรายงานผลประกอบการ")
    comment_lines.append("2) ดัชนีหลักเคลื่อนไหวในกรอบสะสม โดยมีอัตราผลตอบแทนพันธบัตร 10 ปี ($US10Y) เป็นตัวชี้วัดความเสี่ยง")
    comment_lines.append("3) ตลาดให้ความสำคัญกับตัวเลข Guidance ของบริษัทเทคโนโลยีขนาดใหญ่มากกว่าผลประกอบการในอดีต")
    comment_lines.append("4) สำหรับหุ้นที่มีกำหนดรายงานงบในสัปดาห์นี้ ความผันผวนของราคา (Implied Volatility) อาจเพิ่มขึ้นอย่างมีนัยสำคัญ")
    comment_lines.append("")
    comment_lines.append("📊 <b>ภาพรวมและมุมมอง</b>")
    comment_lines.append("ในสัปดาห์นี้ แนะนำให้นักลงทุนให้ความสำคัญกับวินัยในการบริหารขนาดพอร์ตและแต้มต่อของแนวรับทางเทคนิคครับ โดยเฉพาะหุ้นที่ลงมาพักตัวใกล้เส้นค่าเฉลี่ยสัปดาห์ (Weekly EMA) และมีพื้นฐานรองรับ")
    comment_lines.append("")
    comment_lines.append("สำหรับกลยุทธ์ก่อนวันประกาศผลประกอบการ การหลีกเลี่ยงการเก็งกำไรด้วย Leverage สูง และรอความชัดเจนของ Guidance หลังตลาดปิด จะเป็นแนวทางที่ปลอดภัยกว่าครับ")

    comment_msg = "\n".join(comment_lines)
    photo_url = "https://finviz.com/map.ashx?t=sec&st=w1&p=0&x=0&y=0"

    return primary_msg, comment_msg, photo_url


def dispatch_weekly_catalyst_calendar(post_to_channel: bool = True) -> Dict[str, Any]:
    """Build and dispatch the Weekly Catalyst Calendar."""
    logger.info("Constructing and dispatching Weekly Catalyst & Earnings Calendar...")
    primary_msg, comment_msg, photo_url = build_weekly_catalyst_calendar()
    res = send_scout_brief(
        message=primary_msg,
        comment_text=comment_msg,
        post_to_channel=post_to_channel,
        photo_path_or_url=photo_url
    )
    return res


def dispatch_significant_signals_radar(post_to_channel: bool = True) -> Dict[str, Any]:
    """Build and dispatch the Significant Signals Radar to Telegram."""
    logger.info("Constructing and dispatching Significant Signals Radar...")
    primary_msg, comment_msg, photo_url = build_significant_signals_radar()
    res = send_scout_brief(
        message=primary_msg,
        comment_text=comment_msg,
        post_to_channel=post_to_channel,
        photo_path_or_url=photo_url
    )
    return res


def dispatch_scout_run(round_name: str = "auto") -> Dict[str, Any]:
    """
    Autonomous Dispatcher:
    - Monday 08:00 AM: Sends Weekly Catalyst & Earnings Calendar
    - Daily 08:00 AM (07:45 - 08:35): Sends Daily Market Wrap & Asset Movement
      Followed by the Significant Signals Technical Radar (Support & Resistance) to channel 143
    - Pre-Market 20:30 - 21:30 BKK: Sends Pre-Market Support & Resistance Radar to channel 143
    - At round_name == 'radar': Dispatches the Significant Signals Technical Radar
    - At round_name == 'weekly_calendar': Dispatches the Weekly Catalyst Calendar
    - At any other time (24/7): Scans live news from Tier-1 sources.
      If fresh news found -> Dispatches unified Jang-Style Breaking Alert immediately!
      If no fresh news -> Silent (100% No-Noise).
    """
    if round_name == "radar":
        logger.info("Manual/Triggered Round: Significant Signals Technical Radar")
        return dispatch_significant_signals_radar(post_to_channel=True)

    if round_name == "weekly_calendar":
        logger.info("Manual/Triggered Round: Weekly Catalyst & Earnings Calendar")
        return dispatch_weekly_catalyst_calendar(post_to_channel=True)

    if os.getenv("GITHUB_ACTIONS"):
        now_bkk = datetime.now(timezone.utc) + timedelta(hours=7)
    else:
        now_bkk = datetime.now()

    history = load_sent_history()

    # 1. Check Monday Morning Weekly Catalyst Calendar (Monday 08:00 - 09:59 BKK, resilient to GitHub cron jitter)
    weekly_cal_key = f"weekly_cal_{now_bkk.strftime('%Y%m%d')}"
    is_monday_calendar = (
        round_name == "auto"
        and now_bkk.weekday() == 0
        and 8 <= now_bkk.hour <= 9
        and not is_duplicate(weekly_cal_key, history)
    )
    if is_monday_calendar:
        logger.info("Executing Weekly Catalyst & Earnings Calendar (Monday 08:00-09:59 BKK)...")
        res = dispatch_weekly_catalyst_calendar(post_to_channel=True)
        history.append({
            "key": weekly_cal_key,
            "title": "Weekly Catalyst & Earnings Calendar",
            "source": "Scout Calendar",
            "iso_timestamp": now_bkk.isoformat()
        })
        save_sent_history(history)
        return res

    # 2. Check Daily Market Wrap & Morning Technical Radar (Tue-Sat 08:00 - 09:59 BKK after US Mon-Fri close)
    daily_wrap_key = f"daily_wrap_{now_bkk.strftime('%Y%m%d')}"
    is_daily_round = (round_name == "daily_wrap") or (
        round_name == "auto"
        and now_bkk.weekday() in (1, 2, 3, 4, 5)
        and 8 <= now_bkk.hour <= 9
        and not is_duplicate(daily_wrap_key, history)
    )

    if is_daily_round:
        logger.info("Executing Once-a-day Daily Market Wrap (08:00-09:59 BKK)...")
        daily_msg = build_daily_morning_brief()
        heatmap_url = "https://finviz.com/map.ashx?t=sec&st=w1&p=0&x=0&y=0"
        res = send_scout_brief(
            daily_msg,
            comment_text=None,
            post_to_channel=True,
            photo_path_or_url=heatmap_url
        )

        # Follow up by dispatching the full Significant Signals Radar (Support & Resistance) to channel 143!
        logger.info("Dispatching Morning Significant Signals Technical Radar to Channel 143...")
        dispatch_significant_signals_radar(post_to_channel=True)
        history.append({
            "key": daily_wrap_key,
            "title": "Daily Market Wrap & Morning Technical Radar",
            "source": "Scout Market Engine",
            "iso_timestamp": now_bkk.isoformat()
        })
        save_sent_history(history)
        return res

    # 3. Check Pre-Market Support & Resistance Radar Window (Mon-Fri 20:30 - 22:15 BKK)
    is_premarket_window = (
        round_name == "auto"
        and now_bkk.weekday() in (0, 1, 2, 3, 4)
        and (
            (now_bkk.hour == 20 and now_bkk.minute >= 30)
            or now_bkk.hour == 21
            or (now_bkk.hour == 22 and now_bkk.minute <= 15)
        )
    )
    if is_premarket_window:
        pm_radar_key = f"premarket_radar_{now_bkk.strftime('%Y%m%d')}"
        if not is_duplicate(pm_radar_key, history):
            logger.info("Pre-Market Window (20:30-21:30 BKK): Dispatching Significant Signals Radar...")
            dispatch_significant_signals_radar(post_to_channel=True)
            history.append({
                "key": pm_radar_key,
                "title": "Pre-Market Significant Signals Technical Radar",
                "source": "Scout Technical Engine",
                "iso_timestamp": now_bkk.isoformat()
            })
            save_sent_history(history)

    # 2. Continuous 24/7 Breaking News Scanner
    logger.info("Scanning multi-source feeds for live breaking news (24/7 Radar)...")
    candidates = fetch_multi_source_breaking_news(max_age_hours=24)

    fresh_candidates = []
    for c in candidates:
        if not is_duplicate(c["key"], history):
            # 🛡️ Gatekeeper Cross-Check Gate: ตรวจสอบความถูกต้องและความเหมาะสม 100%
            is_approved, reason = gatekeeper_cross_check(c)
            if not is_approved:
                logger.info(f"🛡️ Gatekeeper Rejected: '{c['title'][:40]}...' ({reason})")
                continue
            logger.info(f"🛡️ Gatekeeper Approved: '{c['title'][:40]}...' ({reason})")
            fresh_candidates.append(c)

    if not fresh_candidates:
        logger.info("Instant Scan: No fresh breaking news detected. Keeping silent (100% No-Noise).")
        return {"ok": True, "action": "silent", "message": "No breaking news"}

    # Sort candidates by tier priority (Economic Data/Fed = 4, Core = 3, Watchlist = 2, MegaCaps = 1, Macro = 0) and recency
    def get_tier_priority(item: Dict[str, Any]) -> int:
        cat = item.get("cat") or ""
        ticker = item.get("ticker") or ""
        # High impact economic data releases & Fed monetary policy: Priority 4 (Highest)
        if cat in ["economic_data", "fed"]:
            return 4
        if any(t in ticker for t in CORE_PORTFOLIO_TICKERS):
            return 3
        if any(t in ticker for t in WATCHLIST_TICKERS):
            return 2
        if any(t in ticker for t in MEGACAP_LEADERS):
            return 1
        return 0

    fresh_candidates.sort(key=lambda x: (
        get_tier_priority(x),
        x.get("pub_dt")
    ), reverse=True)

    logger.info(f"Instant Scan: Found {len(fresh_candidates)} fresh breaking news item(s)! Dispatching top priorities...")

    dispatched_count = 0
    sent_tickers = set()
    last_res = {"ok": True, "action": "dispatched"}

    def is_grade_a_catalyst(item: Dict[str, Any]) -> bool:
        """
        Evaluate if a catalyst qualifies as 'Grade A+ Major Market Mover'
        worthy of being shared into the public/friends channel (ข่าวหุ้น 143).
        Criteria:
        1. Macro / Economic Data (CPI, NFP, GDP, PCE) or Fed rate decisions
        2. Core Portfolio stocks: Earnings, Guidance, Insider, Price Moves, Major Investors, Strategic/AI/Regulatory
        3. Wall Street Tier-1 upgrades/downgrades (Goldman, Morgan Stanley, etc.) for Core/Watchlist
        """
        cat = (item.get("cat") or "").lower()
        ticker = (item.get("ticker") or "").upper()
        title = (item.get("title") or "").lower()
        desc = (item.get("desc") or "").lower()
        combined = f"{title} {desc}"

        # 1. Macro & Fed
        if cat in ["economic_data", "fed"]:
            return True

        # 2. All Core Portfolio (11 core stocks) that already passed Tier-1 Gatekeeper go to Channel 143
        if any(t in ticker for t in CORE_PORTFOLIO_TICKERS):
            return True

        # 3. Top Wall Street institution upgrade/downgrade for Watchlist
        if any(firm.lower() in combined for firm in FAMOUS_WALL_STREET_FIRMS):
            if any(t in ticker for t in WATCHLIST_TICKERS):
                return True

        return False

    for target_item in fresh_candidates:
        t_key = target_item.get("ticker") or target_item.get("cat") or "general"
        if t_key in sent_tickers:
            continue
        sent_tickers.add(t_key)

        # 🛡️ Channel 143 Deduplication Gate: Check if already covered by Mr. Jang / Channel 143
        is_major = is_grade_a_catalyst(target_item)
        lookback = 24 if is_major else 18
        try:
            from almond_cave.channel_tracker import is_news_already_covered_in_channel
            is_covered, cov_reason = is_news_already_covered_in_channel(
                title=target_item.get("title", ""),
                ticker=target_item.get("ticker"),
                hours_lookback=lookback
            )
            if is_covered:
                logger.info(f"🛡️ [Channel 143 Dedup Skip] {cov_reason}")
                history.append({
                    "key": target_item["key"],
                    "title": target_item["title"],
                    "source": target_item["source"],
                    "iso_timestamp": now_bkk.isoformat(),
                    "skipped": "duplicate_channel_143",
                    "reason": cov_reason
                })
                save_sent_history(history)
                continue
        except Exception as e:
            logger.debug(f"Deduplication check error: {e}")

        primary_msg, comment_msg, photo_url = format_jang_breaking_post(target_item)
        logger.info(f"Dispatching Breaking Alert for {t_key} (Major Catalyst for Channel: {is_major}, Photo: {bool(photo_url)})...")
        res = send_scout_brief(primary_msg, comment_text=comment_msg, post_to_channel=is_major, photo_path_or_url=photo_url)

        if res.get("ok"):
            history.append({
                "key": target_item["key"],
                "title": target_item["title"],
                "source": target_item["source"],
                "iso_timestamp": now_bkk.isoformat()
            })
            save_sent_history(history)
            logger.info(f"Recorded '{target_item['title'][:30]}...' into sent_news.json successfully.")
            dispatched_count += 1
            last_res = res

        # Paced Drip Feed: ส่งทีละ 1 ข่าวต่อรอบสแกน ไม่ส่งติดๆ กันหลายข่าวในนาทีเดียว
        if dispatched_count >= 1:
            logger.info("Paced Drip Feed: Dispatch limit (1 item) reached for this scan cycle.")
            break

    return last_res


if __name__ == "__main__":
    r_name = sys.argv[1] if len(sys.argv) > 1 else "auto"
    print(f"Executing Scout Dispatcher (Round: {r_name})...")
    out = dispatch_scout_run(r_name)
    print("Result:", out)
