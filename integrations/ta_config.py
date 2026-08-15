import os
from pathlib import Path

TA_HOME = Path(os.getenv("TA_HOME", Path(__file__).parent.parent / "var" / "tradingagents"))

_installed = False


def build_ta_config(output_language: str = "简体中文") -> dict:
    from tradingagents.default_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "anthropic"
    config["deep_think_llm"] = "claude-sonnet-4-6"
    config["quick_think_llm"] = "claude-sonnet-4-6"
    config["anthropic_effort"] = None
    config["output_language"] = output_language
    config["checkpoint_enabled"] = False
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["results_dir"] = str(TA_HOME / "logs")
    config["data_cache_dir"] = str(TA_HOME / "cache")
    config["memory_log_path"] = str(TA_HOME / "memory" / "trading_memory.md")
    config["memory_log_max_entries"] = 200

    from .ta_rag_tool import get_filing_excerpts

    # NO_FILINGS_INDEXED degrades gracefully when nothing's uploaded, so this
    # is always on rather than a separate toggle.
    config["extra_analyst_tools"] = {"fundamentals": [get_filing_excerpts]}
    return config


def install_config(output_language: str = "简体中文") -> dict:
    """Idempotent: writes the TA global config singleton once per process."""
    global _installed
    from tradingagents.dataflows.config import set_config

    config = build_ta_config(output_language)
    set_config(config)
    _installed = True
    return config


def ensure_config() -> None:
    if not _installed:
        install_config()
