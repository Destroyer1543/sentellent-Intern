# app/agent/planner.py
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz

load_dotenv()

API_KEY = os.getenv("PERPLEXITY_API_KEY") or os.getenv("PPLX_API_KEY")
PPLX_URL = os.getenv("PPLX_CHAT_URL", "https://api.perplexity.ai/chat/completions")
MODEL = os.getenv("PPLX_MODEL", "sonar-pro")

# ✅ Default timezone is IST and must NOT change unless user explicitly asks.
IST = pytz.timezone("Asia/Kolkata")

ALLOWED_TOOLS = [
    "handle_confirmation",
    "gmail_list_important",
    "gmail_send",
    "calendar_prepare_event",
    "calendar_list_events",
    "calendar_get_event",
    "calendar_update_event",
    "calendar_delete_events",
    "memory_upsert",
]

# ---------- JSON schemas ----------
PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "response": {"type": "string"},
        "needs_more": {"type": "boolean"},
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tool": {"type": "string", "enum": ALLOWED_TOOLS},
                    "args": {"type": "object"},
                },
                "required": ["tool", "args"],
            },
        },
    },
    "required": ["response", "needs_more", "plan"],
}

EVENT_REPAIR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "start_iso": {"type": "string"},
        "end_iso": {"type": "string"},
    },
    "required": ["start_iso", "end_iso"],
}

WINDOW_REPAIR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "time_min": {"type": "string"},
        "time_max": {"type": "string"},
    },
    "required": ["time_min", "time_max"],
}

PREF_REPAIR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "key": {"type": "string"},
        "value": {"type": "string"},
        "ok": {"type": "boolean"},
        "question": {"type": "string"},
    },
    "required": ["ok"],
}

GMAIL_REPAIR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "ok": {"type": "boolean"},
        "to_email": {"type": "string"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "question": {"type": "string"},
    },
    "required": ["ok"],
}

# ---------- prompts ----------
def _now_ctx() -> str:
    now = datetime.now(IST)
    return (
        f"NOW_ISO={now.isoformat()}\n"
        f"TODAY_DATE={now.date().isoformat()}\n"
        f"WEEKDAY={now.strftime('%A')}\n"
        f"TIMEZONE=Asia/Kolkata (+05:30)\n"
    )

def _mem_ctx(state: dict) -> str:
    mem = state.get("memories") or {}
    if not isinstance(mem, dict):
        mem = {}
    try:
        mem_json = json.dumps(mem, ensure_ascii=False)
    except Exception:
        mem_json = "{}"
    return f"MEMORIES_JSON={mem_json}\n"

def _recent_ctx(state: dict) -> str:
    pi = state.get("pending_intent") or {}
    last_q = ""
    if isinstance(pi, dict):
        last_q = (pi.get("last_question") or "").strip()

    last_tools = state.get("last_tool_results") or []
    try:
        compact = json.dumps(last_tools[-2:], ensure_ascii=False)
    except Exception:
        compact = "[]"

    if len(compact) > 2500:
        compact = compact[:2500] + "…"

    return f"PENDING_LAST_QUESTION={last_q}\nLAST_TOOL_RESULTS_JSON={compact}\n"

