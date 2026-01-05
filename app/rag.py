# rag.py
"""
RAG helpers: retrieval normalization, snippet extraction, and summarization
Improvements:
 - normalize_passages returns evidence[] entries with provenance
 - extract_snippet_best_sentence tries to pick best sentence (embedding-based if available)
 - summarize_with_evidence prompts model to cite passage_ids and returns text
"""

import os
import re
import logging
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger("rag")
logger.setLevel(logging.INFO)

# attempt to import embedding helper; if missing, we'll fallback to simple heuristics
try:
    from app.embeddings import embed_texts
    EMBEDDINGS_AVAILABLE = True
except Exception:
    embed_texts = None
    EMBEDDINGS_AVAILABLE = False
    logger.info("embed_texts not available; sentence rerank will use heuristics")

# vector retrieval adapter (keeps your existing integration)
from app.vector_store import retrieve

# small util: simple cosine for in-memory lists
def _cosine(a: List[float], b: List[float]) -> float:
    try:
        from math import sqrt
        num = sum(x*y for x,y in zip(a,b))
        na = sqrt(sum(x*x for x in a))
        nb = sqrt(sum(y*y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return num / (na * nb)
    except Exception:
        return 0.0

# sentence splitter (lightweight)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')

def split_to_sentences(text: str) -> List[str]:
    if not text:
        return []
    # normalize whitespace
    txt = re.sub(r'\s+', ' ', text.strip())
    sents = _SENTENCE_SPLIT_RE.split(txt)
    # trim very long sentences and whitespace
    return [s.strip() for s in sents if s.strip()]

def extract_snippet_best_sentence(passage_text: str, query: str, ticker: Optional[str] = None, max_sentences_window: int = 2) -> Dict[str, Any]:
    """
    Returns a dict: { 'snippet': str, 'best_idx': int, 'scores': [...], 'method': 'embed'|'heuristic' }
    Strategy:
      - If embed_texts is available: embed the query and each sentence -> pick highest cosine
      - Else: prefer sentence(s) that contain the ticker/company name; else use first 1-2 sentences
    """
    sentences = split_to_sentences(passage_text)
    if not sentences:
        return {"snippet": "", "best_idx": 0, "scores": [], "method": "empty"}

    # 1) If embeddings available, do sentence-level rerank
    if EMBEDDINGS_AVAILABLE and embed_texts:
        try:
            # embed query + sentences in a single batch for efficiency
            texts = [query] + sentences
            embs = embed_texts(texts)
            q_emb = embs[0]
            sent_embs = embs[1:]
            scores = [_cosine(q_emb, s) for s in sent_embs]
            best_idx = int(max(range(len(scores)), key=lambda i: scores[i]))
            start = max(0, best_idx - (max_sentences_window-1))
            end = min(len(sentences), best_idx + max_sentences_window)
            snippet = " ".join(sentences[start:end])
            return {"snippet": snippet, "best_idx": best_idx, "scores": scores, "method": "embed"}
        except Exception as e:
            logger.debug("embed-based snippet extraction failed: %s", e)
            # fall through to heuristic

    # 2) Heuristic: prefer sentences containing the ticker (exact or $TICKER)
    if ticker:
        ticker_upper = ticker.upper()
        for i, s in enumerate(sentences):
            if re.search(rf'\b{re.escape(ticker_upper)}\b', s, flags=re.IGNORECASE) or re.search(r'\$' + re.escape(ticker_upper), s):
                start = max(0, i - (max_sentences_window-1))
                end = min(len(sentences), i + max_sentences_window)
                snippet = " ".join(sentences[start:end])
                return {"snippet": snippet, "best_idx": i, "scores": [], "method": "heuristic_ticker"}
    # 3) Heuristic: fallback to first 1-2 sentences
    end = min(len(sentences), max_sentences_window)
    snippet = " ".join(sentences[:end])
    return {"snippet": snippet, "best_idx": 0, "scores": [], "method": "heuristic_start"}


def normalize_passages(raw_passages: List[Dict[str, Any]], query: Optional[str] = None, ticker: Optional[str] = None, k: int = 6) -> List[Dict[str, Any]]:
    """
    Convert raw retrieval hits (from vector_store.retrieve) into canonical evidence objects.
    Each evidence has:
      - passage_id (string)
      - doc_id / source_url (if present)
      - passage_text (full passage)
      - snippet (best 1-3 sentence excerpt)
      - retrieval_score (float)
      - tickers (metadata tickers)
      - entities (empty list unless you run entity extraction)
      - timestamp (if present in metadata)
    If embeddings are available, sentence-level reranking is attempted using `query`.
    """
    out = []
    if not raw_passages:
        return out

    # limit top raw hits to some reasonable window for processing (e.g. 20)
    raw_window = raw_passages[: max(k*3, len(raw_passages))]

    for hit in raw_window:
        # per-hit type guard
        if not isinstance(hit, dict):
            logger.warning("Non-dict passage returned and skipped: %s", type(hit))
            continue

        # support multiple backends/fields
        text = hit.get("text") or hit.get("metadata", {}).get("text") or hit.get("meta", {}).get("text") or ""
        meta = hit.get("meta") or hit.get("metadata") or {}
        score = float(hit.get("score") if hit.get("score") is not None else 0.0)
        # prefer explicit stable id if present
        doc_id = meta.get("doc_id") or meta.get("id") or meta.get("source_url") or meta.get("url") or None
        source = meta.get("source") or meta.get("host") or meta.get("source_url") or None
        tickers = meta.get("ticker") or meta.get("tickers") or []
        if isinstance(tickers, str):
            tickers = [tickers]
        # run snippet extraction
        snippet_info = extract_snippet_best_sentence(text or "", query or "", ticker=ticker)
        snippet = snippet_info.get("snippet") or (text[:300] if text else "")

        # stable passage id using sha256 of doc_id + text (fallback to text-only)
        id_base = (doc_id or "") + "|" + (text or "")
        sha = hashlib.sha256(id_base.encode("utf-8")).hexdigest()[:12]
        passage_id = (doc_id or "doc") + "_" + sha

        evidence = {
            "passage_id": passage_id,
            "doc_id": doc_id,
            "source": source,
            "source_url": meta.get("source_url") or meta.get("url"),
            "passage_text": text,
            "snippet": snippet,
            "retrieval_score": score,
            "sentence_score": (max(snippet_info.get("scores")) if snippet_info.get("scores") else None),
            "tickers": tickers,
            "entities": meta.get("entities", []),
            "meta": meta,
            "timestamp": meta.get("timestamp") or meta.get("date") or None,
            "snippet_method": snippet_info.get("method"),
        }
        out.append(evidence)

    # filter by ticker presence if ticker provided (ensure relevance). Keep ones that include the ticker in metadata or passage_text
    if ticker:
        ticker_up = ticker.upper()
        filtered = []
        for e in out:
            # check metadata tickers or direct mention
            meta_tickers = [t.upper() for t in (e.get("tickers") or []) if isinstance(t, str)]
            if ticker_up in meta_tickers:
                filtered.append(e)
                continue
            if e.get("passage_text") and re.search(rf'\b{re.escape(ticker_up)}\b', e.get("passage_text"), flags=re.IGNORECASE):
                filtered.append(e)
                continue
        if filtered:
            out = filtered

    # dedupe by doc_id / source_url (prefer higher sentence_score)
    by_source = {}
    for e in out:
        key = e.get("doc_id") or e.get("source_url") or (e.get("source") or "") + "_" + (e["passage_id"][:8])
        existing = by_source.get(key)
        if not existing:
            by_source[key] = e
        else:
            # pick better by sentence_score, then retrieval_score
            cur_score = (e.get("sentence_score") or 0.0)
            ex_score = (existing.get("sentence_score") or 0.0)
            if cur_score > ex_score:
                by_source[key] = e

    unique = list(by_source.values())
    # sort by sentence_score or retrieval_score desc
    unique.sort(key=lambda x: (x.get("sentence_score") or 0.0, x.get("retrieval_score") or 0.0), reverse=True)
    # trim to k
    return unique[:k]


def summarize_with_evidence(
    ticker: str,
    passages: List[Dict[str, Any]],
    extra_context: Optional[str] = None,
    api_key_env: str = "OPENAI_API_KEY",
    model: str = "gpt-4o-mini",
    max_tokens: int = 512,
    temperature: float = 0.0,
):
    """
    Summarize evidence for a ticker using the normalized passages (evidence[]).
    The LLM prompt instructs the model to cite passage_ids when making claims.
    Returns the model's text output (string). The calling orchestrator should keep the evidence[] items for provenance.
    """
    api_key = os.getenv(api_key_env)
    if not api_key:
        return {"error": "OpenAI key not configured"}

    # prepare passages_text built from snippet + id to keep prompt compact
    # If caller passed raw retrieval hits (not normalized), attempt to normalize here
    if passages and isinstance(passages[0], dict) and "passage_id" not in passages[0]:
        # assume raw retrieval hits; normalize
        normalized = normalize_passages(passages, query=ticker, ticker=ticker, k=6)
    else:
        normalized = passages or []

    passages_block = ""
    for e in normalized[:8]:
        pid = e.get("passage_id") or ""
        snip = e.get("snippet") or (e.get("passage_text") or "")[:300]
        src = e.get("source") or e.get("doc_id") or e.get("source_url") or ""
        passages_block += f"- [{pid}] ({src}) {snip}\n"

    # If no PFS context provided, return message asking user to set up profile
    # Don't waste LLM call for generic analysis - personalization is our USP
    if not extra_context:
        return (
            f"**{ticker} Analysis**\n\n"
            "I can provide a much more valuable analysis of this stock if I know your financial situation.\n\n"
            "📊 **To get personalized investment insights:**\n\n"
            "1. Go to the **Profile** page (in the sidebar)\n"
            "2. Enter your financial information:\n"
            "   - Net worth and assets\n"
            "   - Monthly income and expenses\n"
            "   - Risk tolerance and investment goals\n"
            "   - Investment time horizon\n"
            "3. Save your profile\n"
            "4. Come back and ask again!\n\n"
            "Once I have your profile, I'll provide:\n"
            "- Personalized buy/sell recommendations based on YOUR risk capacity\n"
            "- Position sizing tailored to YOUR net worth\n"
            "- Investment strategy aligned with YOUR goals and time horizon\n"
            "- Risk analysis specific to YOUR financial situation\n\n"
            "💡 **This personalized approach is what makes Perfient unique** - generic stock analysis is available everywhere, "
            "but analysis tailored to your specific financial profile is our specialty!"
        )
    
    context_block = f"\n\nUser's Financial Profile (ALREADY PROVIDED - DO NOT REQUEST):\n{extra_context}\n\n"
    pfs_instruction = (
        "\n\nIMPORTANT: The user's complete financial profile is provided above. "
        "DO NOT ask the user to provide their financial statement or profile data. "
        "Instead, use the provided data to tailor your analysis to their specific situation (net worth, risk tolerance, goals, etc.). "
        "Provide personalized insights based on their profile.\n\n"
    )

    # Strong system instruction: produce only a plain text summary and when citing evidence, reference passage ids like [passage_id].
    prompt = (
        f"You are a concise investment assistant. Using only the provided evidence snippets below for {ticker}, "
        "provide a structured analysis covering:\n\n"
        "1. **Business Model**: Briefly describe how the company generates revenue and creates value.\n"
        "2. **Economic Moat**: Identify the company's competitive advantages and barriers to entry.\n"
        "3. **Scalability**: Assess the company's ability to grow and scale operations efficiently.\n"
        "4. **SWOT Analysis**: Summarize key Strengths, Weaknesses, Opportunities, and Threats.\n\n"
        "Keep each section concise (2-3 sentences maximum). "
        "Important: Whenever you make a factual claim that is supported by evidence, append the evidence reference(s) "
        "in square brackets like [passage_id]. Do NOT invent any evidence ids. If a claim is your interpretation and not supported "
        "by the evidence provided, do NOT write an evidence id. Do not output any JSON — use markdown formatting.\n\n"
        "FORMATTING REQUIREMENTS:\n"
        "- Use proper spacing between all words and numbers\n"
        "- Format numbers with commas: $10,000 not $10000\n"
        "- Always include spaces before and after numbers in sentences\n"
        "- Use markdown formatting consistently (bold with **, lists with -, etc.)\n\n"
        f"{pfs_instruction}{context_block}\nPassages:\n{passages_block}\n\n"
        "Write the structured analysis now:"
    )

    # call OpenAI (use your existing wrapper)
    try:
        from openai import OpenAI
        client_local = OpenAI(api_key=api_key)
        resp = client_local.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = ""
        try:
            text = resp.choices[0].message.content or ""
        except Exception:
            # safe fallback if response shape differs
            text = str(resp)
        return text
    except Exception as e:
        logger.exception("OpenAI call failed in summarize_with_evidence: %s", e)
        return "No summary available."


def summarize_with_evidence_and_pfs(ticker: str, passages: List[Dict[str, Any]], pfs_fragment: Optional[str]):
    """
    Convenience wrapper that normalizes passages and injects PFS fragment.
    Returns string summary from summarize_with_evidence.
    """
    # If raw retrieval results passed, normalize with query=ticker
    normalized = None
    if passages and isinstance(passages[0], dict) and "passage_id" not in passages[0]:
        normalized = normalize_passages(passages, query=ticker, ticker=ticker, k=6)
    else:
        normalized = passages or []

    return summarize_with_evidence(ticker, normalized, extra_context=pfs_fragment)
