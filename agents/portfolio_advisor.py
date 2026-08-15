import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from data.stock_data import get_news, get_stock_data
from models.schemas import InvestorProfile

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2000

_client = anthropic.AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

PORTFOLIO_ADVISOR_SYSTEM = (
    "你是这位投资者的私人 AI 顾问，你是唯一知道他完整持仓的 AI。\n"
    "你的分析必须是个性化的，禁止输出任何在不知道持仓情况下也能说的话。\n"
    "裁决结构：\n"
    "1. 持仓健康度总评（A/B/C/D评级 + 一句话理由）\n"
    "2. 最需要关注的1个风险（具体到股票或行业）\n"
    "3. 当前持仓结构与风险偏好是否匹配\n"
    "4. 如果发生[用户指定的宏观场景]，受影响最大的持仓是哪个，为什么\n"
    "5. 一个具体的再平衡建议（不是'分散投资'，而是'考虑将XX从Y%降到Z%'）\n"
    "输出风格：像了解你3年的私人顾问，直接、有观点、不废话。"
)


def _format_profile(profile: InvestorProfile) -> str:
    lines = [
        f"总资产：${profile.total_value:,.0f}（现金 ${profile.cash:,.0f}，现金比 {profile.cash_ratio*100:.1f}%）",
        f"持仓数：{profile.num_positions} 支，风险偏好：{profile.risk_preference}",
        f"平均PE：{profile.avg_holding_pe:.1f}",
        "",
        "【各持仓明细】",
    ]
    for p in profile.positions:
        pnl_sign = "+" if p.unrealized_pnl >= 0 else ""
        lines.append(
            f"  {p.ticker}（{p.sector}）：{p.shares:.0f}股，成本${p.avg_cost:.2f}，"
            f"现价${p.current_price:.2f}，市值${p.market_value:,.0f}，"
            f"占比{p.weight*100:.1f}%，浮盈{pnl_sign}{p.unrealized_pnl_pct:.1f}%"
        )
    lines += [
        "",
        "【行业分布】",
        *[f"  {sector}：{w*100:.1f}%" for sector, w in profile.sector_concentration.items()],
    ]
    return "\n".join(lines)


def _format_risks(
    concentration_risk: dict,
    sector_risk: dict,
    macro_exposure: dict,
) -> str:
    conc_alerts = "\n".join(f"  - {a}" for a in concentration_risk.get("alerts", [])) or "  无"
    sector_warnings = "\n".join(f"  - {w}" for w in sector_risk.get("warnings", [])) or "  无"
    macro_lines = "\n".join(
        f"  {k}：权重{v['weight']*100:.1f}%，敞口{v['level']}"
        for k, v in macro_exposure.items()
    )
    return (
        f"【集中度风险】\n{conc_alerts}\n"
        f"HHI集中度：{sector_risk.get('hhi', 0):.3f}（{sector_risk.get('concentration_level', '')}）\n\n"
        f"【行业风险预警】\n{sector_warnings}\n\n"
        f"【宏观敞口】\n{macro_lines}"
    )


async def portfolio_advisor_agent(
    profile: InvestorProfile,
    concentration_risk: dict,
    sector_risk: dict,
    macro_exposure: dict,
    scenario: str = None,
) -> str:
    profile_text = _format_profile(profile)
    risk_text = _format_risks(concentration_risk, sector_risk, macro_exposure)
    scenario_text = f"\n\n【用户指定宏观场景】\n{scenario}" if scenario else "\n\n【宏观场景】未指定，请选取当前最相关的一个宏观风险场景进行分析。"

    user = (
        f"以下是该投资者的完整持仓和风险数据，请给出私人顾问级别的分析：\n\n"
        f"{profile_text}\n\n"
        f"{risk_text}"
        f"{scenario_text}"
    )

    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=3000,
        system=PORTFOLIO_ADVISOR_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


async def analyze_ticker_with_portfolio_context(
    ticker: str,
    profile: InvestorProfile,
) -> str:
    stock_data = get_stock_data(ticker)
    news_list = get_news(ticker, days=7)
    news_text = "\n".join(
        f"- [{n.get('publishedAt', '')[:10]}] {n.get('title', '')}"
        for n in news_list[:8]
    )

    existing = next((p for p in profile.positions if p.ticker == ticker), None)

    if existing:
        context_block = (
            f"【持仓背景】\n"
            f"该投资者已持有 {ticker} {existing.shares:.0f} 股，"
            f"成本价 ${existing.avg_cost:.2f}，当前价 ${existing.current_price:.2f}，"
            f"浮盈 {'+' if existing.unrealized_pnl_pct >= 0 else ''}{existing.unrealized_pnl_pct:.1f}%，"
            f"持仓市值 ${existing.market_value:,.0f}，占总仓位 {existing.weight*100:.1f}%。\n"
            f"这是对已持有仓位的再评估。"
        )
        task_instruction = (
            "请结合该投资者的成本价和盈亏情况，给出：\n"
            "① 当前是否应该持有、加仓或减仓\n"
            "② 如果减仓，建议将仓位从当前的 X% 调整到什么比例\n"
            "③ 该仓位在整体组合中的角色是否需要重新定位"
        )
    else:
        other_tickers = [p.ticker for p in profile.positions]
        context_block = (
            f"【持仓背景】\n"
            f"该投资者目前不持有 {ticker}，当前持仓为：{', '.join(other_tickers)}。\n"
            f"现金比例：{profile.cash_ratio*100:.1f}%，总资产 ${profile.total_value:,.0f}。"
        )
        task_instruction = (
            "请在分析结尾给出建仓建议：\n"
            "① 是否值得买入，最多建议配置多大仓位比例（相对总资产）\n"
            "② 与现有持仓（科技/金融/能源）的相关性分析：是分散了风险还是加剧集中？\n"
            "③ 如果买入，当前组合的哪个仓位可以适当减少以腾出资金"
        )

    system = (
        "你是这位投资者的私人 AI 分析师。你掌握该投资者的完整持仓，"
        "你的分析必须结合持仓背景，禁止输出任何与持仓无关的通用分析。"
    )
    user = (
        f"【股票基本面数据 - {ticker}】\n"
        f"当前价：${stock_data.get('current_price')}，PE：{stock_data.get('pe_ratio')}，"
        f"EV/EBITDA：{stock_data.get('ev_ebitda')}，市值：${stock_data.get('market_cap'):,}，"
        f"52周区间：${stock_data.get('week_52_low')} - ${stock_data.get('week_52_high')}，"
        f"行业：{stock_data.get('sector')}\n\n"
        f"【近期新闻】\n{news_text}\n\n"
        f"{context_block}\n\n"
        f"{task_instruction}"
    )

    response = await _client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text
