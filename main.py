"""Main entry point for Crypto & Asset Threshold Monitor Daemon."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import sys
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from src.evaluator import ThresholdEvaluator
from src.feed import MarketFeed
from src.models import MonitorConfig
from src.notifier import TelegramNotifier

# Setup default console
console = Console()


def setup_logging(log_level: str = "INFO") -> None:
    """Configure rich logging handler with clean formatting."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, console=console, tracebacks_show_locals=False)],
    )
    # Suppress verbose logs from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def load_configuration(config_path: Path) -> MonitorConfig:
    """Read and validate targets JSON configuration."""
    if not config_path.exists():
        console.print(f"[bold red]Configuration file not found:[/bold red] {config_path}")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MonitorConfig.model_validate(data)
    except Exception as exc:
        console.print(f"[bold red]Failed to parse configuration {config_path}:[/bold red] {exc}")
        sys.exit(1)


def render_watchlist_table(config: MonitorConfig) -> None:
    """Print monitored target symbols and thresholds in a formatted rich table."""
    table = Table(title="[bold cyan]Crypto & Asset Threshold Monitor — Watchlist[/bold cyan]")
    table.add_column("Symbol", style="bold green")
    table.add_column("Name", style="white")
    table.add_column("Upper Limit", style="red")
    table.add_column("Lower Limit", style="blue")
    table.add_column("Cooldown", style="yellow")

    for t in config.targets:
        upper = f"${t.upper_limit:,.2f}" if t.upper_limit else "None"
        lower = f"${t.lower_limit:,.2f}" if t.lower_limit else "None"
        cooldown = f"{t.cooldown_minutes or config.default_cooldown_minutes}m"
        table.add_row(t.symbol, t.display_name, upper, lower, cooldown)

    console.print(table)


class CryptoMonitorDaemon:
    """Daemon manager orchestrating polling, evaluation, notification, and signals."""

    def __init__(
        self,
        config: MonitorConfig,
        state_file: Path,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.state_file = state_file
        self.dry_run = dry_run
        self.running: bool = False

        self.feed = MarketFeed()
        self.evaluator = ThresholdEvaluator(config=config, state_file=state_file)
        self.notifier = TelegramNotifier(dry_run=dry_run)

    async def run_cycle(self) -> None:
        """Execute a single poll-evaluate-alert pipeline iteration."""
        symbols = [t.symbol for t in self.config.targets]
        snapshots = await self.feed.fetch_prices(symbols)

        if not snapshots:
            logging.warning("Market feed returned no price snapshots. Retrying on next cycle.")
            return

        # Display prices in debug/info
        price_summary = ", ".join(f"{s}: ${snap.price:,.2f}" for s, snap in snapshots.items())
        logging.info("[dim]Fetched prices:[/dim] %s", price_summary)

        # Evaluate thresholds
        alerts = self.evaluator.evaluate(snapshots)
        if alerts:
            logging.info("🚨 [bold red]Triggered %d threshold breach alert(s)![/bold red]", len(alerts))
            for alert in alerts:
                await self.notifier.send_alert(alert)

    async def start(self, once: bool = False) -> None:
        """Start the daemon monitoring loop."""
        self.running = True
        loop = asyncio.get_running_loop()

        # Register OS signal handlers for graceful shutdown (Linux/macOS)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: self.stop())
            except NotImplementedError:
                # Windows event loop doesn't support add_signal_handler
                pass

        logging.info("🚀 Crypto Monitor Daemon started (Interval: %ds, Dry-run: %s)",
                     self.config.poll_interval_seconds, self.dry_run)

        try:
            while self.running:
                start_time = asyncio.get_event_loop().time()
                await self.run_cycle()

                if once:
                    logging.info("Ran single cycle (--once). Terminating.")
                    break

                # Sleep remaining time until next scheduled poll
                elapsed = asyncio.get_event_loop().time() - start_time
                sleep_duration = max(1.0, self.config.poll_interval_seconds - elapsed)
                await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            logging.info("Monitoring task cancelled.")
        finally:
            await self.cleanup()

    def stop(self) -> None:
        """Flag daemon to stop cleanly."""
        logging.info("🛑 Received termination signal. Initiating clean shutdown...")
        self.running = False

    async def cleanup(self) -> None:
        """Flush state and close HTTP sessions."""
        self.evaluator.save_state()
        await self.feed.close()
        await self.notifier.close()
        logging.info("✅ State saved and network sessions closed. Daemon stopped safely.")


async def main_async() -> None:
    """Async CLI entry point."""
    parser = argparse.ArgumentParser(
        description="24/7 Lightweight Crypto & Asset Threshold Monitor with Telegram Alerts"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config/targets.json"),
        help="Path to targets JSON configuration file",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("data/state.json"),
        help="Path to persistent state JSON file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Output alerts to console without sending live Telegram messages",
    )
    parser.add_argument(
        "--test-alert",
        action="store_true",
        help="Send a test ping message to Telegram on startup to verify bot credentials",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single poll & evaluation cycle and exit immediately",
    )

    args = parser.parse_args()

    # Load environment variables from .env
    load_dotenv()
    log_level = os.getenv("LOG_LEVEL", "INFO")
    setup_logging(log_level)

    # Load targets configuration
    config = load_configuration(args.config)
    render_watchlist_table(config)

    # Optional test ping
    if args.test_alert:
        notifier = TelegramNotifier(dry_run=args.dry_run)
        test_msg = f"🔔 <b>Crypto Monitor Test Ping</b>\nActive at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        console.print("[cyan]Dispatching test ping...[/cyan]")
        success = await notifier.send_custom_message(test_msg)
        await notifier.close()
        if not success:
            console.print("[bold red]Failed to deliver test alert to Telegram.[/bold red]")
            sys.exit(1)
        console.print("[bold green]Test alert successfully dispatched![/bold green]")
        if args.once:
            return

    # Start daemon
    daemon = CryptoMonitorDaemon(
        config=config,
        state_file=args.state,
        dry_run=args.dry_run,
    )
    await daemon.start(once=args.once)


def main() -> None:
    """Synchronous launcher handling KeyboardInterrupt cleanly."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        console.print("\n[yellow]Keyboard interrupt detected. Exiting.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
