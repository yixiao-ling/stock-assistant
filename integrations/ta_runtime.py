from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from tradingagents.graph.trading_graph import TradingAgentsGraph

# TA never sets max_tokens anywhere in its LLM construction path — every
# client falls back to langchain_anthropic's default of 1024, which silently
# truncates every agent report (they're all prompted to write "详细报告").
# This is the only override this subclass makes.
_MAX_TOKENS = 8000
_TIMEOUT = 180
_MAX_RETRIES = 3


class SAGraph(TradingAgentsGraph):
    def __init__(self, selected_analysts=None, debug=False, config: dict = None, callbacks=None):
        selected_analysts = selected_analysts or ["market", "social", "news", "fundamentals"]
        super().__init__(selected_analysts=selected_analysts, debug=debug, config=config, callbacks=callbacks)

        # _get_provider_kwargs() below only fixes the truncation for
        # providers whose client class forwards "max_tokens" out of its own
        # _PASSTHROUGH_KWARGS tuple (true for anthropic_client.py, NOT true
        # for openai_client.py — DeepSeek and everything else routed through
        # NormalizedChatOpenAI silently drops it). Both deep/quick LLM
        # objects are plain pydantic ChatModel instances by the time
        # super().__init__() returns, so set the field directly — provider-
        # agnostic and doesn't depend on any passthrough list at all.
        for llm in (self.deep_thinking_llm, self.quick_thinking_llm):
            llm.max_tokens = _MAX_TOKENS

        # DeepSeek's V4 models reason internally by default (a hidden
        # `reasoning_content` field) and that reasoning shares the same
        # max_tokens budget as the final answer — verified empirically: a
        # 3-part synthesis prompt at max_tokens=3000 consumed all 3000 on
        # reasoning_content and returned empty content with finish_reason
        # "length". Every agent's prompt here already does the structuring
        # work explicitly, so there's nothing thinking mode adds for this
        # use case — disable it so max_tokens goes entirely to the answer.
        if (self.config or {}).get("llm_provider") == "deepseek":
            for llm in (self.deep_thinking_llm, self.quick_thinking_llm):
                llm.extra_body = {"thinking": {"type": "disabled"}}

        # self.tool_nodes (built during super().__init__() via virtual
        # dispatch to _create_tool_nodes below) already has the extra tools.
        # graph_setup/workflow/graph are hardcoded inline in
        # TradingAgentsGraph.__init__ with no extra_analyst_tools kwarg, so
        # rebuild just those three here rather than duplicating the rest of
        # __init__ (analyst_execution plan, edges, etc.) to override one
        # constructor call — that duplication is exactly the "fork wearing a
        # disguise" the sa-integration branch patch was written to avoid.
        extra = (self.config or {}).get("extra_analyst_tools")
        if extra:
            from tradingagents.graph.setup import GraphSetup

            self.graph_setup = GraphSetup(
                self.quick_thinking_llm,
                self.deep_thinking_llm,
                self.tool_nodes,
                self.conditional_logic,
                analyst_concurrency_limit=self.config.get("analyst_concurrency_limit", 1),
                extra_analyst_tools=extra,
            )
            self.workflow = self.graph_setup.setup_graph(selected_analysts)
            self.graph = self.workflow.compile()

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        kwargs = super()._get_provider_kwargs()
        kwargs["max_tokens"] = _MAX_TOKENS
        kwargs["timeout"] = _TIMEOUT
        kwargs["max_retries"] = _MAX_RETRIES
        return kwargs

    def _create_tool_nodes(self) -> Dict[str, Any]:
        nodes = super()._create_tool_nodes()
        extra_fundamentals = ((self.config or {}).get("extra_analyst_tools") or {}).get("fundamentals")
        if extra_fundamentals:
            from langgraph.prebuilt import ToolNode
            from tradingagents.agents.utils.agent_utils import (
                get_balance_sheet,
                get_cashflow,
                get_fundamentals,
                get_income_statement,
            )

            nodes["fundamentals"] = ToolNode(
                [get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement] + list(extra_fundamentals)
            )
        return nodes


def build_graph(selected_analysts: List[str], config: dict, callbacks: Optional[list] = None) -> SAGraph:
    """Construction is cheap (no network calls) — a fresh graph per run keeps
    per-run stats isolated without needing to reset a cached instance."""
    return SAGraph(selected_analysts=selected_analysts, debug=False, config=config, callbacks=callbacks or [])


# Single worker: TA's dataflows config is a process-global mutable singleton
# (tradingagents.dataflows.config._config) written by set_config() on every
# TradingAgentsGraph.__init__. Serializing all runs through one thread means
# two runs can never observe each other's config mid-flight.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ta")


def submit(fn, *args, **kwargs):
    return _EXECUTOR.submit(fn, *args, **kwargs)
