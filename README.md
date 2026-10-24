# SentinelPulse

SentinelPulse is an asynchronous Python monitor for configured market pairs. It reads prices from Binance, uses CoinGecko as a fallback when the primary request fails, checks upper and lower limits, and sends alerts through Telegram.

It reports price conditions; it does not place trades. The sample watchlist contains example thresholds, so review and change them before relying on alerts.

## Requirements and setup

~~~bash
git clone https://github.com/R3xo666/crypto-telegram-threshold-monitor.git
cd crypto-telegram-threshold-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
~~~

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Keep the file private. `LOG_LEVEL` is optional. The price feeds use public endpoints and need no market-data API key.

## Watchlist configuration

Edit `config/targets.json`:

| Field | Meaning |
| --- | --- |
| `poll_interval_seconds` | Time between checks; minimum 5 seconds |
| `default_cooldown_minutes` | Default wait before another alert for a target |
| `significant_move_override_percent` | Further move that can trigger an alert during cooldown |
| `targets` | List of pairs and their thresholds |
| `targets[].symbol` | Exchange pair, such as `BTCUSDT` |
| `targets[].display_name` | Name shown in the alert |
| `targets[].upper_limit` | Optional upper price boundary |
| `targets[].lower_limit` | Optional lower price boundary |
| `targets[].cooldown_minutes` | Optional per-target cooldown |

An alert is considered when a price reaches or crosses a configured boundary. During the cooldown, the monitor can send another alert if the price moves farther in the same direction by the configured override percentage. The last alert state is stored in `data/state.json` by default.

The CoinGecko fallback currently maps `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `ADAUSDT`, `DOGEUSDT`, and `XRPUSDT`. Other configured pairs depend on the Binance feed.

## Run

Run one check and print alerts to the terminal:

~~~bash
python3 main.py --dry-run --once
~~~

Run continuously with Telegram delivery:

~~~bash
python3 main.py
~~~

### Command-line options

| Option | Description |
| --- | --- |
| `-c`, `--config` | Watchlist JSON file; default `config/targets.json` |
| `--state` | State JSON file; default `data/state.json` |
| `--dry-run` | Print alerts in the terminal instead of sending them |
| `--once` | Run one poll and exit |
| `--test-alert` | Send a Telegram startup test message; combine with `--dry-run` to print it locally |

Without Telegram credentials, notifications fall back to dry-run output. The process handles `Ctrl+C` and saves its alert state on shutdown.

## Tests

~~~bash
pytest -q
~~~