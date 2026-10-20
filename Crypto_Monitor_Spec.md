# Technical Specification & Architecture: Lightweight Crypto & Asset Threshold Monitor with Telegram Alerts

**Target Role:** Elite Solutions Architect & Technical Specification Specialist  
**Domain:** Financial Automation / 24/7 Background Daemon / Resilient Bot Service  
**Client Budget:** $35 | **Platform:** Twitter / X Freelance  

---

## Phase 1: Architectural Assessment & Reality Check

### 1. Underlying Objective
The client needs an autonomous, lightweight 24/7 background monitoring daemon running on a Linux VPS or local Windows workstation. It monitors target cryptocurrency and forex/asset pairs against user-defined upper and lower threshold bands. When a threshold is breached, it dispatches structured, real-time Telegram alerts via the Telegram Bot HTTP API while suppressing alert storms through a persistent, stateful hysteresis cooldown engine.

### 2. Strategy Matrix

| Approach | Architecture | Pros | Cons | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **1. WebSocket Streaming (Binance / Coinbase WS Streams)** | Persistent raw TCP/WebSocket connections streaming continuous ticker ticks. | Sub-millisecond latency. | High socket complexity, frequent silent TCP drops on home networks, aggressive ping/pong keepalive required, hard to monitor non-exchange assets simultaneously. | ❌ Unnecessary complexity & fragile for casual threshold polling (every 30-60s). |
| **2. Paid SaaS Aggregators (CoinMarketCap API / TwelveData Pro)** | Pro API endpoints with dedicated API keys and rate limits. | Standardized interfaces across crypto & forex. | Requires client credit card, monthly recurring costs ($30–$80/mo) which defeats a $35 one-off budget. | ❌ Violates requirement of using free public endpoints. |
| **3. Web Scraping (HTML / Headless Browser)** | Scraping CoinMarketCap or Google Finance pages with Playwright/BS4. | Access to web-rendered prices. | Extremely heavy (RAM/CPU), fragile to DOM layout changes, blocked by Cloudflare anti-bot. | ❌ Anti-pattern for 24/7 monitoring. |
| **4. Multi-Provider REST Polling with Async Resilient HTTP & In-Memory Cooldown** | Asynchronous HTTP polling engine (`httpx` / `aiohttp`) querying official public REST APIs (Binance Public Ticker API + CoinGecko Simple Price fallback) with exponential backoff and persistent state. | Zero API keys required for public market data, ultra-lightweight (<25MB RAM), resilient to transient network drops, cross-platform background daemon. | Rate limits apply if polled too fast (<5s). Handled via batch calls and exponential jitter backoff. | **✅ RECOMMENDED (Optimal)** |

#### Recommended Primary Approach:
**Strategy 4 (Multi-Provider Async Poller with Telegram Bot API & Hysteresis State Engine)**:
- Primary feed: **Binance Public Spot REST API** (`https://api.binance.com/api/v3/ticker/price` & `24hr`) for crypto pairs (no API key required, ultra-fast, high rate limits: 1200 weight/min).
- Fallback / Alt feed: **CoinGecko Simple Price API** for niche tokens.
- Alerting: Direct HTTP POST to Telegram Bot API (`https://api.telegram.org/bot<TOKEN>/sendMessage`) with HTML/MarkdownV2 formatting.
- Hysteresis & Cooldown: Tracks last alert timestamp and last alerted price per symbol to prevent notification spamming.

---

### 3. Obstacle & Failure Surface

1. **Telegram & Exchange API Rate Limits (HTTP 429):**
   - Binance IP bans occur if request weight exceeds 1200/min. Telegram enforces 30 msgs/sec globally and 1 msg/sec per specific chat.
   - *Mitigation:* Single-batch ticker request (fetching multiple symbols in 1 HTTP call) rather than looping individual requests. Request throttling with exponential backoff and randomized jitter on 429/5xx codes.
2. **Alert Flooding / Notification Storms:**
   - If BTC crosses $70,000 and hovers at $70,001 for 10 minutes, a naive bot will send 600 alerts.
   - *Mitigation:* Stateful cooldown matrix:
     - Rule A: Time-based cooldown (e.g., 60 minutes minimum before repeating the same alert).
     - Rule B: Dynamic delta bypass (e.g., if price moves an additional $\ge 5\%$ beyond the alerted level, immediately override cooldown and dispatch an updated alert).
3. **Network Drops & Transient DNS Failures:**
   - Home broadband or VPS hiccups can cause `ConnectTimeout` or `SocketError`.
   - *Mitigation:* Resilient retry loop using exponential backoff with ceiling (1s $\rightarrow$ 2s $\rightarrow$ 4s $\rightarrow$ max 60s). Daemon **never** crashes or exits on network drop.
4. **Clean OS Shutdown & Cross-Platform Background Execution:**
   - Must run as a systemd service on Linux and via standard terminal or `pythonw.exe` / NSSM service on Windows.
   - *Mitigation:* Graceful signal handling (`SIGINT`, `SIGTERM`) ensuring state is saved and active network sessions are closed cleanly.

