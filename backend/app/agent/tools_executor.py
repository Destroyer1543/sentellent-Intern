# app/agent/tools_executor.py
from __future__ import annotations

import re
import traceback
from typing import Any, Optional
from datetime import datetime

from tenacity import retry, stop_after_attempt, wait_fixed, RetryError
from sqlalchemy.orm import Session

from app.db.google_tokens import load_google_token, save_google_token
from app.db.pending_actions import save_pending_action, get_pending_action, clear_pending_action
from app.db.pending_intent import clear_pending_intent  # ensure this matches your module/file

from app.tools.google_creds import creds_from_token_dict, creds_to_dict
from app.tools.gmail import build_gmail_service, list_important_recent, send_email, GMAIL_SCOPES
from app.tools.calendar import (
    build_calendar_service,
    freebusy_conflicts,
    create_event,
    list_events,
    update_event,
    get_event,
    delete_event,
    CAL_SCOPES,
)

from app.db.memories import upsert_memory  # for memory_upsert tool

ALL_SCOPES = list(set(GMAIL_SCOPES + CAL_SCOPES))


# -------------------------
# Helpers
# -------------------------
def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _parse_confirmation(raw: str) -> tuple[str, str]:
    lowered = (raw or "").strip().lower()

    # common yes patterns
    if re.search(r"\b(yes|y|confirm|approved|ok|okay|sure|do it|go ahead|proceed|send it)\b", lowered):
        return "yes", raw

    # common no patterns
    if re.search(r"\b(no|n|cancel|stop|dont|don't|nevermind|never mind)\b", lowered):
        return "no", raw

    return "unknown", raw


def _parse_iso_dt(s: str) -> Optional[datetime]:
    try:
        if not s:
            return None
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        return None


def _no_meetings_before_minutes(state: dict) -> Optional[int]:
    mem = state.get("memories") or {}
    if not isinstance(mem, dict):
        return None

    v = mem.get("no_meetings_before")
    if not v:
        return None

    try:
        hh, mm = str(v).strip().split(":")
        hh_i = int(hh)
        mm_i = int(mm)
        if 0 <= hh_i <= 23 and 0 <= mm_i <= 59:
            return hh_i * 60 + mm_i
    except Exception:
        return None

    return None


def _violates_no_meetings_before(state: dict, start_iso: str) -> tuple[bool, Optional[str]]:
    """
    Returns (violates, pref_value_str)
    """
    limit = _no_meetings_before_minutes(state)
    if limit is None:
        return False, None

    dt = _parse_iso_dt(start_iso)
    if not dt:
        # can't validate reliably -> don't block here
        return False, None

    start_minutes = dt.hour * 60 + dt.minute
    if start_minutes < limit:
        pref = (state.get("memories") or {}).get("no_meetings_before")
        return True, str(pref)

    return False, None


@retry(stop=stop_after_attempt(5), wait=wait_fixed(1))
def _with_google_services(db: Session, user_id: str):
    token = load_google_token(db, user_id)
    if not token:
        raise RuntimeError("Google not connected. Go to /auth/google/start?user_id=... first.")

    creds = creds_from_token_dict(token, scopes=ALL_SCOPES)

    # persist refreshed tokens (preserve refresh_token if google doesn't resend)
    old = token or {}
    new = creds_to_dict(creds) or {}
    if not new.get("refresh_token") and old.get("refresh_token"):
        new["refresh_token"] = old["refresh_token"]
    save_google_token(db, user_id, new)

    gmail = build_gmail_service(creds)
    cal = build_calendar_service(creds)
    return gmail, cal


def _with_google_services_safe(db: Session, user_id: str):
    try:
        return _with_google_services(db, user_id)
    except RetryError as re_err:
        last = re_err.last_attempt.exception()
        print("GOOGLE SERVICES FAILED AFTER RETRIES")
        print("User:", user_id)
        print("Last exception:", type(last).__name__, str(last))
        traceback.print_exception(type(last), last, last.__traceback__)
        raise last


