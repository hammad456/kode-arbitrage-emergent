"""
HYDRA AI Monitor — Production Integration
==========================================
Fixed and integrated version of HYDRA v1000_4.

What changed from the original:
  - CodeSingularity / self-modification removed entirely (unsafe in production)
  - Simulated random trading replaced with real trade data from TradeLogger CSV
  - Chain ID corrected to 80094 (mainnet, not 80069 testnet)
  - Wrong `agent.run(reset=True)` kwarg fixed (not a valid smolagents param)
  - Bare `except:` replaced with `except Exception`
  - AI audit runs unconditionally (not gated behind MUTATION_ENABLED)
  - smolagents agent initialized lazily with retry — offline LM Studio doesn't
    permanently disable the monitor for the session
  - All RPC health checks run concurrently (not sequentially)
  - PortfolioState synced from real trade history, not random simulations
  - Circuit breaker exposed to server.py so AutoExecutionEngine can honor it
  - No mutation tools given to the agent — read-only observation only

Usage in server.py startup:
    from monitor.ai_monitor import start_monitor, get_monitor_status, portfolio
    asyncio.create_task(start_monitor())
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from web3 import Web3

from core.constants import CHAIN_ID  # 80094 — Berachain mainnet

logger = logging.getLogger("hydra.monitor")

# ── RPC cluster ──────────────────────────────────────────────────────────────
_LOCAL_NODE = os.environ.get("LOCAL_NODE_RPC", "")
_FALLBACKS  = [r.strip() for r in os.environ.get("FALLBACK_RPCS", "").split(",") if r.strip()]

RPC_CLUSTER: List[str] = list(filter(None, [
    _LOCAL_NODE,
    os.environ.get("BERACHAIN_RPC", "https://rpc.berachain.com"),
    "https://berachain.drpc.org",
    "https://berachain-rpc.publicnode.com",
    "https://rpc.berachain-apis.com",
    *_FALLBACKS,
]))

# Audit interval — how often the AI reviews system health
AI_AUDIT_INTERVAL_SEC  = int(os.environ.get("AI_AUDIT_INTERVAL",  "300"))  # 5 min
RPC_HEALTH_INTERVAL_SEC = int(os.environ.get("RPC_HEALTH_INTERVAL", "60"))
PORTFOLIO_SYNC_INTERVAL = int(os.environ.get("PORTFOLIO_SYNC_INTERVAL", "30"))


# ── Portfolio state with circuit breaker ─────────────────────────────────────
@dataclass
class PortfolioState:
    """
    Tracks realized PnL from real executed trades and enforces risk limits.
    Data is sourced from TradeLogger CSV — never simulated.
    """
    total_pnl: float       = 0.0
    peak_pnl: float        = 0.0
    current_drawdown: float = 0.0
    trades_total: int      = 0
    trades_win: int        = 0
    consecutive_fails: int = 0
    circuit_breaker_active: bool  = False
    circuit_breaker_until: Optional[float] = None
    pnl_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100))

    # Thresholds — match constants.py philosophy (conservative)
    MAX_DRAWDOWN_PCT: float     = 0.15   # 15 % drawdown on realized PnL peak
    MAX_CONSECUTIVE_FAILS: int  = 5
    PAUSE_SECONDS: int          = 300    # 5 min cooldown

    def record_trade(self, profit_usd: float, success: bool) -> None:
        """Update state from a real completed trade. Thread-safe via caller lock."""
        self.total_pnl    += profit_usd
        self.trades_total += 1

        if success and profit_usd > 0:
            self.trades_win      += 1
            self.consecutive_fails = 0
        else:
            self.consecutive_fails += 1

        if self.total_pnl > self.peak_pnl:
            self.peak_pnl = self.total_pnl

        if self.peak_pnl > 0:
            self.current_drawdown = (self.peak_pnl - self.total_pnl) / self.peak_pnl

        self.pnl_history.append(profit_usd)
        self._maybe_trip_breaker()

    def _maybe_trip_breaker(self) -> None:
        if self.circuit_breaker_active:
            return
        if (self.current_drawdown >= self.MAX_DRAWDOWN_PCT
                or self.consecutive_fails >= self.MAX_CONSECUTIVE_FAILS):
            self.circuit_breaker_active = True
            self.circuit_breaker_until  = time.time() + self.PAUSE_SECONDS
            logger.critical(
                "CIRCUIT BREAKER TRIPPED — "
                f"drawdown={self.current_drawdown:.1%}, "
                f"consecutive_fails={self.consecutive_fails}. "
                f"Pausing {self.PAUSE_SECONDS}s."
            )

    def check_and_maybe_release(self) -> bool:
        """
        Returns True if trading should be halted right now.
        Automatically releases the breaker after the cooldown period.
        """
        if not self.circuit_breaker_active:
            return False
        if self.circuit_breaker_until and time.time() > self.circuit_breaker_until:
            self.circuit_breaker_active = False
            self.circuit_breaker_until  = None
            self.consecutive_fails      = max(0, self.consecutive_fails - 2)
            logger.info("Circuit breaker released — trading may resume.")
            return False
        return True  # still active

    @property
    def win_rate(self) -> float:
        return self.trades_win / self.trades_total if self.trades_total > 0 else 0.0

    def to_dict(self) -> Dict:
        return {
            "total_pnl_usd":        round(self.total_pnl, 4),
            "peak_pnl_usd":         round(self.peak_pnl, 4),
            "drawdown_pct":         round(self.current_drawdown * 100, 2),
            "trades_total":         self.trades_total,
            "trades_win":           self.trades_win,
            "win_rate_pct":         round(self.win_rate * 100, 1),
            "consecutive_fails":    self.consecutive_fails,
            "circuit_breaker":      self.circuit_breaker_active,
            "circuit_breaker_until": (
                datetime.fromtimestamp(self.circuit_breaker_until, tz=timezone.utc).isoformat()
                if self.circuit_breaker_until else None
            ),
        }


# Module-level singleton — imported by server.py to gate AutoExecutionEngine
portfolio = PortfolioState()

# Lock protecting portfolio.record_trade() called from async context
_portfolio_lock = asyncio.Lock()


# ── RPC cluster health tracker ───────────────────────────────────────────────
@dataclass
class RpcNodeStatus:
    url: str
    healthy: bool        = False
    latency_ms: float    = 999.0
    block_height: int    = 0
    last_checked: float  = 0.0
    error: Optional[str] = None


class Web3Cluster:
    """
    Monitors all RPC endpoints concurrently.
    Surfaces the lowest-latency healthy node as `active_node`.
    """

    def __init__(self, urls: List[str]) -> None:
        # Deduplicate while preserving order
        seen: set = set()
        unique = [u for u in urls if u not in seen and not seen.add(u)]  # type: ignore
        self.nodes: Dict[str, RpcNodeStatus] = {u: RpcNodeStatus(url=u) for u in unique}
        self._active_url: Optional[str] = None

    async def _check_one(self, url: str) -> None:
        node = self.nodes[url]
        t0 = time.monotonic()
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 5}))
            block: int = await asyncio.wait_for(
                asyncio.to_thread(lambda: w3.eth.block_number),
                timeout=6.0,
            )
            node.latency_ms   = (time.monotonic() - t0) * 1000
            node.block_height = block
            node.healthy      = True
            node.error        = None
        except Exception as e:
            node.healthy    = False
            node.latency_ms = 999.0
            node.error      = str(e)[:100]
        finally:
            node.last_checked = time.time()

    async def health_check_all(self) -> None:
        """Check every node concurrently; elect the best active node."""
        await asyncio.gather(
            *(self._check_one(url) for url in self.nodes),
            return_exceptions=True,   # one bad node must not cancel others
        )
        healthy = [n for n in self.nodes.values() if n.healthy]
        if healthy:
            best = min(healthy, key=lambda n: n.latency_ms)
            self._active_url = best.url
        else:
            self._active_url = None
            logger.warning("All RPC nodes are unhealthy.")

    @property
    def active_node(self) -> Optional[RpcNodeStatus]:
        return self.nodes.get(self._active_url) if self._active_url else None  # type: ignore

    def to_dict(self) -> Dict:
        nodes_out = []
        for n in self.nodes.values():
            display_url = (n.url[:40] + "...") if len(n.url) > 40 else n.url
            nodes_out.append({
                "url":          display_url,
                "healthy":      n.healthy,
                "latency_ms":   round(n.latency_ms, 1),
                "block_height": n.block_height,
                "error":        n.error,
            })
        active = self.active_node
        return {
            "active_url":    (self._active_url[:40] + "...") if self._active_url and len(self._active_url) > 40 else self._active_url,
            "active_latency_ms":  round(active.latency_ms, 1) if active else None,
            "active_block_height": active.block_height if active else None,
            "healthy_count": sum(1 for n in self.nodes.values() if n.healthy),
            "total_count":   len(self.nodes),
            "nodes":         nodes_out,
        }


rpc_cluster = Web3Cluster(RPC_CLUSTER)


# ── smolagents AI audit (fully optional) ─────────────────────────────────────
# The agent is initialized lazily on first audit attempt.
# If LM Studio is offline, we retry on the next audit cycle instead of
# permanently disabling for the session.
_agent = None
_agent_init_attempted = False


def _try_init_agent() -> bool:
    """
    Attempt to initialize the smolagents CodeAgent.
    Returns True on success, False if smolagents not installed or LM Studio offline.
    Agent only receives read-only monitoring tools — NO mutation capability.
    """
    global _agent, _agent_init_attempted
    _agent_init_attempted = True
    try:
        from smolagents import CodeAgent, OpenAIServerModel, tool  # type: ignore

        lm_base  = os.environ.get("LM_STUDIO_BASE",  "http://localhost:1234/v1")
        lm_key   = os.environ.get("LM_STUDIO_KEY",   "lm-studio")
        lm_model = os.environ.get("LM_STUDIO_MODEL",  "local-model")

        llm = OpenAIServerModel(
            model_id=lm_model,
            api_base=lm_base,
            api_key=lm_key,
        )

        # ── Read-only monitoring tools ────────────────────────────────────
        @tool
        def get_system_health() -> str:
            """
            Returns a JSON report of the arbitrage bot's current health.
            Includes portfolio PnL, circuit breaker status, RPC cluster
            health summary, and the last 5 trade outcomes.

            Returns:
                JSON string with keys: portfolio, rpc_cluster, recent_trades,
                timestamp.
            """
            from execution.atomic_executor import TradeLogger
            tl = TradeLogger()
            raw_trades = tl.get_recent_trades(limit=5)
            recent = [
                {
                    "pair":       t.get("pair", ""),
                    "status":     t.get("status", ""),
                    "profit_usd": t.get("actual_profit_usd", "0"),
                    "error":      t.get("error", ""),
                    "timestamp":  t.get("timestamp", ""),
                }
                for t in raw_trades
            ]
            return json.dumps({
                "timestamp":    datetime.now(timezone.utc).isoformat(),
                "portfolio":    portfolio.to_dict(),
                "rpc_cluster":  rpc_cluster.to_dict(),
                "recent_trades": recent,
            }, indent=2)

        @tool
        def get_pair_metrics() -> str:
            """
            Returns success-rate metrics for the top traded pairs
            from the last 200 trade records.

            Returns:
                JSON string mapping pair_name -> {trades, wins, success_rate_pct}.
            """
            from execution.atomic_executor import TradeLogger
            tl = TradeLogger()
            trades = tl.get_recent_trades(limit=200)
            stats: Dict[str, Dict] = {}
            for t in trades:
                pair = t.get("pair", "unknown")
                if pair not in stats:
                    stats[pair] = {"trades": 0, "wins": 0}
                stats[pair]["trades"] += 1
                if t.get("status") == "success":
                    stats[pair]["wins"] += 1
            result = {
                p: {
                    "trades":           v["trades"],
                    "wins":             v["wins"],
                    "success_rate_pct": round(v["wins"] / v["trades"] * 100, 1),
                }
                for p, v in sorted(stats.items(), key=lambda x: -x[1]["trades"])
            }
            return json.dumps(result, indent=2)

        # ── Build agent (no mutation tools) ──────────────────────────────
        _agent = CodeAgent(
            model=llm,
            tools=[get_system_health, get_pair_metrics],
            add_base_tools=False,
            name="HYDRA_MONITOR",   # alphanumeric + underscore only
            max_steps=10,
        )
        logger.info("smolagents AI monitor initialized successfully.")
        return True

    except ImportError:
        logger.info("smolagents not installed — AI audit loop disabled.")
        return False
    except Exception as e:
        logger.warning(f"AI monitor init failed (will retry next cycle): {e}")
        _agent_init_attempted = False  # allow retry
        return False


async def _run_ai_audit() -> Optional[str]:
    """Run one AI audit pass. Returns the agent's output text or None."""
    global _agent, _agent_init_attempted

    if _agent is None:
        if not _try_init_agent():
            return None

    state = portfolio.to_dict()
    prompt = (
        "You are monitoring a Berachain DEX arbitrage bot. "
        f"Current portfolio state: {json.dumps(state)}. "
        "Use get_system_health() for full details and get_pair_metrics() "
        "for per-pair breakdown. "
        "Identify the top 3 risks or anomalies. "
        "Respond with concise bullet points only — no code, no rewrites."
    )

    try:
        # Reset agent conversation memory before each audit
        if hasattr(_agent, "memory") and hasattr(_agent.memory, "reset"):
            _agent.memory.reset()
        elif hasattr(_agent, "logs"):
            _agent.logs = []

        output = await asyncio.wait_for(
            asyncio.to_thread(_agent.run, prompt),
            timeout=90.0,
        )
        return str(output)
    except asyncio.TimeoutError:
        logger.warning("AI audit timed out after 90 s.")
        return None
    except Exception as e:
        logger.error(f"AI audit error: {e}")
        return None


