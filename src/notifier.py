"""Telegram notification dispatcher with rate limiting, rich HTML styling, and dry-run fallback."""

import asyncio
import logging
import os
from typing import Optional
import html
import httpx
from rich.console import Console
from rich.panel import Panel

from src.models import AlertDirection, AlertEvent

logger = logging.getLogger(__name__)

TELEGRAM_API_URL: str = "https://api.telegram.org/bot{token}/sendMessage"
MIN_DISPATCH_INTERVAL_SECONDS: float = 1.0  # Respect Telegram 1 msg/sec limit per chat


class TelegramNotifier:
    """Dispatches formatted alert messages to Telegram with rate limiting and dry-run support."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        dry_run: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.dry_run = dry_run or not bool(self.bot_token and self.chat_id)
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._console = Console()
        self._last_send_timestamp: float = 0.0

        if not self.bot_token or not self.chat_id:
            logger.info("Telegram credentials not fully set. Defaulting to dry-run terminal mode.")
            self.dry_run = True

    async def close(self) -> None:
        """Close underlying HTTP client session cleanly."""
        if not self._external_client and not self._client.is_closed:
            await self._client.aclose()

    def format_html_message(self, alert: AlertEvent) -> str:
        """Build rich HTML formatted message for Telegram with HTML escaping."""
        is_upper = alert.direction == AlertDirection.UPPER_BREACH
        condition_title = "Upper Limit Breached! 🚀" if is_upper else "Lower Limit Breached! 📉"
        override_note = " <i>[Significant Move Override]</i>" if alert.is_override else ""

        safe_display_name = html.escape(alert.target.display_name)

        change_24h_str = "N/A"
        if alert.snapshot.change_24h_percent is not None:
            sign = "+" if alert.snapshot.change_24h_percent >= 0 else ""
            change_24h_str = f"{sign}{alert.snapshot.change_24h_percent:.2f}%"

        sign_dev = "+" if alert.deviation_percent >= 0 else ""

        msg = (
            f"🚨 <b>PRICE ALERT: {safe_display_name}</b> 🚨{override_note}\n\n"
            f"📈 <b>Condition:</b> {condition_title}\n"
            f"💰 <b>Current Price:</b> ${alert.snapshot.price:,.2f}\n"
            f"🎯 <b>Target Level:</b> ${alert.target_level:,.2f} ({sign_dev}{alert.deviation_percent:.2f}%)\n"
            f"📊 <b>24h Change:</b> {change_24h_str}\n"
            f"⏰ <b>Timestamp:</b> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"<i>Notification suppressed for {alert.cooldown_minutes}m unless price moves ±5.0%.</i>"
        )
        return msg

    async def send_alert(self, alert: AlertEvent) -> bool:
        """Send an alert to Telegram or display in terminal if dry-run."""
        html_msg = self.format_html_message(alert)

        if self.dry_run:
            self._render_terminal_alert(alert, html_msg)
            return True

        return await self._dispatch_telegram_http(html_msg)

    async def send_custom_message(self, text: str) -> bool:
        """Send arbitrary text message (e.g. startup test ping)."""
        if self.dry_run:
            self._console.print(Panel(text, title="[yellow]DRY-RUN CUSTOM MESSAGE[/yellow]"))
            return True
        return await self._dispatch_telegram_http(text)

    def _render_terminal_alert(self, alert: AlertEvent, html_msg: str) -> None:
        """Pretty-print alert to terminal using rich."""
        border_style = "green" if alert.direction == AlertDirection.UPPER_BREACH else "red"
        title = f"[bold {border_style}]ALERT TRIGGERED: {alert.target.symbol}[/bold {border_style}] (DRY RUN)"
        plain_text = html_msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        self._console.print(Panel(plain_text, title=title, border_style=border_style))

    async def _dispatch_telegram_http(self, message: str) -> bool:
        """Perform rate-limited HTTP POST to Telegram Bot API."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_send_timestamp
        if elapsed < MIN_DISPATCH_INTERVAL_SECONDS:
            await asyncio.sleep(MIN_DISPATCH_INTERVAL_SECONDS - elapsed)

        url = TELEGRAM_API_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            resp = await self._client.post(url, json=payload)
            self._last_send_timestamp = asyncio.get_event_loop().time()
            if resp.status_code == 200:
                logger.info("Successfully dispatched Telegram alert to chat_id=%s", self.chat_id)
                return True
            logger.error("Telegram API rejected message (status %d): %s", resp.status_code, resp.text)
            return False
        except Exception as exc:
            logger.error("Failed to connect to Telegram API: %s", exc)
            return False
