from typing import Any, Dict, List


def _collect_warnings(final_state: dict) -> List[str]:
    """Surface TA's NO_DATA_AVAILABLE sentinel (route_to_vendor's anti-
    hallucination guardrail) rather than letting a silent data gap pass
    through as if every report is fully grounded."""
    labels = {
        "market_report": "行情与技术面",
        "sentiment_report": "社交情绪",
        "news_report": "新闻与宏观",
        "fundamentals_report": "基本面",
    }
    warnings = []
    for key, label in labels.items():
        text = final_state.get(key) or ""
        if "NO_DATA_AVAILABLE" in text or "NO_MARKET_DATA" in text:
            warnings.append(f"{label}：数据缺失")
    return warnings


def to_frontend(final_state: Dict[str, Any], rating: str, stats: Dict[str, Any]) -> Dict[str, Any]:
    ids = final_state.get("investment_debate_state") or {}
    rds = final_state.get("risk_debate_state") or {}
    return {
        "ticker": final_state.get("company_of_interest"),
        "trade_date": final_state.get("trade_date"),
        "rating": rating,
        "reports": {
            "market": final_state.get("market_report") or "",
            "sentiment": final_state.get("sentiment_report") or "",
            "news": final_state.get("news_report") or "",
            "fundamentals": final_state.get("fundamentals_report") or "",
        },
        "research": {
            "bull": ids.get("bull_history") or "",
            "bear": ids.get("bear_history") or "",
            "manager": final_state.get("investment_plan") or "",
        },
        "trader_plan": final_state.get("trader_investment_plan") or "",
        "risk": {
            "aggressive": rds.get("aggressive_history") or "",
            "conservative": rds.get("conservative_history") or "",
            "neutral": rds.get("neutral_history") or "",
        },
        "final_decision": final_state.get("final_trade_decision") or "",
        "warnings": _collect_warnings(final_state),
        "stats": stats,
    }
