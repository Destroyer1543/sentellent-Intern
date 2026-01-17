# app/agent/summary_memory.py
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import requests


PPLX_URL = os.getenv("PPLX_CHAT_URL", "https://api.perplexity.ai/chat/completions")
MODEL = os.getenv("PPLX_MODEL", "sonar-pro")
API_KEY = os.getenv("PERPLEXITY_API_KEY") or os.getenv("PPLX_API_KEY")


SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
    },
    "required": ["summary"],
}


def _extract_json(text: str) -> dict:
    if not text:
        raise ValueError("Empty model output")
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError(f"Model did not return JSON. Output starts with: {text[:120]!r}")
    candidate = m.group(0).strip()
    candidate = re.sub(r"^```(?:json)?", "", candidate).strip()
    candidate = re.sub(r"```$", "", candidate).strip()
    return json.loads(candidate)


def update_conversation_summary(
    old_summary: str,
    new_user_message: str,
    max_words: int = 220,
) -> str:
    """
    Produces updated rolling summary. Keeps:
    - user preferences (hard constraints)
    - currently active/unfinished task context
    - entities (names, titles, dates)
    """
    if not API_KEY:
        # fail-soft: if no API key, just append (bounded)
        merged = (old_summary + "\n" + new_user_message).strip()
        return merged[-3000:]

    system = f"""
You maintain a rolling conversation memory for an assistant.

Return ONLY JSON:
{{"summary":"..."}}

Rules:
- Keep it <= {max_words} words.
- Preserve stable user preferences (e.g. "no meetings before 10AM").
- Preserve unfinished tasks and missing slots (e.g. "Scheduling: title=..., missing date").
- Do NOT include secrets, API keys, tokens, passwords.
- Be compact and factual. No fluff.
""".strip()

    user = f"""
OLD_SUMMARY:
{old_summary or "(empty)"}

NEW_USER_MESSAGE:
{new_user_message}
""".strip()

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 400,
        "response_format": {"type": "json_schema", "json_schema": {"schema": SUMMARY_SCHEMA}},
    }

    r = requests.post(PPLX_URL, headers=headers, json=payload, timeout=30)
    if r.status_code == 400:
        payload.pop("response_format", None)
        r = requests.post(PPLX_URL, headers=headers, json=payload, timeout=30)

    r.raise_for_status()
    data = r.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    obj = _extract_json(content)
    return (obj.get("summary") or "").strip() or (old_summary or "")
