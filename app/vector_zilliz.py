# app/vector_zilliz.py
"""
Zilliz Cloud (Milvus) adapter — serverless / free-tier friendly.
Uses MilvusClient(uri=..., token=...) as provided by Zilliz Cloud Connect panel.

Exposes:
- upsert_zilliz(docs, embeddings, batch_size=128) -> bool
  docs: list of {"id","text","metadata"}
  embeddings: list[list[float]]
- retrieve_zilliz(query_or_ticker, k=5) -> list[{"score","text","meta"}]
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional

import numpy as np
from pymilvus import MilvusClient, DataType

logger = logging.getLogger("vector_zilliz")
logger.setLevel(logging.INFO)

# env
ZILLIZ_URI = os.getenv("ZILLIZ_URI", "https://in03-982cc98d9d872a1.serverless.gcp-us-west1.cloud.zilliz.com")                # required for Free Tier
ZILLIZ_TOKEN = os.getenv("ZILLIZ_TOKEN", "ac53e89c704282a8d849337a7aa7d3d7f53502b71d3298e43f722da4198bd272fb70396b187d22d93b007124f8cd43d963e2b0fe")            # required for Free Tier
ZILLIZ_COLLECTION = os.getenv("ZILLIZ_COLLECTION", "perfient_collection")
Z_VECTOR_DIM = int(os.getenv("ZILLIZ_VECTOR_DIM", "1536"))
Z_METRIC = os.getenv("ZILLIZ_METRIC", "COSINE").upper()  # COSINE / L2 / IP

_client: Optional[MilvusClient] = None

def _get_client() -> MilvusClient:
    global _client
    if _client is None:
        if not ZILLIZ_URI or not ZILLIZ_TOKEN:
            raise RuntimeError("ZILLIZ_URI and ZILLIZ_TOKEN env vars must be set for Zilliz Cloud")
        logger.info("Connecting to Zilliz Cloud MilvusClient uri=%s", ZILLIZ_URI)
        _client = MilvusClient(uri=ZILLIZ_URI, token=ZILLIZ_TOKEN)
    return _client

def _ensure_collection(dim: int = None):
    client = _get_client()
    coll_name = ZILLIZ_COLLECTION
    # if missing, create the collection
    existing = client.list_collections()
    if coll_name in existing:
        logger.debug("collection %s already exists", coll_name)
        return coll_name

    dim = dim or Z_VECTOR_DIM
    logger.info("Creating collection '%s' dim=%s metric=%s", coll_name, dim, Z_METRIC)
    # lightweight schema
    fields = [
        {"name": "doc_id", "dtype": "VARCHAR", "max_length": 128},
        {"name": "ticker", "dtype": "VARCHAR", "max_length": 16},
        {"name": "text", "dtype": "VARCHAR", "max_length": 4096},
        {"name": "embedding", "dtype": "FLOAT_VECTOR", "dim": dim}
    ]
    client.create_collection(collection_name=coll_name, fields=fields)
    # create index on embedding with HNSW
    index_params = {"index_type": "HNSW", "metric_type": Z_METRIC, "params": {"M": 16, "efConstruction": 256}}
    try:
        client.create_index(collection_name=coll_name, field_name="embedding", index_params=index_params)
    except Exception as e:
        logger.warning("create_index raised: %s (continuing)", e)
    return coll_name

def _sanitize_and_validate(docs: List[Dict[str, Any]], embeddings: List[List[float]], dim: int):
    if not docs:
        return [], [], [], []

    if len(docs) != len(embeddings):
        raise ValueError("docs and embeddings length mismatch")

    ids = []
    tickers = []
    texts = []
    vecs = []

    for i, doc in enumerate(docs):
        # doc id
        did = doc.get("id") or doc.get("metadata", {}).get("doc_id") or doc.get("metadata", {}).get("id") or ""
        if not isinstance(did, str):
            did = str(did)
        ids.append(did[:128])

        # ticker
        tk = (doc.get("metadata", {}) or {}).get("ticker") or doc.get("ticker") or ""
        if not isinstance(tk, str):
            tk = str(tk)
        tickers.append(tk[:16])

        # text
        txt = doc.get("text") or ""
        if not isinstance(txt, str):
            txt = str(txt)
        texts.append(txt[:4096])

        # vector
        v = embeddings[i]
        if hasattr(v, "tolist"):
            v = v.tolist()
        else:
            v = list(v)
        # convert numeric types to floats
        try:
            v = [float(x) for x in v]
        except Exception:
            v = [float(x) if (x is not None) else 0.0 for x in v]
        if len(v) != dim:
            raise ValueError(f"Embedding length mismatch at index {i}: expected {dim}, got {len(v)}")
        vecs.append(v)

    return ids, tickers, texts, vecs

def upsert_zilliz(docs: List[Dict[str, Any]], embeddings: List[List[float]], batch_size: int = 128) -> bool:
    """
    Insert or update docs (id,text,ticker) + embeddings into Zilliz Cloud collection.
    """
    if not docs:
        return True
    dim = len(embeddings[0])
    coll_name = _ensure_collection(dim=dim)
    client = _get_client()

    # prepare and insert in batches
    i = 0
    last_error = None
    while i < len(docs):
        slice_docs = docs[i:i+batch_size]
        slice_embs = embeddings[i:i+batch_size]
        try:
            ids, tickers, texts, vecs = _sanitize_and_validate(slice_docs, slice_embs, dim)
            # MilvusClient expects data as list of columns matching the fields order
            data_block = [ids, tickers, texts, vecs]
            client.insert(collection_name=coll_name, data=data_block)
            i += batch_size
        except Exception as e:
            last_error = e
            logger.exception("Failed to insert batch into Zilliz/Milvus collection. Last error: %s", e)
            raise RuntimeError(f"Failed to insert batch into Zilliz/Milvus collection. Last error: {e}")
    try:
        client.flush(collection_name=coll_name)
    except Exception as e:
        logger.debug("flush warning: %s", e)
    return True

def retrieve_zilliz(query_or_ticker: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    If query_or_ticker is a ticker (1-5 alphabetic), perform metadata query; otherwise do semantic search by embedding.
    Returns list of {"score","text","meta"}.
    """
    client = _get_client()
    coll_name = _ensure_collection()
    is_ticker = isinstance(query_or_ticker, str) and query_or_ticker.isalpha() and 1 <= len(query_or_ticker) <= 5
    results = []
    if is_ticker:
        ticker_upper = query_or_ticker.upper()
        # Try direct ticker lookup first
        expr = f"ticker == '{ticker_upper}'"
        try:
            hits = client.query(collection_name=coll_name, expr=expr, output_fields=["doc_id", "text", "ticker"])
            for h in hits[:k]:
                meta = {"doc_id": h.get("doc_id"), "ticker": h.get("ticker")}
                results.append({"score": 1.0, "text": h.get("text",""), "meta": meta})
            if results:
                return results
        except Exception as e:
            logger.warning("Direct ticker query failed for %s: %s", ticker_upper, e)
        
        # If no results, try searching by doc_id pattern (doc:TICKER)
        try:
            doc_id_pattern = f"doc:{ticker_upper}"
            expr = f"doc_id like '{doc_id_pattern}%'"
            hits = client.query(collection_name=coll_name, expr=expr, output_fields=["doc_id", "text", "ticker"])
            for h in hits[:k]:
                meta = {"doc_id": h.get("doc_id"), "ticker": h.get("ticker")}
                results.append({"score": 1.0, "text": h.get("text",""), "meta": meta})
            if results:
                return results
        except Exception as e:
            logger.warning("Doc ID pattern query failed for %s: %s", ticker_upper, e)
        
        # If ticker not found via metadata, fall back to semantic search
        # This ensures we always return relevant results even if ticker field is missing/incorrect
        logger.info("Ticker %s not found via metadata, falling back to semantic search", ticker_upper)

    # semantic: compute embedding via app.embeddings
    try:
        from app.embeddings import embed_texts
        qemb = embed_texts([query_or_ticker])[0]
    except Exception as e:
        logger.exception("Failed to compute embedding for query: %s", e)
        return []

    search_params = {"metric_type": Z_METRIC, "params": {"ef": 64}}
    try:
        resp = client.search(collection_name=coll_name, data=[qemb], limit=k, output_fields=["doc_id","text","ticker"], search_params=search_params)
        # resp is a list of lists (one list per query)
        hits = resp[0] if resp else []
        out = []
        for h in hits:
            # h typically is dict-like with 'score' and 'entity' payload
            score = float(h.get("score", 0.0))
            text = h.get("text", "") or (h.get("entity") or {}).get("text", "")
            meta = {"doc_id": h.get("doc_id") or (h.get("entity") or {}).get("doc_id"), "ticker": h.get("ticker") or (h.get("entity") or {}).get("ticker")}
            out.append({"score": score, "text": text, "meta": meta})
        return out
    except Exception as e:
        logger.exception("Milvus search failed: %s", e)
        return []
