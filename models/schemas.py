from dataclasses import dataclass, field


@dataclass
class Position:
    ticker: str
    shares: float
    avg_cost: float
    current_price: float
    sector: str
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    weight: float


@dataclass
class InvestorProfile:
    positions: list[Position] = field(default_factory=list)
    total_value: float = 0.0
    cash: float = 0.0
    cash_ratio: float = 0.0
    num_positions: int = 0
    top_holding_weight: float = 0.0
    sector_concentration: dict[str, float] = field(default_factory=dict)
    macro_exposures: dict[str, float] = field(default_factory=dict)
    risk_preference: str = ""
    avg_holding_pe: float = 0.0


@dataclass
class DebateResult:
    ticker: str
    bull_case: str
    bear_case: str
    bull_rebuttal: str
    bear_rebuttal: str
    verdict: str
