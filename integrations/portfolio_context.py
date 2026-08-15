import asyncio
import time

from data.portfolio.loader import load_portfolio
from data.portfolio.risk_analyzer import analyze_concentration_risk, build_investor_profile
from models.schemas import InvestorProfile

_CACHE_TTL_S = 300
_cache = {"profile": None, "ts": 0.0}
_lock = asyncio.Lock()


def _build_profile_sync() -> InvestorProfile:
    raw = load_portfolio("mock")
    return build_investor_profile(raw["positions"], cash=raw.get("cash", 0.0))


async def get_cached_profile(ttl_s: int = _CACHE_TTL_S) -> InvestorProfile:
    """build_investor_profile does N serial blocking yf.Ticker().info calls —
    threadpooled + TTL-cached so a /deep start doesn't add ~5s of latency and
    doesn't compete with /portfolio for the same yfinance round-trips."""
    async with _lock:
        now = time.time()
        if _cache["profile"] is not None and now - _cache["ts"] < ttl_s:
            return _cache["profile"]
        profile = await asyncio.to_thread(_build_profile_sync)
        _cache["profile"] = profile
        _cache["ts"] = now
        return profile


def build_portfolio_block(profile: InvestorProfile, ticker: str) -> str:
    """~250 tokens of Chinese markdown describing the investor's holdings
    relative to `ticker`, for injection into TA's past_context (read only by
    the Portfolio Manager). Mines the existing/not-existing branch logic from
    agents/portfolio_advisor.py::analyze_ticker_with_portfolio_context — dead
    code today (api.py never calls it) — without importing that
    CLAUDE.md-protected module, so this can evolve independently.

    The header re-scopes the block: past_context's literal prompt label is
    "Lessons from prior decisions and outcomes", and holdings are not a
    lesson — without this the model may file "already holds 22%" under past
    mistakes instead of present position sizing.
    """
    existing = next((p for p in profile.positions if p.ticker == ticker), None)
    alerts = analyze_concentration_risk(profile).get("alerts") or []

    lines = [
        "### 当前投资组合背景（这不是历史教训，是投资者此刻的实际持仓）",
        f"总资产 ${profile.total_value:,.0f}，现金比 {profile.cash_ratio * 100:.1f}%，风险偏好 {profile.risk_preference}",
    ]
    if existing:
        pnl_sign = "+" if existing.unrealized_pnl_pct >= 0 else ""
        lines.append(
            f"该投资者已持有 {ticker} {existing.shares:.0f} 股，成本价 ${existing.avg_cost:.2f}，"
            f"现价 ${existing.current_price:.2f}，浮盈 {pnl_sign}{existing.unrealized_pnl_pct:.1f}%，"
            f"占总仓位 {existing.weight * 100:.1f}%"
        )
    else:
        other = ", ".join(p.ticker for p in profile.positions) or "无"
        lines.append(f"该投资者目前不持有 {ticker}，当前持仓为：{other}")

    sectors = ", ".join(f"{s} {w * 100:.0f}%" for s, w in profile.sector_concentration.items())
    if sectors:
        lines.append(f"行业分布：{sectors}")
    if alerts:
        lines.append("集中度告警：" + "；".join(alerts))

    return "\n".join(lines)


async def get_portfolio_context(ticker: str) -> str:
    profile = await get_cached_profile()
    return build_portfolio_block(profile, ticker)
