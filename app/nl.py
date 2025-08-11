from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


INTENT_CHOICES = {"cheapest", "best_rated", "average_cost", "compare_costs"}


def is_scope_relevant(question: str) -> bool:
    q = question.lower()
    keywords = [
        "drg",
        "ms-drg",
        "hospital",
        "provider",
        "rating",
        "cost",
        "price",
        "charges",
        "payment",
        "near",
        "zip",
    ]
    return any(k in q for k in keywords)


@dataclass
class NLParams:
    intent: str
    drg_query: Optional[str]
    zip_code: Optional[str]
    radius_km: Optional[int]
    top_k: int = 3


def _fallback_parse(question: str) -> NLParams:
    # naive regex-based extraction as fallback if OpenAI not configured
    drg = None
    m = re.search(r"\bdrg\s*(\d{3})\b", question, re.IGNORECASE)
    if m:
        drg = m.group(1)
    zip_code = None
    m = re.search(r"\b(\d{5})\b", question)
    if m:
        zip_code = m.group(1)
    # miles or km
    radius_km = None
    m = re.search(r"\b(\d{1,3})\s*(mile|miles|mi)\b", question, re.IGNORECASE)
    if m:
        radius_km = int(m.group(1)) * 1609 // 1000
    m2 = re.search(r"\b(\d{1,3})\s*(km|kilometers)\b", question, re.IGNORECASE)
    if m2:
        radius_km = int(m2.group(1))
    # intent
    q = question.lower()
    if any(w in q for w in ["cheap", "cheapest", "low cost", "lowest"]):
        intent = "cheapest"
    elif any(w in q for w in ["best", "top", "highest rating", "rated"]):
        intent = "best_rated"
    elif "average" in q:
        intent = "average_cost"
    else:
        intent = "cheapest"
    return NLParams(intent=intent, drg_query=drg, zip_code=zip_code, radius_km=radius_km, top_k=3)


@retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
def extract_params_with_openai(question: str) -> NLParams:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return _fallback_parse(question)

    client = OpenAI(api_key=api_key)
    system = (
        "You are a data assistant that extracts structured parameters for hospital pricing queries. "
        "Return a strict JSON object with keys: intent (one of cheapest, best_rated, average_cost, compare_costs), "
        "drg_query (string or null), zip_code (5-digit string or null), radius_km (integer or null), top_k (int). "
        "If query mentions miles, convert to kilometers. If not provided, use radius_km=40."
    )
    user = f"Question: {question}"
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    intent = str(data.get("intent") or "cheapest").strip().lower()
    if intent not in INTENT_CHOICES:
        intent = "cheapest"
    drg_query = data.get("drg_query")
    if drg_query is not None:
        drg_query = str(drg_query).strip()
    zip_code = data.get("zip_code")
    if zip_code is not None:
        zip_code = str(zip_code).strip()
        m = re.match(r"^\d{5}$", zip_code)
        if not m:
            zip_code = None
    radius_km = data.get("radius_km")
    if radius_km is not None:
        try:
            radius_km = int(radius_km)
        except Exception:
            radius_km = None
    top_k = data.get("top_k") or 3
    try:
        top_k = int(top_k)
    except Exception:
        top_k = 3
    if radius_km is None:
        radius_km = 40
    return NLParams(
        intent=intent, drg_query=drg_query, zip_code=zip_code, radius_km=radius_km, top_k=top_k
    )