# ── Portfolio sync from real trade history ────────────────────────────────────
_synced_trade_count = 0
_sync_lock = asyncio.Lock()


async def _sync_portfolio() -> None:
    """Load new trades from TradeLogger CSV and update PortfolioState."""
    global _synced_trade_count
    async with _sync_lock:
        try:
            from execution.atomic_executor import TradeLogger
            tl = TradeLogger()
            all_trades = tl.get_recent_trades(limit=1000)
            new_trades = all_trades[_synced_trade_count:]
            async with _portfolio_lock:
                for t in new_trades:
                    try:
                        profit  = float(t.get("actual_profit_usd") or 0)
                        success = (t.get("status") == "success")
                        portfolio.record_trade(profit, success)
                    except (ValueError, TypeError):
                        pass
            _synced_trade_count = len(all_trades)
        except Exception as e:
            logger.debug(f"Portfolio sync error: {e}")


# ── Shared status snapshot ─────────────────────────────────────────────────────
_last_audit_output: Optional[str] = None
_last_audit_at:     Optional[float] = None


def get_monitor_status() -> Dict:
    """
    Synchronous snapshot for the /api/monitor/status endpoint.
    Safe to call from any FastAPI route handler.
    """
    active = rpc_cluster.active_node
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "portfolio": portfolio.to_dict(),
        "circuit_breaker_active": portfolio.circuit_breaker_active,
        "rpc": {
            "active_url":        rpc_cluster._active_url,
            "active_latency_ms": round(active.latency_ms, 1) if active else None,
            "active_block":      active.block_height if active else None,
            "healthy_nodes":     rpc_cluster.to_dict()["healthy_count"],
            "total_nodes":       len(rpc_cluster.nodes),
        },
        "ai_agent": {
            "available":  _agent is not None,
            "last_audit": (
                datetime.fromtimestamp(_last_audit_at, tz=timezone.utc).isoformat()
                if _last_audit_at else None
            ),
            "output":     _last_audit_output,
        },
    }


