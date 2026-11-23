# -*- coding: utf-8 -*-
"""
almond_cave/technical_scanner.py
---------------------------------
Comprehensive Technical & Macro Scanner for Scout Radar:
1. Weekly EMAs (50, 100, 200) - Macro structural trends
2. Daily EMAs (20, 50, 200) - Dynamic swing levels with Historical Bounce Rate check
3. RSI(14) Momentum & Divergence - Oversold (<= 30) & Overbought (>= 70)
4. Volume Spikes & Capitulation - Volume > 1.8x of 20-day average volume
5. Macro Snapshot & Economic Data Tracker (^GSPC, ^IXIC, ^TNX, BTC, ETH)
"""

import sys
import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("technical_scanner")

CORE_PORTFOLIO = [
    "SOFI", "META", "IREN", "VST", "APP",
    "NFLX", "NVO", "MSFT", "NVDA", "PLTR", "HIMS"
]

WATCHLIST = [
    "UBER", "ASML", "GOOGL", "AMZN", "TSM",
    "GEV", "BE", "CRWV", "VOYG", "ASTS",
    "RKLB", "MELI", "ZETA", "ORCL", "NBIS",
    "NOW", "MU", "RDDT", "BABA", "ALAB",
    "ANET", "AVGO", "CRDO"
]

POPULAR_RADAR_TICKERS = [
    "NVDA", "TSLA", "AAPL", "MSFT", "META", "GOOGL", "AMZN",
    "PLTR", "SOFI", "IREN", "ORCL", "AMD",
    "SPY", "QQQ", "BTC-USD"
]

MACRO_TICKERS = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^TNX": "US 10Y Yield",
    "^VIX": "VIX (Fear Index)",
    "CL=F": "WTI Crude Oil",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum"
}


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index (RSI)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def evaluate_ema_bounce_rate(df: pd.DataFrame, ema_series: pd.Series, span_name: str) -> Optional[str]:
    """
    Examine historical touches of a Daily EMA over the past 1-2 years.
    Returns a stat string if there is a significant bounce history (e.g. >= 60% bounce rate).
    """
    try:
        if len(df) < 60:
            return None

        # A "touch" occurs when Low <= EMA <= High (or within 1%)
        lows = df["Low"]
        highs = df["High"]
        closes = df["Close"]

        touch_mask = (lows <= ema_series * 1.01) & (highs >= ema_series * 0.99)
        touch_indices = df.index[touch_mask].tolist()

        if len(touch_indices) < 3:
            return None

        # Exclude recent 5 bars to assess forward return
        valid_touches = [idx for idx in touch_indices if df.index.get_loc(idx) < len(df) - 5]
        if len(valid_touches) < 3:
            return None

        bounces = 0
        for idx in valid_touches:
            pos = df.index.get_loc(idx)
            entry_p = closes.iloc[pos]
            forward_5_max = closes.iloc[pos + 1: pos + 6].max()
            if forward_5_max >= entry_p * 1.025:  # +2.5% bounce within 5 bars
                bounces += 1

        rate = (bounces / len(valid_touches)) * 100
        if rate >= 60.0:
            return f"สถิติจุดนี้ลงมาทีไรมักจะเด้งกลับ (เด้ง {rate:.0f}% จาก {len(valid_touches)} ครั้ง)"
        return None
    except Exception:
        return None


