"""
Claude-powered analysis engine.
Fetches market intelligence via the built-in web_search tool and
returns structured JSON verdicts for each holding.
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

MODEL = "claude-opus-4-5"
HISTORY_PATH = Path(__file__).parent / "verdict_history.json"

# ── verdict history ──────────────────────────────────────────────────────────

def _load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except Exception:
            return {}
    return {}


def _save_history(history: dict) -> None:
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def _record_verdict(ticker: str, verdict: str, history: dict) -> None:
    history.setdefault(ticker, [])
    history[ticker].append({"date": datetime.now().isoformat(), "verdict": verdict})
    history[ticker] = history[ticker][-30:]  # keep last 30 entries


def _check_overtrading(ticker: str, new_verdict: str, urgent: bool, history: dict) -> tuple[str, str | None]:
    """
    If a Trim/Sell fires within 5 days of a Buy/Accumulate — and there's no
    urgent flag — downgrade to 'Hold — monitor' to prevent knee-jerk trading.
    """
    trim_sell = ("trim", "sell")
    buy_signal = ("strong buy", "accumulate", "buy")

    if not any(k in new_verdict.lower() for k in trim_sell):
        return new_verdict, None
    if urgent:
        return new_verdict, None

    cutoff = (datetime.now() - timedelta(days=5)).isoformat()
    for entry in history.get(ticker, []):
        if entry["date"] >= cutoff and any(k in entry["verdict"].lower() for k in buy_signal):
            return "Hold — monitor", "Short-term signal conflict — waiting for confirmation."

    return new_verdict, None


# ── prompt builders ───────────────────────────────────────────────────────────

def _build_holding_prompt(holding: dict, current_price: float, headlines: list[str]) -> str:
    ticker    = holding["ticker"]
    shares    = holding["shares"]
    avg_price = holding["avg_price"]
    pnl_pct   = (current_price - avg_price) / avg_price * 100 if avg_price else 0
    position_value = current_price * shares

    news_block = (
        "\n".join(f"- {h}" for h in headlines)
        if headlines else "No Finnhub headlines available for this window."
    )

    return f"""You are a professional financial analyst writing a morning brief for a retail investor.

PORTFOLIO CONTEXT
Ticker            : {ticker}
Shares held       : {shares}
Average buy price : ${avg_price:.2f}
Current price     : ${current_price:.2f}  (sourced from Finnhub)
Unrealised P&L    : {pnl_pct:+.1f}%
Position value    : ${position_value:,.2f}

RECENT HEADLINES (last 48 h, from Finnhub)
{news_block}

YOUR TASKS — perform in order:
1. Use web_search to confirm the absolute latest price for {ticker} and any intraday moves.
2. Use web_search for any {ticker} news from the last 24–48 h not already listed above.
3. Use web_search for recent analyst rating changes or price-target revisions for {ticker}.
4. Use web_search for macro / sector tailwinds or headwinds affecting {ticker} right now.
5. Use web_search explicitly for: SEC investigations, DOJ action, fraud allegations, bankruptcy risk,
   CEO resignation, earnings miss, or analyst downgrade related to {ticker}.

NEWS FILTERING RULES (apply before writing the response):
• Ignore articles older than 48 hours.
• Ignore pure chart / technical-analysis pieces with no fundamental content.
• PRIORITISE any article containing the words SEC, DOJ, fraud, bankruptcy, "CEO resign",
  "earnings miss", or "downgrade" — surface these first and set urgent_flag to true.

After all searches, return EXACTLY this JSON object and nothing else:
{{
  "verdict": "<Strong Buy | Accumulate | Hold | Trim X% | Sell | Watch for Dip>",
  "confidence": "<Low | Medium | High>",
  "thesis": "<2–3 sentence investment thesis integrating your research>",
  "price_target_12m": <number>,
  "entry_zone": "<e.g. '$25–$28'>",
  "stop_loss": <number>,
  "scores": {{
    "fundamentals": <1–10>,
    "valuation": <1–10>,
    "momentum": <1–10>,
    "macro": <1–10>
  }},
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "bull_catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "current_price": <number — from web search>,
  "urgent_flag": <true | false>,
  "urgent_reason": "<one sentence if urgent_flag is true, otherwise null>"
}}

Return ONLY the JSON object. No markdown fences, no preamble, no trailing text."""


def _build_opportunity_prompt(best_performers: list[dict]) -> str:
    profiles = "\n".join(
        f"- {p['ticker']}: {p['pnl_pct']:+.1f}% unrealised P&L"
        for p in best_performers[:3]
    )
    return f"""You are a buy-side equity analyst.

My top-performing holdings are:
{profiles}

Use web_search to find 2–3 publicly listed stocks with similar characteristics:
• High revenue growth (>20 % YoY)
• Expanding gross or operating margins
• Strong backlog, ARR, or recurring revenue
• Positive price momentum over the last 3 months
• NOT already in the list above

For each candidate use web_search to retrieve current price and recent news, then return:
[
  {{
    "ticker": "<SYMBOL>",
    "company_name": "<full company name>",
    "current_price": <number>,
    "bull_case": "<2-sentence bull case backed by searched data>",
    "bear_case": "<2-sentence bear case>",
    "similarity_reason": "<why this resembles the winning holdings>"
  }}
]

Return ONLY the JSON array. No preamble, no markdown fences."""


# ── JSON extraction ───────────────────────────────────────────────────────────

def _extract_json_object(text: str) -> dict | None:
    """Try direct parse, then progressively looser regex extraction."""
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Find the first { … } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _extract_json_array(text: str) -> list | None:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, list) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]+\]", text)
    if match:
        try:
            obj = json.loads(match.group())
            return obj if isinstance(obj, list) else None
        except json.JSONDecodeError:
            pass
    return None


def _collect_text(content) -> str:
    return "".join(b.text for b in content if hasattr(b, "text") and b.text)


# ── public API ────────────────────────────────────────────────────────────────

def analyze_holding(
    holding: dict,
    current_price: float,
    headlines: list[str],
    client: anthropic.Anthropic,
) -> dict | None:
    """
    Analyze a single holding via Claude + web_search.
    Returns a verdict dict or None on total failure (caller writes fallback card).
    """
    ticker = holding["ticker"]
    prompt = _build_holding_prompt(holding, current_price, headlines)

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _collect_text(response.content)
            result = _extract_json_object(raw)

            if not result or "verdict" not in result:
                raise ValueError(f"Unparseable response: {raw[:300]}")

            # Overtrading guardrail
            history = _load_history()
            result["verdict"], conflict_note = _check_overtrading(
                ticker, result["verdict"], result.get("urgent_flag", False), history
            )
            if conflict_note:
                result["conflict_note"] = conflict_note

            _record_verdict(ticker, result["verdict"], history)
            _save_history(history)
            return result

        except Exception as exc:
            wait = 2 ** attempt
            print(f"  [{ticker}] Attempt {attempt + 1}/3 failed: {exc}")
            if attempt < 2:
                print(f"  [{ticker}] Retrying in {wait}s…")
                time.sleep(wait)
            else:
                print(f"  [{ticker}] All retries exhausted — will write fallback card.")
    return None


def scan_opportunities(
    best_performers: list[dict],
    client: anthropic.Anthropic,
) -> list[dict]:
    """Find 2-3 stocks similar to the portfolio's best performers."""
    if not best_performers:
        return []

    prompt = _build_opportunity_prompt(best_performers)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1800,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _collect_text(response.content)
        result = _extract_json_array(raw)
        return result or []
    except Exception as exc:
        print(f"  Opportunity scanner failed: {exc}")
        return []
