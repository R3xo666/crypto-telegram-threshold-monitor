"""Threshold evaluation and anti-spam hysteresis cooldown engine with state persistence."""

from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from src.models import (
    AlertDirection,
    AlertEvent,
    MonitorConfig,
    MonitorState,
    PriceSnapshot,
    SymbolState,
    TargetConfig,
)

logger = logging.getLogger(__name__)


class ThresholdEvaluator:
    """Evaluates price snapshots against target thresholds with hysteresis suppression."""

    def __init__(self, config: MonitorConfig, state_file: Path) -> None:
        self.config = config
        self.state_file = state_file
        self.state: MonitorState = self._load_state()

    def _load_state(self) -> MonitorState:
        """Load persistent alert state from disk, or initialize fresh."""
        if not self.state_file.exists():
            return MonitorState()

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return MonitorState.model_validate(raw_data)
        except Exception as exc:
            logger.warning("Could not read state file (%s). Initializing fresh state.", exc)
            return MonitorState()

    def save_state(self) -> None:
        """Persist alert state to disk atomically using temporary file rename."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.state.model_dump(mode="json"), f, indent=2)
            temp_file.replace(self.state_file)
            logger.debug("Successfully saved state to %s", self.state_file)
        except Exception as exc:
            logger.error("Failed to save state to disk: %s", exc)

    def evaluate(self, snapshots: Dict[str, PriceSnapshot]) -> List[AlertEvent]:
        """
        Evaluate all current price snapshots against targets.
        Returns a list of triggered AlertEvents respecting cooldown and delta override rules.
        """
        now = datetime.now(timezone.utc)
        triggered_alerts: List[AlertEvent] = []

        for target in self.config.targets:
            snapshot = snapshots.get(target.symbol)
            if not snapshot:
                continue

            event = self._evaluate_target(target, snapshot, now)
            if event:
                triggered_alerts.append(event)
                # Update persistent state
                self.state.alerts[target.symbol] = SymbolState(
                    symbol=target.symbol,
                    last_alert_timestamp=now,
                    last_alert_price=snapshot.price,
                    last_alert_direction=event.direction,
                )

        if triggered_alerts:
            self.save_state()

        return triggered_alerts

    def _evaluate_target(
        self,
        target: TargetConfig,
        snapshot: PriceSnapshot,
        now: datetime,
    ) -> Optional[AlertEvent]:
        """Check a single target for threshold breaches and apply hysteresis logic."""
        direction: Optional[AlertDirection] = None
        target_level: float = 0.0

        if target.upper_limit is not None and snapshot.price >= target.upper_limit:
            direction = AlertDirection.UPPER_BREACH
            target_level = target.upper_limit
        elif target.lower_limit is not None and snapshot.price <= target.lower_limit:
            direction = AlertDirection.LOWER_BREACH
            target_level = target.lower_limit

        if direction is None:
            return None

        cooldown_mins = target.cooldown_minutes or self.config.default_cooldown_minutes
        cooldown_delta = timedelta(minutes=cooldown_mins)
        last_state = self.state.alerts.get(target.symbol)

        is_override = False
        deviation_percent = ((snapshot.price - target_level) / target_level) * 100.0

        if last_state:
            time_since_last = now - last_state.last_alert_timestamp
            in_cooldown = time_since_last < cooldown_delta

            if in_cooldown:
                # Check Dynamic Delta Override:
                # Has price moved further in breach direction by >= override percent compared to last alerted price?
                override_threshold = self.config.significant_move_override_percent
                if direction == AlertDirection.UPPER_BREACH and snapshot.price > last_state.last_alert_price:
                    move_percent = ((snapshot.price - last_state.last_alert_price) / last_state.last_alert_price) * 100.0
                    if move_percent >= override_threshold:
                        is_override = True
                elif direction == AlertDirection.LOWER_BREACH and snapshot.price < last_state.last_alert_price:
                    move_percent = ((last_state.last_alert_price - snapshot.price) / last_state.last_alert_price) * 100.0
                    if move_percent >= override_threshold:
                        is_override = True

                if not is_override:
                    logger.debug(
                        "Suppressed alert for %s: in cooldown (elapsed %.1fm / %dm). Price: %.2f",
                        target.symbol,
                        time_since_last.total_seconds() / 60.0,
                        cooldown_mins,
                        snapshot.price,
                    )
                    return None

        return AlertEvent(
            target=target,
            snapshot=snapshot,
            direction=direction,
            target_level=target_level,
            deviation_percent=deviation_percent,
            is_override=is_override,
            cooldown_minutes=cooldown_mins,
            timestamp=now,
        )
