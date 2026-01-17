# app/tools/calendar.py
from __future__ import annotations

from googleapiclient.discovery import build
from datetime import datetime
from typing import Any
import pytz

CAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]

IST = pytz.timezone("Asia/Kolkata")


def build_calendar_service(creds):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse_iso(s: str) -> datetime:
    """
    Parse ISO string. If timezone is missing, assume IST.
    Supports 'Z' by converting to '+00:00' for fromisoformat.
    """
    if not s:
        raise ValueError("Empty datetime string")
    s2 = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = IST.localize(dt)
    return dt


def _to_utc_z(dt: datetime) -> str:
    """
    Convert dt to UTC RFC3339 Z string.
    """
    utc_dt = dt.astimezone(pytz.UTC)
    return utc_dt.isoformat().replace("+00:00", "Z")


def _normalize_rfc3339(s: str) -> str:
    """
    Google Calendar endpoints accept RFC3339. Normalize:
    - If string already has timezone offset or Z, keep it.
    - If naive, assume IST and convert to UTC Z string.
    """
    if not s:
        return s
    try:
        dt = _parse_iso(s)
        return _to_utc_z(dt)
    except Exception:
        # If it's already some RFC3339-like string but parsing failed,
        # return as-is and let Google validate.
        return s


def _event_time_iso(event: dict, key: str) -> str:
    """
    Extract start/end ISO from Google event payload.
    """
    if not isinstance(event, dict):
        return ""
    obj = event.get(key) or {}
    if isinstance(obj, dict):
        return obj.get("dateTime") or obj.get("date") or ""
    if isinstance(obj, str):
        return obj
    return ""


def list_events(service, time_min_iso: str, time_max_iso: str, max_results: int = 10):
    tmin = _normalize_rfc3339(time_min_iso)
    tmax = _normalize_rfc3339(time_max_iso)

    resp = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=tmin,
            timeMax=tmax,
            singleEvents=True,
            orderBy="startTime",
            maxResults=max_results,
        )
        .execute()
    )

    items = resp.get("items", []) or []
    # Ensure consistent dict list
    return [e for e in items if isinstance(e, dict)]


def freebusy_conflicts(service, start_iso: str, end_iso: str):
    """
    Returns conflicts as: [{"start": "...", "end": "..."}, ...]
    Normalizes input to UTC Z strings (RFC3339).
    """
    s = _normalize_rfc3339(start_iso)
    e = _normalize_rfc3339(end_iso)

    body = {
        "timeMin": s,
        "timeMax": e,
        "items": [{"id": "primary"}],
    }

    resp = service.freebusy().query(body=body).execute()
    busy = (resp.get("calendars") or {}).get("primary", {}).get("busy") or []

    out = []
    for b in busy:
        if isinstance(b, dict):
            out.append({"start": b.get("start"), "end": b.get("end")})
    return out


def create_event(
    service,
    summary: str,
    start_iso: str,
    end_iso: str,
    attendees: list[str] | None = None,
    description: str | None = None,
):
    # Ensure timezone exists; assume IST if missing
    s = _parse_iso(start_iso)
    e = _parse_iso(end_iso)

    ev: dict[str, Any] = {
        "summary": summary or "Event",
        "start": {"dateTime": s.isoformat()},
        "end": {"dateTime": e.isoformat()},
    }
    if description:
        ev["description"] = description
    if attendees:
        ev["attendees"] = [{"email": a} for a in attendees if isinstance(a, str) and a.strip()]

    return service.events().insert(calendarId="primary", body=ev).execute()


def update_event(service, event_id: str, patch: dict):
    """
    Patch update. If patch includes start/end, normalize them to ISO with TZ.
    Acceptable patch examples:
      {"summary": "New title"}
      {"start": {"dateTime": "..."}, "end": {"dateTime": "..."}}
    """
    if not event_id:
        raise ValueError("Missing event_id")

    if isinstance(patch, dict):
        # Normalize start/end dateTime if present
        for k in ("start", "end"):
            v = patch.get(k)
            if isinstance(v, dict) and v.get("dateTime"):
                try:
                    dt = _parse_iso(v["dateTime"])
                    v["dateTime"] = dt.isoformat()
                except Exception:
                    pass

    return service.events().patch(calendarId="primary", eventId=event_id, body=patch).execute()


def get_event(service, event_id: str):
    if not event_id:
        raise ValueError("Missing event_id")
    return service.events().get(calendarId="primary", eventId=event_id).execute()


def delete_event(service, event_id: str):
    if not event_id:
        raise ValueError("Missing event_id")
    # Google returns empty body on success
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"id": event_id, "deleted": True}
