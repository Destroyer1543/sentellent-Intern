# app/agent/responder.py
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz

IST = pytz.timezone("Asia/Kolkata")


def _fmt_dt(s: str) -> str:
    if not s:
        return ""
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)

        # convert aware dt to IST for display
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST)

        # all-day / date-only style
        if "T" not in s and dt.hour == 0 and dt.minute == 0:
            return dt.strftime("%b %d, %Y")

        return dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return s


def _coerce_events_list(result: Any) -> list[dict]:
    if result is None:
        return []
    if isinstance(result, list):
        return [e for e in result if isinstance(e, dict)]
    if isinstance(result, dict):
        for k in ("events", "items", "result"):
            v = result.get(k)
            if isinstance(v, list):
                return [e for e in v if isinstance(e, dict)]
    return []


def _extract_event_times(e: dict) -> tuple[str, str]:
    start = ""
    end = ""

    s = e.get("start")
    if isinstance(s, dict):
        start = s.get("dateTime") or s.get("date") or ""
    elif isinstance(s, str):
        start = s

    en = e.get("end")
    if isinstance(en, dict):
        end = en.get("dateTime") or en.get("date") or ""
    elif isinstance(en, str):
        end = en

    if not start:
        start = e.get("start_iso") or ""
    if not end:
        end = e.get("end_iso") or ""
    return start, end


def _format_pending_calendar_create(pending: dict) -> str:
    payload = pending.get("payload") or {}
    summary = payload.get("summary", "Event")
    start_iso = payload.get("start_iso", "")
    end_iso = payload.get("end_iso", "")
    conflicts = payload.get("conflicts") or []

    base = [
        "Action waiting for confirmation",
        f"**{summary}**",
        f"Start: {_fmt_dt(start_iso)}",
        f"End: {_fmt_dt(end_iso)}",
    ]

    if conflicts:
        lines = []
        for c in conflicts[:5]:
            if isinstance(c, dict):
                # show ISO directly; _fmt_dt might not parse all RFC3339 variants reliably
                lines.append(f"- {c.get('start')} → {c.get('end')}")
            else:
                lines.append(f"- {str(c)}")
        base.append("")
        base.append("Conflicts:")
        base.extend(lines)

    base.append("")
    base.append("Use **Confirm** or **Cancel** in the UI (or send `/confirm yes` / `/confirm no`).")
    return "\n".join(base)


def _format_pending_calendar_update(pending: dict) -> str:
    payload = pending.get("payload") or {}
    event_id = (payload.get("event_id") or "").strip()
    patch = payload.get("patch") or {}

    lines = [
        "Action waiting for confirmation",
        "**Update calendar event**",
        f"Event ID: `{event_id or '(missing)'}`",
    ]

    if isinstance(patch, dict) and patch:
        if "summary" in patch:
            lines.append(f"New title: **{patch.get('summary') or ''}**")

        start = (patch.get("start") or {}).get("dateTime") if isinstance(patch.get("start"), dict) else None
        end = (patch.get("end") or {}).get("dateTime") if isinstance(patch.get("end"), dict) else None
        if start:
            lines.append(f"New start: {_fmt_dt(str(start))}")
        if end:
            lines.append(f"New end: {_fmt_dt(str(end))}")

        if "description" in patch:
            desc = patch.get("description") or ""
            if isinstance(desc, str) and desc.strip():
                d = desc.strip()
                if len(d) > 200:
                    d = d[:200] + "…"
                lines.append(f"Description: {d}")

        # If someone passes attendees in patch (rare), show count
        if "attendees" in patch and isinstance(patch.get("attendees"), list):
            lines.append(f"Attendees: {len(patch.get('attendees') or [])}")

    lines.append("")
    lines.append("Use **Confirm** or **Cancel** in the UI (or send `/confirm yes` / `/confirm no`).")
    return "\n".join(lines)


