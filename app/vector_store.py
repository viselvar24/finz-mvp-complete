# app/vector_store.py
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger("vector_store")
logger.setLevel(logging.INFO)

BACKEND = os.getenv("USE_VECTOR_BACKEND", "zilliz").lower()

def _noop_upsert(docs, embeddings):
    logger.warning("No vector backend configured; upsert noop")
    return False

def _noop_retrieve(q, k=5):
    return []

if BACKEND == "zilliz":
    try:
        from app.vector_zilliz import upsert_zilliz as _backend_upsert, retrieve_zilliz as _backend_retrieve
        logger.info("vector_store: using zilliz backend")
    except Exception as e:
        logger.exception("vector_store import zilliz failed: %s", e)
        _backend_upsert = _noop_upsert
        _backend_retrieve = _noop_retrieve
elif BACKEND == "pinecone":
    try:
        from app.vector_pinecone import upsert_pinecone as _backend_upsert, retrieve_pinecone as _backend_retrieve
        logger.info("vector_store: using pinecone backend")
    except Exception as e:
        logger.exception("vector_store import pinecone failed: %s", e)
        _backend_upsert = _noop_upsert
        _backend_retrieve = _noop_retrieve
else:
    try:
        from app.vector_local import upsert_documents_local as _backend_upsert, retrieve_local as _backend_retrieve
        logger.info("vector_store: using local backend")
    except Exception as e:
        logger.warning("vector_store local import failed: %s", e)
        _backend_upsert = _noop_upsert
        _backend_retrieve = _noop_retrieve

def upsert(docs: List[Dict[str, Any]], embeddings: List[List[float]]) -> bool:
    try:
        return _backend_upsert(docs, embeddings)
    except Exception as e:
        logger.exception("vector_store.upsert failed: %s", e)
        return False

def retrieve(query_or_ticker: str, k: int = 5):
    try:
        return _backend_retrieve(query_or_ticker, k=k)
    except Exception as e:
        logger.exception("vector_store.retrieve failed: %s", e)
        return []
