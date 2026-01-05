from google.cloud import firestore
import json
from google.api_core.exceptions import GoogleAPIError
import uuid
import time
from datetime import datetime, date
import numpy as np

_db = firestore.Client()

def _clean_value(v):
    """Convert common non-serializable types to serializable ones."""
    # primitives
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    # datetime/date -> iso str
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    # numpy types
    if isinstance(v, (np.integer, np.floating, np.bool_)):
        return v.item()
    # lists / tuples
    if isinstance(v, (list, tuple)):
        return [_clean_value(x) for x in v]
    # dicts
    if isinstance(v, dict):
        return {str(k): _clean_value(val) for k, val in v.items()}
    # dataclasses / objects with to_dict
    if hasattr(v, "to_dict") and callable(getattr(v, "to_dict")):
        try:
            return _clean_value(v.to_dict())
        except Exception:
            pass
    if hasattr(v, "__dict__"):
        try:
            return _clean_value(vars(v))
        except Exception:
            pass
    # fallback to str
    try:
        return str(v)
    except Exception:
        return None

def persist_decision_trace_safe(user_id: str, decision_obj: dict) -> str:
    """
    Clean and persist a decision trace to Firestore. NEVER raises to caller.
    Returns document id (string). On failure returns a generated UUID string.
    """
    try:
        # shallow copy then clean
        clean_obj = {}
        for k, v in (decision_obj or {}).items():
            clean_obj[k] = _clean_value(v)

        # add timestamps / meta
        clean_obj["_written_at_iso"] = datetime.utcnow().isoformat()
        doc_ref = _db.collection("users").document(user_id).collection("decisions").document()
        # set the id in the doc so we can reference it later
        clean_obj["_id"] = doc_ref.id
        clean_obj["created_at_ms"] = int(time.time() * 1000)
        doc_ref.set(clean_obj)
        return doc_ref.id
    except GoogleAPIError as e:
        print("persist_decision_trace_safe: Firestore error:", e)
        return str(uuid.uuid4())
    except Exception as ex:
        # catch-all: logging failure should not break the app
        print("persist_decision_trace_safe: unknown error:", ex)
        return str(uuid.uuid4())