def _format_pending_calendar_delete(pending: dict) -> str:
    payload = pending.get("payload") or {}
    ids = payload.get("event_ids") or []
    summaries = payload.get("summaries") or []

    lines = [
        "Action waiting for confirmation",
        "**Delete calendar event(s)**",
    ]

    if isinstance(ids, list) and ids:
        max_show = 8
        for i, eid in enumerate(ids[:max_show]):
            title = ""
            if isinstance(summaries, list) and i < len(summaries) and isinstance(summaries[i], str):
                title = summaries[i].strip()
            if title:
                lines.append(f"- **{title}** (`{eid}`)")
            else:
                lines.append(f"- `{eid}`")
        if len(ids) > max_show:
            lines.append(f"- …and {len(ids) - max_show} more")
    else:
        lines.append("- (missing event ids)")

    lines.append("")
    lines.append("Use **Confirm** or **Cancel** in the UI (or send `/confirm yes` / `/confirm no`).")
    return "\n".join(lines)


def _format_pending_gmail(pending: dict) -> str:
    payload = pending.get("payload") or {}
    to_email = (payload.get("to_email") or "").strip()
    subject = (payload.get("subject") or "(no subject)").strip()

    return "\n".join(
        [
            "Action waiting for confirmation",
            f"**Email to {to_email or '(missing)'}**",
            f"Subject: **{subject}**",
            "",
            "Use **Confirm** or **Cancel** in the UI (or send `/confirm yes` / `/confirm no`).",
        ]
    )


def _format_important_emails(state: dict, mails: list[dict]) -> str:
    if not mails:
        return "No important/starred emails found in that period."

    signals = ""
    mem = state.get("memories") or {}
    if isinstance(mem, dict):
        signals = (mem.get("inbox_signals") or "").strip()

    lines = []
    for m in mails[:10]:
        subj = (m.get("subject") or "(no subject)").strip()
        frm = (m.get("from") or "").strip()
        snip = (m.get("snippet") or "").strip()
        url = (m.get("url") or "").strip()

        title = f"[{subj}]({url})" if url else f"**{subj}**"

        lines.append(
            "\n".join(
                [
                    f"- {title}",
                    f"  - From: {frm}" if frm else "  - From: (unknown)",
                    f"  - {snip}" if snip else "  - (no preview)",
                ]
            )
        )

    header = "Here are your important/starred emails:"
    if signals:
        header += f"\nSignals: {signals}"

    return header + "\n" + "\n".join(lines)


