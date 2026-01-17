from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from app.google.oauth import dict_to_creds, creds_to_dict
from app.db.google_tokens import load_google_token, save_google_token

def get_creds(user_id: str):
    token = load_google_token(user_id)
    if not token:
        raise RuntimeError("Google not connected for this user.")

    creds = dict_to_creds(token)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_google_token(user_id, creds_to_dict(creds))

    return creds

def calendar_service(user_id: str):
    creds = get_creds(user_id)
    return build("calendar", "v3", credentials=creds)

def gmail_service(user_id: str):
    creds = get_creds(user_id)
    return build("gmail", "v1", credentials=creds)
