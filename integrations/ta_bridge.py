import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional, Tuple

from .ta_config import build_ta_config
from .ta_events import emit_events_from
from .ta_result import to_frontend
from .ta_runtime import build_graph

DEFAULT_ANALYSTS: Tuple[str, ...] = ("market", "social", "news", "fundamentals")


@dataclass(frozen=True)
class DeepRunRequest:
    ticker: str
    trade_date: Optional[str] = None
    portfolio_context: str = ""
    selected_analysts: Tuple[str, ...] = DEFAULT_ANALYSTS


def run_deep_analysis_sync(req: DeepRunRequest, emit: Callable[[dict], None] = lambda e: None) -> dict:
    """Blocking — the full 12-agent TA pipeline. Must be called via
    integrations.ta_runtime.submit() (the single-worker executor), never
    directly on the FastAPI event loop: every call inside here (yfinance,
    Reddit, StockTwits, the Anthropic SDK's sync path via langchain) is
    synchronous I/O.

    Deliberately does not call TradingAgentsGraph.propagate() — propagate()
    consumes graph.stream() internally with no hook to forward chunks out,
    so there is no way to get live progress through it. This reimplements
    propagate()'s six steps directly instead.
    """
    trade_date = req.trade_date or date.today().isoformat()
    from .ta_stats import StatsCallbackHandler

    stats_handler = StatsCallbackHandler()
    config = build_ta_config()
    g = build_graph(list(req.selected_analysts), config, callbacks=[stats_handler])

    g.ticker = req.ticker
    g._resolve_pending_entries(req.ticker)

    memory_ctx = g.memory_log.get_past_context(req.ticker)
    past_context = "\n\n".join(x for x in (memory_ctx, req.portfolio_context) if x)
    instrument_context = g.resolve_instrument_context(req.ticker, "stock")

    state = g.propagator.create_initial_state(
        req.ticker,
        trade_date,
        asset_type="stock",
        past_context=past_context,
        instrument_context=instrument_context,
    )
    args = g.propagator.get_graph_args(callbacks=[stats_handler])

    started = time.monotonic()
    final_state: dict = {}
    seen_msg_ids: set = set()
    seen_keys: set = set()
    for chunk in g.graph.stream(state, **args):
        final_state.update(chunk)
        emit_events_from(chunk, seen_msg_ids, seen_keys, emit)
    elapsed_s = round(time.monotonic() - started, 1)

    g._log_state(trade_date, final_state)
    g.memory_log.store_decision(
        ticker=req.ticker,
        trade_date=trade_date,
        final_trade_decision=final_state["final_trade_decision"],
    )
    rating = g.process_signal(final_state["final_trade_decision"])

    stats = stats_handler.get_stats()
    stats["elapsed_s"] = elapsed_s
    return to_frontend(final_state, rating, stats)
