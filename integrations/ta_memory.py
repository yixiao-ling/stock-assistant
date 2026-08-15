from typing import Optional

from .ta_config import build_ta_config


def _get_memory_log():
    from tradingagents.agents.utils.memory import TradingMemoryLog

    return TradingMemoryLog(build_ta_config())


def _parse_pct(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return float(s.strip().rstrip("%")) / 100
    except ValueError:
        return None


def list_entries(ticker: Optional[str] = None, limit: int = 50) -> list:
    """TradingMemoryLog.load_entries()/_parse_entry() already return exactly
    the shape the UI needs (date/ticker/rating/pending/raw/alpha/holding/
    decision/reflection) — reused verbatim, just sorted and floated."""
    log = _get_memory_log()
    entries = log.load_entries()
    if ticker:
        t = ticker.strip().upper()
        entries = [e for e in entries if e["ticker"] == t]
    entries = sorted(entries, key=lambda e: e["date"], reverse=True)
    return [
        {**e, "raw_pct": _parse_pct(e.get("raw")), "alpha_pct": _parse_pct(e.get("alpha"))}
        for e in entries[:limit]
    ]


def summary() -> dict:
    log = _get_memory_log()
    entries = log.load_entries()
    n_total = len(entries)
    resolved = [e for e in entries if not e["pending"]]
    n_resolved = len(resolved)

    alphas = [a for a in (_parse_pct(e.get("alpha")) for e in resolved) if a is not None]
    win_rate = (sum(1 for a in alphas if a > 0) / len(alphas)) if alphas else None
    avg_alpha = (sum(alphas) / len(alphas)) if alphas else None

    by_rating: dict = {}
    for e in resolved:
        bucket = by_rating.setdefault(e["rating"], {"n": 0, "_alphas": []})
        bucket["n"] += 1
        a = _parse_pct(e.get("alpha"))
        if a is not None:
            bucket["_alphas"].append(a)
    for bucket in by_rating.values():
        alist = bucket.pop("_alphas")
        bucket["avg_alpha"] = (sum(alist) / len(alist)) if alist else None

    return {
        "n_total": n_total,
        "n_resolved": n_resolved,
        "n_pending": n_total - n_resolved,
        "win_rate": win_rate,
        "avg_alpha": avg_alpha,
        "by_rating": by_rating,
    }


def resolve_pending_sync(ticker: Optional[str] = None) -> dict:
    """Blocking — must run via integrations.ta_runtime.submit(), never on the
    event loop (constructs LLM clients and makes a real reflection call per
    ticker, ~$0.01 each). Sweeps every distinct pending ticker (or just
    `ticker` if given) rather than the upstream behavior of only resolving
    on the next same-ticker deep run.
    """
    from .ta_runtime import build_graph

    config = build_ta_config()
    g = build_graph(["market"], config)  # any single analyst — only memory_log/_resolve_pending_entries needed

    log = g.memory_log
    pending_before = log.get_pending_entries()
    if ticker:
        pending_before = [e for e in pending_before if e["ticker"] == ticker.strip().upper()]
    tickers = sorted({e["ticker"] for e in pending_before})

    for t in tickers:
        g._resolve_pending_entries(t)

    pending_after = {e["ticker"] for e in log.get_pending_entries() if e["ticker"] in tickers}
    n_after = sum(1 for e in log.get_pending_entries() if e["ticker"] in tickers)
    return {"resolved": len(pending_before) - n_after, "still_pending": sorted(pending_after)}