def _planner_system_prompt(state: dict) -> str:
    return f"""
You are Sentellent Planner. Convert the user request into a tool execution plan.

Return ONLY valid JSON (no markdown, no code fences, no extra text).
{_now_ctx()}{_mem_ctx(state)}{_recent_ctx(state)}

Output JSON format:
{{
  "response": "<string>",
  "needs_more": <true|false>,
  "plan": [{{"tool":"<one of {ALLOWED_TOOLS}>","args":{{...}}}}]
}}

RESPONSE FIELD RULE (CRITICAL):
- If plan is non-empty: set "response" to "".
- Only use "response" when needs_more=true (ask exactly one question) OR when plan is empty.
- Never add extra narration that the user didn't ask for.

ABSOLUTE CONTROL RULE (CRITICAL):
- If the user message contains "/confirm" OR starts with/contains "CONFIRMATION:" then:
  - Output ONLY: tool=handle_confirmation args={{"raw":"<entire original message>"}}
  - needs_more=false
  - response=""
  - plan contains exactly one tool call.
  - Never use memory_upsert for confirmation.

PENDING ACTION RULE:
- If state has a pending_action and the user is NOT confirming, do not plan new actions.

TIMEZONE RULES:
- Default timezone is Asia/Kolkata (+05:30).
- Do NOT ask about timezone.
- Do NOT change timezone unless user explicitly requests another timezone.

TOOL REQUIREMENTS:
- calendar_prepare_event args MUST include: summary, start_iso, end_iso
- calendar_list_events args MUST include: time_min, time_max
- calendar_get_event args MUST include: event_id
- calendar_update_event args MUST include: event_id, patch (object)
- calendar_delete_events args MUST include: event_ids (list of strings), summaries optional
- gmail_send args MUST include: to_email (subject/body optional)
- memory_upsert args MUST include: key AND value

QUALITY / ROBUSTNESS RULES:
- Handle typos, slang, short queries.
- Use context:
  - If PENDING_LAST_QUESTION is non-empty, the user is likely answering it.
  - Use ORIGINAL_REQUEST + USER_FOLLOWUP to fill missing slots.
  - Use LAST_TOOL_RESULTS_JSON for follow-ups like "the first one", "delete Meeting 5", "send that", "do it again".
- Choose the MINIMUM tool calls needed.
- If required info is missing: needs_more=true, plan=[], ask EXACTLY ONE question.

GMAIL SEND (CRITICAL):
- If the user gives an email address anywhere (especially as USER_FOLLOWUP after you asked for it),
  you MUST place it in args.to_email and proceed with gmail_send.
- Keep subject/body from ORIGINAL_REQUEST if they were provided there.

PREFERENCES (CRITICAL):
- For time prefs like "don't schedule meetings before 10AM": normalize into 24h HH:MM.
- If you cannot infer the time, ask ONE question: "What time should I use (e.g., 10:00 or 22:30)?"
""".strip()

def _event_repair_prompt(state: dict) -> str:
    return f"""
You are a datetime normalizer for calendar event creation.

Return ONLY JSON:
{{
  "summary": "<string optional>",
  "start_iso": "YYYY-MM-DDTHH:MM:SS+05:30",
  "end_iso":   "YYYY-MM-DDTHH:MM:SS+05:30"
}}

{_now_ctx()}{_mem_ctx(state)}

Rules:
- Timezone is Asia/Kolkata (+05:30) unless user explicitly specifies another timezone.
- Do NOT ask about timezone.
- Parse dates like 17-01-2026, 17th Jan 2026, "next Tuesday", "tomorrow".
- Parse times like 10 AM, 10:30pm, 22:00.
- If duration is mentioned, end_iso must reflect it.
- If duration is NOT mentioned and MEMORIES_JSON has "default_meeting_minutes", use it.
""".strip()

def _window_repair_prompt(state: dict) -> str:
    return f"""
You are a datetime normalizer for calendar listing windows.

Return ONLY JSON:
{{
  "time_min": "YYYY-MM-DDTHH:MM:SS+05:30",
  "time_max": "YYYY-MM-DDTHH:MM:SS+05:30"
}}

{_now_ctx()}

Rules:
- Timezone is Asia/Kolkata (+05:30).
- Do NOT ask about timezone.
- If user says "tomorrow": time_min = tomorrow 00:00, time_max = day-after 00:00.
- If user says "today": time_min=today 00:00, time_max=tomorrow 00:00.
""".strip()

def _pref_repair_prompt(state: dict) -> str:
    return f"""
You are a preference normalizer.

Return ONLY JSON:
{{
  "ok": true|false,
  "key": "<preference key>",
  "value": "<normalized preference value>",
  "question": "<single clarification question if ok=false>"
}}

{_now_ctx()}{_mem_ctx(state)}

Task:
- Planner attempted memory_upsert but it was missing/invalid. Fix it if possible.
- If you cannot infer the value, ok=false and ask ONE question only.

Rules:
- no_meetings_before: normalize to HH:MM 24h.
- default_meeting_minutes: integer string like "45".
- NEVER ok=true without BOTH key and value.
""".strip()

def _gmail_repair_prompt(state: dict) -> str:
    return f"""
You are a Gmail send argument normalizer.

Return ONLY JSON:
{{
  "ok": true|false,
  "to_email": "<recipient email>",
  "subject": "<subject string (can be empty)>",
  "body": "<body string (can be empty)>",
  "question": "<single clarification question if ok=false>"
}}

{_now_ctx()}{_recent_ctx(state)}

Task:
- The planner attempted gmail_send but to_email was missing/invalid.
- Use ORIGINAL_REQUEST + USER_FOLLOWUP (already included in user_text) and PENDING_LAST_QUESTION.
- If USER_FOLLOWUP contains an email address, that MUST be the to_email.

Rules:
- ok=true ONLY if to_email is a valid email.
- Keep subject/body from ORIGINAL_REQUEST if present.
- If subject/body not present, allow empty subject/body.
- If you cannot find a recipient email, ok=false and ask ONE question:
  "What email address should I send it to?"
""".strip()