def _clear_pending_intent_safe(state: dict, db: Session, user_id: str) -> None:
    """
    Best-effort clear (DB + in-memory).
    Keeps code resilient even if DB hiccup.
    """
    try:
        clear_pending_intent(db, user_id)
    except Exception:
        pass
    state["pending_intent"] = None


def _safe_clear_pending_action(state: dict, db: Session, user_id: str) -> None:
    """
    Clear pending action (DB + in-memory) safely.
    """
    try:
        clear_pending_action(db, user_id)
    except Exception:
        pass
    state["pending_action"] = None


# -------------------------
# Tool Handlers
# -------------------------
def _tool_handle_confirmation(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]

    decision, _raw = _parse_confirmation(args.get("raw", ""))
    pending = get_pending_action(db, user_id)

    # ✅ Multi-tab safe: if another tab already handled it, don't error.
    if not pending:
        state["pending_action"] = None
        _clear_pending_intent_safe(state, db, user_id)
        return {
            "tool": "handle_confirmation",
            "ok": True,
            "result": "No pending action anymore (already handled in another tab).",
            "already_handled": True,
        }

    if decision == "unknown":
        return {"tool": "handle_confirmation", "ok": False, "error": "Please reply with 'yes' or 'no'."}

    if decision == "no":
        _safe_clear_pending_action(state, db, user_id)
        _clear_pending_intent_safe(state, db, user_id)
        return {"tool": "handle_confirmation", "ok": True, "result": "Cancelled pending action."}

    # yes -> execute pending
    gmail, cal = _with_google_services_safe(db, user_id)
    ptype = pending.get("type")

    if ptype == "calendar_create":
        payload = pending.get("payload", {})
        res = create_event(
            cal,
            summary=payload.get("summary", "Event"),
            start_iso=payload["start_iso"],
            end_iso=payload["end_iso"],
            attendees=payload.get("attendees"),
            description=payload.get("description"),
        )
        _safe_clear_pending_action(state, db, user_id)
        return {
            "tool": "calendar_create",
            "ok": True,
            "result": {"id": res.get("id"), "htmlLink": res.get("htmlLink")},
        }

    if ptype == "gmail_send":
        payload = pending.get("payload", {})
        res = send_email(
            gmail,
            to_email=payload["to_email"],
            subject=payload.get("subject", "Sentellent Assistant Email"),
            body=payload.get("body", ""),
        )
        _safe_clear_pending_action(state, db, user_id)
        return {"tool": "gmail_send", "ok": True, "result": {"id": res.get("id")}}

    if ptype == "calendar_update":
        payload = pending.get("payload", {})
        event_id = (payload.get("event_id") or "").strip()
        patch = payload.get("patch") or {}

        if not event_id or not isinstance(patch, dict) or not patch:
            _safe_clear_pending_action(state, db, user_id)
            return {"tool": "calendar_update_event", "ok": False, "error": "Pending update payload was invalid."}

        res = update_event(cal, event_id=event_id, patch=patch)
        _safe_clear_pending_action(state, db, user_id)
        return {
            "tool": "calendar_update_event",
            "ok": True,
            "result": {"id": res.get("id"), "htmlLink": res.get("htmlLink")},
        }

    if ptype == "calendar_delete_many":
        payload = pending.get("payload", {})
        ids = payload.get("event_ids") or []

        if not isinstance(ids, list) or not all(isinstance(x, str) and x.strip() for x in ids):
            _safe_clear_pending_action(state, db, user_id)
            return {"tool": "calendar_delete_events", "ok": False, "error": "Pending delete payload was invalid."}

        results = []
        for eid in ids:
            eid2 = eid.strip()
            try:
                delete_event(cal, eid2)
                results.append({"id": eid2, "ok": True})
            except Exception as e:
                results.append({"id": eid2, "ok": False, "error": f"{type(e).__name__}: {str(e)}"})

        _safe_clear_pending_action(state, db, user_id)
        return {"tool": "calendar_delete_events", "ok": True, "result": results}

    _safe_clear_pending_action(state, db, user_id)
    return {"tool": "handle_confirmation", "ok": False, "error": f"Unknown pending action type: {ptype}"}