---

### 4. Viability & Scope
- **Environment:** Pure Python 3.10+ (compatible with Linux, Windows 10/11, macOS).
- **Footprint:** Extremely low (<25 MB RAM, negligible CPU <0.1%).
- **Feasibility:** 100% viable within scope.

---

## Phase 2: System Design & Zero-Hardcode Architecture

### 1. Architectural Layers & Separation of Concerns

```
                  ┌──────────────────────────────┐
                  │      config/targets.json     │
                  │ (Symbols, limits, intervals) │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
┌────────────────────────────────────────────────────────┐
│  Poller & Feed Ingestion Layer (src/feed.py)           │
│  - Async HTTP client with connection pooling           │
│  - Batch ticker fetching (Binance / CoinGecko)         │
│  - Exponential backoff retry engine for 429/5xx/drops  │
└──────────────────────────┬─────────────────────────────┘
                           │ PriceSnapshot DTOs
                           ▼
┌────────────────────────────────────────────────────────┐
│  Hysteresis & Alert Evaluator (src/evaluator.py)       │
│  - Threshold breach detection (Upper / Lower)          │
│  - Cooldown timer verification (e.g., 1 hour lock)     │
│  - Significant delta override check (e.g., ±5% jump)   │
│  - State serialization to cache/state.json             │
└──────────────────────────┬─────────────────────────────┘
                           │ Verified Alert Event
                           ▼
┌────────────────────────────────────────────────────────┐
│  Notifier & Delivery Layer (src/notifier.py)           │
│  - Telegram Bot HTTP API client                        │
│  - Styled HTML messages with emojis, price & 24h delta │
│  - Rate-limit queue (max 1 msg/sec to single chat)     │
└────────────────────────────────────────────────────────┘
```

### 2. Zero-Hardcode Configuration Standard

#### A. Environment Variables (`.env`):
```ini
TELEGRAM_BOT_TOKEN="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
TELEGRAM_CHAT_ID="987654321"
LOG_LEVEL="INFO"
```

#### B. Watchlist Configuration (`config/targets.json`):
```json
{
  "poll_interval_seconds": 30,
  "default_cooldown_minutes": 60,
  "significant_move_override_percent": 5.0,
  "targets": [
    {
      "symbol": "BTCUSDT",
      "display_name": "Bitcoin (BTC)",
      "upper_limit": 70000.0,
      "lower_limit": 62000.0,
      "cooldown_minutes": 60
    },
    {
      "symbol": "ETHUSDT",
      "display_name": "Ethereum (ETH)",
      "upper_limit": 3800.0,
      "lower_limit": 3200.0,
      "cooldown_minutes": 60
    },
    {
      "symbol": "SOLUSDT",
      "display_name": "Solana (SOL)",
      "upper_limit": 200.0,
      "lower_limit": 140.0,
      "cooldown_minutes": 30
    }
  ]
}
```

---

## Phase 3: Client Handoff & Value Delivery

### 1. Client Pitch / Acknowledgment Message
> *"Hi! I have reviewed your requirement for the 24/7 background crypto threshold monitor. I can build a lightweight, rock-solid Python daemon that monitors your target pairs (BTC, ETH, SOL, etc.) using free public endpoints with zero API keys required. It features smart anti-spam cooldowns (1-hour suppress with dynamic 5% move override), automatic exponential backoff for network drops, and instant rich Telegram alerts. The bot is fully decoupled with `.env` and `config.json` and comes ready with Linux systemd service files and Windows background startup scripts. Delivery within 24 hours."*

### 2. Deliverable Manifest
```
crypto-alert-monitor/
├── venv/                       # Virtual environment setup
├── config/
│   └── targets.json            # Target symbols, price limits, polling rules
├── data/
│   └── state.json              # Persistent cooldown & last-alert state
├── src/
│   ├── __init__.py
│   ├── models.py               # TargetConfig, PriceSnapshot, AlertEvent DTOs
│   ├── feed.py                 # Async market data poller with backoff
│   ├── evaluator.py            # Threshold & hysteresis cooldown evaluator
│   └── notifier.py             # Telegram Bot API client with HTML formatting
├── scripts/
│   ├── install_service.sh      # Linux systemd auto-installer
│   └── run_background_win.vbs  # Windows silent background runner
├── main.py                     # Main CLI orchestrator & signal handler
├── test_telegram.py            # Quick standalone Telegram connection tester
├── requirements.txt            # Pinned dependencies
├── .env.example                # Sample environment variables template
└── README.md                   # Complete installation, service setup & guide
```

---

## Phase 4: Downstream Coding AI Prompt (The Anti-Gravity Directive)