# ---------- low-level utils ----------
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

def _call_perplexity(system_prompt: str, user_text: str, schema: Optional[Dict[str, Any]] = None) -> str:
    if not API_KEY:
        raise RuntimeError("Missing PERPLEXITY_API_KEY / PPLX_API_KEY")

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    payload: Dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.0,
        "max_tokens": 1500,
    }

    if schema is not None:
        payload["response_format"] = {"type": "json_schema", "json_schema": {"schema": schema}}

    r = requests.post(PPLX_URL, headers=headers, json=payload, timeout=30)

    if r.status_code == 400 and "response_format" in payload:
        payload.pop("response_format", None)
        r = requests.post(PPLX_URL, headers=headers, json=payload, timeout=30)

    r.raise_for_status()
    data = r.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")

def _extract_title_from_text(raw: str) -> Optional[str]:
    m = re.search(r"(?:title|called|titled)\s*[: ]\s*['\"]([^'\"]+)['\"]", raw, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    q = re.search(r"['\"]([^'\"]+)['\"]", raw)
    if q:
        return q.group(1).strip()
    return None

def _memory_default_minutes(state: dict) -> Optional[int]:
    mem = state.get("memories") or {}
    if not isinstance(mem, dict):
        return None
    v = mem.get("default_meeting_minutes")
    if v is None:
        return None
    try:
        n = int(str(v).strip())
        if 5 <= n <= 480:
            return n
        return None
    except Exception:
        return None

def _user_says_no_attendees(raw: str) -> bool:
    t = (raw or "").strip().lower()
    return any(
        p in t
        for p in [
            "no attendees",
            "dont mention attendees",
            "don't mention attendees",
            "no need attendees",
            "skip attendees",
            "without attendees",
            "just me",
            "only me",
        ]
    )

def _looks_like_yes_no_only(raw: str) -> bool:
    t = (raw or "").strip().lower()
    t = re.sub(r"[.!?✅🙂😂🤣😅🙏]+$", "", t).strip()
    return bool(
        re.fullmatch(
            r"(yes|y|yeah|yep|confirm|ok|okay|sure|do it|send it|go ahead|proceed|no|n|nope|cancel|stop|don't|dont|nevermind|never mind)",
            t,
        )
    )

def _looks_like_upcoming_list_request(raw: str) -> bool:
    t = (raw or "").strip().lower()
    return (
        ("upcoming" in t or "next" in t)
        and ("meeting" in t or "meetings" in t or "events" in t or "calendar" in t)
    ) or t in ("list them", "list it", "show them", "show it")

def _default_upcoming_window() -> Tuple[str, str]:
    now = datetime.now(IST)
    end = now + timedelta(days=7)
    return now.isoformat(), end.isoformat()

# ---------- deterministic helpers (email routing) ----------
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.IGNORECASE)

def _looks_like_send_email_request(raw: str) -> bool:
    """
    Detects intent to SEND, not list.
    Must run BEFORE important-email hard route.
    """
    t = (raw or "").strip().lower()
    if any(k in t for k in ["send email", "send an email", "email to ", "mail to ", "send mail", "compose email"]):
        return True
    if "subject" in t or "body" in t:
        # If user included an address and subject/body, it's clearly a send.
        if _EMAIL_RE.search(raw or ""):
            return True
    # "send to x@y.com"
    if "send" in t and _EMAIL_RE.search(raw or ""):
        return True
    return False

def _extract_send_email_args(raw: str) -> Optional[dict]:
    """
    Best-effort parsing for: Send email to X subject ... body ...
    If it can't parse, return None and let LLM plan it.
    """
    if not raw:
        return None
    to = ""
    m = _EMAIL_RE.search(raw)
    if m:
        to = m.group(0).strip()

    if not to:
        return None

    # subject: take text after 'subject' up to 'body' (or end)
    subj = ""
    body = ""
    msub = re.search(r"\bsubject\b\s*[:\-]?\s*(.+?)(?=\bbody\b|$)", raw, flags=re.IGNORECASE | re.DOTALL)
    if msub:
        subj = msub.group(1).strip()

    mbody = re.search(r"\bbody\b\s*[:\-]?\s*(.+)$", raw, flags=re.IGNORECASE | re.DOTALL)
    if mbody:
        body = mbody.group(1).strip()

    return {"to_email": to, "subject": subj or "", "body": body or ""}

