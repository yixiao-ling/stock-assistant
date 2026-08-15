from typing import Callable, Set

Emit = Callable[[dict], None]

# Graph order, top-level report keys.
_STAGE_KEYS = (
    ("market_report", "行情与技术面"),
    ("sentiment_report", "社交情绪"),
    ("news_report", "新闻与宏观"),
    ("fundamentals_report", "基本面"),
)

_DEBATE_KEYS = (
    ("bull_history", "多头研究员"),
    ("bear_history", "空头研究员"),
)

_RISK_KEYS = (
    ("aggressive_history", "激进风控"),
    ("conservative_history", "保守风控"),
    ("neutral_history", "中性风控"),
)


def _emit_once(seen_keys: Set[str], key: str, label: str, text: str, emit: Emit) -> None:
    if not text or key in seen_keys:
        return
    seen_keys.add(key)
    emit({"type": "stage", "key": key, "label": label, "status": "done", "chars": len(text)})
    emit({"type": "section", "key": key, "text": text})


def emit_events_from(chunk: dict, seen_msg_ids: Set[str], seen_keys: Set[str], emit: Emit) -> None:
    """Derive progress events from a graph.stream(..., stream_mode="values")
    chunk. Stage keys go from empty to non-empty exactly once each as the
    graph advances — same signal cli/main.py's live TUI uses, reimplemented
    here rather than imported (cli.* is off-limits from a server)."""
    messages = chunk.get("messages") or []
    if messages:
        last = messages[-1]
        msg_id = getattr(last, "id", None)
        if msg_id and msg_id not in seen_msg_ids:
            seen_msg_ids.add(msg_id)
            for tc in getattr(last, "tool_calls", None) or []:
                emit({"type": "tool", "tool": tc.get("name"), "args": tc.get("args", {})})

    for key, label in _STAGE_KEYS:
        _emit_once(seen_keys, key, label, chunk.get(key) or "", emit)

    ids = chunk.get("investment_debate_state") or {}
    for sub_key, label in _DEBATE_KEYS:
        _emit_once(seen_keys, f"investment_debate_state.{sub_key}", label, ids.get(sub_key) or "", emit)
    judge = ids.get("judge_decision") or ""
    if judge and "investment_debate_state.judge_decision" not in seen_keys:
        _emit_once(seen_keys, "investment_debate_state.judge_decision", "研究主管定调", judge, emit)
        _emit_once(seen_keys, "investment_plan", "研究主管定调", chunk.get("investment_plan") or "", emit)

    _emit_once(seen_keys, "trader_investment_plan", "交易员方案", chunk.get("trader_investment_plan") or "", emit)

    rds = chunk.get("risk_debate_state") or {}
    for sub_key, label in _RISK_KEYS:
        _emit_once(seen_keys, f"risk_debate_state.{sub_key}", label, rds.get(sub_key) or "", emit)

    _emit_once(seen_keys, "final_trade_decision", "投资经理终裁", chunk.get("final_trade_decision") or "", emit)
