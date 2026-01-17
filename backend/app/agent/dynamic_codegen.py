# app/agent/dynamic_codegen.py
import json

def dynamic_codegen(state: dict) -> dict:
    # IMPORTANT:
    # - Don't increment code_attempts here (do it in sandbox so it always increments)
    # - Don't clear attempts here either
    state["generated_code"] = None
    state["code_error"] = None
    state["code_result"] = None

    task = state.get("code_task")

    if task == "extract_datetime":
        ctx = state.get("time_extraction_context") or {}
        raw = ctx.get("raw", state.get("input", ""))
        minutes = int(ctx.get("minutes", 60))

        code = f"""
import json
from datetime import timedelta
import pytz
from dateparser.search import search_dates
import dateparser

RAW = {json.dumps(raw)}
MINUTES = {minutes}
TZ = pytz.timezone("Asia/Kolkata")

settings = {{
  "TIMEZONE": "Asia/Kolkata",
  "RETURN_AS_TIMEZONE_AWARE": True,
  "PREFER_DATES_FROM": "future",
}}

# Prefer search_dates because it extracts date/time fragments from sentences.
found = search_dates(RAW, settings=settings) or []

dt = None
if found:
    # Usually the last match is the most specific time reference
    dt = found[-1][1]

if dt is None:
    # Fallback: strip odd punctuation and parse
    cleaned = "".join(ch if (ch.isalnum() or ch.isspace() or ch in [":"]) else " " for ch in RAW)
    cleaned = " ".join(cleaned.split())
    dt = dateparser.parse(cleaned, settings=settings)

if dt is None:
    print(json.dumps({{"start_iso": None, "end_iso": None}}))
else:
    start = dt.astimezone(TZ)
    end = start + timedelta(minutes=MINUTES)
    print(json.dumps({{"start_iso": start.isoformat(), "end_iso": end.isoformat()}}))
"""
        state["generated_code"] = code
        return state

    # If you got here, planner routed to codegen without a supported task.
    state["code_error"] = f"Unsupported code_task: {task}"
    return state