```markdown
# AGENT DIRECTIVE: 24/7 Lightweight Crypto Threshold Monitor with Telegram Alerts

You are an expert Python systems and automation engineer. Build a rock-solid, production-grade 24/7 background monitoring daemon that watches crypto/asset prices using free public APIs and dispatches instant Telegram alerts upon threshold breaches, with an anti-spam hysteresis cooldown engine.

---

### 1. Environment & Setup
- Target Environment: Linux (Ubuntu/Debian/Fedora/Arch) and Windows 10/11 (Python 3.10+).
- Setup commands:
  ```bash
  python3 -m venv venv
  source venv/bin/activate  # On Windows: venv\Scripts\activate
  pip install -r requirements.txt
  ```
- Required Dependencies in `requirements.txt`:
  ```text
  httpx==0.28.1
  python-dotenv==1.0.1
  rich==13.9.4
  pydantic==2.10.6
  ```

---

### 2. Functional Requirements

#### A. Free Public Market Data Poller (`src/feed.py`):
1. Use Binance Public REST API (no API key required):
   - Price ticker: `https://api.binance.com/api/v3/ticker/price` (batch or per-symbol).
   - 24-hr change ticker: `https://api.binance.com/api/v3/ticker/24hr`.
2. Implement an automatic fallback mechanism (e.g. CoinGecko simple price) or multi-endpoint support.
3. Network Fault Tolerance:
   - Wrap all requests in `try/except (httpx.RequestError, httpx.HTTPStatusError)`.
   - On connection failure, DNS failure, or HTTP 429/5xx, execute exponential backoff retry (1s, 2s, 4s... max 60s) with jitter.
   - **NEVER EXIT OR CRASH** on transient network loss. Log a warning and keep retrying.

#### B. Threshold & Hysteresis Anti-Spam Evaluator (`src/evaluator.py`):
1. Compare current price against `upper_limit` and `lower_limit`.
2. Hysteresis Anti-Spam Rules:
   - Once an alert is sent for a symbol, put that symbol/direction on a configurable cooldown (e.g., 60 minutes).
   - **Dynamic Delta Override**: If the price continues moving in the breach direction by more than `significant_move_override_percent` (e.g., $\ge 5\%$) from the last alerted price, bypass the cooldown immediately and dispatch an updated alert.
3. State Persistence:
   - Save the active alert history and timestamps into `data/state.json` so stopping and restarting the daemon does not trigger duplicate alerts.

#### C. Rich Telegram Alert Dispatcher (`src/notifier.py`):
1. Send message via HTTP POST to `https://api.telegram.org/bot{TOKEN}/sendMessage`.
2. Message must use HTML formatting with clean visual hierarchy:
   ```html
   🚨 <b>PRICE ALERT: Bitcoin (BTC)</b> 🚨

   📈 <b>Condition:</b> Upper Limit Breached!
   💰 <b>Current Price:</b> $71,240.50
   🎯 <b>Target Level:</b> $70,000.00 (+1.77%)
   📊 <b>24h Change:</b> +4.82%
   ⏰ <b>Timestamp:</b> 2026-10-20 17:45:00 UTC

   <i>Notification suppressed for 60m unless price moves ±5.0%.</i>
   ```
3. Support dry-run mode: if `TELEGRAM_BOT_TOKEN` is not configured or `--dry-run` flag is passed, print formatted alert cleanly to terminal via `rich` without failing.

#### D. Operational Lifecycle & CLI (`main.py`):
1. CLI flags via `argparse`:
   - `--config` / `-c`: Path to targets JSON config (default: `config/targets.json`).
   - `--dry-run`: Poll prices and evaluate triggers, but output alerts to terminal without calling Telegram API.
   - `--test-alert`: Dispatch a test message to Telegram on startup to verify bot credentials.
   - `--once`: Run a single check cycle and exit (useful for cron jobs or testing).
2. Clean Signal Trapping:
   - Register handlers for `SIGINT` (Ctrl+C) and `SIGTERM`.
   - On shutdown, flush `data/state.json`, log clean exit message, and terminate with exit code `0`.
3. Provide `test_telegram.py`:
   - Standalone script that reads `.env`, validates bot token and chat ID via `getMe` and `sendMessage`, and prints instant diagnostic status.

#### E. Service Deployment Files:
1. `scripts/crypto-monitor.service`: Standard systemd service unit file with auto-restart on failure (`Restart=on-failure`, `RestartSec=10s`).
2. `scripts/run_background_win.vbs`: VBScript runner to launch the script silently in the background on Windows without keeping a command prompt window open.

---

### 3. Modular Code Structure to Implement

```
crypto-alert-monitor/
├── .env.example
├── config/
│   └── targets.json
├── data/
│   └── state.json
├── scripts/
│   ├── crypto-monitor.service
│   └── run_background_win.vbs
├── src/
│   ├── __init__.py
│   ├── models.py
│   ├── feed.py
│   ├── evaluator.py
│   └── notifier.py
├── tests/
│   ├── __init__.py
│   └── test_monitor.py
├── main.py
├── test_telegram.py
├── requirements.txt
└── README.md
```

---

### 4. Code Standards & Constraints
- Zero hardcoding of tokens, chat IDs, file paths, or intervals.
- Full type annotations on all classes and methods.
- Comprehensive automated test suite with `pytest` testing threshold triggers, cooldown logic, and mock API failures.
```