# ── Background loops ──────────────────────────────────────────────────────────
async def _rpc_health_loop() -> None:
    await rpc_cluster.health_check_all()  # immediate first pass
    while True:
        await asyncio.sleep(RPC_HEALTH_INTERVAL_SEC)
        try:
            await rpc_cluster.health_check_all()
            node = rpc_cluster.active_node
            if node:
                logger.debug(
                    f"RPC best: {node.url[:35]}  "
                    f"latency={node.latency_ms:.0f} ms  block={node.block_height}"
                )
        except Exception as e:
            logger.error(f"RPC health loop error: {e}")


async def _portfolio_sync_loop() -> None:
    await _sync_portfolio()  # immediate first pass
    while True:
        await asyncio.sleep(PORTFOLIO_SYNC_INTERVAL)
        try:
            await _sync_portfolio()
            # Release circuit breaker if cooldown expired
            portfolio.check_and_maybe_release()
        except Exception as e:
            logger.error(f"Portfolio sync loop error: {e}")


async def _ai_audit_loop() -> None:
    global _last_audit_output, _last_audit_at
    await asyncio.sleep(60)  # wait 1 min after startup before first audit
    while True:
        try:
            output = await _run_ai_audit()
            if output:
                _last_audit_output = output
                _last_audit_at     = time.time()
                logger.info(f"AI audit complete:\n{output[:400]}")
        except Exception as e:
            logger.error(f"AI audit loop error: {e}")
        await asyncio.sleep(AI_AUDIT_INTERVAL_SEC)


async def start_monitor() -> None:
    """
    Launch all monitor background coroutines.

    Call once from server.py startup:
        asyncio.create_task(start_monitor())
    """
    logger.info(
        f"HYDRA monitor starting — "
        f"{len(rpc_cluster.nodes)} RPC nodes, "
        f"audit every {AI_AUDIT_INTERVAL_SEC}s"
    )
    await asyncio.gather(
        _rpc_health_loop(),
        _portfolio_sync_loop(),
        _ai_audit_loop(),
        return_exceptions=True,   # one crashed loop must not kill the others
    )
