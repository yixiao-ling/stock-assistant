import asyncio
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import anthropic
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from integrations.auth import require_deep_token

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


# ── /deep/{ticker} · /deep/stream/{job_id} · /deep/result/{job_id} · /deep/jobs ─
# Deep research: TA's full 12-agent LangGraph pipeline. ~$1-1.7/run, 4-8 min,
# so job-id + SSE rather than a blocking request (nginx proxy_read_timeout is
# 300s and this box is single-worker). Gated behind SA_DEEP_TOKEN and capped
# at one run at a time — see integrations/jobs.py::try_start.

class DeepStartRequest(BaseModel):
    trade_date: Optional[str] = None
    with_portfolio: bool = True
    analysts: List[str] = ["market", "social", "news", "fundamentals"]


@app.post("/deep/{ticker}")
async def deep_start(ticker: str, body: DeepStartRequest, _auth=Depends(require_deep_token)):
    from integrations import jobs
    from integrations.ta_bridge import DeepRunRequest, run_deep_analysis_sync
    from integrations.ta_runtime import submit

    ticker = ticker.strip().upper()
    job = jobs.create(ticker)
    if not jobs.try_start(job.id):
        return JSONResponse(status_code=409, content={"error": "已有深度分析在运行中，请稍后再试"})

    loop = asyncio.get_running_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(jobs.append, job, event)

    portfolio_context = ""
    if body.with_portfolio:
        try:
            from integrations.portfolio_context import get_portfolio_context

            portfolio_context = await get_portfolio_context(ticker)
        except Exception:
            portfolio_context = ""

    def run() -> None:
        job.state = "running"
        try:
            req = DeepRunRequest(
                ticker=ticker,
                trade_date=body.trade_date,
                portfolio_context=portfolio_context,
                selected_analysts=tuple(body.analysts),
            )
            result = run_deep_analysis_sync(req, emit=emit)
            job.result = result
            job.state = "done"
            emit({"type": "done", "result_url": f"/deep/result/{job.id}"})
        except Exception as e:
            job.error = str(e)
            job.state = "error"
            emit({"type": "error", "message": str(e)})
        finally:
            jobs.finish(job.id)

    submit(run)
    return {"job_id": job.id}


@app.get("/deep/stream/{job_id}")
async def deep_stream(job_id: str, request: Request, from_seq: int = 0, _auth=Depends(require_deep_token)):
    from integrations import jobs

    job = jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "job not found"})

    # Native EventSource auto-reconnects with a Last-Event-ID header rather
    # than letting JS rewrite the URL's from_seq query param — honor it so a
    # dropped connection resumes instead of replaying the whole backlog.
    last_event_id = request.headers.get("last-event-id")
    start_seq = int(last_event_id) + 1 if last_event_id is not None else from_seq

    async def gen():
        q = jobs.subscribe(job)
        try:
            backlog = [e for e in job.events if e["seq"] >= start_seq]
            last_seq_sent = start_seq - 1
            for e in backlog:
                last_seq_sent = e["seq"]
                yield f"event: {e['type']}\nid: {e['seq']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            if backlog and backlog[-1]["type"] in ("done", "error"):
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if e["seq"] <= last_seq_sent:
                    continue
                last_seq_sent = e["seq"]
                yield f"event: {e['type']}\nid: {e['seq']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                if e["type"] in ("done", "error"):
                    break
        finally:
            jobs.unsubscribe(job, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/deep/result/{job_id}")
async def deep_result(job_id: str, _auth=Depends(require_deep_token)):
    from integrations import jobs

    job = jobs.get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "job not found"})
    if job.state == "done":
        return job.result
    if job.state == "error":
        return {"error": job.error}
    return {"state": job.state, "seq": job.next_seq}


@app.get("/deep/jobs")
async def deep_jobs(_auth=Depends(require_deep_token)):
    from integrations import jobs

    return [
        {"job_id": j.id, "ticker": j.ticker, "state": j.state, "created_at": j.created_at}
        for j in jobs.list_recent(20)
    ]


# ── /review · /review/resolve ────────────────────────────────────────────────
# Decision review: reads TA's outcome-graded memory log (every deep-run
# decision, realized return + alpha vs benchmark once resolved, and the
# model's own reflection on what it got right or wrong).

@app.get("/review")
async def review(ticker: str = "", limit: int = 50):
    try:
        from integrations.ta_memory import list_entries, summary

        return {
            "summary": summary(),
            "entries": list_entries(ticker=ticker or None, limit=limit),
        }
    except Exception as e:
        return {"error": str(e)}


class ReviewResolveRequest(BaseModel):
    ticker: Optional[str] = None


@app.post("/review/resolve")
async def review_resolve(body: ReviewResolveRequest, _auth=Depends(require_deep_token)):
    try:
        from integrations.ta_memory import resolve_pending_sync
        from integrations.ta_runtime import submit

        future = submit(resolve_pending_sync, body.ticker)
        result = await asyncio.wrap_future(future)
        return result
    except Exception as e:
        return {"error": str(e)}
