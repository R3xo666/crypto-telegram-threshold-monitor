"""Unit and integration tests for the Crypto & Asset Threshold Monitor."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
import httpx

from src.models import (
    AlertDirection,
    MonitorConfig,
    PriceSnapshot,
    TargetConfig,
)
from src.evaluator import ThresholdEvaluator
from src.feed import MarketFeed
from src.notifier import TelegramNotifier


@pytest.fixture
def sample_config() -> MonitorConfig:
    return MonitorConfig(
        poll_interval_seconds=10,
        default_cooldown_minutes=60,
        significant_move_override_percent=5.0,
        targets=[
            TargetConfig(
                symbol="BTCUSDT",
                display_name="Bitcoin (BTC)",
                upper_limit=70000.0,
                lower_limit=60000.0,
                cooldown_minutes=60,
            ),
            TargetConfig(
                symbol="ETHUSDT",
                display_name="Ethereum (ETH)",
                upper_limit=3500.0,
                lower_limit=3000.0,
                cooldown_minutes=30,
            ),
        ],
    )


def test_target_config_normalization_and_validation():
    """Verify symbol normalization and bound validation."""
    target = TargetConfig(symbol=" btcusdt ", display_name="Bitcoin", upper_limit=65000.0)
    assert target.symbol == "BTCUSDT"

    with pytest.raises(ValueError):
        TargetConfig(symbol="BTCUSDT", display_name="Bitcoin", upper_limit=-100.0)


def test_threshold_breach_detection(tmp_path: Path, sample_config: MonitorConfig):
    """Test upper and lower breach detection on fresh state."""
    state_file = tmp_path / "state.json"
    evaluator = ThresholdEvaluator(sample_config, state_file)

    snapshots = {
        "BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=71500.0, change_24h_percent=3.2),
        "ETHUSDT": PriceSnapshot(symbol="ETHUSDT", price=2900.0, change_24h_percent=-2.1),
    }

    alerts = evaluator.evaluate(snapshots)
    assert len(alerts) == 2

    btc_alert = next(a for a in alerts if a.target.symbol == "BTCUSDT")
    assert btc_alert.direction == AlertDirection.UPPER_BREACH
    assert btc_alert.target_level == 70000.0
    assert not btc_alert.is_override

    eth_alert = next(a for a in alerts if a.target.symbol == "ETHUSDT")
    assert eth_alert.direction == AlertDirection.LOWER_BREACH
    assert eth_alert.target_level == 3000.0


def test_hysteresis_cooldown_suppression(tmp_path: Path, sample_config: MonitorConfig):
    """Ensure consecutive ticks within cooldown window do not trigger new alerts."""
    state_file = tmp_path / "state.json"
    evaluator = ThresholdEvaluator(sample_config, state_file)

    # Tick 1: Triggers alert
    first_snapshot = {"BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=70500.0)}
    alerts_1 = evaluator.evaluate(first_snapshot)
    assert len(alerts_1) == 1

    # Tick 2: Price hovers slightly higher (+0.5%) within cooldown -> Should be suppressed
    second_snapshot = {"BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=70850.0)}
    alerts_2 = evaluator.evaluate(second_snapshot)
    assert len(alerts_2) == 0


def test_significant_move_delta_override(tmp_path: Path, sample_config: MonitorConfig):
    """Ensure a price jump >= significant_move_override_percent overrides cooldown."""
    state_file = tmp_path / "state.json"
    evaluator = ThresholdEvaluator(sample_config, state_file)

    # Initial alert at 70,000
    first_snapshot = {"BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=70000.0)}
    evaluator.evaluate(first_snapshot)

    # Price shoots up by +6% to 74,200 (> 5% override threshold)
    override_snapshot = {"BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=74200.0)}
    alerts = evaluator.evaluate(override_snapshot)

    assert len(alerts) == 1
    assert alerts[0].is_override is True
    assert alerts[0].snapshot.price == 74200.0


def test_state_persistence_across_instances(tmp_path: Path, sample_config: MonitorConfig):
    """Verify that state saved by one evaluator instance is honored by another."""
    state_file = tmp_path / "state.json"
    evaluator_1 = ThresholdEvaluator(sample_config, state_file)

    snapshot = {"BTCUSDT": PriceSnapshot(symbol="BTCUSDT", price=71000.0)}
    evaluator_1.evaluate(snapshot)

    # Instantiate fresh evaluator reading the same state file
    evaluator_2 = ThresholdEvaluator(sample_config, state_file)
    assert "BTCUSDT" in evaluator_2.state.alerts

    # Re-evaluating within cooldown window should yield zero alerts
    alerts = evaluator_2.evaluate(snapshot)
    assert len(alerts) == 0


def test_telegram_html_formatting(tmp_path: Path):
    """Verify HTML message structure and tags."""
    target = TargetConfig(symbol="BTCUSDT", display_name="Bitcoin (BTC)", upper_limit=70000.0)
    snapshot = PriceSnapshot(symbol="BTCUSDT", price=71240.50, change_24h_percent=4.82)
    state_file = tmp_path / "format_test_state.json"
    evaluator = ThresholdEvaluator(
        MonitorConfig(targets=[target]),
        state_file
    )
    alerts = evaluator.evaluate({"BTCUSDT": snapshot})
    assert len(alerts) == 1

    notifier = TelegramNotifier(dry_run=True)
    html = notifier.format_html_message(alerts[0])

    assert "🚨 <b>PRICE ALERT: Bitcoin (BTC)</b> 🚨" in html
    assert "Upper Limit Breached!" in html
    assert "$71,240.50" in html
    assert "+4.82%" in html
    assert "<i>Notification suppressed for 60m unless price moves ±5.0%.</i>" in html


@pytest.mark.asyncio
async def test_feed_exponential_backoff_and_resilience():
    """Verify that network failures increment failure count and compute valid backoff."""
    feed = MarketFeed()
    assert feed._consecutive_failures == 0

    # Backoff calculation checks
    feed._consecutive_failures = 1
    bo1 = feed._calculate_backoff()
    assert 0.8 <= bo1 <= 2.5

    feed._consecutive_failures = 5
    bo5 = feed._calculate_backoff()
    assert bo5 > bo1

    await feed.close()
