"""
Pivot Point Detector for Arbitrage Entry/Exit Timing
======================================================
Uses classic technical analysis pivot points to detect optimal
arbitrage entry windows.

Standard Pivot Levels:
  P  = (H + L + C) / 3          Pivot Point (central)
  R1 = 2P - L                   Resistance 1
  R2 = P + (H - L)              Resistance 2
  S1 = 2P - H                   Support 1
  S2 = P - (H - L)              Support 2

For on-chain DEX prices, "candles" are derived from rolling price
observations captured during arbitrage scans (no OHLCV oracle needed).

Signal Logic:
  ENTRY LONG  : price bouncing up from S1/S2 zone → buy signal
  ENTRY SHORT : price rejecting from R1/R2 zone   → sell/arb signal
  NEUTRAL     : price between S1 and R1           → no strong signal

Integration with Arbitrage:
  - Boosts opportunity rank_score when price is near a pivot extreme
  - Reduces false positives by filtering noise in flat markets
  - Detects momentum reversals that create temporary DEX price divergences
"""
import time
import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Configuration
PIVOT_WINDOW_SIZE = 20      # Number of price observations per candle
PIVOT_CANDLE_INTERVAL = 60  # Seconds per synthetic candle
PIVOT_PROXIMITY_PCT = 0.5   # % within level to trigger signal
MAX_CANDLE_HISTORY = 5      # How many previous candles to keep
STRONG_SIGNAL_BOOST = 0.15  # Rank score boost for near-pivot opportunities


@dataclass
class PivotLevels:
    """Computed pivot point levels for a trading pair"""
    pair: str
    pivot: float
    r1: float
    r2: float
    s1: float
    s2: float
    high: float
    low: float
    close: float
    candle_start: float
    signal: str          # "buy", "sell", "neutral", "strong_buy", "strong_sell"
    signal_strength: float  # 0.0 to 1.0

    def to_dict(self) -> Dict:
        return {
            "pair": self.pair,
            "pivot": round(self.pivot, 8),
            "r1": round(self.r1, 8),
            "r2": round(self.r2, 8),
            "s1": round(self.s1, 8),
            "s2": round(self.s2, 8),
            "high": round(self.high, 8),
            "low": round(self.low, 8),
            "close": round(self.close, 8),
            "signal": self.signal,
            "signal_strength": round(self.signal_strength, 3),
            "candle_age_secs": round(time.time() - self.candle_start, 1),
        }


class _SyntheticCandle:
    """Accumulates price ticks into OHLCV-like data"""

    def __init__(self, start_time: float):
        self.start_time = start_time
        self.open: Optional[float] = None
        self.high: float = 0.0
        self.low: float = float("inf")
        self.close: float = 0.0
        self.tick_count: int = 0

    def add_tick(self, price: float) -> None:
        if self.open is None:
            self.open = price
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.tick_count += 1

    def is_complete(self, interval: float = PIVOT_CANDLE_INTERVAL) -> bool:
        return (
            self.tick_count >= PIVOT_WINDOW_SIZE
            or time.time() - self.start_time >= interval
        )

    def is_valid(self) -> bool:
        return (
            self.open is not None
            and self.tick_count >= 3
            and self.high > 0
            and self.low < float("inf")
        )


