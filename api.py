from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents.analyst import run_full_analysis
from agents.debate import run_debate
from agents.portfolio_advisor import portfolio_advisor_agent
from data.portfolio.loader import load_portfolio
from data.portfolio.risk_analyzer import (
    analyze_concentration_risk,
    analyze_macro_exposure,
    analyze_sector_risk,
    build_investor_profile,
)

app = FastAPI(title="股票投研助手 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND = Path(__file__).parent / "index.html"


@app.get("/")
async def serve_frontend():
    return FileResponse(_FRONTEND, media_type="text/html")



# ── /analyze/{ticker} ────────────────────────────────────────────────────────

@app.post("/analyze/{ticker}")
async def analyze(ticker: str):
    try:
        result = await run_full_analysis(ticker.strip().upper())
        return result
    except Exception as e:
        return {"error": str(e)}


# ── /debate/{ticker} ─────────────────────────────────────────────────────────

class DebateRequest(BaseModel):
    fundamental: str
    sentiment: str
    technical: str


@app.post("/debate/{ticker}")
async def debate(ticker: str, body: DebateRequest):
    try:
        result = await run_debate(
            ticker.strip().upper(),
            body.fundamental,
            body.sentiment,
            body.technical,
        )
        return asdict(result)
    except Exception as e:
        return {"error": str(e)}


# ── /portfolio ────────────────────────────────────────────────────────────────

@app.get("/portfolio")
async def portfolio():
    try:
        raw = load_portfolio("mock")
        profile = build_investor_profile(raw["positions"], cash=raw.get("cash", 0.0))
        concentration_risk = analyze_concentration_risk(profile)
        sector_risk = analyze_sector_risk(profile)
        macro_exposure = analyze_macro_exposure(profile)

        positions_data = [
            {
                "ticker": p.ticker,
                "shares": p.shares,
                "avg_cost": p.avg_cost,
                "current_price": p.current_price,
                "sector": p.sector,
                "market_value": p.market_value,
                "unrealized_pnl": p.unrealized_pnl,
                "unrealized_pnl_pct": p.unrealized_pnl_pct,
                "weight": p.weight,
            }
            for p in profile.positions
        ]

        return {
            "summary": {
                "total_value": profile.total_value,
                "cash": profile.cash,
                "cash_ratio": profile.cash_ratio,
                "num_positions": profile.num_positions,
                "risk_preference": profile.risk_preference,
                "avg_holding_pe": profile.avg_holding_pe,
            },
            "positions": positions_data,
            "concentration_risk": concentration_risk,
            "sector_risk": sector_risk,
            "macro_exposure": macro_exposure,
        }
    except Exception as e:
        return {"error": str(e)}


# ── /advisor ──────────────────────────────────────────────────────────────────

class AdvisorRequest(BaseModel):
    scenario: str = ""


@app.post("/advisor")
async def advisor(body: AdvisorRequest):
    try:
        raw = load_portfolio("mock")
        profile = build_investor_profile(raw["positions"], cash=raw.get("cash", 0.0))
        concentration_risk = analyze_concentration_risk(profile)
        sector_risk = analyze_sector_risk(profile)
        macro_exposure = analyze_macro_exposure(profile)

        text = await portfolio_advisor_agent(
            profile=profile,
            concentration_risk=concentration_risk,
            sector_risk=sector_risk,
            macro_exposure=macro_exposure,
            scenario=body.scenario or None,
        )
        return {"analysis": text}
    except Exception as e:
        return {"error": str(e)}
