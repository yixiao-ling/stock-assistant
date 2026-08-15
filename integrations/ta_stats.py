import threading
from typing import Any, Dict

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage
from langchain_core.outputs import LLMResult

# Vendored from TradingAgents' cli/stats_handler.py rather than imported —
# cli/utils.py has interactive exit()/getpass() calls that are unsafe to pull
# into a server process, so "never import cli.*" is a hard rule here.

# DeepSeek V4-Flash rates (quick_think_llm, used by 10 of 12 graph nodes).
# Research Manager + Portfolio Manager use the pricier V4-Pro tier, so this
# slightly underestimates total cost — a rough live counter, not an invoice.
_USD_PER_MTOK_IN = 0.14
_USD_PER_MTOK_OUT = 0.28


class StatsCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.llm_calls = 0
        self.tool_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def on_llm_start(self, serialized, prompts, **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_chat_model_start(self, serialized, messages, **kwargs: Any) -> None:
        with self._lock:
            self.llm_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        try:
            generation = response.generations[0][0]
        except (IndexError, TypeError):
            return
        usage_metadata = None
        if hasattr(generation, "message"):
            message = generation.message
            if isinstance(message, AIMessage) and hasattr(message, "usage_metadata"):
                usage_metadata = message.usage_metadata
        if usage_metadata:
            with self._lock:
                self.tokens_in += usage_metadata.get("input_tokens", 0)
                self.tokens_out += usage_metadata.get("output_tokens", 0)

    def on_tool_start(self, serialized, input_str, **kwargs: Any) -> None:
        with self._lock:
            self.tool_calls += 1

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            usd_est = (
                self.tokens_in / 1_000_000 * _USD_PER_MTOK_IN
                + self.tokens_out / 1_000_000 * _USD_PER_MTOK_OUT
            )
            return {
                "llm_calls": self.llm_calls,
                "tool_calls": self.tool_calls,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "usd_est": round(usd_est, 4),
            }