def build_response(state: dict) -> dict:
    raw = (state.get("input") or "").strip().lower()
    is_confirm_like = ("confirmation:" in raw) or ("/confirm" in raw)

    # 1) If there is a pending_action and user isn't confirming: always show the pending banner.
    pending = state.get("pending_action")
    if pending and not is_confirm_like:
        ptype = pending.get("type")

        if ptype == "calendar_create":
            state["response"] = _format_pending_calendar_create(pending)
            return state

        if ptype == "calendar_update":
            state["response"] = _format_pending_calendar_update(pending)
            return state

        if ptype == "calendar_delete_many":
            state["response"] = _format_pending_calendar_delete(pending)
            return state

        if ptype == "gmail_send":
            state["response"] = _format_pending_gmail(pending)
            return state

        state["response"] = "Action waiting for confirmation. Use Confirm/Cancel to continue."
        return state

    # 2) If planner asked a question (needs_more), show it.
    if state.get("needs_more") and (state.get("response") or "").strip():
        return state

    # 3) Prefer last tool batch.
    last_batch = state.get("last_tool_results") or []
    if not last_batch:
        if (state.get("response") or "").strip():
            return state
        state["response"] = "Tell me what you want me to do with Gmail/Calendar."
        return state

    # If any tool failed, surface the last failure (most recent error)
    for item in reversed(last_batch):
        if item.get("ok") is False:
            state["response"] = f"Tool failed: {item.get('error', 'unknown error')}"
            return state

    last = last_batch[-1]
    tool = last.get("tool")
    ok = last.get("ok")

    # Confirmation handler
    if tool == "handle_confirmation":
        if last.get("already_handled"):
            state["response"] = "✅ That pending action was already handled in another tab/window."
            return state

        res = last.get("result")
        if isinstance(res, str) and res.strip():
            state["response"] = res.strip()
            return state

        state["response"] = "✅ Confirmation processed."
        return state

    # Calendar create result
    if tool == "calendar_create" and ok:
        res = last.get("result") or {}
        if isinstance(res, dict):
            link = res.get("htmlLink")
            ev_id = res.get("id")
            if link:
                state["response"] = f"✅ Created the calendar event.\nLink: {link}"
                return state
            if ev_id:
                state["response"] = f"✅ Created the calendar event (id: {ev_id})."
                return state
        state["response"] = "✅ Created the calendar event."
        return state

    # Calendar update result
    if tool == "calendar_update_event" and ok:
        res = last.get("result")
        # gated path
        if isinstance(res, str) and "Pending confirmation" in res:
            state["response"] = "Action waiting for confirmation. Use Confirm/Cancel to continue."
            return state

        # executed path (from confirmation)
        if isinstance(res, dict):
            link = res.get("htmlLink")
            ev_id = res.get("id")
            if link:
                state["response"] = f"✅ Updated the calendar event.\nLink: {link}"
                return state
            if ev_id:
                state["response"] = f"✅ Updated the calendar event (id: {ev_id})."
                return state

        state["response"] = "✅ Updated the calendar event."
        return state

    # Calendar delete result
    if tool == "calendar_delete_events" and ok:
        res = last.get("result")
        # gated path
        if isinstance(res, str) and "Pending confirmation" in res:
            state["response"] = "Action waiting for confirmation. Use Confirm/Cancel to continue."
            return state

        # executed path
        if isinstance(res, list):
            ok_count = sum(1 for r in res if isinstance(r, dict) and r.get("ok") is True)
            fail_count = sum(1 for r in res if isinstance(r, dict) and r.get("ok") is False)
            if fail_count:
                state["response"] = f"✅ Deleted {ok_count} event(s). ⚠️ {fail_count} failed."
                return state
            state["response"] = f"✅ Deleted {ok_count} event(s)."
            return state

        state["response"] = "✅ Deleted event(s)."
        return state

    # Calendar prepare (gated)
    if tool == "calendar_prepare_event" and ok:
        state["response"] = "Action waiting for confirmation. Use Confirm/Cancel to continue."
        return state

    # Gmail send result (actual send OR gated)
    if tool == "gmail_send" and ok:
        res = last.get("result")
        if isinstance(res, str) and "Pending confirmation" in res:
            state["response"] = "Action waiting for confirmation. Use Confirm/Cancel to continue."
            return state

        if isinstance(res, dict) and res.get("id"):
            state["response"] = f"✅ Email sent. (id: {res.get('id')})"
            return state

        state["response"] = "✅ Email sent."
        return state

    # List important emails
    if tool in ("gmail_list_important", "gmail_list_important_recent") and ok:
        mails = last.get("result") or []
        if not isinstance(mails, list):
            mails = []
        state["response"] = _format_important_emails(state, mails)
        return state

    # List events
    if tool in ("calendar_list_events", "calendar_list") and ok:
        events = _coerce_events_list(last.get("result"))
        if not events:
            state["response"] = "You have no events in that time range."
            return state

        lines = []
        for e in events[:15]:
            title = e.get("summary") or e.get("title") or "(no title)"
            start, end = _extract_event_times(e)
            start_s = _fmt_dt(start)
            end_s = _fmt_dt(end)
            if start_s and end_s:
                lines.append(f"- **{start_s}** → {end_s} — {title}")
            elif start_s:
                lines.append(f"- **{start_s}** — {title}")
            else:
                lines.append(f"- {title}")

        state["response"] = "Here are your events:\n" + "\n".join(lines)
        return state

    # Memory save
    if tool == "memory_upsert" and ok:
        res = last.get("result") or {}
        k = (res.get("key") or "").strip()
        v = res.get("value")
        state["response"] = f"✅ Saved preference: **{k}** = **{'' if v is None else str(v)}**"
        return state

    if (state.get("response") or "").strip():
        return state

    state["response"] = "✅ Completed."
    return state
