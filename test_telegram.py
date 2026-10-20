"""Standalone diagnostic tool to verify Telegram bot credentials and chat connectivity."""

import argparse
import asyncio
import os
import sys
from dotenv import load_dotenv
import httpx
from rich.console import Console
from rich.panel import Panel

console = Console()


async def verify_telegram_setup(dry_run: bool = False) -> bool:
    """Check Telegram bot token via getMe and test sending a message to chat_id."""
    load_dotenv()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    console.print(Panel("[bold cyan]Telegram Connectivity & Diagnostics Check[/bold cyan]"))

    if not bot_token or not chat_id:
        console.print("[bold yellow]⚠️ Missing Telegram credentials in .env[/bold yellow]")
        console.print("Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env or run with --dry-run.")
        if dry_run:
            console.print("[green]Dry run mode active. Validation skipped successfully.[/green]")
            return True
        return False

    # Mask token for security in accordance with credentials and security-patterns protocols
    masked_token = bot_token[:8] + "..." + bot_token[-4:] if len(bot_token) > 12 else "***"
    console.print(f"Token: [bold]{masked_token}[/bold] | Target Chat ID: [bold]{chat_id}[/bold]")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Test getMe
        try:
            get_me_url = f"https://api.telegram.org/bot{bot_token}/getMe"
            resp = await client.get(get_me_url)
            if resp.status_code != 200:
                console.print(f"[bold red]❌ Bot Token Invalid (HTTP {resp.status_code}):[/bold red] {resp.text}")
                return False

            bot_info = resp.json().get("result", {})
            console.print(f"✅ Bot Connected: [bold green]@{bot_info.get('username')}[/bold green] ({bot_info.get('first_name')})")
        except Exception as exc:
            console.print(f"[bold red]❌ Failed to connect to Telegram API:[/bold red] {exc}")
            return False

        if dry_run:
            console.print("[green]✅ Dry run check completed successfully without sending message.[/green]")
            return True

        # 2. Test sendMessage
        try:
            send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": "🤖 <b>Crypto Monitor Diagnostic Ping</b>\nTelegram integration is verified and operational!",
                "parse_mode": "HTML",
            }
            send_resp = await client.post(send_url, json=payload)
            if send_resp.status_code != 200:
                console.print(f"[bold red]❌ Failed to send message to chat {chat_id} (HTTP {send_resp.status_code}):[/bold red] {send_resp.text}")
                return False

            console.print(f"✅ Diagnostic test message sent successfully to Chat ID [bold green]{chat_id}[/bold green]!")
            return True
        except Exception as exc:
            console.print(f"[bold red]❌ Failed to dispatch test message:[/bold red] {exc}")
            return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram Bot Diagnostics and Connection Verifier")
    parser.add_argument("--dry-run", action="store_true", help="Validate without sending actual message")
    args = parser.parse_args()

    success = asyncio.run(verify_telegram_setup(dry_run=args.dry_run))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
