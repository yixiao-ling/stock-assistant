import asyncio
from datetime import date

from .ta_config import ensure_config


def get_technical_snapshot(ticker: str, curr_date: str | None = None, look_back_days: int = 30) -> str:
    """Deterministic OHLCV + indicator snapshot. Never raises — returns a
    NO_MARKET_DATA: sentinel on failure so callers can render it verbatim."""
    ensure_config()
    from tradingagents.dataflows.market_data_validator import build_verified_market_snapshot

    d = curr_date or date.today().isoformat()
    try:
        return build_verified_market_snapshot(ticker, d, look_back_days=look_back_days)
    except Exception as e:
        return f"NO_MARKET_DATA: {ticker} 行情快照获取失败（{e}）"


async def aget_technical_snapshot(ticker: str, curr_date: str | None = None, look_back_days: int = 30) -> str:
    return await asyncio.to_thread(get_technical_snapshot, ticker, curr_date, look_back_days)
