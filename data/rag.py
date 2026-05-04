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
        doc_id = f"{ticker}_chunk_{chunk['chunk_id']}"
        if doc_id in existing:
            continue
        new_ids.append(doc_id)
        new_docs.append(chunk["text"])
        new_metas.append({"ticker": chunk["ticker"], "page": chunk["page"]})

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
