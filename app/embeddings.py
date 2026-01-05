# app/embeddings.py
import os
import time
import logging
from typing import List, Dict, Any

logger = logging.getLogger("embeddings")
logger.setLevel(logging.INFO)

# modern OpenAI client
try:
    from openai import OpenAI
    OPENAI_KEY = os.getenv("OPENAI_API_KEY")
    if not OPENAI_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    openai_client = OpenAI(api_key=OPENAI_KEY)
except Exception as e:
    openai_client = None
    logger.warning("OpenAI client not initialized: %s", e)

def embed_texts(texts: List[str], model: str = "text-embedding-3-small", batch_size: int = 100) -> List[List[float]]:
    if openai_client is None:
        # fallback deterministic dev embedding (not for prod)
        logger.warning("OpenAI unavailable; returning fallback embeddings")
        return [[float(sum(map(ord, t[:50])) % 1000) / 1000.0] * 1536 for t in texts]

    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        tries = 3
        for attempt in range(1, tries+1):
            try:
                resp = openai_client.embeddings.create(model=model, input=batch)
                emb_batch = [d.embedding for d in resp.data]
                all_embs.extend(emb_batch)
                break
            except Exception as e:
                wait = 2 ** (attempt - 1)
                logger.warning("OpenAI embed attempt %s failed: %s; retrying in %ss", attempt, e, wait)
                if attempt == tries:
                    logger.exception("OpenAI embedding failed after %s attempts", tries)
                    raise
                time.sleep(wait)
    return all_embs

# upsert delegator
def upsert_documents(docs: List[Dict[str, Any]]) -> bool:
    """
    docs: list of {"id","text","metadata"}
    This computes embeddings (if not present) and delegates to app.vector_store.upsert
    """
    try:
        from app.vector_store import upsert
    except Exception as e:
        logger.exception("vector_store not available: %s", e)
        return False

    texts = [d.get("text","") for d in docs]
    try:
        embs = embed_texts(texts)
    except Exception as e:
        logger.exception("Failed to compute embeddings for upsert: %s", e)
        return False

    # ensure plain lists
    embs = [list(e) for e in embs]
    return upsert(docs, embs)
