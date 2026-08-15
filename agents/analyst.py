import asyncio
import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2000

_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


async def fundamental_agent(ticker: str, stock_data: dict, extra_context: str = "") -> str:
    system = (
        "你是价值投资视角的基本面分析师。每条结论必须引用具体数字，"
        "不允许无数据支撑的推断。输出：3-5个关键发现，每条50字以内，"
        "最后给出基本面评级 A/B/C/D。"
    )
    user = (
        f"请分析 {ticker} 的基本面数据：\n{stock_data}"
        + (f"\n\n补充背景：{extra_context}" if extra_context else "")
    )
    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def sentiment_agent(ticker: str, news_list: list, extra_context: str = "") -> str:
    system = (
        "你是情绪分析师。对每条新闻打分（+2强利好到-2强利空），"
        "输出：情绪总分、最重要的3条新闻及其影响、整体情绪判断。"
    )
    news_text = "\n".join(
        f"- [{n.get('publishedAt', '')}] {n.get('title', '')}：{n.get('description', '')}"
        for n in news_list
    )
    user = (
        f"请分析 {ticker} 的近期新闻情绪：\n{news_text}"
        + (f"\n\n补充背景：{extra_context}" if extra_context else "")
    )
    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def technical_agent(ticker: str, stock_data: dict, extra_context: str = "", snapshot: str = "") -> str:
    system = (
        "你是技术面分析师。下面提供的行情快照由程序确定性计算得出，是唯一可信数值来源。"
        "只允许引用快照中出现的具体数字，禁止推断或编造任何未列出的指标值。"
        "用自然语言解读 RSI、MACD、布林带等信号，不堆砌数字，说清楚信号含义和潜在走势方向。"
    )
    if snapshot and not snapshot.startswith("NO_MARKET_DATA"):
        user = (
            f"请对 {ticker} 做技术面分析，以下为确定性计算的真实行情快照：\n\n{snapshot}\n\n"
            f"请解读 RSI、MACD、布林带信号含义，给出短期走势判断。只允许引用快照中出现的数字。"
            + (f"\n\n补充背景：{extra_context}" if extra_context else "")
        )
    else:
        price = stock_data.get("current_price")
        high = stock_data.get("week_52_high")
        low = stock_data.get("week_52_low")
        reason = snapshot or "未获取到行情快照"
        user = (
            f"请对 {ticker} 做技术面分析。当前无法获取详细行情快照（{reason}），"
            f"仅有基础信息：当前价 {price}，52周高 {high}，52周低 {low}。"
            f"请基于这些有限信息给出保守判断，明确说明数据不足，不要编造具体的 RSI/MACD 数值。"
            + (f"\n\n补充背景：{extra_context}" if extra_context else "")
        )
    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def _synthesis_agent(ticker: str, fundamental: str, sentiment: str, technical: str) -> str:
    system = (
        "你是首席投资研究员，负责整合三位分析师的报告，输出完整的综合研究报告。"
        "报告结构：①核心投资观点（2-3句）②基本面要点 ③情绪与催化剂 ④技术面判断 "
        "⑤综合结论与操作建议。每个部分写完整，不截断。"
    )
    user = (
        f"请整合以下 {ticker} 的三份分析报告，输出完整综合研究报告：\n\n"
        f"【基本面报告】\n{fundamental}\n\n"
        f"【情绪报告】\n{sentiment}\n\n"
        f"【技术面报告】\n{technical}"
    )
    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def run_full_analysis(ticker: str, extra_context: str = "") -> dict:
    from data.stock_data import get_news, get_stock_data
    from integrations.ta_snapshot import aget_technical_snapshot

    stock_data = get_stock_data(ticker)
    news_list = get_news(ticker)

    snapshot, fundamental, sentiment = await asyncio.gather(
        aget_technical_snapshot(ticker),
        fundamental_agent(ticker, stock_data, extra_context),
        sentiment_agent(ticker, news_list, extra_context),
    )
    technical = await technical_agent(ticker, stock_data, extra_context, snapshot=snapshot)

    synthesis = await _synthesis_agent(ticker, fundamental, sentiment, technical)

    return {
        "fundamental": fundamental,
        "sentiment": sentiment,
        "technical": technical,
        "synthesis": synthesis,
        "snapshot": snapshot,
    }