def _looks_like_important_email_request(raw: str) -> bool:
    """
    IMPORTANT: do NOT trigger on 'send email ...'
    This is for listing important/starred.
    """
    t = (raw or "").strip().lower()

    # If it looks like a SEND request, it's not a listing request.
    if _looks_like_send_email_request(raw):
        return False

    # Strong signals
    if any(k in t for k in ["important", "starred", "flagged"]):
        return True

    # Listing verbs + email nouns
    listing_verbs = ["show", "list", "display", "fetch", "get", "see"]
    email_nouns = ["email", "emails", "inbox", "mail", "messages"]
    if any(v in t for v in listing_verbs) and any(n in t for n in email_nouns):
        # But avoid generic "email me" etc.
        if "email me" in t or "mail me" in t:
            return False
        return True

    return False

def _extract_days(raw: str, default_days: int = 4) -> int:
    t = (raw or "").lower()

    m = re.search(r"\blast\s+(\d{1,2})\s*days?\b", t)
    if m:
        n = int(m.group(1))
        return max(1, min(30, n))

    m2 = re.search(r"\b(\d{1,3})\s*hours?\b", t)
    if m2:
        hrs = int(m2.group(1))
        n = max(1, min(30, (hrs + 23) // 24))
        return n

    if "yesterday" in t:
        return 2
    if "today" in t:
        return 1

    return default_days

def _wants_all(raw: str) -> bool:
    t = (raw or "").lower()
    return any(k in t for k in ["show all", "list all", "all important", "all starred", "all emails", "everything"])

# ---------- deterministic helpers (prefs + delete by title) ----------
_TIME_HHMM_24H = re.compile(r"\b([01]?\d|2[0-3])\s*[:.]\s*([0-5]\d)\b")
_TIME_H_12H = re.compile(r"\b(1[0-2]|0?[1-9])(?:\s*[:.]\s*([0-5]\d))?\s*(am|pm)\b", re.IGNORECASE)

def _normalize_time_to_hhmm(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.strip().lower()

    m24 = _TIME_HHMM_24H.search(t)
    if m24:
        hh = int(m24.group(1))
        mm = int(m24.group(2))
        return f"{hh:02d}:{mm:02d}"

    m12 = _TIME_H_12H.search(t)
    if m12:
        hh = int(m12.group(1))
        mm = int(m12.group(2) or "0")
        ap = (m12.group(3) or "").lower()
        if ap == "pm" and hh != 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        return f"{hh:02d}:{mm:02d}"

    mH = re.search(r"\b([01]?\d|2[0-3])\b", t)
    if mH and ("before" in t or "after" in t or "from" in t or "at" in t):
        hh = int(mH.group(1))
        return f"{hh:02d}:00"

    return None

def _is_no_meetings_before_pref(raw: str) -> bool:
    t = (raw or "").lower()
    return any(
        p in t
        for p in [
            "no meetings before",
            "dont schedule meetings before",
            "don't schedule meetings before",
            "do not schedule meetings before",
            "no meeting before",
            "no events before",
            "no calendar before",
        ]
    )

def _is_default_meeting_minutes_pref(raw: str) -> bool:
    t = (raw or "").lower()
    return any(
        p in t
        for p in [
            "default meeting minutes",
            "default meetings to",
            "default my meetings to",
            "set default meeting duration",
            "default meeting duration",
        ]
    )

def _extract_int_minutes(raw: str) -> Optional[int]:
    t = (raw or "").lower()
    m = re.search(r"\b(\d{1,3})\s*(minutes?|mins?)\b", t)
    if m:
        n = int(m.group(1))
        if 5 <= n <= 480:
            return n
    m2 = re.search(r"\b(\d{1,3})\b", t)
    if m2 and ("default" in t and ("meeting" in t or "meetings" in t)):
        n = int(m2.group(1))
        if 5 <= n <= 480:
            return n
    return None

def _extract_delete_title(raw: str) -> Optional[str]:
    t = (raw or "").strip()
    low = t.lower()

    if not any(w in low for w in ["delete", "remove", "cancel"]):
        return None

    m = re.search(r'(?:delete|remove|cancel)\s+["\']([^"\']+)["\']', t, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m2 = re.search(r"(?:delete|remove|cancel)\s+(.+)$", t, flags=re.IGNORECASE)
    if m2:
        cand = m2.group(1).strip()
        cand = re.split(r"\b(which|that|scheduled|tomorrow|today|on)\b", cand, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        cand = cand.strip(" .,!?:;")
        if cand:
            return cand

    return None

def _events_from_last_tool_results(state: dict) -> List[dict]:
    out: List[dict] = []
    batches = state.get("tool_results") or []
    if not isinstance(batches, list):
        batches = []
    for item in batches[::-1]:
        if not isinstance(item, dict):
            continue
        if item.get("tool") != "calendar_list_events":
            continue
        if item.get("ok") is not True:
            continue
        res = item.get("result")
        if isinstance(res, list):
            out = [e for e in res if isinstance(e, dict)]
            if out:
                return out
        if isinstance(res, dict):
            items = res.get("items")
            if isinstance(items, list):
                out = [e for e in items if isinstance(e, dict)]
                if out:
                    return out
    return out

def _match_events_by_title(events: List[dict], title: str) -> List[dict]:
    if not title:
        return []
    t = title.strip().lower()
    t = re.sub(r"\s+", " ", t)

    hits: List[dict] = []
    for e in events:
        s = (e.get("summary") or e.get("title") or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        if not s:
            continue
        if s == t:
            hits.append(e)
            continue
        if t in s:
            hits.append(e)
    return hits

def _tomorrow_window_iso() -> Tuple[str, str]:
    now = datetime.now(IST)
    tmr = (now + timedelta(days=1)).date()
    start = IST.localize(datetime(tmr.year, tmr.month, tmr.day, 0, 0, 0))
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()

# ---------- plan normalization ----------
def _repair_calendar_args(state: dict, plan: List[dict], user_text: str) -> List[dict]:
    fixed: List[dict] = []
    inferred_title = _extract_title_from_text(user_text)
    _ = _memory_default_minutes(state)

    for c in plan or []:
        tool = c.get("tool")
        args = c.get("args") or {}

        if tool not in ALLOWED_TOOLS:
            continue

        if tool == "calendar_prepare_event":
            if "title" in args and "summary" not in args:
                args["summary"] = args.pop("title")
            if (not args.get("summary")) and inferred_title:
                args["summary"] = inferred_title

            if (not args.get("start_iso")) or (not args.get("end_iso")):
                out = _call_perplexity(_event_repair_prompt(state), user_text, schema=EVENT_REPAIR_SCHEMA)
                obj = _extract_json(out)
                if obj.get("summary") and not args.get("summary"):
                    args["summary"] = obj.get("summary")
                args["start_iso"] = obj.get("start_iso")
                args["end_iso"] = obj.get("end_iso")

            if not args.get("summary"):
                args["summary"] = "Event"

        if tool == "calendar_list_events":
            if "time_min_iso" in args and "time_min" not in args:
                args["time_min"] = args.pop("time_min_iso")
            if "time_max_iso" in args and "time_max" not in args:
                args["time_max"] = args.pop("time_max_iso")

            if (not args.get("time_min")) or (not args.get("time_max")):
                out = _call_perplexity(_window_repair_prompt(state), user_text, schema=WINDOW_REPAIR_SCHEMA)
                obj = _extract_json(out)
                args["time_min"] = obj.get("time_min")
                args["time_max"] = obj.get("time_max")

            if "max_results" not in args:
                args["max_results"] = 50

        if tool == "gmail_send":
            if "subject" not in args or args["subject"] is None:
                args["subject"] = ""
            if "body" not in args or args["body"] is None:
                args["body"] = ""

        if tool == "gmail_list_important":
            if "days" not in args:
                args["days"] = 4
            if "max_results" not in args:
                args["max_results"] = 10

        if tool == "handle_confirmation":
            if "raw" not in args:
                args["raw"] = user_text

        if tool == "calendar_get_event":
            if "id" in args and "event_id" not in args:
                args["event_id"] = args.pop("id")

        if tool == "calendar_update_event":
            if "id" in args and "event_id" not in args:
                args["event_id"] = args.pop("id")

        if tool == "calendar_delete_events":
            if "ids" in args and "event_ids" not in args:
                args["event_ids"] = args.pop("ids")

        if tool == "memory_upsert":
            if "pref_key" in args and "key" not in args:
                args["key"] = args.pop("pref_key")
            if "pref_value" in args and "value" not in args:
                args["value"] = args.pop("pref_value")

            k = (args.get("key") or "").strip()
            if k in ("no_meeting_before", "no_meetings_before_time", "no_events_before"):
                args["key"] = "no_meetings_before"
            if k in ("default_meeting_duration", "default_meeting_mins", "default_meeting_minutes_min"):
                args["key"] = "default_meeting_minutes"

        fixed.append({"tool": tool, "args": args})

    return fixed

def _final_validate(plan: List[dict]) -> Tuple[List[dict], Optional[str]]:
    safe: List[dict] = []

    for c in plan or []:
        tool = c.get("tool")
        args = c.get("args") or {}

        if tool not in ALLOWED_TOOLS:
            continue

        if tool == "calendar_prepare_event":
            if not args.get("start_iso") or not args.get("end_iso"):
                return [], "I couldn't determine the exact date/time. Please restate it like `2026-01-17 10:00`."
            if not args.get("summary"):
                args["summary"] = "Event"

        if tool == "calendar_list_events":
            if not args.get("time_min") or not args.get("time_max"):
                return [], "I couldn't determine the time window. Say 'tomorrow' or give start/end dates."
            if "max_results" not in args:
                args["max_results"] = 50

        if tool == "calendar_get_event":
            if not (args.get("event_id") and str(args.get("event_id")).strip()):
                return [], "Missing event_id to fetch the event."

        if tool == "calendar_update_event":
            if not (args.get("event_id") and str(args.get("event_id")).strip()):
                return [], "Missing event_id to update the event."
            if not isinstance(args.get("patch"), dict) or not args.get("patch"):
                return [], "Missing patch object to update the event."

        if tool == "calendar_delete_events":
            ids = args.get("event_ids")
            if not isinstance(ids, list) or not all(isinstance(x, str) and x.strip() for x in ids):
                return [], "Missing event_ids (list of event id strings)."

        if tool == "gmail_send":
            if not (args.get("to_email") and str(args.get("to_email")).strip()):
                return [], "MISSING_TO_EMAIL"

        if tool == "memory_upsert":
            if not (args.get("key") and isinstance(args.get("value"), str) and args.get("value").strip()):
                return [], "MISSING_PREF_VALUE"

        safe.append({"tool": tool, "args": args})

    return safe, None

# ---------- pending-intent helpers ----------
def _pending_original_request(state: dict, raw: str) -> str:
    pi = state.get("pending_intent")
    if isinstance(pi, dict) and (pi.get("original_request") or "").strip():
        return str(pi.get("original_request")).strip()
    return raw

def _combined_user_text_for_multiturn(state: dict, raw: str) -> str:
    pi = state.get("pending_intent")
    if isinstance(pi, dict) and (pi.get("original_request") or "").strip():
        return f"ORIGINAL_REQUEST: {pi.get('original_request')}\nUSER_FOLLOWUP: {raw}"
    return raw

def _repair_missing_preference_with_llm(state: dict, user_text: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        out = _call_perplexity(_pref_repair_prompt(state), user_text, schema=PREF_REPAIR_SCHEMA)
        obj = _extract_json(out)
    except Exception:
        return None, "What time should I use (e.g., 10:00 or 22:30)?"

    ok = bool(obj.get("ok"))
    if not ok:
        q = (obj.get("question") or "").strip()
        return None, q or "What time should I use (e.g., 10:00 or 22:30)?"

    key = (obj.get("key") or "").strip()
    val = (obj.get("value") or "").strip()
    if not key or not val:
        return None, "What time should I use (e.g., 10:00 or 22:30)?"

    return {"key": key, "value": val}, None

def _repair_missing_gmail_to_with_llm(state: dict, user_text: str) -> Tuple[Optional[dict], Optional[str]]:
    try:
        out = _call_perplexity(_gmail_repair_prompt(state), user_text, schema=GMAIL_REPAIR_SCHEMA)
        obj = _extract_json(out)
    except Exception:
        return None, "What email address should I send it to?"

    ok = bool(obj.get("ok"))
    if not ok:
        q = (obj.get("question") or "").strip()
        return None, q or "What email address should I send it to?"

    to_email = (obj.get("to_email") or "").strip()
    subject = obj.get("subject")
    body = obj.get("body")

    if not to_email:
        return None, "What email address should I send it to?"

    if subject is None:
        subject = ""
    if body is None:
        body = ""

    return {"to_email": to_email, "subject": str(subject), "body": str(body)}, None

# ---------- main planner ----------
def planner(state: dict) -> dict:
    raw = (state.get("input") or "").strip()

    state["plan"] = []
    state["needs_more"] = False
    state["response"] = ""

    state["pending_intent_op"] = None
    state["pending_intent_out"] = None

    low = raw.lower()
    is_confirm_like = ("confirmation:" in low) or ("/confirm" in low)

    # ✅ HARD ROUTE: explicit confirm commands
    if is_confirm_like:
        state["plan"] = [{"tool": "handle_confirmation", "args": {"raw": raw}}]
        state["needs_more"] = False
        state["response"] = ""
        return state

    # ✅ HARD ROUTE: if pending_action exists and user typed a bare yes/no -> treat as confirmation
    if state.get("pending_action") and _looks_like_yes_no_only(raw):
        state["plan"] = [{"tool": "handle_confirmation", "args": {"raw": raw}}]
        state["needs_more"] = False
        state["response"] = ""
        return state

    # ✅ If there's a pending action and user isn't confirming, don't plan new actions.
    if state.get("pending_action"):
        state["plan"] = []
        state["needs_more"] = False
        state["response"] = ""
        return state

    # ✅ HARD ROUTE: gmail_send (MUST be before important-email listing)
    if _looks_like_send_email_request(raw):
        args = _extract_send_email_args(raw)
        if args:
            state["plan"] = [{"tool": "gmail_send", "args": args}]
            state["needs_more"] = False
            state["response"] = ""
            state["pending_intent_op"] = "clear"
            state["pending_intent_out"] = None
            return state
        # If parsing failed, let the LLM planner handle it (but DO NOT fall into list_important)
        # Continue to LLM section below.

    # ✅ HARD ROUTE: Important/starred email listing
    if _looks_like_important_email_request(raw):
        days = _extract_days(raw, default_days=4)
        max_results = 50 if _wants_all(raw) else 10
        state["plan"] = [{"tool": "gmail_list_important", "args": {"days": days, "max_results": max_results}}]
        state["needs_more"] = False
        state["response"] = ""
        state["pending_intent_op"] = "clear"
        state["pending_intent_out"] = None
        return state

    # ✅ Deterministic preference parsing
    if _is_no_meetings_before_pref(raw):
        hhmm = _normalize_time_to_hhmm(raw)
        if hhmm:
            state["plan"] = [{"tool": "memory_upsert", "args": {"key": "no_meetings_before", "value": hhmm}}]
            state["needs_more"] = False
            state["response"] = ""
            state["pending_intent_op"] = "clear"
            state["pending_intent_out"] = None
            return state

        state["plan"] = []
        state["needs_more"] = True
        state["response"] = "What time should I use (e.g., 10:00 or 22:30)?"
        state["pending_intent_op"] = "save"
        state["pending_intent_out"] = {
            "original_request": _pending_original_request(state, raw),
            "last_question": state["response"],
            "updated_at_iso": datetime.now(IST).isoformat(),
        }
        return state

    if _is_default_meeting_minutes_pref(raw):
        mins = _extract_int_minutes(raw)
        if mins is not None:
            state["plan"] = [{"tool": "memory_upsert", "args": {"key": "default_meeting_minutes", "value": str(mins)}}]
            state["needs_more"] = False
            state["response"] = ""
            state["pending_intent_op"] = "clear"
            state["pending_intent_out"] = None
            return state

    # ✅ Deterministic delete-by-title (uses last calendar_list_events output)
    del_title = _extract_delete_title(raw)
    if del_title:
        events = _events_from_last_tool_results(state)
        hits = _match_events_by_title(events, del_title)

        if len(hits) == 1:
            eid = (hits[0].get("id") or "").strip()
            summary = hits[0].get("summary") or del_title
            if eid:
                state["plan"] = [{"tool": "calendar_delete_events", "args": {"event_ids": [eid], "summaries": [str(summary)]}}]
                state["needs_more"] = False
                state["response"] = ""
                state["pending_intent_op"] = "clear"
                state["pending_intent_out"] = None
                return state

        if len(hits) > 1:
            opts = []
            for e in hits[:5]:
                s = e.get("summary") or "(no title)"
                st = ""
                en = ""
                ss = e.get("start")
                ee = e.get("end")
                if isinstance(ss, dict):
                    st = ss.get("dateTime") or ss.get("date") or ""
                if isinstance(ee, dict):
                    en = ee.get("dateTime") or ee.get("date") or ""
                opts.append(f"- {s} ({st} → {en})")
            state["plan"] = []
            state["needs_more"] = True
            state["response"] = "Which one should I delete?\n" + "\n".join(opts)
            state["pending_intent_op"] = "save"
            state["pending_intent_out"] = {
                "original_request": _pending_original_request(state, raw),
                "last_question": state["response"],
                "updated_at_iso": datetime.now(IST).isoformat(),
            }
            return state

        if "tomorrow" in low:
            tmin, tmax = _tomorrow_window_iso()
            state["plan"] = [{"tool": "calendar_list_events", "args": {"time_min": tmin, "time_max": tmax, "max_results": 50}}]
            state["needs_more"] = False
            state["response"] = ""
            state["pending_intent_op"] = "save"
            state["pending_intent_out"] = {
                "original_request": _pending_original_request(state, raw),
                "last_question": "Which event should I delete? (Reply with the exact title.)",
                "updated_at_iso": datetime.now(IST).isoformat(),
            }
            return state

        state["plan"] = []
        state["needs_more"] = True
        state["response"] = "I can’t find that event yet. Say “list my meetings tomorrow” first, then tell me which one to delete."
        state["pending_intent_op"] = "save"
        state["pending_intent_out"] = {
            "original_request": _pending_original_request(state, raw),
            "last_question": state["response"],
            "updated_at_iso": datetime.now(IST).isoformat(),
        }
        return state

    user_text = _combined_user_text_for_multiturn(state, raw)

    try:
        content = _call_perplexity(_planner_system_prompt(state), user_text, schema=PLAN_SCHEMA)
        obj = _extract_json(content)

        state["needs_more"] = bool(obj.get("needs_more", False))
        raw_response = obj.get("response", "") or ""

        if state["needs_more"]:
            state["plan"] = []
            state["response"] = raw_response

            original_request = _pending_original_request(state, raw)
            state["pending_intent_op"] = "save"
            state["pending_intent_out"] = {
                "original_request": original_request,
                "last_question": state["response"],
                "updated_at_iso": datetime.now(IST).isoformat(),
            }

            if not state["response"].strip():
                state["response"] = "I need one more detail to proceed. What exactly should I do?"
            return state

        plan = obj.get("plan") or []
        plan2 = _repair_calendar_args(state, plan, user_text)
        safe_plan, err = _final_validate(plan2)

        if err == "MISSING_PREF_VALUE":
            repaired, question = _repair_missing_preference_with_llm(state, user_text)
            if repaired:
                safe_plan = [{"tool": "memory_upsert", "args": repaired}]
                err = None
            else:
                state["plan"] = []
                state["needs_more"] = True
                state["response"] = question or "What time should I use (e.g., 10:00 or 22:30)?"
                original_request = _pending_original_request(state, raw)
                state["pending_intent_op"] = "save"
                state["pending_intent_out"] = {
                    "original_request": original_request,
                    "last_question": state["response"],
                    "updated_at_iso": datetime.now(IST).isoformat(),
                }
                return state

        if err == "MISSING_TO_EMAIL":
            repaired, question = _repair_missing_gmail_to_with_llm(state, user_text)
            if repaired:
                safe_plan = [{"tool": "gmail_send", "args": repaired}]
                err = None
            else:
                state["plan"] = []
                state["needs_more"] = True
                state["response"] = question or "What email address should I send it to?"
                original_request = _pending_original_request(state, raw)
                state["pending_intent_op"] = "save"
                state["pending_intent_out"] = {
                    "original_request": original_request,
                    "last_question": state["response"],
                    "updated_at_iso": datetime.now(IST).isoformat(),
                }
                return state

        if err:
            state["plan"] = []
            state["needs_more"] = True
            state["response"] = err
            original_request = _pending_original_request(state, raw)
            state["pending_intent_op"] = "save"
            state["pending_intent_out"] = {
                "original_request": original_request,
                "last_question": state["response"],
                "updated_at_iso": datetime.now(IST).isoformat(),
            }
            return state

        if (not safe_plan) and _looks_like_upcoming_list_request(raw):
            tmin, tmax = _default_upcoming_window()
            state["plan"] = [{"tool": "calendar_list_events", "args": {"time_min": tmin, "time_max": tmax, "max_results": 50}}]
            state["needs_more"] = False
            state["response"] = ""
            state["pending_intent_op"] = "clear"
            state["pending_intent_out"] = None
            return state

        state["plan"] = safe_plan
        state["response"] = "" if state["plan"] else raw_response

        if _user_says_no_attendees(raw):
            for c in state["plan"]:
                if c.get("tool") == "calendar_prepare_event":
                    (c.get("args") or {}).pop("attendees", None)

        if state["plan"]:
            state["pending_intent_op"] = "clear"
            state["pending_intent_out"] = None

        if not state["plan"] and not (state["response"] or "").strip():
            state["response"] = (
                "Tell me what you want. Examples:\n"
                "- show important emails last 4 days\n"
                "- send email to x@y.com subject ... body ...\n"
                "- show my events tomorrow\n"
                "- schedule meeting on 17-01-2026 at 10am for 60 mins\n"
                "- don't schedule meetings before 10:00\n"
                "- default my meetings to 45 minutes\n"
                "- delete Meeting 5 tomorrow\n"
                "- update event <id> (requires event id)"
            )

        return state

    except Exception as e:
        state["plan"] = []
        state["needs_more"] = False
        state["response"] = f"Planner error: {type(e).__name__}: {str(e)}"
        return state