class PivotPointDetector:
    """
    Tracks DEX pair prices and computes pivot point signals in real time.

    Usage:
        detector = PivotPointDetector()
        detector.record_price("WBERA/USDC", 5.23)
        levels = detector.get_levels("WBERA/USDC")
        signal = detector.get_signal_for_opportunity(opp)
    """

    def __init__(self):
        # Active candles per pair
        self._active_candles: Dict[str, _SyntheticCandle] = {}
        # Completed candle history per pair (deque of _SyntheticCandle)
        self._history: Dict[str, deque] = {}
        # Latest pivot levels per pair
        self._levels: Dict[str, PivotLevels] = {}
        # Current price per pair
        self._current_prices: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_price(self, pair: str, price: float) -> None:
        """Record a new price observation for a trading pair."""
        if price <= 0:
            return

        self._current_prices[pair] = price

        # Initialise active candle if needed
        if pair not in self._active_candles:
            self._active_candles[pair] = _SyntheticCandle(time.time())
            self._history[pair] = deque(maxlen=MAX_CANDLE_HISTORY)

        candle = self._active_candles[pair]
        candle.add_tick(price)

        # Rotate candle when complete
        if candle.is_complete():
            if candle.is_valid():
                self._history[pair].append(candle)
                self._levels[pair] = self._compute_pivots(pair, candle)
            # Start fresh candle
            self._active_candles[pair] = _SyntheticCandle(time.time())

    def get_levels(self, pair: str) -> Optional[PivotLevels]:
        """Get the latest computed pivot levels for a pair."""
        return self._levels.get(pair)

    def get_signal(self, pair: str) -> str:
        """Get the current trading signal for a pair."""
        levels = self._levels.get(pair)
        if levels is None:
            return "neutral"
        return levels.signal

    def get_all_levels(self) -> Dict[str, Dict]:
        """Get pivot levels for all tracked pairs as dicts."""
        return {pair: lvl.to_dict() for pair, lvl in self._levels.items()}

    def get_signal_for_opportunity(self, opp: Dict) -> Tuple[str, float]:
        """
        Given an arbitrage opportunity dict, return (signal, rank_boost).

        The rank_boost is added to the opportunity's rank_score when:
          - signal is "strong_buy" / "strong_sell" → +STRONG_SIGNAL_BOOST
          - signal is "buy" / "sell"               → +STRONG_SIGNAL_BOOST * 0.5
          - signal is "neutral"                    → 0.0
        """
        pair = opp.get("token_pair", "")
        # Normalise pair key: "WBERA/USDC" or "WBERA → USDC" → "WBERA/USDC"
        normalised = pair.replace(" → ", "/").split(" → ")[0]

        levels = self._levels.get(normalised)
        if levels is None:
            # Try individual token pairs
            for key in self._levels:
                if any(t in key for t in normalised.split("/")):
                    levels = self._levels[key]
                    break

        if levels is None:
            return "neutral", 0.0

        signal = levels.signal
        if signal in ("strong_buy", "strong_sell"):
            return signal, STRONG_SIGNAL_BOOST
        if signal in ("buy", "sell"):
            return signal, STRONG_SIGNAL_BOOST * 0.5
        return "neutral", 0.0

    def get_stats(self) -> Dict:
        """Return detector statistics."""
        return {
            "tracked_pairs": len(self._active_candles),
            "pairs_with_levels": len(self._levels),
            "current_prices": {
                p: round(v, 8) for p, v in self._current_prices.items()
            },
            "signals": {
                p: lvl.signal for p, lvl in self._levels.items()
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_pivots(
        self, pair: str, candle: _SyntheticCandle
    ) -> PivotLevels:
        """Compute standard pivot levels from a completed candle."""
        H = candle.high
        L = candle.low
        C = candle.close

        P = (H + L + C) / 3
        R1 = 2 * P - L
        R2 = P + (H - L)
        S1 = 2 * P - H
        S2 = P - (H - L)

        current = self._current_prices.get(pair, C)
        signal, strength = self._classify_signal(current, P, R1, R2, S1, S2)

        return PivotLevels(
            pair=pair,
            pivot=P,
            r1=R1,
            r2=R2,
            s1=S1,
            s2=S2,
            high=H,
            low=L,
            close=C,
            candle_start=candle.start_time,
            signal=signal,
            signal_strength=strength,
        )

    @staticmethod
    def _classify_signal(
        price: float,
        P: float,
        R1: float,
        R2: float,
        S1: float,
        S2: float,
    ) -> Tuple[str, float]:
        """
        Classify the trading signal based on price proximity to levels.

        Returns (signal_name, strength_0_to_1).
        """
        if P == 0:
            return "neutral", 0.0

        prox = PIVOT_PROXIMITY_PCT / 100  # e.g. 0.005

        def near(level: float) -> bool:
            return abs(price - level) / P < prox

        def below(level: float) -> bool:
            return price < level

        def above(level: float) -> bool:
            return price > level

        # Strong signals near extreme levels (S2 / R2)
        if near(S2) or below(S2):
            return "strong_buy", 1.0
        if near(R2) or above(R2):
            return "strong_sell", 1.0

        # Moderate signals near S1 / R1
        if near(S1):
            strength = 1.0 - abs(price - S1) / (P * prox)
            return "buy", max(0.1, min(1.0, strength))
        if near(R1):
            strength = 1.0 - abs(price - R1) / (P * prox)
            return "sell", max(0.1, min(1.0, strength))

        # Below S1 (oversold territory) → buy
        if below(S1):
            dist = (S1 - price) / P
            return "buy", min(1.0, dist * 10)

        # Above R1 (overbought territory) → sell
        if above(R1):
            dist = (price - R1) / P
            return "sell", min(1.0, dist * 10)

        # Between S1 and R1 → neutral
        return "neutral", 0.0
