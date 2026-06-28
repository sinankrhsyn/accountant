#!/usr/bin/env python3
"""
Accountant — Daily Portfolio Intelligence Brief
Entry point: python accountant.py --now
"""

import argparse
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── US market holidays (NYSE schedule) ───────────────────────────────────────
_HOLIDAYS = {
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 12, 25),
}


def _is_market_closed() -> bool:
    today = date.today()
    return today.weekday() >= 5 or today in _HOLIDAYS


# ── Logging ───────────────────────────────────────────────────────────────────

def _setup_logging() -> None:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"run_{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── Finnhub helpers ───────────────────────────────────────────────────────────

_FINNHUB_BASE = "https://finnhub.io/api/v1"


def _finnhub_price(ticker: str, key: str) -> float:
    """Return current price from Finnhub (field 'c'). Returns 0 on error."""
    try:
        r = requests.get(
            f"{_FINNHUB_BASE}/quote",
            params={"symbol": ticker, "token": key},
            timeout=10,
        )
        r.raise_for_status()
        return float(r.json().get("c", 0))
    except Exception as exc:
        logging.warning("Finnhub price fetch failed for %s: %s", ticker, exc)
        return 0.0


def _finnhub_news(ticker: str, key: str, hours: int = 48) -> list[str]:
    """Return headline strings for the last `hours` hours from Finnhub."""
    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(hours=hours)
    try:
        r = requests.get(
            f"{_FINNHUB_BASE}/company-news",
            params={
                "symbol": ticker,
                "from":   from_dt.strftime("%Y-%m-%d"),
                "to":     to_dt.strftime("%Y-%m-%d"),
                "token":  key,
            },
            timeout=10,
        )
        r.raise_for_status()
        articles = r.json()
        # Filter to genuine last-48-h window and deduplicate
        cutoff = int(from_dt.timestamp())
        seen: set[str] = set()
        headlines: list[str] = []
        for art in articles:
            ts  = art.get("datetime", 0)
            hl  = art.get("headline", "").strip()
            if ts >= cutoff and hl and hl not in seen:
                seen.add(hl)
                headlines.append(hl)
            if len(headlines) >= 20:
                break
        return headlines
    except Exception as exc:
        logging.warning("Finnhub news fetch failed for %s: %s", ticker, exc)
        return []


# ── Notification ──────────────────────────────────────────────────────────────

def _notify(title: str, message: str) -> None:
    system = platform.system()
    if system == "Darwin":
        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(["osascript", "-e", script], check=False)
    else:
        # Windows / Linux fallback — print is always visible in terminal
        print(f"\n[NOTIFICATION] {title}: {message}")


# ── Best performers helper ────────────────────────────────────────────────────

def _best_performers(holdings: list, analyses: dict, finnhub_prices: dict) -> list[dict]:
    ranked = []
    for h in holdings:
        t   = h["ticker"]
        a   = analyses.get(t) or {}
        cur = a.get("current_price") or finnhub_prices.get(t) or h["avg_price"]
        avg = h["avg_price"]
        pnl = (cur - avg) / avg * 100 if avg else 0
        ranked.append({"ticker": t, "pnl_pct": pnl})
    return sorted(ranked, key=lambda x: x["pnl_pct"], reverse=True)


# ── Core run ──────────────────────────────────────────────────────────────────

def run() -> None:
    _setup_logging()
    load_dotenv()

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    finnhub_key   = os.getenv("FINNHUB_API_KEY", "")

    if not anthropic_key:
        logging.error("ANTHROPIC_API_KEY not set in .env — aborting.")
        sys.exit(1)

    # Load config
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from config import HOLDINGS, WATCHLIST, REPORT_SAVE_PATH  # noqa: F401
    except ImportError:
        logging.error("config.py not found. Run: python setup.py")
        sys.exit(1)

    if not HOLDINGS:
        logging.error("No holdings in config.py. Run: python setup.py")
        sys.exit(1)

    import anthropic as _anthropic
    from analyzer import analyze_holding, scan_opportunities
    from pdf_generator import generate_report

    client = _anthropic.Anthropic(api_key=anthropic_key)
    market_closed = _is_market_closed()

    if market_closed:
        logging.info("Markets are closed today — analysis will reflect last session.")

    # ── Fetch prices via Finnhub ──────────────────────────────────────────
    finnhub_prices: dict[str, float] = {}
    if finnhub_key:
        logging.info("Fetching current prices from Finnhub…")
        for h in HOLDINGS:
            t = h["ticker"]
            logging.info("  Price: %s", t)
            finnhub_prices[t] = _finnhub_price(t, finnhub_key)
            time.sleep(0.4)  # stay well under 60 req/min free tier
    else:
        logging.warning("FINNHUB_API_KEY not set — using avg_price as fallback.")

    # ── Fetch news via Finnhub ────────────────────────────────────────────
    finnhub_news: dict[str, list[str]] = {}
    if finnhub_key:
        logging.info("Fetching recent headlines from Finnhub…")
        for h in HOLDINGS:
            t = h["ticker"]
            logging.info("  News: %s", t)
            finnhub_news[t] = _finnhub_news(t, finnhub_key)
            time.sleep(0.4)

    # ── Analyse each holding ──────────────────────────────────────────────
    analyses: dict = {}
    for h in HOLDINGS:
        t       = h["ticker"]
        price   = finnhub_prices.get(t) or h.get("avg_price", 0)
        news    = finnhub_news.get(t, [])
        logging.info("Analysing %s (current: $%.2f, %d headlines)…", t, price, len(news))
        analyses[t] = analyze_holding(h, price, news, client)

    # ── Opportunity scanner ───────────────────────────────────────────────
    best  = _best_performers(HOLDINGS, analyses, finnhub_prices)
    logging.info("Scanning for opportunities based on top performers…")
    opps  = scan_opportunities(best, client)

    # ── Generate PDF ──────────────────────────────────────────────────────
    date_str    = datetime.now().strftime("%B %d, %Y")
    report_dir  = Path(REPORT_SAVE_PATH).expanduser()
    report_dir.mkdir(parents=True, exist_ok=True)
    filename    = f"Accountant_{datetime.now().strftime('%Y-%m-%d')}.pdf"
    output_path = str(report_dir / filename)

    logging.info("Generating PDF → %s", output_path)
    generate_report(
        holdings       = HOLDINGS,
        analyses       = analyses,
        opportunities  = opps,
        is_market_closed = market_closed,
        output_path    = output_path,
        date_str       = date_str,
        finnhub_prices = finnhub_prices,
    )

    logging.info("Report saved: %s", output_path)
    _notify("Accountant", "Your morning brief is ready. Check your Desktop.")
    logging.info("Done.")


# ── Entry ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Accountant — AI-powered daily portfolio brief"
    )
    parser.add_argument(
        "--now", action="store_true",
        help="Run analysis immediately (also the default for scheduled runs)",
    )
    args = parser.parse_args()

    # --now flag is accepted for explicit invocation and scheduler compatibility.
    # Currently the only mode — always runs.
    run()


if __name__ == "__main__":
    main()