def scan_ticker_technicals(ticker_symbol: str) -> Optional[Dict[str, Any]]:
    """
    Fetch historical data for a ticker and evaluate:
    - 50-Week, 100-Week, 200-Week EMA (ภาษาคนเข้าใจง่าย)
    - Daily 20-Day, 50-Day, 200-Day EMA + Bounce Confluence
    - RSI(14) (แรงซื้อเยอะเกิน / แรงขายเยอะเกิน / Divergence)
    - Volume Spike (วอลุ่มผิดปกติ / รายใหญ่เข้าเก็บของ)
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(ticker_symbol)

        # 1. Weekly data for Weekly EMAs
        w_df = ticker.history(period="5y", interval="1wk")
        if w_df.empty or len(w_df) < 55:
            w_df = ticker.history(period="2y", interval="1wk")
            if w_df.empty:
                return None

        current_price = float(w_df["Close"].iloc[-1])

        # Weekly EMAs
        w_ema_50 = float(w_df["Close"].ewm(span=50, adjust=False).mean().iloc[-1]) if len(w_df) >= 50 else None
        w_ema_100 = float(w_df["Close"].ewm(span=100, adjust=False).mean().iloc[-1]) if len(w_df) >= 100 else None
        w_ema_200 = float(w_df["Close"].ewm(span=200, adjust=False).mean().iloc[-1]) if len(w_df) >= 200 else None

        # 2. Daily data (1-2 years) for Daily EMAs, RSI, Volume
        d_df = ticker.history(period="1y", interval="1d")
        if d_df.empty or len(d_df) < 25:
            return None

        d_closes = d_df["Close"]
        d_ema_20 = d_closes.ewm(span=20, adjust=False).mean()
        d_ema_50 = d_closes.ewm(span=50, adjust=False).mean()
        d_ema_200 = d_closes.ewm(span=200, adjust=False).mean() if len(d_df) >= 180 else None

        last_d_ema_20 = float(d_ema_20.iloc[-1])
        last_d_ema_50 = float(d_ema_50.iloc[-1])
        last_d_ema_200 = float(d_ema_200.iloc[-1]) if d_ema_200 is not None else None

        # RSI 14
        rsi_series = compute_rsi(d_closes, period=14)
        rsi_14 = float(rsi_series.iloc[-1]) if not rsi_series.empty else None

        # Volume
        recent_vol = float(d_df["Volume"].iloc[-1])
        avg_vol_20 = float(d_df["Volume"].iloc[-21:-1].mean()) if len(d_df) >= 21 else recent_vol
        vol_ratio = (recent_vol / avg_vol_20) if avg_vol_20 > 0 else 1.0

        alerts = []

        # Weekly EMA Alerts (+/- 2%)
        for ema_val, name in [
            (w_ema_50, "เส้น 50 สัปดาห์ (แนวรับรอบปี)"),
            (w_ema_100, "เส้น 100 สัปดาห์ (แนวรับรอบ 2 ปี)"),
            (w_ema_200, "เส้น 200 สัปดาห์ (ฐานใหญ่รอบ 4 ปี)")
        ]:
            if ema_val is not None:
                diff_pct = abs(current_price - ema_val) / ema_val * 100
                if diff_pct <= 2.0:
                    status = "ลงมาแตะ" if diff_pct <= 1.0 else "จ่อลงมาใกล้"
                    alerts.append(f"{status}{name} (${ema_val:.2f} | ห่าง {diff_pct:.1f}%)")

        # Daily EMA Alerts & Historical Bounce Confluence (+/- 1.5%)
        daily_emas = [
            (last_d_ema_20, d_ema_20, "เส้น 20 วัน (แนวรับระยะสั้น)"),
            (last_d_ema_50, d_ema_50, "เส้น 50 วัน (จุดพักตัวรอบกลาง)"),
            (last_d_ema_200, d_ema_200, "เส้น 200 วัน (ด่านชี้ชะตาขาขึ้น-ขาลงรอบปี)")
        ]
        for ema_val, ema_s, name in daily_emas:
            if ema_val is not None:
                diff_pct = abs(current_price - ema_val) / ema_val * 100
                if diff_pct <= 1.5:
                    bounce_stat = evaluate_ema_bounce_rate(d_df, ema_s, name)
                    bounce_text = f" -> 🎯 {bounce_stat}" if bounce_stat else ""
                    alerts.append(f"ลงมาทดสอบ {name} (${ema_val:.2f} | ห่าง {diff_pct:.1f}%){bounce_text}")

        # RSI Alerts & Divergence (ภาษาคนเข้าใจง่าย)
        if rsi_14 is not None:
            if rsi_14 <= 30.0:
                alerts.append(f"RSI {rsi_14:.1f} (🚨 แรงขายเยอะเกินไป / โดนเทหนัก ลุ้นเด้งสั้น)")
            elif rsi_14 >= 70.0:
                alerts.append(f"RSI {rsi_14:.1f} (🔥 แรงซื้อเยอะเกินไป / ร้อนแรง ระวังคนเทขายทำกำไร)")

            # Check Bullish / Bearish Divergence in pullback
            if len(d_closes) >= 15:
                p_min_recent = d_closes.iloc[-5:].min()
                p_min_prior = d_closes.iloc[-15:-5].min()
                r_min_recent = rsi_series.iloc[-5:].min()
                r_min_prior = rsi_series.iloc[-15:-5].min()
                if p_min_recent < p_min_prior and r_min_recent > r_min_prior and rsi_14 <= 45.0:
                    alerts.append("สัญญาณกลับตัว: ราคาลงแต่แรงขายเริ่มหมด (ลุ้นดีดกลับขึ้น)")

                p_max_recent = d_closes.iloc[-5:].max()
                p_max_prior = d_closes.iloc[-15:-5].max()
                r_max_recent = rsi_series.iloc[-5:].max()
                r_max_prior = rsi_series.iloc[-15:-5].max()
                if p_max_recent > p_max_prior and r_max_recent < r_max_prior and rsi_14 >= 65.0:
                    alerts.append("สัญญาณเตือน: ราคาขึ้นแต่แรงซื้อเริ่มแผ่ว (ระวังคนเทขายทำกำไร)")

        # 52-Week Range Extremes
        h_52w = float(d_df["High"].max())
        l_52w = float(d_df["Low"].min())
        diff_h = (abs(current_price - h_52w) / h_52w) * 100
        diff_l = (abs(current_price - l_52w) / l_52w) * 100

        if diff_h <= 2.0:
            alerts.append(f"🔥 ราคาวิ่งจ่อจุดสูงสุดรอบปี (${h_52w:.2f} | ห่าง {diff_h:.1f}%) ลุ้นเบรกไฮใหม่")
        elif diff_l <= 2.0:
            alerts.append(f"🚨 ราคาหลุดลงมาใกล้จุดต่ำสุดรอบปี (${l_52w:.2f} | ห่าง {diff_l:.1f}%) เสี่ยงไหลลงต่อ")

        # Volume Spike & Capitulation Radar
        day_chg_pct = float(((d_closes.iloc[-1] - d_closes.iloc[-2]) / d_closes.iloc[-2]) * 100) if len(d_closes) >= 2 else 0.0
        if vol_ratio >= 2.0 and recent_vol > 500000:
            if day_chg_pct <= -2.5:
                alerts.append(f"วอลุ่มเทรดทะลัก {vol_ratio:.1f} เท่า (🚨 คนเทขายยอมจำนนหนาแน่นผิดปกติ)")
            elif day_chg_pct >= 2.5:
                alerts.append(f"วอลุ่มเทรดทะลัก {vol_ratio:.1f} เท่า (🔥 รายใหญ่แย่งกันซื้อของก้อนโต)")
            else:
                alerts.append(f"วอลุ่มเทรดสูงผิดปกติ ({vol_ratio:.1f} เท่าของค่าเฉลี่ย 20 วัน)")
        elif vol_ratio >= 1.8 and recent_vol > 500000:
            alerts.append(f"วอลุ่มเทรดหนาแน่น ({vol_ratio:.1f} เท่าของค่าเฉลี่ย 20 วัน)")

        return {
            "ticker": ticker_symbol,
            "price": current_price,
            "weekly_ema_50": w_ema_50,
            "weekly_ema_100": w_ema_100,
            "weekly_ema_200": w_ema_200,
            "daily_ema_20": last_d_ema_20,
            "daily_ema_50": last_d_ema_50,
            "daily_ema_200": last_d_ema_200,
            "rsi_14": rsi_14,
            "vol_ratio": vol_ratio,
            "high_52w": h_52w,
            "low_52w": l_52w,
            "alerts": alerts,
        }

    except Exception as e:
        logger.warning(f"Error scanning {ticker_symbol}: {e}")
        return None


def get_macro_snapshot() -> Dict[str, Dict[str, Any]]:
    """Fetch snapshot of major indices and yields."""
    snapshot = {}
    try:
        import yfinance as yf
        for symbol, name in MACRO_TICKERS.items():
            t = yf.Ticker(symbol)
            df = t.history(period="5d", interval="1d")
            if not df.empty:
                last_price = float(df["Close"].iloc[-1])
                prev_price = float(df["Close"].iloc[-2]) if len(df) >= 2 else last_price
                chg_pct = ((last_price - prev_price) / prev_price) * 100 if prev_price else 0.0
                snapshot[symbol] = {
                    "name": name,
                    "price": last_price,
                    "change_pct": chg_pct,
                }
    except Exception as e:
        logger.warning(f"Error fetching macro snapshot: {e}")
    return snapshot


def calculate_support_resistance(ticker_symbol: str, df: Optional[pd.DataFrame] = None) -> Optional[Dict[str, Any]]:
    """
    Calculate Support (แนวรับ 3 ระดับ: ตื้น/กลาง/ลึก โดยรับลึกเป็น Weekly EMA 50/100/200) & Resistance (แนวต้าน) using:
    1. Swing Highs & Lows (20D, 60D, 120D, 52W)
    2. Dynamic Daily EMAs (20D, 50D, 100D, 200D)
    3. Classic Floor Pivot Points (PP, R1, R2, S1, S2, S3)
    4. Weekly EMAs (50W, 100W, 200W) for Macro Deep Support
    5. RSI(14) with plain human-readable momentum commentary
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker_symbol)
        if df is None or df.empty:
            df = t.history(period="1y", interval="1d")

        if df.empty or len(df) < 20:
            return None

        # Fetch Weekly data for Weekly EMAs (50W, 100W, 200W)
        w_df = t.history(period="5y", interval="1wk")
        w_ema_50 = None
        w_ema_100 = None
        w_ema_200 = None
        if not w_df.empty:
            w_closes = w_df["Close"]
            w_ema_50 = float(w_closes.ewm(span=50, adjust=False).mean().iloc[-1]) if len(w_closes) >= 50 else None
            w_ema_100 = float(w_closes.ewm(span=100, adjust=False).mean().iloc[-1]) if len(w_closes) >= 100 else None
            w_ema_200 = float(w_closes.ewm(span=200, adjust=False).mean().iloc[-1]) if len(w_closes) >= 200 else None

        closes = df["Close"]
        highs = df["High"]
        lows = df["Low"]

        current_price = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else current_price
        day_chg = ((current_price - prev_close) / prev_close) * 100

        # Dynamic EMAs
        ema_20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        ema_50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1]) if len(closes) >= 50 else None
        ema_100 = float(closes.ewm(span=100, adjust=False).mean().iloc[-1]) if len(closes) >= 100 else None
        ema_200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1]) if len(closes) >= 180 else None

        # Swing levels
        swing_high_20 = float(highs.iloc[-20:].max())
        swing_low_20 = float(lows.iloc[-20:].min())
        swing_high_60 = float(highs.iloc[-60:].max()) if len(highs) >= 60 else swing_high_20
        swing_low_60 = float(lows.iloc[-60:].min()) if len(lows) >= 60 else swing_low_20
        swing_low_120 = float(lows.iloc[-120:].min()) if len(lows) >= 120 else swing_low_60
        swing_low_year = float(lows.min())

        # Pivot Points based on previous trading session
        p_high = float(highs.iloc[-2]) if len(highs) >= 2 else float(highs.iloc[-1])
        p_low = float(lows.iloc[-2]) if len(lows) >= 2 else float(lows.iloc[-1])
        p_close = float(closes.iloc[-2]) if len(closes) >= 2 else float(closes.iloc[-1])

        pp = (p_high + p_low + p_close) / 3.0
        r1 = 2 * pp - p_low
        s1 = 2 * pp - p_high
        r2 = pp + (p_high - p_low)
        s2 = pp - (p_high - p_low)
        s3 = p_low - 2 * (p_high - pp)

        # RSI(14)
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)
        avg_gain = gain.ewm(com=13, min_periods=14).mean()
        avg_loss = loss.ewm(com=13, min_periods=14).mean()
        rs = avg_gain / avg_loss
        rsi = float(100 - (100 / (1 + rs)).iloc[-1])

        # Plain human-readable RSI description (ภาษาคนเข้าใจง่าย)
        if rsi < 30:
            rsi_desc = f"{rsi:.1f} (🚨 แรงขายเยอะเกิน / โดนเทหนัก ลุ้นเด้งสั้น)"
        elif rsi < 45:
            rsi_desc = f"{rsi:.1f} (แรงขายมากกว่าแรงซื้อ / ยังซึมลง)"
        elif rsi <= 55:
            rsi_desc = f"{rsi:.1f} (ซื้อขายพอกัน / แกว่งตัวนิ่งๆ รอดูเชิง)"
        elif rsi <= 70:
            rsi_desc = f"{rsi:.1f} (แรงซื้อแน่น / คนแย่งกันซื้อต่อเนื่อง)"
        else:
            rsi_desc = f"{rsi:.1f} (🔥 แรงซื้อเยอะเกินไป / ร้อนแรง ระวังคนเทขายทำกำไร)"

        # Synthesize Resistances (> current_price)
        potential_resistances = []
        if r1 > current_price * 1.002: potential_resistances.append((r1, "Pivot R1"))
        if r2 > current_price * 1.002: potential_resistances.append((r2, "Pivot R2"))
        if swing_high_20 > current_price * 1.004: potential_resistances.append((swing_high_20, "20-Day Swing High"))
        if swing_high_60 > current_price * 1.006 and abs(swing_high_60 - swing_high_20) / current_price > 0.01:
            potential_resistances.append((swing_high_60, "60-Day High"))
        if ema_20 > current_price * 1.003: potential_resistances.append((ema_20, "20D EMA"))
        if ema_50 and ema_50 > current_price * 1.003: potential_resistances.append((ema_50, "50D EMA"))
        if ema_200 and ema_200 > current_price * 1.003: potential_resistances.append((ema_200, "200D EMA"))

        potential_resistances.sort(key=lambda x: x[0])
        filtered_resistances = []
        for price, label in potential_resistances:
            if not any(abs(price - p) / price < 0.012 for p, _ in filtered_resistances):
                filtered_resistances.append((price, label))

        # Synthesize All Supports (< current_price)
        raw_supports = []
        if s1 < current_price * 0.998: raw_supports.append((s1, "Pivot S1"))
        if s2 < current_price * 0.998: raw_supports.append((s2, "Pivot S2"))
        if s3 < current_price * 0.998: raw_supports.append((s3, "Pivot S3"))
        if swing_low_20 < current_price * 0.995: raw_supports.append((swing_low_20, "20-Day Swing Low"))
        if swing_low_60 < current_price * 0.992: raw_supports.append((swing_low_60, "60-Day Low"))
        if swing_low_120 < current_price * 0.985: raw_supports.append((swing_low_120, "Major Low 6M"))
        if swing_low_year < current_price * 0.980: raw_supports.append((swing_low_year, "52W Low"))
        if ema_20 < current_price * 0.997: raw_supports.append((ema_20, "20D EMA"))
        if ema_50 and ema_50 < current_price * 0.997: raw_supports.append((ema_50, "50D EMA"))
        if ema_100 and ema_100 < current_price * 0.997: raw_supports.append((ema_100, "100D EMA"))
        if ema_200 and ema_200 < current_price * 0.997: raw_supports.append((ema_200, "200D EMA"))

        raw_supports.sort(key=lambda x: x[0], reverse=True)
        unique_supports = []
        for price, label in raw_supports:
            if not any(abs(price - p) / price < 0.012 for p, _ in unique_supports):
                unique_supports.append((price, label))

        # Natural 3-Tier Classification:
        # 1. รับแรก (Shallow / Minor Support): ด่านแรกที่ใกล้ราคาปัจจุบันที่สุด (~1-3%)
        # 2. รับกลาง (Medium / Key Support): ด่านวัดใจถัดไปที่มีระยะห่างพอสมควร (~4-7%)
        # 3. รับลึก (Deep / Weekly EMAs): เส้นค่าเฉลี่ยสัปดาห์ 50W, 100W, 200W EMA
        if unique_supports:
            sup_shallow = unique_supports[0]

            med_list = [s for s in unique_supports[1:] if (sup_shallow[0] - s[0]) / current_price >= 0.012]
            if med_list:
                sup_medium = med_list[0]
            elif len(unique_supports) > 1:
                sup_medium = unique_supports[1]
            else:
                sup_medium = (sup_shallow[0] * 0.97, "แนวรับกลาง")
        else:
            sup_shallow = (current_price * 0.98, "รับแรก")
            sup_medium = (current_price * 0.95, "รับกลาง")

        # Format helpers
        is_btc = "BTC" in ticker_symbol
        p_fmt = lambda p: f"${p:,.0f}" if is_btc else f"${p:,.2f}"

        # Weekly EMAs as Deep Support (รับลึก)
        weekly_support_items = []
        if w_ema_50 and w_ema_50 < current_price:
            weekly_support_items.append((w_ema_50, f"50W {p_fmt(w_ema_50)}"))
        if w_ema_100 and w_ema_100 < current_price:
            weekly_support_items.append((w_ema_100, f"100W {p_fmt(w_ema_100)}"))
        if w_ema_200 and w_ema_200 < current_price:
            weekly_support_items.append((w_ema_200, f"200W {p_fmt(w_ema_200)}"))

        if weekly_support_items:
            weekly_desc = " | ".join([desc for _, desc in weekly_support_items])
            sup_deep = (weekly_support_items[0][0], f"Weekly EMA ({weekly_support_items[0][1]})")
        else:
            if w_ema_200:
                weekly_desc = f"200W {p_fmt(w_ema_200)} (หลุดต่ำกว่าเส้น) | ฐาน {p_fmt(swing_low_year)}"
                sup_deep = (swing_low_year, "52W Low")
            else:
                weekly_desc = p_fmt(swing_low_year)
                sup_deep = (swing_low_year, "52W Low")

        # Trend Determination (ภาษาคนเข้าใจง่าย)
        if ema_50:
            if current_price > ema_20 > ema_50:
                trend = "🟢 ขาขึ้นชัดเจน (แรงซื้อคุมเกม)"
            elif current_price > ema_50:
                trend = "🟡 ย่อตัวปกติในขาขึ้น (ยังไม่เสียทรง)"
            elif current_price < ema_20 and current_price < ema_50:
                trend = "🔴 ขาลงชัดเจน (แรงขายเทกดดัน)"
            else:
                trend = "⚪ แกว่งตัวในกรอบ (รอดูเชิง)"
        else:
            trend = "⚪ กำลังสร้างฐานราคา"

        return {
            "ticker": ticker_symbol,
            "price": current_price,
            "change_pct": day_chg,
            "rsi_14": rsi,
            "rsi_desc": rsi_desc,
            "trend": trend,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "ema_100": ema_100,
            "ema_200": ema_200,
            "w_ema_50": w_ema_50,
            "w_ema_100": w_ema_100,
            "w_ema_200": w_ema_200,
            "resistances": filtered_resistances[:2],
            "supports": [sup_shallow, sup_medium, sup_deep],
            "sup_shallow": sup_shallow,
            "sup_medium": sup_medium,
            "sup_deep": sup_deep,
            "weekly_desc": weekly_desc,
        }
    except Exception as e:
        logger.warning(f"Error calculating support/resistance for {ticker_symbol}: {e}")
        return None


