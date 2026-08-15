from typing import Annotated

from langchain_core.tools import tool

_MAX_PASSAGE_CHARS = 1200
_MAX_TOP_K = 4


@tool
def get_filing_excerpts(
    symbol: Annotated[str, "Ticker symbol, e.g. NVDA"],
    question: Annotated[str, "Specific question about the filing, e.g. segment revenue, guidance, risk factors"],
    top_k: Annotated[int, "Number of passages to return"] = _MAX_TOP_K,
) -> str:
    """Search the user's uploaded SEC filings (10-K/10-Q PDFs) for this
    ticker and return verbatim excerpts with page citations. Call this
    before making any specific claim about segment revenue, forward
    guidance, or risk factors — do not rely on memorized knowledge of past
    filings. Returns NO_FILINGS_INDEXED if nothing has been uploaded for
    this symbol yet; in that case say so rather than guessing.
    """
    from data.rag import query_filings_with_meta

    ticker = symbol.strip().upper()
    passages = query_filings_with_meta(ticker, question, top_k=min(top_k, _MAX_TOP_K))
    if not passages:
        return f"NO_FILINGS_INDEXED: 尚未为 {ticker} 上传任何财报 PDF，无法检索原文。"

    blocks = []
    for p in passages:
        text = (p["text"] or "")[:_MAX_PASSAGE_CHARS]
        blocks.append(f"[p.{p['page']} · {p['source']}]\n{text}")
    return "\n\n---\n\n".join(blocks)
