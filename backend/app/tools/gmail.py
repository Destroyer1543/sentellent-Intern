# app/tools/gmail.py
from googleapiclient.discovery import build

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def list_important_recent(service, days: int = 4, max_results: int = 10):
    q = f"newer_than:{days}d (is:important OR is:starred)"
    resp = service.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
    msgs = resp.get("messages", [])
    out = []
    for m in msgs:
        mid = m.get("id") or ""
        if not mid:
            continue

        full = service.users().messages().get(userId="me", id=mid, format="metadata").execute()
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}

        out.append(
            {
                "id": mid,
                # ✅ Useful for UI + “real product” feel
                "url": f"https://mail.google.com/mail/u/0/#inbox/{mid}",
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "snippet": full.get("snippet", ""),
            }
        )
    return out


def send_email(service, to_email: str, subject: str, body: str):
    # minimal RFC 2822 email
    raw = f"To: {to_email}\r\nSubject: {subject}\r\n\r\n{body}"
    import base64

    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")
    return service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def build_gmail_service(creds):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