def _tool_gmail_list_important(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    gmail, _cal = _with_google_services_safe(db, user_id)

    days = _safe_int(args.get("days", 4), 4)
    max_results = _safe_int(args.get("max_results", 10), 10)

    res = list_important_recent(gmail, days=days, max_results=max_results)
    return {"tool": "gmail_list_important", "ok": True, "result": res}


def _tool_gmail_send_gated(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]

    to_email = (args.get("to_email") or "").strip()
    subject = (args.get("subject") or "Sentellent Assistant Email").strip()
    body = args.get("body")
    if body is None:
        body = ""

    if not to_email:
        return {
            "tool": "gmail_send",
            "ok": False,
            "error": "Missing recipient email (e.g., 'send email to xyz@gmail.com').",
        }

    pending = {
        "type": "gmail_send",
        "payload": {"to_email": to_email, "subject": subject, "body": body},
    }
    save_pending_action(db, user_id, pending)

    _clear_pending_intent_safe(state, db, user_id)
    state["pending_action"] = pending
    return {"tool": "gmail_send", "ok": True, "result": "Pending confirmation to send email."}


def _tool_calendar_prepare_event_gated(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    _gmail, cal = _with_google_services_safe(db, user_id)

    start_iso = args.get("start_iso")
    end_iso = args.get("end_iso")
    if not start_iso or not end_iso:
        return {"tool": "calendar_prepare_event", "ok": False, "error": "Missing start_iso or end_iso."}

    # ✅ SAFETY NET: enforce no_meetings_before
    violates, pref = _violates_no_meetings_before(state, start_iso)
    if violates:
        _clear_pending_intent_safe(state, db, user_id)
        return {
            "tool": "calendar_prepare_event",
            "ok": False,
            "error": f"Start time violates your preference: no meetings before {pref}. Please pick a later time.",
        }

    summary = args.get("summary", "Event")
    attendees = args.get("attendees")
    description = args.get("description")

    conflicts = freebusy_conflicts(cal, start_iso=start_iso, end_iso=end_iso)

    pending = {
        "type": "calendar_create",
        "payload": {
            "summary": summary,
            "start_iso": start_iso,
            "end_iso": end_iso,
        },
    }
    if attendees:
        pending["payload"]["attendees"] = attendees
    if description:
        pending["payload"]["description"] = description
    if conflicts:
        pending["payload"]["conflicts"] = conflicts

    save_pending_action(db, user_id, pending)

    _clear_pending_intent_safe(state, db, user_id)
    state["pending_action"] = pending
    return {"tool": "calendar_prepare_event", "ok": True, "result": {"conflicts": conflicts, "pending": True}}


def _tool_calendar_list_events(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    _gmail, cal = _with_google_services_safe(db, user_id)

    time_min = args.get("time_min")
    time_max = args.get("time_max")
    if not time_min or not time_max:
        return {"tool": "calendar_list_events", "ok": False, "error": "Missing time_min or time_max."}

    max_results = _safe_int(args.get("max_results", 10), 10)
    res = list_events(cal, time_min_iso=time_min, time_max_iso=time_max, max_results=max_results)
    return {"tool": "calendar_list_events", "ok": True, "result": res}


def _tool_calendar_update_event_gated(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    _gmail, cal = _with_google_services_safe(db, user_id)

    event_id = (args.get("event_id") or "").strip()
    patch = args.get("patch")

    if not event_id:
        return {"tool": "calendar_update_event", "ok": False, "error": "Missing event_id."}
    if not isinstance(patch, dict) or not patch:
        return {"tool": "calendar_update_event", "ok": False, "error": "Missing patch object."}

    # Optional: guard preference when changing start time
    if isinstance(patch.get("start"), dict) and patch["start"].get("dateTime"):
        violates, pref = _violates_no_meetings_before(state, str(patch["start"]["dateTime"]))
        if violates:
            _clear_pending_intent_safe(state, db, user_id)
            return {
                "tool": "calendar_update_event",
                "ok": False,
                "error": f"Updated start time violates your preference: no meetings before {pref}.",
            }

    pending = {
        "type": "calendar_update",
        "payload": {"event_id": event_id, "patch": patch},
    }
    save_pending_action(db, user_id, pending)

    _clear_pending_intent_safe(state, db, user_id)
    state["pending_action"] = pending
    return {"tool": "calendar_update_event", "ok": True, "result": "Pending confirmation to update event."}


def _tool_calendar_delete_events_gated(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    _gmail, cal = _with_google_services_safe(db, user_id)  # validate token early

    event_ids = args.get("event_ids") or []
    if not isinstance(event_ids, list) or not all(isinstance(x, str) and x.strip() for x in event_ids):
        return {
            "tool": "calendar_delete_events",
            "ok": False,
            "error": "Missing event_ids (list of event id strings).",
        }

    pending = {
        "type": "calendar_delete_many",
        "payload": {
            "event_ids": [x.strip() for x in event_ids],
            "summaries": args.get("summaries") or [],
        },
    }
    save_pending_action(db, user_id, pending)

    _clear_pending_intent_safe(state, db, user_id)
    state["pending_action"] = pending
    return {"tool": "calendar_delete_events", "ok": True, "result": "Pending confirmation to delete events."}


def _tool_calendar_get_event(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]
    _gmail, cal = _with_google_services_safe(db, user_id)

    event_id = (args.get("event_id") or "").strip()
    if not event_id:
        return {"tool": "calendar_get_event", "ok": False, "error": "Missing event_id."}

    res = get_event(cal, event_id=event_id)
    return {"tool": "calendar_get_event", "ok": True, "result": res}


def _tool_memory_upsert(state: dict, db: Session, args: dict) -> dict:
    user_id = state["user_id"]

    key = (args.get("key") or "").strip()
    value = args.get("value")

    if not key or value is None:
        return {"tool": "memory_upsert", "ok": False, "error": "Missing key/value."}

    upsert_memory(db, user_id=user_id, key=key, value=str(value))

    mem = state.get("memories") or {}
    if isinstance(mem, dict):
        mem[key] = str(value)
        state["memories"] = mem

    _clear_pending_intent_safe(state, db, user_id)
    return {"tool": "memory_upsert", "ok": True, "result": {"key": key, "value": str(value)}}


# -------------------------
# Registry + Executor
# -------------------------
TOOL_REGISTRY = {
    "handle_confirmation": _tool_handle_confirmation,
    "gmail_list_important": _tool_gmail_list_important,
    "gmail_send": _tool_gmail_send_gated,
    "calendar_prepare_event": _tool_calendar_prepare_event_gated,
    "calendar_list_events": _tool_calendar_list_events,
    "calendar_update_event": _tool_calendar_update_event_gated,
    "calendar_delete_events": _tool_calendar_delete_events_gated,
    "calendar_get_event": _tool_calendar_get_event,
    "memory_upsert": _tool_memory_upsert,
}


def execute_tools(state: dict, db: Session) -> dict:
    user_id = state.get("user_id")
    plan = state.get("plan") or []
    results = []

    for call in plan:
        tool = call.get("tool")
        args = call.get("args") or {}

        handler = TOOL_REGISTRY.get(tool)
        if not handler:
            results.append({"tool": tool, "ok": False, "error": f"Unknown tool: {tool}"})
            continue

        try:
            out = handler(state, db, args)
            results.append(out)
        except Exception as e:
            print("TOOL EXECUTION ERROR")
            print("User:", user_id)
            print("Tool:", tool)
            print("Args:", args)
            print("Error:", type(e).__name__, str(e))
            traceback.print_exception(type(e), e, e.__traceback__)
            results.append({"tool": tool, "ok": False, "error": f"{type(e).__name__}: {str(e)}"})

    state["last_tool_results"] = results
    state["tool_results"] = (state.get("tool_results") or []) + results
    return state
