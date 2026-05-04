import sys
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from models.schemas import InvestorProfile, Position

_MACRO_MAP = {
    "interest_rate_sensitive": {"Real Estate", "Utilities", "Financial Services"},
    "usd_strength":            {"Technology", "Consumer Cyclical"},
    "geopolitical_risk":       {"Energy", "Materials", "Industrials"},
    "consumer_confidence":     {"Consumer Cyclical", "Communication Services"},
}

_HHI_THRESHOLDS = (0.15, 0.25)  # (dispersed, moderate, concentrated)


def build_investor_profile(raw_positions: list[dict], cash: float = 0.0) -> InvestorProfile:
    positions: list[Position] = []
    pe_values: list[float] = []

    for raw in raw_positions:
        ticker = raw["ticker"]
        shares = float(raw["shares"])
        avg_cost = float(raw["avg_cost"])
        try:
            info = yf.Ticker(ticker).info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice") or avg_cost
            sector = info.get("sector") or "Unknown"
            pe = info.get("trailingPE")
            if pe:
                pe_values.append(pe)
        except Exception:
            current_price = avg_cost
            sector = "Unknown"

        market_value = shares * current_price
        unrealized_pnl = (current_price - avg_cost) * shares
        unrealized_pnl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost else 0.0

        positions.append(Position(
            ticker=ticker,
            shares=shares,
            avg_cost=avg_cost,
            current_price=current_price,
            sector=sector,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            weight=0.0,  # filled below
        ))

    equity = sum(p.market_value for p in positions)
    total_value = equity + cash

    for p in positions:
        p.weight = p.market_value / total_value if total_value else 0.0

    sector_concentration: dict[str, float] = {}
    for p in positions:
        sector_concentration[p.sector] = sector_concentration.get(p.sector, 0.0) + p.weight

    top_holding_weight = max((p.weight for p in positions), default=0.0)
    tech_weight = sector_concentration.get("Technology", 0.0)
    num_sectors = len(sector_concentration)

    if top_holding_weight > 0.25 or tech_weight > 0.60:
        risk_preference = "aggressive"
    elif num_sectors >= 4 and top_holding_weight <= 0.20:
        risk_preference = "conservative"
    else:
        risk_preference = "moderate"

    return InvestorProfile(
        positions=positions,
        total_value=total_value,
        cash=cash,
        cash_ratio=cash / total_value if total_value else 0.0,
        num_positions=len(positions),
        top_holding_weight=top_holding_weight,
        sector_concentration=sector_concentration,
        macro_exposures={},  # populated by analyze_macro_exposure
        risk_preference=risk_preference,
        avg_holding_pe=sum(pe_values) / len(pe_values) if pe_values else 0.0,
    )


def analyze_concentration_risk(profile: InvestorProfile) -> dict:
    alerts: list[str] = []
    positions_over_10pct: list[dict] = []

    for p in profile.positions:
        pct = p.weight * 100
        if p.weight > 0.20:
            alerts.append(f"{p.ticker} 单仓占比 {pct:.1f}%，高危")
        elif p.weight > 0.10:
            alerts.append(f"{p.ticker} 单仓占比 {pct:.1f}%，警示")
        if p.weight > 0.10:
            positions_over_10pct.append({"ticker": p.ticker, "weight": round(p.weight, 4)})

    return {
        "max_single_position": round(profile.top_holding_weight, 4),
        "positions_over_10pct": positions_over_10pct,
        "alerts": alerts,
    }


def analyze_sector_risk(profile: InvestorProfile) -> dict:
    sc = profile.sector_concentration
    hhi = sum(w ** 2 for w in sc.values())

    if hhi < _HHI_THRESHOLDS[0]:
        concentration_level = "分散"
    elif hhi < _HHI_THRESHOLDS[1]:
        concentration_level = "中等"
    else:
        concentration_level = "集中"

    warnings: list[str] = [
        f"{sector} 占比 {w*100:.1f}%，超过 40% 预警"
        for sector, w in sc.items() if w > 0.40
    ]

    return {
        "sector_weights": {k: round(v, 4) for k, v in sc.items()},
        "hhi": round(hhi, 4),
        "concentration_level": concentration_level,
        "warnings": warnings,
    }


def analyze_macro_exposure(profile: InvestorProfile) -> dict:
    result: dict[str, dict] = {}
    for factor, sectors in _MACRO_MAP.items():
        weight = sum(
            w for sector, w in profile.sector_concentration.items()
            if sector in sectors
        )
        if weight > 0.40:
            level = "高"
        elif weight > 0.20:
            level = "中"
        else:
            level = "低"
        result[factor] = {"weight": round(weight, 4), "level": level}
    return result
