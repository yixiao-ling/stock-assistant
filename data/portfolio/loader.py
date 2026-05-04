import json
from pathlib import Path

_MOCK_PATH = Path(__file__).parent / "mock_data.json"


def load_portfolio(source: str = "mock") -> dict:
    if source == "mock":
        with open(_MOCK_PATH) as f:
            return json.load(f)
    elif source == "csv":
        raise NotImplementedError("CSV source not yet implemented")
    else:
        raise ValueError(f"Unknown source: {source!r}")
