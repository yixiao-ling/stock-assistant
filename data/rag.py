import hashlib
from pathlib import Path

import chromadb
import fitz  # pymupdf

_CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
_CHUNK_CHARS = 2000  # ~500 tokens at 1 token ≈ 4 chars


def _get_collection(ticker: str):
    client = chromadb.PersistentClient(path=_CHROMA_PATH)
    return client.get_or_create_collection(
        name=f"{ticker}_filings",
        metadata={"hnsw:space": "cosine"},
    )


def load_and_chunk_pdf(filepath: str, ticker: str) -> list[dict]:
    # doc_id is a hash of the file's own bytes, not a per-call counter — a
    # second filing for the same ticker used to restart chunk_id at 0 and get
    # silently deduped away as "already exists" (store_chunks' `existing`
    # check matched `{ticker}_chunk_{n}` regardless of which PDF it came
    # from). Keyed by content, a second upload of a genuinely new filing gets
    # its own id space; re-uploading the same PDF is still a correct no-op.
    doc_id = hashlib.sha256(Path(filepath).read_bytes()).hexdigest()[:12]
    source = Path(filepath).name

    doc = fitz.open(filepath)
    chunks = []
    chunk_id = 0

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text().strip()
        if not text:
            continue

        for start in range(0, len(text), _CHUNK_CHARS):
            chunk_text = text[start : start + _CHUNK_CHARS].strip()
            if not chunk_text:
                continue
            chunks.append(
                {
                    "text": chunk_text,
                    "ticker": ticker,
                    "page": page_num,
                    "chunk_id": chunk_id,
                    "doc_id": doc_id,
                    "source": source,
                }
            )
            chunk_id += 1

    doc.close()
    return chunks


def store_chunks(ticker: str, chunks: list[dict]) -> None:
    if not chunks:
        return

    collection = _get_collection(ticker)
    existing = set(collection.get()["ids"])

    new_ids, new_docs, new_metas = [], [], []
    for chunk in chunks:
        doc_id = chunk.get("doc_id", "")
        chroma_id = f"{ticker}_{doc_id}_{chunk['chunk_id']}" if doc_id else f"{ticker}_chunk_{chunk['chunk_id']}"
        if chroma_id in existing:
            continue
        new_ids.append(chroma_id)
        new_docs.append(chunk["text"])
        new_metas.append(
            {
                "ticker": chunk["ticker"],
                "page": chunk["page"],
                "doc_id": doc_id,
                "source": chunk.get("source", ""),
            }
        )

    if new_ids:
        collection.add(ids=new_ids, documents=new_docs, metadatas=new_metas)
        print(f"[store_chunks] 存入 {len(new_ids)} 个 chunks（{ticker}）")
    else:
        print(f"[store_chunks] 已存在，跳过（{ticker}）")


def query_filings(ticker: str, question: str, top_k: int = 5) -> list[str]:
    collection = _get_collection(ticker)
    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[question], n_results=min(top_k, collection.count()))
    return results["documents"][0]


def query_filings_with_meta(ticker: str, question: str, top_k: int = 5) -> list[dict]:
    """Like query_filings but keeps page/source metadata for citations —
    used by the TA filing-excerpt tool. query_filings itself is left
    untouched so /rag/query has zero regression risk."""
    collection = _get_collection(ticker)
    if collection.count() == 0:
        return []

    results = collection.query(query_texts=[question], n_results=min(top_k, collection.count()))
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    return [
        {"text": doc, "page": meta.get("page"), "source": meta.get("source") or "未知来源"}
        for doc, meta in zip(docs, metas)
    ]