def scan_popular_support_resistance(tickers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Scan Support & Resistance levels for popular tickers."""
    target_tickers = tickers or POPULAR_RADAR_TICKERS
    results = []
    try:
        import yfinance as yf
        data = yf.download(target_tickers, period="1y", interval="1d", group_by="ticker", progress=False)
        for ticker in target_tickers:
            df = data[ticker].dropna() if isinstance(data.columns, pd.MultiIndex) else data.dropna()
            sr = calculate_support_resistance(ticker, df)
            if sr:
                results.append(sr)
    except Exception as e:
        logger.warning(f"Batch download failed, falling back to sequential: {e}")
        for ticker in target_tickers:
            sr = calculate_support_resistance(ticker)
            if sr:
                results.append(sr)
    return results


def get_all_radar_tickers() -> List[str]:
    """
    Returns the comprehensive deduplicated list of tickers to track:
    1. Core Portfolio (11 tickers)
    2. Popular Radar (NVDA, TSLA, AAPL, MSFT, META, GOOGL, AMZN, PLTR, SOFI, IREN, ORCL, AMD, SPY, QQQ, BTC-USD)
    3. Dynamic tickers discovered from channel destination channel (Channel Tracker)
    4. Watchlist (23 tickers)
    """
    try:
        from almond_cave.channel_tracker import get_all_dynamic_tickers
        dyn = get_all_dynamic_tickers()
    except Exception:
        dyn = []

    combined = []
    seen = set()
    for group in [CORE_PORTFOLIO, POPULAR_RADAR_TICKERS, dyn, WATCHLIST]:
        for t in group:
            sym = t.upper().strip()
            if sym == "BTC":
                sym = "BTC-USD"
            elif sym == "ETH":
                sym = "ETH-USD"
            if sym not in seen and len(sym) >= 2:
                seen.add(sym)
                combined.append(sym)
    return combined


def is_significant_alert(alert_text: str) -> bool:
    """Check if an alert string qualifies as a strictly significant signal."""
    # 1. Divergence
    if any(k in alert_text for k in ["สัญญาณกลับตัว", "สัญญาณเตือน", "Divergence"]):
        return True
    # 2. Major Weekly EMAs or 200-Day EMA
    if any(k in alert_text for k in ["เส้น 50 สัปดาห์", "เส้น 100 สัปดาห์", "เส้น 200 สัปดาห์", "เส้น 200 วัน"]):
        return True
    # 3. Daily EMA with high statistical bounce rate confluence (>= 60%)
    if "🎯 สถิติจุดนี้" in alert_text:
        return True
    # 4. Volume Spikes & Capitulation (>= 1.8x)
    if any(k in alert_text for k in ["วอลุ่มเทรดทะลัก", "วอลุ่มเทรดพุ่ง", "วอลุ่มเทรดสูงผิดปกติ", "วอลุ่มเทรดหนาแน่น"]):
        return True
    # 5. 52-Week Range Extremes
    if any(k in alert_text for k in ["สูงสุดรอบปี", "ต่ำสุดรอบปี"]):
        return True
    return False


LARGE_CAP_LEADERS = set(
    CORE_PORTFOLIO + POPULAR_RADAR_TICKERS + [
        "UBER", "ASML", "GOOGL", "AMZN", "TSM", "AVGO", "BABA", "ORCL", "NOW", "MU"
    ]
)


def get_earnings_and_insider_data(ticker_symbol: str) -> Dict[str, Any]:
    """
    Fetch:
    1. Next Earnings Date & Proximity Warning (เตือนระวังงบออกล่วงหน้า)
    2. SEC Form 4 Insider Open Market Purchases (ช้อนซื้อจริงของผู้บริหาร >= $50k)
    """
    # Skip crypto, indices, and major index ETFs which lack SEC insider/earnings filings
    if any(k in ticker_symbol for k in ["BTC", "ETH", "CL=F", "^"]) or ticker_symbol in ["SPY", "QQQ"]:
        return {"earnings_warning": None, "earnings_note": None, "insider_buy": None}

    try:
        import yfinance as yf
        from datetime import datetime, date
        t = yf.Ticker(ticker_symbol)
        today = date.today()

        # 1. Earnings Proximity
        earnings_warning = None
        earnings_note = None
        try:
            cal = t.calendar
            if cal and isinstance(cal, dict) and "Earnings Date" in cal:
                ed_list = cal["Earnings Date"]
                if ed_list and len(ed_list) > 0:
                    e_date = ed_list[0]
                    if isinstance(e_date, datetime):
                        e_date = e_date.date()
                    delta = (e_date - today).days
                    if delta == 0:
                        earnings_warning = f"⚠️ [ระวังงบออกวันนี้!]: งบออกวันนี้ ({e_date.strftime('%d/%m/%Y')}) กราฟเทคนิคอาจผันผวนรุนแรง"
                    elif 1 <= delta <= 7:
                        earnings_warning = f"⚠️ [เตือนระวังงบออก]: งบออก {e_date.strftime('%d/%m/%Y')} (อีก {delta} วัน! ระวังงบผันผวน กราฟเทคนิคอาจเสียทรง)"
                    elif 8 <= delta <= 14:
                        earnings_note = f"📅 งบออก {e_date.strftime('%d/%m/%Y')} (อีก {delta} วัน)"
        except Exception:
            pass

        # 2. Insider Purchases (SEC Form 4)
        insider_buy_info = None
        try:
            df = t.insider_transactions
            if df is not None and not df.empty:
                buys = df[df["Text"].str.contains("Purchase|Buy", case=False, na=False)]
                if not buys.empty:
                    recent_buys = []
                    for _, r in buys.iterrows():
                        dt = r.get("Start Date")
                        if dt:
                            dt_str = str(dt)[:10]
                            val = float(r.get("Value") or 0)
                            name = str(r.get("Insider") or "").title()
                            pos = str(r.get("Position") or "")
                            if val >= 50000:
                                recent_buys.append((dt_str, name, pos, val))
                    if recent_buys:
                        top_b = recent_buys[0]
                        insider_buy_info = f"🐋 ผู้บริหารเข้าซื้อ: {top_b[0]} | {top_b[1]} ({top_b[2]}) ซื้อ ${top_b[3]:,.0f}"
        except Exception:
            pass

        return {
            "earnings_warning": earnings_warning,
            "earnings_note": earnings_note,
            "insider_buy": insider_buy_info
        }
    except Exception:
        return {"earnings_warning": None, "earnings_note": None, "insider_buy": None}


def scan_significant_signals(
    tickers: Optional[List[str]] = None,
    max_workers: int = 10
) -> List[Dict[str, Any]]:
    """
    Scans tickers and returns ONLY those with STRICT SIGNIFICANT SIGNALS:
    - Focus mainly on Large-Cap leaders (Core Portfolio, Popular Radar, MegaCaps).
    - For Small-Caps & dynamic channel tickers: MUST have Multi-Signal Confluence (>= 2 signals) to filter out noise!
    - Enriched with Earnings Proximity Warnings and SEC Form 4 Insider Buying.
    """
    target_tickers = tickers or get_all_radar_tickers()
    triggered = []

    def _eval(sym: str) -> Optional[Dict[str, Any]]:
        # Normalize BTC
        clean_sym = "BTC-USD" if sym == "BTC" else ("ETH-USD" if sym == "ETH" else sym)
        tech = scan_ticker_technicals(clean_sym)
        if not tech:
            return None

        rsi = tech.get("rsi_14")
        alerts = tech.get("alerts", [])

        sig_list = []

        # 1. Extreme RSI
        if rsi is not None:
            if rsi <= 30.0:
                sig_list.append(f"🚨 แรงขายเยอะเกินไป / โดนเทหนัก (RSI {rsi:.1f} ลุ้นเด้งสั้น)")
            elif rsi >= 70.0:
                sig_list.append(f"🔥 แรงซื้อเยอะเกินไป / ร้อนแรง (RSI {rsi:.1f} ระวังคนเทขายทำกำไร)")

        # 2. Filter alerts for significant ones only
        for a in alerts:
            if is_significant_alert(a):
                sig_list.append(a)

        # Deduplicate signals
        sig_list = list(dict.fromkeys(sig_list))
        if not sig_list:
            return None

        is_large = clean_sym in LARGE_CAP_LEADERS

        # Strict Confluence Filter:
        # Small-caps & dynamic channel tickers MUST have at least 2 strong overlapping signals!
        if not is_large and len(sig_list) < 2:
            return None

        sr = calculate_support_resistance(clean_sym)
        if sr:
            fund_info = get_earnings_and_insider_data(clean_sym)
            return {
                "ticker": clean_sym,
                "is_large": is_large,
                "price": tech["price"],
                "rsi_14": rsi,
                "rsi_desc": sr.get("rsi_desc"),
                "trend": sr.get("trend"),
                "signals": sig_list,
                "signal_count": len(sig_list),
                "earnings_warning": fund_info.get("earnings_warning"),
                "earnings_note": fund_info.get("earnings_note"),
                "insider_buy": fund_info.get("insider_buy"),
                "sr": sr
            }
        return None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_eval, t): t for t in target_tickers}
        for future in as_completed(futures):
            res = future.result()
            if res:
                triggered.append(res)

    # Sort priority:
    # 1. Earnings Warnings (Today or <= 7 days) -> Highest impact!
    # 2. Core Portfolio & Large-caps
    # 3. Extreme RSI (<=30 or >=70) & Divergence
    # 4. Multi-Signal Confluence count
    def _rank(item):
        has_earnings_warn = 0 if item.get("earnings_warning") else 1
        is_core = 0 if item["ticker"] in CORE_PORTFOLIO else (1 if item.get("is_large") else 2)
        rsi = item["rsi_14"] or 50.0
        is_extreme = 0 if (rsi <= 30.0 or rsi >= 70.0) else 1
        has_div = 0 if any("สัญญาณกลับตัว" in s or "สัญญาณเตือน" in s for s in item["signals"]) else 1
        return (has_earnings_warn, is_core, is_extreme, has_div, -item.get("signal_count", 1), item["ticker"])

    triggered.sort(key=_rank)
    return triggered


def run_full_technical_scan() -> Dict[str, Any]:
    """Scan all tracked tickers concurrently and return macro + triggered technical alerts + support/resistance."""
    all_tickers = get_all_radar_tickers()
    logger.info(f"Concurrently scanning {len(all_tickers)} tickers for STRICT SIGNIFICANT SIGNALS...")

    significant_items = scan_significant_signals(all_tickers)

    triggered_alerts = []
    for item in significant_items:
        triggered_alerts.append({
            "ticker": item["ticker"],
            "price": item["price"],
            "rsi_14": item["rsi_14"],
            "alerts": item["signals"],
            "sr": item["sr"]
        })

    macro_data = get_macro_snapshot()
    sr_data = [item["sr"] for item in significant_items[:8]] if significant_items else scan_popular_support_resistance(POPULAR_RADAR_TICKERS[:8])

    return {
        "macro": macro_data,
        "triggered": triggered_alerts,
        "significant_items": significant_items,
        "support_resistance": sr_data,
        "total_scanned": len(all_tickers),
    }


if __name__ == "__main__":
    results = run_full_technical_scan()
    print("\n--- MACRO SNAPSHOT ---")
    for sym, m in results["macro"].items():
        if "Yield" in m["name"]:
            print(f"{m['name']} ({sym}): {m['price']:.2f}% ({m['change_pct']:+.2f}%)")
        else:
            print(f"{m['name']} ({sym}): ${m['price']:,.2f} ({m['change_pct']:+.2f}%)")

    print(f"\n--- TRIGGERED TECHNICAL ALERTS ({len(results['triggered'])}/{results['total_scanned']}) ---")
    if not results["triggered"]:
        print("ไม่มีหุ้นตัวใดที่เข้าเกณฑ์ Technical Alert ในขณะนี้")
    else:
        for t in results["triggered"]:
            print(f"\n• ${t['ticker']} (ราคาปัจจุบัน: ${t['price']:.2f})")
            for alert in t["alerts"]:
                print(f"  ⚡ {alert}")
