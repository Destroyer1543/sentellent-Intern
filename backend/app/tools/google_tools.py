import base64
from email.mime.text import MIMEText
from tenacity import retry, stop_after_attempt, wait_exponential
from app.google.service import calendar_service, gmail_service

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=10))
def list_events(user_id: str, time_min: str, time_max: str):
    svc = calendar_service(user_id)
    res = svc.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return res.get("items", [])

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=10))
def create_event(user_id: str, summary: str, start_iso: str, end_iso: str, timezone: str = "Asia/Kolkata"):
    svc = calendar_service(user_id)
    body = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }
    return svc.events().insert(calendarId="primary", body=body).execute()

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=10))
def update_event(user_id: str, event_id: str, summary: str | None = None, start_iso: str | None = None, end_iso: str | None = None, timezone: str = "Asia/Kolkata"):
    svc = calendar_service(user_id)
    ev = svc.events().get(calendarId="primary", eventId=event_id).execute()

    if summary: ev["summary"] = summary
    if start_iso: ev["start"] = {"dateTime": start_iso, "timeZone": timezone}
    if end_iso: ev["end"] = {"dateTime": end_iso, "timeZone": timezone}

    return svc.events().update(calendarId="primary", eventId=event_id, body=ev).execute()

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=10))
def gmail_search(user_id: str, query: str, max_results: int = 10):
    svc = gmail_service(user_id)
    res = svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    return res.get("messages", [])

@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=10))
def send_email(user_id: str, to: str, subject: str, body_text: str):
    svc = gmail_service(user_id)
    msg = MIMEText(body_text)
    msg["to"] = to
    msg["subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return svc.users().messages().send(userId="me", body={"raw": raw}).execute()
