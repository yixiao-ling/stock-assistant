import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
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
from data.rag import load_and_chunk_pdf, query_filings, store_chunks

load_dotenv()
_rag_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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


# ── /rag/upload ───────────────────────────────────────────────────────────────

@app.post("/rag/upload")
async def rag_upload(ticker: str = Form(...), file: UploadFile = File(...)):
    try:
        ticker = ticker.strip().upper()
        suffix = Path(file.filename).suffix or ".pdf"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name
        chunks = load_and_chunk_pdf(tmp_path, ticker)
        Path(tmp_path).unlink(missing_ok=True)
        store_chunks(ticker, chunks)
        return {"ticker": ticker, "chunks": len(chunks)}
    except Exception as e:
        return {"error": str(e)}


# ── /rag/query ────────────────────────────────────────────────────────────────

class RagQueryRequest(BaseModel):
    ticker: str
    question: str


@app.post("/rag/query")
async def rag_query(body: RagQueryRequest):
    try:
        ticker = body.ticker.strip().upper()
        passages = query_filings(ticker, body.question, top_k=5)
        if not passages:
            return {"answer": "未找到相关内容，请先上传该公司的财报 PDF。"}

        context = "\n\n---\n\n".join(passages)
        response = await _rag_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            system=(
                "你是财报分析专家。根据以下财报原文片段回答用户问题，"
                "引用具体数据，不允许无依据的推断。如原文未提及，请明确说明。"
            ),
            messages=[{
                "role": "user",
                "content": f"【财报原文片段】\n{context}\n\n【问题】\n{body.question}",
            }],
        )
        return {"answer": response.content[0].text}
    except Exception as e:
        return {"error": str(e)}
