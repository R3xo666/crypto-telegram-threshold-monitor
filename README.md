# SentinelPulse

SentinelPulse is an asynchronous Python service that checks configured market pairs against upper and lower price limits. It reads prices from Binance, falls back to CoinGecko when the primary request fails, and sends threshold alerts through Telegram.

The watchlist, polling interval, and alert cooldowns are stored in `config/targets.json`. Alert state is saved to a JSON file so cooldowns survive restarts. The monitor reports prices and sends alerts; it does not place trades.

## Setup

~~~bash
git clone https://github.com/R3xo666/crypto-telegram-threshold-monitor.git
cd crypto-telegram-threshold-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
~~~

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`. Keep that file private. Market data uses public endpoints and does not require an API key.

Edit `config/targets.json` to set the symbols, threshold prices, polling interval, and cooldowns.

## Run

Poll once and print any resulting alert instead of sending it:

~~~bash
python3 main.py --dry-run --once
~~~

Start the continuous monitor:

~~~bash
python3 main.py
~~~

`--config` selects another watchlist file, `--state` changes the state-file path, and `--test-alert` sends a Telegram test message. Use `--dry-run` with that option to keep the message in the console.

## Tests

~~~bash
pytest -q
~~~