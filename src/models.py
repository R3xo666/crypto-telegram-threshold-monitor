"""Data models and type definitions for Crypto Alert Monitor."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class AlertDirection(str, Enum):
    """Direction of a price threshold breach."""
    UPPER_BREACH = "UPPER_BREACH"
    LOWER_BREACH = "LOWER_BREACH"


class TargetConfig(BaseModel):
    """Monitoring criteria for a single trading pair."""
    symbol: str = Field(..., description="Trading pair symbol (e.g. BTCUSDT)")
    display_name: str = Field(..., description="Human-readable asset title (e.g. Bitcoin (BTC))")
    upper_limit: Optional[float] = Field(default=None, description="Upper threshold price in quote currency")
    lower_limit: Optional[float] = Field(default=None, description="Lower threshold price in quote currency")
    cooldown_minutes: Optional[int] = Field(default=None, ge=1, description="Custom cooldown minutes for this symbol")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("upper_limit", "lower_limit")
    @classmethod
    def validate_positive_bounds(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("Price thresholds must be strictly positive numbers")
        return v


class MonitorConfig(BaseModel):
    """Global monitoring configuration."""
    poll_interval_seconds: int = Field(default=30, ge=5, description="Interval in seconds between poll cycles")
    default_cooldown_minutes: int = Field(default=60, ge=1, description="Default hysteresis cooldown duration")
    significant_move_override_percent: float = Field(
        default=5.0,
        gt=0.0,
        description="Percentage price delta beyond last alert to bypass cooldown"
    )
    targets: List[TargetConfig] = Field(default_factory=list, description="Watchlist targets")


class PriceSnapshot(BaseModel):
    """Point-in-time market price data for a symbol."""
    symbol: str
    price: float
    change_24h_percent: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AlertEvent(BaseModel):
    """Represents a validated threshold breach event ready for dispatch."""
    target: TargetConfig
    snapshot: PriceSnapshot
    direction: AlertDirection
    target_level: float
    deviation_percent: float
    is_override: bool = False
    cooldown_minutes: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SymbolState(BaseModel):
    """Persistent state for an individual symbol's alert history."""
    symbol: str
    last_alert_timestamp: datetime
    last_alert_price: float
    last_alert_direction: AlertDirection


class MonitorState(BaseModel):
    """Global persistent state cache."""
    alerts: dict[str, SymbolState] = Field(default_factory=dict)
