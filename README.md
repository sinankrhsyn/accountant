markdown# Accountant — AI-Powered Portfolio Intelligence System

> Automated investment analysis platform that generates institutional-grade daily reports on equity holdings and macroeconomic indicators using Claude AI and live market data.

---

## What This Is

Accountant is a personal portfolio monitoring system I built to bridge the gap between raw market data and actionable investment insight. It runs three autonomous agents on a schedule — morning report, afternoon update, and a real-time news watcher — and delivers formatted PDF briefs directly to the desktop.

The system doesn't just pull prices. It instructs Claude to reason through macro conditions (Fed policy, real interest rates, USD strength, geopolitical risk, central bank activity) and produce structured investment verdicts with a built-in Devil's Advocate argument for every position.

**Why I built it:** I wanted a daily analytical workflow that mirrors how institutional analysts think — not just "stock is up/down" but *why*, and what the macro context means for each position.

---

## Architecture
accountant/

├── accountant.py        Orchestrator — morning + afternoon sessions

├── watcher.py           Real-time alert monitor (continuous loop)

├── setup.py             One-time equity extraction from brokerage screenshot

├── config.py            Holdings config (gold/silver permanent + equities)

├── analyzer.py          Claude prompts, strict analyst mode, verdict logic

├── pdf_generator.py     ReportLab: reports, alert PDFs, macro panels

├── scheduler.py         macOS Launch Agent + Windows Task Scheduler setup

├── verdict_history.json Overtrading guardrail state (auto-created)

├── cache/

│   └── last_headlines.json  Watcher headline cache (auto-created)

└── logs/                Run logs (auto-created)

### Three autonomous agents

| Agent | Schedule | Output |
|---|---|---|
| **Morning** | 7:00 AM daily | Full report — all holdings analyzed, opportunity scanner |
| **Afternoon** | 2:00 PM daily | Same analysis, "Afternoon Portfolio Update" cover |
| **Watcher** | Continuous (KeepAlive) | Polls Finnhub every 30 min, fires alerts on trigger keywords |

### Model strategy

| Task | Model | Reason |
|---|---|---|
| Holding analysis | `claude-opus-4-5` | Deepest reasoning for investment decisions |
| Watcher urgent alerts | `claude-opus-4-5` | Risk analysis demands highest accuracy |
| Opportunity scanner | `claude-sonnet-4-6` | Cost-efficient for daily screening |

---

## Key Features

### Strict analyst mode
All Claude prompts enforce institutional-grade discipline:
- Default to caution over optimism
- Unverified news flagged "unconfirmed" — cannot be sole basis for a buy
- Strong Buy requires all four equity scores ≥ 7 (or two macro factors for metals)
- Ambiguity between Hold and Trim → always takes the more conservative verdict
- Every position includes a **Devil's Advocate box**: exactly 2 sentences arguing the opposite of the current verdict

### Macro analysis framework (precious metals)
Gold (`XAUUSD`) and Silver (`XAGUSD`) are permanent holdings and macro indicators. Each report analyzes:

| Factor | Signal |
|---|---|
| USD Trend (DXY) | Weak USD = bullish metals |
| Real Interest Rates | Falling TIPS yields = bullish |
| Fed Policy | FOMC stance, dot plot, rate probabilities |
| Geopolitical Risk | Safe-haven demand driver |
| Central Bank Activity | Net buying/selling by China, India, Russia, Turkey |
| Industrial Demand *(Silver)* | EV, solar, electronics trends |

Visualized as directional triangle indicators (↑ bullish / ↓ bearish / → neutral) rendered with ReportLab.

### Real-time watcher
Monitors every new Finnhub headline for 30+ trigger keywords:
war · sanctions · crash · bankruptcy · sec · doj · fraud · resign · miss ·

downgrade · explosion · tariff · fed · rate hike · investigation · recall ·

hack · breach · layoffs · collapse · invasion · default · contagion ·

recession · emergency · seized · indicted

Urgency levels: **Low** (log only) → **Medium / High / Critical** (desktop notification + emergency PDF)

Emergency PDFs named: `accountant_ALERT_TICKER_YYYY-MM-DD_HH-MM.pdf`

### Overtrading guardrail
`verdict_history.json` tracks recent verdicts per ticker. If the system detects rapidly oscillating signals (e.g., Buy → Sell → Buy within 48 hours), it flags the conflict and defaults to Hold — preventing AI-generated overtrading.

### Cross-platform
Runs identically on macOS and Windows. `utils.py` detects OS at runtime:
- **macOS** — notifications via `osascript`, scheduling via Launch Agent plists
- **Windows** — notifications via `plyer`, scheduling via PowerShell Task Scheduler

---

## Tech Stack

| Layer | Tools |
|---|---|
| Language | Python 3.11+ |
| AI / LLM | Anthropic Claude API (Opus 4.5 + Sonnet 4.6) |
| Market Data | Finnhub API (free tier) |
| PDF Generation | ReportLab |
| Scheduling | macOS launchd / Windows Task Scheduler |
| Notifications | osascript (macOS) / plyer (Windows) |
| Storage | JSON (verdict history, headline cache) |

---

## Setup

### Requirements
- Python 3.11+
- Anthropic API key — [console.anthropic.com](https://console.anthropic.com)
- Finnhub API key — [finnhub.io](https://finnhub.io) (free tier sufficient)

### Installation

```bash
git clone https://github.com/sinankrhsyn/accountant
cd accountant
pip install -r requirements.txt
```

### Configure

Create `.env` in the project root:
ANTHROPIC_API_KEY=sk-ant-...

FINNHUB_API_KEY=your_key_here

### Initialize holdings

```bash
python setup.py
```

Upload a screenshot of your brokerage holdings. Claude extracts your equity positions automatically. Gold and Silver are added as permanent entries.

### Test a dry run

```bash
python accountant.py --now                      # Morning report
python accountant.py --now --session afternoon  # Afternoon report
```

Reports appear in `~/Desktop/reports/`.

### Schedule all three agents

```bash
python scheduler.py
```

**macOS** — writes and loads three Launch Agent plists automatically.

**Windows** — writes `schedule_tasks.ps1`. Run once as Administrator:

```powershell
cd "C:\Users\yourname\Desktop\accountant"
Set-ExecutionPolicy Bypass -Scope Process -Force
.\schedule_tasks.ps1
```

---

## Estimated Running Cost

| Component | Frequency | Est. cost |
|---|---|---|
| Morning report (2 equities + gold + silver) | Daily | ~$0.60–$1.20 |
| Afternoon report | Daily | ~$0.60–$1.20 |
| Watcher alert (triggered) | Per trigger | ~$0.05–$0.15 |
| **Weekly total (5 trading days)** | | **~$4–8/week** |

Finnhub free tier covers all price and news data at no cost.

---

## Disclaimer

All analysis is AI-generated for personal research only. Not financial advice. Always verify independently before making any investment decisions.
